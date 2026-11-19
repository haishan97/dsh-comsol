"""dsh-comsol handlers — register + dispatch the existing COMSOL MCP tool surface.

WHY THIS FILE EXISTS
--------------------
The 155 COMSOL tools already exist, but they are **nested functions** created
inside ``register_*_tools(mcp)`` decorator blocks in
``E:\\ICE\\_tools\\COMSOL_Multiphysics_MCP\\src\\tools\\*.py``.  They cannot be
imported individually.  What we *can* do is build one ``FastMCP`` instance,
call every ``register_*_tools(mcp)`` into it, and then dispatch by name through
that instance's own tool manager::

    mcp = FastMCP("dsh-comsol")
    session.register_session_tools(mcp)      # ... x20 registration functions
    mcp._tool_manager.get_tool(name)         # -> Tool (name, description, schema)
    await mcp.call_tool(name, arguments)     # -> runs the original implementation

So this module is *only* three things — **registration**, **dispatch**, and
**result normalisation**.  Zero reimplementation of COMSOL logic.

TRAPS THAT ARE ALREADY HANDLED HERE (do not "simplify" them away)
-----------------------------------------------------------------
1. **Never import ``src.server``.**  It does ``from comsol_kb import
   register_tools`` and ``comsol_kb`` does not exist on this machine
   (``ModuleNotFoundError``).  We import ``src.tools.*`` directly instead.
2. **Registration function discovery is signature-based, not name-based.**
   ``modify.py`` exposes ``register_interpolate_tool`` and ``audit.py``
   exposes ``register_boundary_info_tool`` — neither ends in ``_tools`` — and
   ``physicsbuilder.py`` exports ``register_mphphb(filepath)`` which must NOT
   be called.  We accept a callable whose *only* positional parameter is named
   ``mcp``, defined in that module.  That rule picks exactly the 20 real
   registration functions (157 tools) and skips ``register_mphphb``.
3. **Never import ``src/tools/__init__.py``'s convenience re-exports for
   registration.**  ``audit.py`` and ``audit_repro.py`` both define
   ``register_audit_tools``; importing the *module* keeps them distinct.
4. **stdout is the JSON-RPC channel.**  Tool bodies that print would corrupt
   the MCP framing, so ``dispatch()`` redirects stdout during the call and
   logs anything captured to stderr instead.
5. **JPype allows one COMSOL client per process.**  A second ``comsol_start``
   is answered with an explicit, non-crashing error dict *before* it reaches
   MPh (whose ``Client()`` would also silently clear loaded models).
6. **One event loop for the whole process.**  A persistent loop thread keeps
   ``asyncio.run()``'s "cannot be called from a running event loop" failure
   mode away and lets background tool state survive between calls.

PUBLIC API (what server.py / bridge.py / the doctor CLI use)
------------------------------------------------------------
    ToolError                        exception raised on any dispatch failure
    dispatch(name, arguments=None)   -> plain JSON-serialisable Python data
    tool_names()                     -> sorted list[str] of the live registry
    tool_specs()                     -> [{"name","description","input_schema"}]
    tool_schema(name)                -> input JSON schema for one tool
    health()                         -> dict: deps, install, registry, contract, session
    preload()                        -> build the registry early (same as ensure_ready)

Run it directly for a smoke report::

    python handlers.py            # prints health() + a 2-tool dispatch probe

Environment
-----------
    DSH_COMSOL_PACKAGE_ROOT   override the existing MCP package root
    DSH_COMSOL_CONTRACT       override path to _contract/tools_inventory.json
    DSH_COMSOL_DISPATCH_TIMEOUT  seconds; 0/unset = block until the tool returns
    COMSOL_MCP_VERSION        forwarded to MPh (selects COMSOL back-end version)
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import inspect
import io
import json
import logging
import os
import sys
import threading
import time
import traceback
from typing import Any, Callable, Iterable

__all__ = [
    "ToolError",
    "dispatch",
    "tool_names",
    "tool_specs",
    "tool_schema",
    "health",
    "preload",
    "ensure_ready",
    "is_ready",
    "COMSOL_PACKAGE_ROOT",
    "TOOL_MODULES",
    "CONTRACT_PATH",
]

LOG = logging.getLogger("dsh_comsol.handlers")
LOG.addHandler(logging.NullHandler())

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

#: Root of the pre-existing COMSOL MCP package whose tools we reuse.
COMSOL_PACKAGE_ROOT = os.path.abspath(
    os.environ.get("DSH_COMSOL_PACKAGE_ROOT") or r"E:\ICE\_tools\COMSOL_Multiphysics_MCP"
)

#: Tool modules to import (exactly the set ``src/server.py`` registers, minus
#: the two modules that need the missing ``comsol_kb`` package:
#: ``knowledge.embedded`` and ``comsol_kb`` itself).
TOOL_MODULES: tuple[str, ...] = (
    "session",
    "model",
    "parameters",
    "geometry",
    "physics",
    "electrochemistry",
    "static_catalog",
    "physicsbuilder",
    "mesh",
    "study",
    "results",
    "audit",
    "audit_repro",
    "modify",
    "remote",
    "repro",
    "verification",
    "plot_export",
    "arc_figs",
)

_HERE = os.path.dirname(os.path.abspath(__file__))

#: Modules owned by dsh-comsol itself (they live next to this file, not in the
#: reused ``src/tools`` package).  ``extra_tools`` adds the COMSOL 6.4 model
#: operations the inherited surface never exposed: named selection sets,
#: component variables, probes, export nodes and plot groups.
EXTRA_TOOL_MODULES: tuple[str, ...] = ("extra_tools", "gui_tools")

#: ``_contract/tools_inventory.json`` — the 155-name contract for this plugin.
CONTRACT_PATH = os.environ.get("DSH_COMSOL_CONTRACT") or os.path.normpath(
    os.path.join(_HERE, os.pardir, "_contract", "tools_inventory.json")
)

#: Candidate COMSOL installations, most specific first.
_COMSOL_INSTALL_CANDIDATES = (
    r"C:\Program Files\COMSOL\COMSOL64\Multiphysics",
    r"C:\Program Files\COMSOL\COMSOL63\Multiphysics",
    r"C:\Program Files\COMSOL\COMSOL62\Multiphysics",
    r"C:\Program Files\COMSOL\COMSOL61\Multiphysics",
    r"C:\Program Files\COMSOL\COMSOL60\Multiphysics",
)


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class ToolError(RuntimeError):
    """Raised when a tool cannot be dispatched or the tool itself fails.

    Carries the offending tool name so callers (server.py) can put it in the
    ``isError`` payload without re-deriving it from the message.
    """

    def __init__(self, message: str, tool: str | None = None, kind: str = "tool_error"):
        super().__init__(message)
        self.tool = tool
        self.kind = kind  # "unknown_tool" | "import" | "tool_error" | "timeout"

    def to_dict(self) -> dict:
        return {"error": str(self), "tool": self.tool, "kind": self.kind}


# --------------------------------------------------------------------------- #
# Module state
# --------------------------------------------------------------------------- #

_LOCK = threading.RLock()          # protects registry construction
_DISPATCH_LOCK = threading.RLock()  # serialises COMSOL access (not re-entrant per tool)
_LOOP_LOCK = threading.RLock()

_mcp: Any = None                   # FastMCP instance
_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None

_STATE: dict[str, Any] = {
    "ready": False,
    "built_at": None,
    "build_seconds": None,
    "registrations": [],   # [{"module","function","added","added_names","overwritten","error"}]
    "failures": [],        # [{"module","function","error"}]
    "tool_count": 0,
    "tool_names": [],
}


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #


def _ensure_package_on_path() -> str:
    """Put the reused package root on ``sys.path`` and validate it."""
    root = COMSOL_PACKAGE_ROOT
    if not os.path.isdir(root):
        raise ToolError(
            f"COMSOL MCP package root not found: {root}. "
            "Set DSH_COMSOL_PACKAGE_ROOT to the directory that contains src/tools.",
            kind="import",
        )
    if not os.path.isdir(os.path.join(root, "src", "tools")):
        raise ToolError(
            f"{root} does not look like the COMSOL MCP package "
            "(missing src/tools). Set DSH_COMSOL_PACKAGE_ROOT.",
            kind="import",
        )
    if root not in sys.path:
        sys.path.insert(0, root)
    # Our own tool modules live beside this file; import them by bare name.
    if _HERE not in sys.path:
        sys.path.insert(0, _HERE)
    return root


def _configure_logging() -> None:
    """MPh logs at INFO while the JVM starts, which deadlocks with JPype
    (reproduced on Windows + COMSOL 6.3/6.4).  The original server.py does the
    same; we replicate it because we may be the first importer of mph."""
    logging.getLogger("mph").setLevel(logging.WARNING)


def _protect_stdout() -> None:
    """Retarget any root log handler that points at stdout onto stderr.

    Under a stdio MCP transport stdout carries the JSON-RPC framing, so a
    library that calls ``logging.basicConfig()`` before we own logging would
    corrupt every response.  Cheap, idempotent, and it only ever moves handlers
    to stderr.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        stream = getattr(handler, "stream", None)
        is_stdout = stream is sys.stdout or getattr(stream, "name", "") == "<stdout>"
        if not is_stdout:
            continue
        try:
            handler.setStream(sys.stderr)  # Python >= 3.7
        except Exception:
            try:
                handler.stream = sys.stderr
            except Exception:
                root.removeHandler(handler)


def _registration_functions(module: Any) -> list[tuple[str, Callable[[Any], Any]]]:
    """Find ``register_*_tools(mcp)``-style callables *defined in* ``module``.

    Signature-based so that ``register_interpolate_tool`` /
    ``register_boundary_info_tool`` are found while
    ``physicsbuilder.register_mphphb(filepath)`` is skipped.
    """
    found: list[tuple[str, Callable[[Any], Any]]] = []
    for name, obj in vars(module).items():
        if not name.startswith("register_") or not callable(obj):
            continue
        if getattr(obj, "__module__", None) != module.__name__:
            continue  # re-export, not defined here
        try:
            sig = inspect.signature(obj)
        except (TypeError, ValueError):
            continue
        positional = [
            p
            for p in sig.parameters.values()
            if p.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        if len(positional) != 1 or positional[0].name != "mcp":
            continue  # e.g. register_mphphb(filepath)
        found.append((name, obj))
    return found


def _live_tool_names(mcp: Any) -> set[str]:
    try:
        return {t.name for t in mcp._tool_manager.list_tools()}
    except Exception:  # pragma: no cover - defensive
        return set()


def _live_tool_ids(mcp: Any) -> dict[str, int]:
    """name -> identity of the registered Tool object (for overwrite detection)."""
    try:
        return {t.name: id(t) for t in mcp._tool_manager.list_tools()}
    except Exception:  # pragma: no cover - defensive
        return {}


def _build_registry() -> Any:
    """Import every tool module, register into ONE FastMCP, record failures."""
    global _mcp
    if _STATE["ready"] and _mcp is not None:
        return _mcp
    with _LOCK:
        if _STATE["ready"] and _mcp is not None:
            return _mcp

        started = time.perf_counter()
        root = _ensure_package_on_path()
        _configure_logging()

        try:
            from mcp.server.fastmcp import FastMCP
        except Exception as exc:  # pragma: no cover - env problem
            raise ToolError(
                f"cannot import FastMCP from the mcp package ({exc}). "
                "handlers.py must run under the MPh venv python "
                "(E:/ICE/_tools/COMSOL_Multiphysics_MCP/.venv/Scripts/python.exe).",
                kind="import",
            ) from exc

        mcp = FastMCP("dsh-comsol")
        registrations: list[dict] = []
        failures: list[dict] = []
        imported_modules: list[str] = []

        def _register_module(dotted: str, module: Any) -> None:
            """Register every ``register_*(mcp)`` defined in one imported module."""
            functions = _registration_functions(module)
            if not functions:
                failures.append(
                    {
                        "module": dotted,
                        "function": "<none>",
                        "error": "no register_*(mcp) function found",
                    }
                )
                return

            for fn_name, fn in functions:
                before_ids = _live_tool_ids(mcp)
                try:
                    fn(mcp)
                except Exception as exc:
                    failures.append(
                        {
                            "module": dotted,
                            "function": fn_name,
                            "error": f"{type(exc).__name__}: {exc}",
                            "traceback": traceback.format_exc(limit=4),
                        }
                    )
                    LOG.warning("handlers: %s.%s failed: %s", dotted, fn_name, exc)
                    continue
                after_ids = _live_tool_ids(mcp)
                added = sorted(set(after_ids) - set(before_ids))
                overwritten = sorted(
                    name
                    for name in set(after_ids) & set(before_ids)
                    if after_ids[name] != before_ids[name]
                )
                if overwritten:
                    # A later registration replaced an earlier tool of the same name.
                    LOG.warning(
                        "handlers: %s.%s overwrote existing tool(s): %s",
                        dotted,
                        fn_name,
                        overwritten,
                    )
                registrations.append(
                    {
                        "module": dotted,
                        "function": fn_name,
                        "added": len(added),
                        "added_names": added,
                        "overwritten": overwritten,
                        "error": None,
                    }
                )

        for module_name in TOOL_MODULES:
            dotted = f"src.tools.{module_name}"
            try:
                module = importlib.import_module(dotted)
            except Exception as exc:
                failures.append(
                    {
                        "module": dotted,
                        "function": "<import>",
                        "error": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc(limit=4),
                    }
                )
                LOG.warning("handlers: cannot import %s: %s", dotted, exc)
                continue
            imported_modules.append(dotted)
            _register_module(dotted, module)

        # dsh-comsol owned modules (extra_tools): imported by bare name from
        # _HERE, which _ensure_package_on_path() put on sys.path.
        for module_name in EXTRA_TOOL_MODULES:
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:
                failures.append(
                    {
                        "module": module_name,
                        "function": "<import>",
                        "error": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc(limit=4),
                    }
                )
                LOG.warning("handlers: cannot import %s: %s", module_name, exc)
                continue
            imported_modules.append(module_name)
            _register_module(module_name, module)

        names = sorted(_live_tool_names(mcp))
        _protect_stdout()
        _mcp = mcp
        _STATE.update(
            {
                "ready": True,
                "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "build_seconds": round(time.perf_counter() - started, 3),
                "registrations": registrations,
                "failures": failures,
                "tool_count": len(names),
                "tool_names": names,
                "package_root": root,
                "imported_modules": imported_modules,
            }
        )
        LOG.info(
            "handlers: registered %d tools from %d registration functions (%d failures)",
            len(names),
            len(registrations),
            len(failures),
        )
        return _mcp


def ensure_ready() -> Any:
    """Build (once) and return the shared FastMCP instance."""
    return _build_registry()


def preload() -> dict:
    """Warm the registry up front; returns a small summary (never raises)."""
    try:
        mcp = _build_registry()
        return {
            "ready": True,
            "tool_count": len(_live_tool_names(mcp)),
            "build_seconds": _STATE.get("build_seconds"),
        }
    except Exception as exc:  # pragma: no cover
        return {"ready": False, "error": f"{type(exc).__name__}: {exc}"}


def is_ready() -> bool:
    return bool(_STATE["ready"])


# --------------------------------------------------------------------------- #
# Event loop (persistent, in a daemon thread)
# --------------------------------------------------------------------------- #


def _loop_main(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop, _loop_thread
    with _LOOP_LOCK:
        if _loop is not None and not _loop.is_closed():
            return _loop
        loop = asyncio.new_event_loop()
        thread = threading.Thread(
            target=_loop_main, args=(loop,), name="dsh-comsol-loop", daemon=True
        )
        thread.start()
        _loop, _loop_thread = loop, thread
        return loop


def _run_coroutine(coro, timeout: float | None = None):
    """Run ``coro`` on the persistent loop from a synchronous caller."""
    loop = _get_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        return future.result(timeout)
    except BaseException:
        if not future.done():
            future.cancel()
        raise


def _dispatch_timeout() -> float | None:
    raw = (os.environ.get("DSH_COMSOL_DISPATCH_TIMEOUT") or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


# --------------------------------------------------------------------------- #
# Result normalisation
# --------------------------------------------------------------------------- #


def _truncate(text: str, limit: int = 2000) -> str:
    return text if len(text) <= limit else text[:limit] + f"... [{len(text)} chars]"


def _jsonable(obj: Any, _depth: int = 0) -> Any:
    """Best-effort conversion of arbitrary tool return values to JSON data."""
    if _depth > 12:
        return repr(obj)
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):  # NaN / inf
            return str(obj)
        return obj
    if isinstance(obj, dict):
        return {str(k): _jsonable(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_jsonable(v, _depth + 1) for v in obj]
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode("utf-8", "replace")

    # pydantic models (FastMCP content blocks, Tool objects, ...)
    for attr in ("model_dump", "dict"):
        dump = getattr(obj, attr, None)
        if callable(dump):
            try:
                return _jsonable(dump(mode="json") if attr == "model_dump" else dump(), _depth + 1)
            except Exception:
                try:
                    return _jsonable(dump(), _depth + 1)
                except Exception:
                    pass
    if hasattr(obj, "text") and isinstance(getattr(obj, "text"), str):
        return getattr(obj, "text")
    if hasattr(obj, "item") and callable(getattr(obj, "item")):  # numpy scalar
        try:
            return _jsonable(obj.item(), _depth + 1)
        except Exception:
            pass
    if hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:
            pass
    if hasattr(obj, "value") and type(obj).__module__ == "enum":
        return _jsonable(obj.value, _depth + 1)
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return _truncate(repr(obj))


def _normalise_content_block(block: Any) -> Any:
    """Turn one FastMCP content block into plain data."""
    block_type = getattr(block, "type", None)
    if block_type == "text":
        return getattr(block, "text", "")
    if block_type is None:
        return _jsonable(block)
    payload = {"type": block_type}
    for field in ("text", "data", "mimeType", "uri", "resource"):
        value = getattr(block, field, None)
        if value is not None:
            payload[field] = _jsonable(value)
    return payload


def _maybe_json(text: str) -> Any:
    """Parse a JSON-looking string; return the string unchanged otherwise."""
    stripped = text.strip()
    if not stripped or stripped[0] not in "{[":
        return text
    try:
        return json.loads(stripped)
    except Exception:
        return text


def _normalise_result(result: Any) -> Any:
    """Flatten what ``FastMCP.call_tool`` returns into plain JSON data.

    Shapes handled:
      * ``CallToolResult``            -> structuredContent, else content list
      * ``(content, structured)``     -> structured when present (output schema)
      * ``list[ContentBlock]``        -> single text block parsed as JSON, else text
      * anything else                 -> ``_jsonable``
    """
    # 1. CallToolResult
    structured = getattr(result, "structuredContent", None)
    if structured is None and hasattr(result, "content") and hasattr(result, "isError"):
        structured = getattr(result, "structuredContent", None)
        content = getattr(result, "content", None)
        if structured is not None:
            return _jsonable(structured)
        return _normalise_result(content)

    # 2. (content, structured) tuple from a tool with an output schema
    if isinstance(result, tuple) and len(result) == 2:
        content, structured_content = result
        if isinstance(structured_content, dict):
            return _jsonable(structured_content)
        return _normalise_result(content)

    # 3. list of content blocks
    if isinstance(result, (list, tuple)):
        blocks = list(result)
        if blocks and all(hasattr(b, "type") for b in blocks):
            if len(blocks) == 1 and getattr(blocks[0], "type", None) == "text":
                return _maybe_json(getattr(blocks[0], "text", ""))
            return [_normalise_content_block(b) for b in blocks]
        return [_jsonable(b) for b in blocks]

    # 4. plain python value returned by the function itself
    return _jsonable(result)


# --------------------------------------------------------------------------- #
# COMSOL single-client guard
# --------------------------------------------------------------------------- #


def _existing_client() -> Any:
    """Return the live MPh client of this process, or None."""
    try:
        from src.tools import session as session_module  # noqa: WPS433 (lazy by design)

        client = getattr(session_module.session_manager, "client", None)
        if client is not None:
            return client
    except Exception:
        pass
    try:
        import mph.session as mph_session  # noqa: WPS433

        return getattr(mph_session, "client", None)
    except Exception:
        return None


def _describe_client(client: Any) -> dict:
    info: dict[str, Any] = {}
    for attr in ("version", "cores", "standalone", "port", "host"):
        try:
            info[attr] = getattr(client, attr)
        except Exception:
            pass
    try:
        info["models"] = [m.name() for m in client.models()]
    except Exception:
        info["models"] = []
    return _jsonable(info)


def _session_guard(name: str) -> dict | None:
    """Pre-flight check for the two tools that create the single COMSOL client.

    Returns a *result dict* (already a valid tool answer) when the call must be
    short-circuited, or None to let the real tool run.

    Rationale: JPype permits exactly one client per process, and MPh's
    ``Client()`` failure path in ``session_manager.start()`` clears the model
    registry — so a repeated ``comsol_start`` would silently lose loaded
    models.  We answer with an explicit, actionable error instead.
    """
    if name not in ("comsol_start", "comsol_connect"):
        return None
    client = _existing_client()
    if client is None:
        return None
    info = _describe_client(client)
    return {
        "success": False,
        "already_running": True,
        "error": (
            "A COMSOL client is already alive in this process. Refusing to create a "
            "second one: JPype allows only one client per process, and re-starting "
            "would also clear the models currently loaded."
        ),
        "session": info,
        "hint": (
            "Use comsol_status / model_list to inspect the live session and keep "
            "working. Only if you really need a fresh session, call comsol_disconnect "
            "first, then comsol_start."
        ),
    }


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #


def _suggestions(name: str, limit: int = 5) -> list[str]:
    """Cheap close-name suggestions for a mistyped tool name."""
    import difflib

    candidates = _STATE.get("tool_names") or []
    if not candidates:
        return []
    return difflib.get_close_matches(name, candidates, n=limit, cutoff=0.45)


def dispatch(name: str, arguments: Any = None) -> Any:
    """Execute one COMSOL MCP tool by name and return plain JSON data.

    Parameters
    ----------
    name:
        Exact tool name (e.g. ``"comsol_status"``).  Callers should obtain it
        from ``search_tools`` rather than guessing.
    arguments:
        Tool arguments as a dict (a JSON string is accepted too). ``None`` -> ``{}``.

    Raises
    ------
    ToolError
        Unknown tool, import/registration problem, tool exception, or timeout.
        The message always names the tool and carries the original detail.
    """
    if not isinstance(name, str) or not name.strip():
        raise ToolError("tool name must be a non-empty string", kind="unknown_tool")
    name = name.strip()

    if arguments is None:
        args: dict[str, Any] = {}
    elif isinstance(arguments, str):
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except Exception as exc:
            raise ToolError(
                f"arguments for {name!r} were a string but not valid JSON: {exc}", tool=name
            ) from exc
    elif isinstance(arguments, dict):
        args = dict(arguments)
    else:
        raise ToolError(
            f"arguments for {name!r} must be a dict, got {type(arguments).__name__}",
            tool=name,
            kind="bad_arguments",
        )

    timeout = _dispatch_timeout()
    stray_stdout = io.StringIO()
    started = time.perf_counter()
    with _DISPATCH_LOCK:
        try:
            # Build (import) and execute both under the stdout guard: import-time
            # chatter must not reach the JSON-RPC stream either.
            with contextlib.redirect_stdout(stray_stdout):
                mcp = _build_registry()
                tool = mcp._tool_manager.get_tool(name)
                if tool is None:
                    near = _suggestions(name)
                    hint = (" Close matches: " + ", ".join(near)) if near else ""
                    raise ToolError(
                        f"unknown COMSOL tool {name!r}.{hint} "
                        "Use search_tools to find the exact name.",
                        tool=name,
                        kind="unknown_tool",
                    )
                guard = _session_guard(name)
                if guard is not None:
                    return guard
                result = _run_coroutine(mcp.call_tool(name, args), timeout=timeout)
        except ToolError:
            raise
        except asyncio.CancelledError as exc:  # pragma: no cover
            raise ToolError(f"{name} was cancelled", tool=name, kind="timeout") from exc
        except TimeoutError as exc:
            raise ToolError(
                f"{name} exceeded DSH_COMSOL_DISPATCH_TIMEOUT={timeout}s", tool=name, kind="timeout"
            ) from exc
        except BaseException as exc:  # noqa: BLE001 - must never kill the server
            detail = str(exc).strip() or repr(exc)
            # FastMCP re-raises as ToolError("Error executing tool x: ...") — unwrap once
            if type(exc).__name__ == "ToolError" and "Error executing tool" in detail:
                detail = detail.split("Error executing tool", 1)[1].lstrip(" :")
            raise ToolError(
                f"{name} failed: {type(exc).__name__}: {detail}",
                tool=name,
                kind="tool_error",
            ) from exc
        finally:
            stray = stray_stdout.getvalue()
            if stray.strip():
                # stdout belongs to the JSON-RPC framing; keep it off the wire.
                LOG.warning(
                    "tool %s wrote %d chars to stdout (redirected to stderr): %s",
                    name,
                    len(stray),
                    _truncate(stray, 500),
                )
                sys.stderr.write(_truncate(stray, 500))

    LOG.debug(
        "tool %s finished in %.1f ms", name, (time.perf_counter() - started) * 1000.0
    )
    return _normalise_result(result)


# --------------------------------------------------------------------------- #
# Introspection
# --------------------------------------------------------------------------- #


def tool_names() -> list[str]:
    """Sorted names of every tool reachable through :func:`dispatch`."""
    mcp = _build_registry()
    return sorted(_live_tool_names(mcp))


def tool_specs() -> list[dict]:
    """``[{"name", "description", "input_schema"}]`` for the whole registry."""
    mcp = _build_registry()
    specs = []
    for tool in mcp._tool_manager.list_tools():
        specs.append(
            {
                "name": tool.name,
                "description": (tool.description or "").strip(),
                "input_schema": _jsonable(tool.parameters or {}),
            }
        )
    specs.sort(key=lambda item: item["name"])
    return specs


def tool_schema(name: str) -> dict:
    """Input JSON schema for one tool (empty dict if unknown)."""
    mcp = _build_registry()
    tool = mcp._tool_manager.get_tool(name)
    if tool is None:
        return {}
    return _jsonable(tool.parameters or {})


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #


def _package_versions() -> dict:
    import importlib.metadata as md

    out = {}
    for dist in ("mcp", "pydantic", "mph", "jpype1", "numpy", "anyio"):
        try:
            out[dist] = md.version(dist)
        except Exception:
            out[dist] = None
    return out


def _comsol_install() -> dict:
    """Which COMSOL the *MPh stack* will actually use, plus a filesystem fallback.

    ``mph.discovery.backend()`` is authoritative: it is exactly what MPh hands to
    JPype when a client starts, so it cannot disagree with a real solve.
    """
    info: dict[str, Any] = {
        "path": None,
        "exists": False,
        "source": None,
        "version": None,
        "candidates": [],
    }

    try:
        from mph import discovery as mph_discovery  # noqa: WPS433

        backend = mph_discovery.backend()
        if isinstance(backend, dict) and backend.get("root"):
            root = str(backend["root"])
            info.update(
                {
                    "path": root,
                    "exists": os.path.isdir(root),
                    "source": "mph.discovery.backend()",
                    "version": backend.get("name"),
                    "build": backend.get("build"),
                    "server": [str(item) for item in backend.get("server") or []],
                    "jvm": str(backend.get("jvm") or ""),
                }
            )
    except Exception as exc:
        info["mph_backend_error"] = f"{type(exc).__name__}: {exc}"

    # Filesystem fallback (also reported as diagnostics when MPh succeeded).
    env_root = os.environ.get("COMSOL_MCP_COMSOL_ROOT") or os.environ.get("COMSOL_ROOT")
    candidates = ([env_root] if env_root else []) + list(_COMSOL_INSTALL_CANDIDATES)
    for candidate in candidates:
        if not candidate:
            continue
        exists = os.path.isdir(candidate)
        info["candidates"].append({"path": candidate, "exists": exists})
        if exists and not info["exists"]:
            info.update({"path": candidate, "exists": True, "source": "filesystem-scan"})
    return info


def _contract_status(live_names: Iterable[str]) -> dict:
    live = set(live_names)
    status: dict[str, Any] = {
        "path": CONTRACT_PATH,
        "exists": os.path.isfile(CONTRACT_PATH),
        "count": None,
        "missing": [],
        "extra": [],
        "satisfied": None,
    }
    if not status["exists"]:
        return status
    try:
        with open(CONTRACT_PATH, encoding="utf-8") as handle:
            payload = json.load(handle)
        names = {entry["name"] for entry in payload if isinstance(entry, dict) and "name" in entry}
    except Exception as exc:
        status["error"] = f"{type(exc).__name__}: {exc}"
        return status
    status["count"] = len(names)
    status["missing"] = sorted(names - live)
    status["extra"] = sorted(live - names)
    status["satisfied"] = not status["missing"]
    return status


def _session_status() -> dict:
    client = _existing_client()
    if client is None:
        return {"client_alive": False, "message": "No active COMSOL session."}
    info = _describe_client(client)
    info["client_alive"] = True
    try:
        from src.tools import session as session_module

        info["current_model"] = session_module.session_manager.current_model
    except Exception:
        pass
    return info


def _static_catalog_status() -> dict:
    meta_path = os.path.join(
        COMSOL_PACKAGE_ROOT, "src", "resources", "static_catalog", "meta.json"
    )
    info: dict[str, Any] = {"meta_path": meta_path, "exists": os.path.isfile(meta_path)}
    if not info["exists"]:
        return info
    try:
        with open(meta_path, encoding="utf-8") as handle:
            meta = json.load(handle)
        info["provenance_version"] = meta.get("comsol_version")
        info["provenance_root"] = meta.get("comsol_root")
        info["counts"] = meta.get("counts")
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def health() -> dict:
    """Doctor-style snapshot of everything handlers.py depends on.

    Never raises: registry/import problems are reported as data so that
    ``bin/dsh-comsol.mjs doctor`` and ``server.py`` can always print something.
    Runtime strings stay ASCII-only so they survive a cp936/cp1252 console.
    """
    report: dict[str, Any] = {
        "ok": False,
        "handlers": {
            "file": os.path.abspath(__file__),
            "python": sys.executable,
            "python_version": sys.version.split()[0],
            "pid": os.getpid(),
        },
        "package_root": {
            "path": COMSOL_PACKAGE_ROOT,
            "exists": os.path.isdir(COMSOL_PACKAGE_ROOT),
            "on_sys_path": COMSOL_PACKAGE_ROOT in sys.path,
        },
        "deps": _package_versions(),
        "comsol_install": _comsol_install(),
        "static_catalog": _static_catalog_status(),
        "registry": {
            "ready": False,
            "tools": 0,
            "build_seconds": None,
            "built_at": None,
            "modules_requested": list(TOOL_MODULES) + list(EXTRA_TOOL_MODULES),
            "modules_imported": [],
            "registration_functions": [],
            "overwritten": [],
            "failed": [],
        },
        "contract": {},
        "session": {},
        "warnings": [],
    }

    # Build first, then snapshot the state it produced.
    try:
        mcp = _build_registry()
        names = sorted(_live_tool_names(mcp))
        report["package_root"]["on_sys_path"] = COMSOL_PACKAGE_ROOT in sys.path
        report["registry"].update(
            {
                "ready": bool(_STATE["ready"]),
                "tools": len(names),
                "build_seconds": _STATE.get("build_seconds"),
                "built_at": _STATE.get("built_at"),
                "modules_imported": _STATE.get("imported_modules", []),
                "failed": _STATE["failures"],
                "registration_functions": [
                    {
                        "module": reg["module"].split(".")[-1],
                        "function": reg["function"],
                        "added": reg["added"],
                        **({"overwritten": reg["overwritten"]} if reg.get("overwritten") else {}),
                    }
                    for reg in _STATE["registrations"]
                ],
                "overwritten": sorted(
                    {name for reg in _STATE["registrations"] for name in reg.get("overwritten", [])}
                ),
            }
        )
        report["contract"] = _contract_status(names)
    except Exception as exc:
        report["registry"]["error"] = f"{type(exc).__name__}: {exc}"
        report["contract"] = {"path": CONTRACT_PATH, "exists": os.path.isfile(CONTRACT_PATH)}

    try:
        report["session"] = _session_status()
    except Exception as exc:
        report["session"] = {"client_alive": False, "error": f"{type(exc).__name__}: {exc}"}

    # ---- warnings (ASCII only) -------------------------------------------
    warnings = report["warnings"]
    if not report["package_root"]["exists"]:
        warnings.append(
            f"COMSOL MCP package root missing: {COMSOL_PACKAGE_ROOT} "
            "(set DSH_COMSOL_PACKAGE_ROOT)"
        )
    if report["registry"].get("error"):
        warnings.append(f"registry build failed: {report['registry']['error']}")
    if report["registry"]["failed"]:
        warnings.append(
            f"{len(report['registry']['failed'])} registration failure(s) - "
            "some tools are unavailable; see registry.failed"
        )
    if report["registry"]["overwritten"]:
        warnings.append(
            "duplicate tool name(s) overwritten by a later registration: "
            f"{report['registry']['overwritten']}"
        )
    contract = report["contract"]
    if contract.get("exists") and contract.get("missing"):
        warnings.append(
            f"contract mismatch: {len(contract['missing'])} tool(s) from "
            f"tools_inventory.json are not registered: {contract['missing'][:8]}"
        )
    if contract.get("exists") and contract.get("extra"):
        warnings.append(
            f"registry is a superset of the contract (+{len(contract['extra'])}): "
            f"{contract['extra']}"
        )
    install = report["comsol_install"]
    if not install.get("exists"):
        warnings.append(
            "no COMSOL installation found in the usual locations; "
            "set COMSOL_MCP_COMSOL_ROOT if COMSOL lives elsewhere"
        )
    catalog = report["static_catalog"]
    if catalog.get("exists") and catalog.get("provenance_version"):
        warnings.append(
            "static catalog was extracted from COMSOL "
            f"{catalog['provenance_version']} at {catalog.get('provenance_root')} - it is a "
            "bundled dataset, not a live probe of the installed version. Type/property names "
            "can lag a newer install; confirm critical names against a live session."
        )

    report["ok"] = bool(
        report["registry"]["ready"]
        and report["registry"]["tools"] > 0
        and not contract.get("missing")
    )
    return _jsonable(report)


# --------------------------------------------------------------------------- #
# Self-test / CLI
# --------------------------------------------------------------------------- #

if __name__ == "__main__":  # pragma: no cover
    print(json.dumps(health(), indent=2, ensure_ascii=False))
    print("\n--- dispatch probes ---")
    for probe, probe_args in (("comsol_status", {}), ("static_catalog_info", {})):
        try:
            out = dispatch(probe, probe_args)
            text = json.dumps(out, ensure_ascii=False)
            print(f"{probe}: {text[:400]}{'...' if len(text) > 400 else ''}")
        except ToolError as exc:
            print(f"{probe}: ToolError[{exc.kind}] {exc}")
