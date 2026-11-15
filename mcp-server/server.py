# -*- coding: utf-8 -*-
"""COMSOL MCP server: two discovery tools over the COMSOL/MPh bridge.

Advertises exactly `search_tools` and `call_tool` so an idle session costs a few
hundred tokens instead of the full tool schemas; the catalogue lives in
catalog.py and is searched on demand. That progressive-disclosure design is the
whole point of this server: do not expose the 157 tools individually.

Transport is MCP stdio (JSON-RPC 2.0), implemented with the standard library
only -- newline-delimited frames and Content-Length frames are both accepted.
The heavy lifting (MPh / JPype / COMSOL) lives in handlers.py, which is imported
lazily so catalogue search still works when that module is absent or broken.

Run:   <mph-venv-python> server.py
Test:  python server.py --list
       python server.py --search "网格"
       python server.py --search "solve" --top-k 3
       python server.py --call comsol_status "{}"
"""
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import catalog  # noqa: E402  (same directory, stdlib only)

SERVER_NAME = "comsol-mcp"
SERVER_VERSION = "0.1.0"
PROTOCOL = "2024-11-05"


# --------------------------------------------------------------------------- #
# stdio plumbing
# --------------------------------------------------------------------------- #

def _harden_stdio():
    """Windows consoles default to cp936/cp437; JSON-RPC is UTF-8."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def log(msg):
    try:
        sys.stderr.write("[comsol-mcp] %s\n" % msg)
        sys.stderr.flush()
    except Exception:
        pass


class ToolError(RuntimeError):
    """A tool-level failure: reported as isError=true, never as transport error."""


# --------------------------------------------------------------------------- #
# handlers.py (MPh/JPype) -- lazy, tolerant import
# --------------------------------------------------------------------------- #

_HANDLERS = None
_HANDLERS_ERROR = None
_HANDLERS_TRIED = False


def get_handlers():
    """Import handlers.py on first use. Missing/broken -> ToolError, not crash."""
    global _HANDLERS, _HANDLERS_ERROR, _HANDLERS_TRIED
    if _HANDLERS is not None:
        return _HANDLERS
    if not _HANDLERS_TRIED:
        _HANDLERS_TRIED = True
        try:
            import handlers as mod  # noqa: F401
            _HANDLERS = mod
            log("handlers loaded: %s" % (getattr(mod, "__file__", "?") or "?"))
        except Exception as exc:
            _HANDLERS_ERROR = "%s: %s" % (type(exc).__name__, exc)
            log("handlers.py unavailable (%s)" % _HANDLERS_ERROR)
    if _HANDLERS is None:
        raise ToolError(
            "tool execution unavailable: handlers.py could not be imported "
            "(%s). Catalogue search still works; run the server with the MPh "
            "virtualenv python (mph + jpype installed)." % _HANDLERS_ERROR)
    return _HANDLERS


def dispatch_tool(name, arguments):
    """Call handlers.dispatch(name, arguments); tolerate a call_tool alias."""
    mod = get_handlers()
    fn = getattr(mod, "dispatch", None) or getattr(mod, "call_tool", None)
    if fn is None:
        raise ToolError("handlers.py exposes neither dispatch(name, arguments) "
                        "nor call_tool(name, arguments)")
    return fn(name, arguments or {})


def render_result(result):
    """Tool results become one text block: strings verbatim, rest as JSON."""
    if isinstance(result, str):
        return result
    if result is None:
        return "ok"
    try:
        return json.dumps(result, ensure_ascii=False, default=repr)
    except Exception:
        return repr(result)


# --------------------------------------------------------------------------- #
# the only two advertised tools
# --------------------------------------------------------------------------- #

SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": ("Intent or COMSOL concept, Chinese or English: "
                            "网格, 求解, 温度, 电场, 几何, mesh, solve, boundary, "
                            "battery, export..."),
        },
        "top_k": {"type": "integer", "default": 6, "minimum": 1, "maximum": 25},
    },
    "required": ["query"],
}

CALL_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string",
                 "description": "Exact tool name returned by search_tools"},
        "arguments": {"type": "object",
                      "description": "Tool arguments (see the args line)"},
    },
    "required": ["name"],
}

TOOLS_LIST = [
    {
        "name": "search_tools",
        "description": ("Search the COMSOL tool catalogue by intent (Chinese or "
                        "English). Returns exact tool names, one-line purpose and "
                        "arguments. Call this before call_tool; never guess names."),
        "inputSchema": SEARCH_SCHEMA,
    },
    {
        "name": "call_tool",
        "description": ("Run one COMSOL tool by exact name. Every tool returns "
                        "compact JSON. Search first to discover the name."),
        "inputSchema": CALL_SCHEMA,
    },
]

INSTRUCTIONS = (
    "COMSOL Multiphysics 6.4 automation over MPh/JPype. The full catalogue has "
    "%d tools but only search_tools and call_tool are exposed: call "
    "search_tools('网格' / 'solve' / '温度' ...) first, then call_tool with the "
    "exact name it returns. The COMSOL client/mphserver starts on demand via "
    "comsol_start / comsol_connect. Lengthy solves should use study_solve_async "
    "or the remote_* job tools instead of a blocking study_solve."
) % len(catalog.TOOLS)


def tool_text(tools, top_k):
    lines = ["%d matches (top_k=%d):" % (len(tools), top_k)]
    for t in tools:
        lines.append(catalog.describe(t))
    return "\n".join(lines)


def do_search(args):
    query = args.get("query") or ""
    try:
        top_k = int(args.get("top_k") or 6)
    except (TypeError, ValueError):
        top_k = 6
    top_k = max(1, min(25, top_k))
    return tool_text(catalog.search(query, top_k=top_k), top_k)


def do_call(args):
    name = args.get("name")
    if not name:
        raise ToolError("name is required")
    if name == "search_tools":
        return do_search(args.get("arguments") or {})
    if name == "call_tool":
        raise ToolError("call_tool cannot call itself")
    if catalog.by_name(name) is None:
        near = catalog.close_matches(name, top_k=4)
        raise ToolError(
            "unknown tool %r. Close matches:\n%s"
            % (name, "\n".join(catalog.describe(t) for t in near)))
    return render_result(dispatch_tool(name, args.get("arguments") or {}))


# --------------------------------------------------------------------------- #
# JSON-RPC
# --------------------------------------------------------------------------- #

def handle_request(msg):
    method = msg.get("method")
    params = msg.get("params") or {}
    rid = msg.get("id")

    if method == "initialize":
        version = params.get("protocolVersion") or PROTOCOL
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": INSTRUCTIONS,
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS_LIST}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if name == "search_tools":
                text = do_search(args)
            elif name == "call_tool":
                text = do_call(args)
            else:
                raise ToolError("unknown tool %r" % name)
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            }}
        except Exception as exc:  # tool failures are results, not transport errors
            detail = "%s: %s" % (type(exc).__name__, exc)
            log("tool error: " + detail.replace("\n", " | "))
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": detail}],
                "isError": True,
            }}
    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"resources": []}}
    if method == "resources/templates/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"resourceTemplates": []}}
    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"prompts": []}}
    if method == "logging/setLevel":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": "method not found: %s" % method}}


def read_message(stream):
    """One JSON-RPC message: newline-delimited, or Content-Length framed."""
    line = stream.readline()
    if not line:
        return None
    text = line.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    if text.lower().startswith("content-length:"):
        try:
            length = int(text.split(":", 1)[1].strip())
        except ValueError:
            return None
        while True:
            head = stream.readline()
            if not head or not head.strip():
                break
        body = stream.read(length)
        return json.loads(body.decode("utf-8"))
    return json.loads(text)


def write_message(obj, stream):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    stream.write(data + b"\n")
    stream.flush()


def serve():
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    log("ready (pid %d, python %s, %d catalogue tools)"
        % (os.getpid(), sys.version.split()[0], len(catalog.TOOLS)))
    while True:
        try:
            msg = read_message(stdin)
        except Exception as exc:
            log("bad frame: %s" % exc)
            break
        if msg is None:
            break
        if "id" not in msg:
            continue  # notification (notifications/initialized, cancelled...)
        try:
            resp = handle_request(msg)
        except Exception as exc:
            log(traceback.format_exc())
            resp = {"jsonrpc": "2.0", "id": msg.get("id"),
                    "error": {"code": -32603, "message": str(exc)}}
        try:
            write_message(resp, stdout)
        except Exception as exc:
            log("write failed: %s" % exc)
            break
    log("bye")


# --------------------------------------------------------------------------- #
# CLI (for tests / troubleshooting without an MCP client)
# --------------------------------------------------------------------------- #

USAGE = """usage: server.py [--list | --search QUERY [--top-k N] | --call NAME [JSON]]

  (no args)          serve MCP over stdio
  --list             print the whole catalogue (%d tools)
  --search QUERY     ranked search, Chinese or English
  --call NAME [JSON] call one tool, e.g. --call comsol_status '{}'
  --version          print server version
""" % len(catalog.TOOLS)


def _flag_value(argv, flag, default=None):
    if flag not in argv:
        return default
    i = argv.index(flag)
    return argv[i + 1] if len(argv) > i + 1 else default


def cli(argv):
    if "--help" in argv or "-h" in argv:
        print(USAGE)
        return 0
    if "--version" in argv:
        print("%s %s (protocol %s, %d tools)"
              % (SERVER_NAME, SERVER_VERSION, PROTOCOL, len(catalog.TOOLS)))
        return 0
    if "--list" in argv:
        print("%d tools in catalogue:" % len(catalog.TOOLS))
        for t in catalog.TOOLS:
            print(catalog.describe(t))
        return 0
    if "--search" in argv:
        q = _flag_value(argv, "--search", "")
        top_k = int(_flag_value(argv, "--top-k", 10))
        print(do_search({"query": q, "top_k": top_k}))
        return 0
    if "--call" in argv:
        i = argv.index("--call")
        name = argv[i + 1] if len(argv) > i + 1 else ""
        raw = argv[i + 2] if len(argv) > i + 2 else "{}"
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            sys.stderr.write("arguments are not valid JSON: %s\n" % exc)
            return 2
        try:
            print(do_call({"name": name, "arguments": payload}))
            return 0
        except Exception as exc:
            print("ERROR (%s): %s" % (type(exc).__name__, exc))
            return 1
    serve()
    return 0


def _silence_stdout():
    """Point fd 1 at the null device so the interpreter's shutdown flush cannot
    raise after the client closed the pipe."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)
    except Exception:
        pass


def main(argv=None):
    _harden_stdio()
    code = 0
    try:
        code = cli(sys.argv[1:] if argv is None else argv)
    except KeyboardInterrupt:
        code = 130
    except (BrokenPipeError, OSError):
        # A closed pipe (`server.py --list | head`) is a normal way to stop the
        # CLI. Windows raises OSError EINVAL here, not BrokenPipeError.
        code = 0
    finally:
        try:
            sys.stdout.flush()
        except Exception:
            _silence_stdout()
    return code


if __name__ == "__main__":
    sys.exit(main())
