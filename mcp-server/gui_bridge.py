# -*- coding: utf-8 -*-
"""COMSOL GUI bridge for dsh-comsol.

Starts an `comsolmphserver` in **multi-client** mode and attaches the COMSOL
Desktop to it, so the user sees the live model in the COMSOL window while the
MCP server drives it through the Java API.

Why `-multi on` is required
---------------------------
By default an mphserver accepts ONE client. If the Desktop connects first, the
API client is kicked out with "Server is in use by another client" (reproduced).
The 6.4 Reference Manual (comsol_ref_running.38.31.html) documents:

    -multi {auto} | on | off    Accept repeated client connections.

With `-multi on`, both the Desktop and the API client hold the same session.
Verified on this machine: the API client kept seeing the model list while the
Desktop was attached, and kept driving it (set a parameter, resized a block).

Desktop side syntax (comsol_ref_running.38.31/33.html,
"COMSOL Multiphysics Client Commands"):

    comsol mphclient -server <server name> -port <port>

Note `comsol.exe mphclient` is a launcher: it exits immediately (code 0) and the
real process is `ComsolUI.exe`. Do not treat the launcher's exit as a failure.

No third-party packages beyond MPh, which the MCP server already needs.
"""
import os
import socket
import subprocess
import sys
import time

DEFAULT_PORT = 2036
START_TIMEOUT = 90.0

#: Suppress the console window for every child process.
#: Without this, each `nvidia-smi` / `powershell` / `comsolmphserver` spawn flashes a
#: black console window on the user's desktop (reported: "命令窗口一直弹").
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class GuiBridgeError(RuntimeError):
    pass


def _log(msg):
    sys.stderr.write("[gui-bridge] %s\n" % msg)
    sys.stderr.flush()


def port_open(port, host="127.0.0.1", timeout=1.0):
    with socket.socket() as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def find_bin_dir(comsol_root):
    """Return the win64 bin folder for a COMSOL install root."""
    candidates = [
        os.path.join(comsol_root, "bin", "win64"),
        os.path.join(comsol_root, "bin"),
        comsol_root,
    ]
    for cand in candidates:
        if os.path.exists(os.path.join(cand, "comsolmphserver.exe")):
            return cand
    raise GuiBridgeError(
        "comsolmphserver.exe not found under %s (looked in %s)"
        % (comsol_root, ", ".join(candidates))
    )


def _wait_port(port, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(port):
            return True
        time.sleep(0.5)
    return False


def _free_port(preferred):
    """Return `preferred` if free, else a free ephemeral port."""
    if not port_open(preferred):
        return preferred
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_server(comsol_root, port=DEFAULT_PORT, timeout=START_TIMEOUT):
    """Start `comsolmphserver -multi on` and return (process, port)."""
    bin_dir = find_bin_dir(comsol_root)
    exe = os.path.join(bin_dir, "comsolmphserver.exe")
    chosen = _free_port(port)
    args = [exe, "-multi", "on", "-port", str(chosen), "-silent"]
    _log("starting: " + " ".join(args))
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            close_fds=True, creationflags=CREATE_NO_WINDOW)
    if not _wait_port(chosen, timeout):
        try:
            proc.kill()
        except Exception:
            pass
        raise GuiBridgeError(
            "mphserver did not open port %d within %ds (pid %s)"
            % (chosen, timeout, proc.pid)
        )
    _log("mphserver up on port %d (pid %d)" % (chosen, proc.pid))
    return proc, chosen


def launch_desktop(comsol_root, port, server_name="localhost"):
    """Launch the COMSOL Desktop attached to `port`. Returns the launcher Popen."""
    bin_dir = find_bin_dir(comsol_root)
    exe = os.path.join(bin_dir, "comsol.exe")
    args = [exe, "mphclient", "-server", server_name, "-port", str(port)]
    _log("launching Desktop: " + " ".join(args))
    proc = subprocess.Popen(args, close_fds=True, creationflags=CREATE_NO_WINDOW)
    # The launcher exits 0 once ComsolUI.exe is spawned; give it a moment and
    # report whether a Desktop process actually appeared.
    time.sleep(6.0)
    ui_count = count_desktops()
    return proc, ui_count


def count_desktops():
    """How many ComsolUI.exe processes are running (Windows only)."""
    if os.name != "nt":
        return 0
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process ComsolUI -ErrorAction SilentlyContinue | Measure-Object).Count"],
            capture_output=True, text=True, timeout=20,
            creationflags=CREATE_NO_WINDOW,
        )
        return int((out.stdout or "0").strip() or 0)
    except Exception:
        return 0


def stop_desktops():
    """Close every COMSOL Desktop window."""
    if os.name != "nt":
        return 0
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process ComsolUI -ErrorAction SilentlyContinue | Stop-Process -Force"],
            capture_output=True, text=True, timeout=20,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        pass
    return count_desktops()
