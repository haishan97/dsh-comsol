# -*- coding: utf-8 -*-
"""Host-side bridge: COMSOL install discovery, session state, job bookkeeping.

This module owns the *knowledge* about a COMSOL installation and about the
state left on disk between MCP calls. It deliberately does not import MPh or
jpype: the MCP server must be able to answer `search_tools` (and `--list`) on a
bare Python 3.8+ interpreter. Actual execution -- starting mphserver, running
Java API calls, solving -- belongs to handlers.py.

State layout (all under DSH_HOME, default ~/.dsh):

    <DSH_HOME>/comsol.json            user config (workDir, port, exe paths)
    <DSH_HOME>/comsol/session.json    live session record (pid, port, version)
    <DSH_HOME>/comsol/jobs.json       job registry (remote/background solves)
    <DSH_HOME>/comsol/work/           default scratch / model directory
    <DSH_HOME>/comsol/logs/           mphserver logs

Environment overrides: COMSOL_MCP_WORKDIR, COMSOL_EXE, COMSOL_MPHSERVER_EXE,
COMSOL_MCP_PORT, COMSOL_MCP_VERSION, DSH_HOME.
"""
import json
import os
import re
import shutil
import socket
import subprocess

#: Suppress the console window for child processes (otherwise every spawn flashes
#: a black command window on the user's desktop).
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
import sys
import time

HOME = os.path.expanduser("~")
DSH_HOME = os.environ.get("DSH_HOME") or os.path.join(HOME, ".dsh")
CONFIG_PATH = os.path.join(DSH_HOME, "comsol.json")
STATE_DIR = os.path.join(DSH_HOME, "comsol")
SESSION_PATH = os.path.join(STATE_DIR, "session.json")
JOBS_PATH = os.path.join(STATE_DIR, "jobs.json")
WORK_DIR = os.path.join(STATE_DIR, "work")
LOG_DIR = os.path.join(STATE_DIR, "logs")

# COMSOL's mphserver listens on 2036 by default; mph's Client() uses the same.
DEFAULT_PORT = 2036

# Job states kept in jobs.json.
QUEUED = "QUEUED"
RUNNING = "RUNNING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"
TERMINAL = (COMPLETED, FAILED, CANCELLED)


class BridgeError(RuntimeError):
    """Anything that stops the bridge from doing what was asked."""


# --------------------------------------------------------------------------- #
# small fs helpers
# --------------------------------------------------------------------------- #

def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    try:
        os.replace(tmp, path)  # atomic-ish: never leaves a half-written state file
    except OSError:
        os.remove(tmp)
        raise


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _program_files_roots():
    roots = []
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        val = os.environ.get(var)
        if val:
            roots.append(val)
    for drive in ("C:", "D:", "E:", "F:"):
        roots.append(os.path.join(drive + os.sep, "Program Files"))
    out = []
    for r in roots:
        if r and r not in out and os.path.isdir(r):
            out.append(r)
    return out


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #

#: env var -> config key. The plugin (lib/index.js) passes these to the server
#: process and also writes them into comsol.json; env wins because the plugin
#: may re-point them per session.
ENV_KEYS = {
    "COMSOL_MCP_WORKDIR": "workDir",
    "COMSOL_EXE": "comsolExe",
    "COMSOL_MPHSERVER_EXE": "mphserverExe",
    "COMSOL_BATCH_EXE": "batchExe",
    "COMSOL_VERSION": "comsolVersion",
    "COMSOL_MIN_VERSION": "minVersion",
    "COMSOL_MCP_MODE": "mode",
}


def load_config():
    """User config + env overrides. Never raises, never touches cwd.

    Keys (from the plugin-scaffold contract): workDir, python, comsolExe,
    mphserverExe, batchExe, port, mode, comsolVersion, comsolInstallRoot,
    minVersion, mphVersion, pythonVersion.
    """
    cfg = _read_json(CONFIG_PATH, {})
    if not isinstance(cfg, dict):
        cfg = {}
    for env_key, cfg_key in ENV_KEYS.items():
        if os.environ.get(env_key):
            cfg[cfg_key] = os.environ[env_key]
    if os.environ.get("COMSOL_MCP_PORT"):
        try:
            cfg["port"] = int(os.environ["COMSOL_MCP_PORT"])
        except ValueError:
            pass
    try:
        cfg["port"] = int(cfg.get("port") or DEFAULT_PORT)
    except (TypeError, ValueError):
        cfg["port"] = DEFAULT_PORT
    cfg.setdefault("host", "localhost")
    cfg.setdefault("timeout", 1800)          # COMSOL solves are hour-scale
    cfg.setdefault("mode", "mphserver")      # mphserver | gui
    cfg.setdefault("cores", None)
    if not cfg.get("workDir"):
        cfg["workDir"] = WORK_DIR
    cfg["workDir"] = os.path.abspath(os.path.expanduser(str(cfg["workDir"])))
    # exe paths: contract value -> install root -> scan -> PATH
    if not cfg.get("comsolExe"):
        cfg["comsolExe"] = _exe_from_root(cfg.get("comsolInstallRoot"), "comsol.exe") \
            or find_comsol("comsol") or ""
    if not cfg.get("mphserverExe"):
        cfg["mphserverExe"] = _exe_from_root(cfg.get("comsolInstallRoot"),
                                             "comsolmphserver.exe") \
            or find_comsol("mphserver") or ""
    if not cfg.get("batchExe"):
        cfg["batchExe"] = _exe_from_root(cfg.get("comsolInstallRoot"),
                                         "comsolbatch.exe") \
            or find_comsol("batch") or ""
    if not cfg.get("comsolVersion"):
        cfg["comsolVersion"] = detect_version() or ""
    return cfg


def _exe_from_root(root, exe):
    """<installRoot>/Multiphysics/bin/win64/<exe>, if it exists."""
    if not root:
        return None
    path = os.path.join(str(root), "Multiphysics", "bin", "win64", exe)
    return path if os.path.exists(path) else None


def config_summary(cfg=None):
    """The subset worth logging at startup (no secrets, no huge paths)."""
    cfg = cfg or load_config()
    return {k: cfg.get(k) for k in
            ("workDir", "python", "comsolExe", "mphserverExe", "batchExe",
             "port", "mode", "comsolVersion", "comsolInstallRoot", "minVersion")}


def save_config(cfg):
    _write_json(CONFIG_PATH, cfg)
    return CONFIG_PATH


# --------------------------------------------------------------------------- #
# installation discovery
# --------------------------------------------------------------------------- #

_DETECT_CACHE = {}


def _parse_version(root):
    """Version from <root>/Multiphysics/about.txt ("SOFTWARE COMPONENTS IN
    COMSOL 6.4") or from the directory name (COMSOL64 / COMSOL6.4)."""
    for rel in (os.path.join("Multiphysics", "about.txt"), "about.txt"):
        path = os.path.join(root, rel)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                head = fh.read(4000)
        except Exception:
            continue
        m = re.search(r"COMSOL\s+(\d+(?:\.\d+)+)", head)
        if m:
            return m.group(1)
    m = re.search(r"(\d+(?:\.\d+)+)", os.path.basename(root.rstrip("\\/")))
    if m:
        return m.group(1)
    m = re.search(r"(\d)(\d)", os.path.basename(root.rstrip("\\/")))
    if m and os.path.basename(root).upper().startswith("COMSOL"):
        return "%s.%s" % (m.group(1), m.group(2))
    return None


def list_installations(force=False):
    """Every COMSOL install found, newest first.

    Layout handled: <PF>/COMSOL/COMSOL*/Multiphysics/bin/win64 and the flat
    <PF>/COMSOL*/Multiphysics/bin/win64. This machine has COMSOL64, not
    COMSOL6.4, so the directory name is only a hint -- about.txt is the truth.
    """
    if _DETECT_CACHE.get("installs") is not None and not force:
        return _DETECT_CACHE["installs"]
    found = []
    seen = set()
    for pf in _program_files_roots():
        bases = [os.path.join(pf, "COMSOL")]
        try:
            bases += [os.path.join(pf, d) for d in os.listdir(pf)
                      if d.upper().startswith("COMSOL")]
        except OSError:
            pass
        for base in bases:
            if not os.path.isdir(base):
                continue
            try:
                names = os.listdir(base)
            except OSError:
                continue
            candidates = []
            if os.path.isdir(os.path.join(base, "Multiphysics")):
                candidates.append(base)          # flat <PF>/COMSOL64/Multiphysics
            candidates += [os.path.join(base, n) for n in names
                           if os.path.isdir(os.path.join(base, n, "Multiphysics"))]
            for root in candidates:
                bin_dir = os.path.join(root, "Multiphysics", "bin", "win64")
                if not os.path.isdir(bin_dir) or bin_dir.lower() in seen:
                    continue
                seen.add(bin_dir.lower())
                entry = {
                    "root": root,
                    "binDir": bin_dir,
                    "version": _parse_version(root),
                    "comsol": os.path.join(bin_dir, "comsol.exe"),
                    "mphserver": os.path.join(bin_dir, "comsolmphserver.exe"),
                    "batch": os.path.join(bin_dir, "comsolbatch.exe"),
                }
                for key in ("comsol", "mphserver", "batch"):
                    if not os.path.exists(entry[key]):
                        entry[key] = None
                found.append(entry)

    def sort_key(entry):
        parts = []
        for piece in (entry.get("version") or "0").split("."):
            try:
                parts.append(int(piece))
            except ValueError:
                parts.append(0)
        return parts

    found.sort(key=sort_key, reverse=True)
    _DETECT_CACHE["installs"] = found
    return found


def detect_version(force=False):
    """Installed COMSOL version string, e.g. "6.4", or None."""
    if _DETECT_CACHE.get("version") and not force:
        return _DETECT_CACHE["version"]
    installs = list_installations(force=force)
    version = installs[0]["version"] if installs else None
    _DETECT_CACHE["version"] = version
    return version


def find_comsol(kind="comsol"):
    """Path to comsol.exe / comsolmphserver.exe / comsolbatch.exe.

    Order: env var -> PATH -> scanned installs. Returns None when nothing is
    installed; callers must handle that (this machine has COMSOL64 only).
    """
    kind = (kind or "comsol").lower()
    if kind in ("mphserver", "server"):
        entry_key, env_key, exe = "mphserver", "COMSOL_MPHSERVER_EXE", "comsolmphserver.exe"
    elif kind in ("batch", "comsolbatch"):
        entry_key, env_key, exe = "batch", "COMSOL_BATCH_EXE", "comsolbatch.exe"
    else:
        entry_key, env_key, exe = "comsol", "COMSOL_EXE", "comsol.exe"
    env = os.environ.get(env_key)
    if env and os.path.exists(env):
        return env
    which = shutil.which(exe[:-4])
    if which:
        return which
    for install in list_installations():
        path = install.get(entry_key)
        if path and os.path.exists(path):
            return path
    return None


def find_mphserver():
    return find_comsol("mphserver")


def find_batch():
    return find_comsol("batch")


def mode(cfg=None):
    """mphserver (headless, default) or gui."""
    return (cfg or load_config()).get("mode") or "mphserver"


def doctor():
    """One-call environment report: is COMSOL usable from here?"""
    installs = list_installations()
    version = detect_version()
    cfg = load_config()
    return {
        "dshHome": DSH_HOME,
        "configPath": CONFIG_PATH,
        "stateDir": STATE_DIR,
        "installs": [{"version": i["version"], "root": i["root"]} for i in installs],
        "version": version,
        "config": config_summary(cfg),
        "comsolExe": cfg.get("comsolExe"),
        "mphserverExe": cfg.get("mphserverExe"),
        "batchExe": cfg.get("batchExe"),
        "mode": mode(cfg),
        "port": cfg.get("port"),
        "serverAlive": server_alive(cfg),
        "workDir": cfg.get("workDir"),
        "session": session_state(),
        "jobs": len(list_jobs()),
        "python": sys.executable,
    }


# --------------------------------------------------------------------------- #
# work dir / python
# --------------------------------------------------------------------------- #

def work_dir(cfg=None):
    cfg = cfg or load_config()
    return os.path.abspath(os.path.expanduser(cfg.get("workDir") or WORK_DIR))


def ensure_work_dir(cfg=None):
    path = work_dir(cfg)
    os.makedirs(path, exist_ok=True)
    return path


def ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)
    return LOG_DIR


def python_exe(cfg=None):
    """Interpreter that should run handlers.py (the MPh venv one)."""
    cfg = cfg or load_config()
    configured = cfg.get("python")
    if configured and os.path.exists(configured):
        return configured
    return sys.executable


# --------------------------------------------------------------------------- #
# mphserver liveness (plain sockets, no MPh)
# --------------------------------------------------------------------------- #

def port_open(port, host="localhost", timeout=0.6):
    """True when something accepts a TCP connection on host:port."""
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False
    sock = None
    try:
        sock = socket.create_connection((host or "localhost", port), timeout)
        return True
    except OSError:
        return False
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def server_alive(cfg=None):
    cfg = cfg or load_config()
    return port_open(cfg.get("port") or DEFAULT_PORT, cfg.get("host") or "localhost")


def wait_for_server(port=None, host="localhost", timeout=60.0, poll=0.5):
    """Block until mphserver accepts connections. Returns True/False."""
    port = int(port or (load_config().get("port") or DEFAULT_PORT))
    deadline = time.time() + float(timeout)
    while time.time() < deadline:
        if port_open(port, host):
            return True
        time.sleep(poll)
    return False


# --------------------------------------------------------------------------- #
# session state (session.json)
# --------------------------------------------------------------------------- #

def session_state():
    """Recorded session plus liveness, e.g. {"pid":..., "port":..., "alive":...}."""
    recorded = _read_json(SESSION_PATH, {})
    if not isinstance(recorded, dict):
        recorded = {}
    state = dict(recorded)
    port = state.get("port") or load_config().get("port") or DEFAULT_PORT
    host = state.get("host") or "localhost"
    state["port"] = port
    state["host"] = host
    state["recorded"] = bool(recorded)
    state["alive"] = port_open(port, host)
    if state.get("pid"):
        state["pidAlive"] = pid_alive(state["pid"])
    # stale = a session was recorded but nothing answers and its pid is gone
    state["stale"] = bool(recorded) and not state["alive"] and not state.get("pidAlive")
    return state


def save_session(**fields):
    """Merge fields into session.json (pid, port, version, started, model...)."""
    state = _read_json(SESSION_PATH, {})
    if not isinstance(state, dict):
        state = {}
    state.update(fields)
    state.setdefault("started", _now())
    state["updated"] = _now()
    _write_json(SESSION_PATH, state)
    return state


def clear_session():
    try:
        os.remove(SESSION_PATH)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# mphserver process helpers (knowledge only; handlers decides when to launch)
# --------------------------------------------------------------------------- #

def mphserver_command(port=None, cfg=None):
    """argv that starts a headless COMSOL server, or None if not installed."""
    cfg = cfg or load_config()
    exe = cfg.get("mphserverExe") or find_mphserver()
    if not exe:
        return None
    argv = [exe, "-port", str(int(port or cfg.get("port") or DEFAULT_PORT))]
    if cfg.get("cores"):
        argv += ["-np", str(int(cfg["cores"]))]
    return argv


def start_mphserver(port=None, cfg=None, timeout=90.0):
    """Launch comsolmphserver detached and record the session.

    Not called by this module or by server.py -- handlers.py owns execution.
    """
    cfg = cfg or load_config()
    port = int(port or cfg.get("port") or DEFAULT_PORT)
    if port_open(port):
        save_session(port=port, host="localhost", version=detect_version(),
                     started=_now(), external=True)
        return {"started": False, "reason": "port already open", "port": port}
    argv = mphserver_command(port, cfg)
    if not argv:
        raise BridgeError("comsolmphserver.exe not found; install COMSOL or set "
                          "COMSOL_MPHSERVER_EXE")
    logs = ensure_log_dir()
    log_path = os.path.join(logs, "mphserver_%d.log" % port)
    creation = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | CREATE_NO_WINDOW
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT,
                                creationflags=creation,
                                cwd=ensure_work_dir(cfg))
    ok = wait_for_server(port, timeout=timeout)
    save_session(pid=proc.pid, port=port, host="localhost",
                 version=detect_version(), started=_now(), log=log_path)
    return {"started": True, "pid": proc.pid, "port": port,
            "alive": ok, "log": log_path}


def stop_mphserver(pid=None, timeout=10.0):
    """Terminate the recorded mphserver (or an explicit pid). Best effort."""
    if pid is None:
        pid = (_read_json(SESSION_PATH, {}) or {}).get("pid")
    if not pid:
        return {"stopped": False, "reason": "no pid recorded"}
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                           capture_output=True, timeout=timeout)
        else:
            os.kill(int(pid), 15)
    except Exception as exc:
        return {"stopped": False, "pid": pid, "error": str(exc)}
    deadline = time.time() + timeout
    while time.time() < deadline and pid_alive(pid):
        time.sleep(0.3)
    clear_session()
    return {"stopped": True, "pid": pid, "alive": pid_alive(pid)}


def pid_alive(pid):
    """True while the process exists (Windows and POSIX, no third-party libs)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            k32.GetExitCodeProcess.restype = wintypes.BOOL
            k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE,
                                               ctypes.POINTER(wintypes.DWORD)]
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = k32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
            if not handle:
                err = ctypes.get_last_error()
                return err != 87  # 87 = ERROR_INVALID_PARAMETER -> gone
            code = wintypes.DWORD()
            ok = k32.GetExitCodeProcess(handle, ctypes.byref(code))
            k32.CloseHandle(handle)
            if not ok:
                return True
            return code.value == 259  # STILL_ACTIVE
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# job registry (jobs.json)
# --------------------------------------------------------------------------- #

def _read_jobs():
    jobs = _read_json(JOBS_PATH, {})
    return jobs if isinstance(jobs, dict) else {}


def _write_jobs(jobs):
    _write_json(JOBS_PATH, jobs)


def register_job(name, **fields):
    """Create or update one job record. Returns the stored record."""
    if not name:
        raise BridgeError("job name is required")
    jobs = _read_jobs()
    rec = jobs.get(name) or {"name": name, "created": _now()}
    rec.update(fields)
    rec["name"] = name
    rec["updated"] = _now()
    rec.setdefault("state", QUEUED)
    jobs[name] = rec
    _write_jobs(jobs)
    return rec


def update_job(name, **fields):
    jobs = _read_jobs()
    rec = jobs.get(name)
    if rec is None:
        raise BridgeError("unknown job %r" % name)
    rec.update(fields)
    rec["updated"] = _now()
    jobs[name] = rec
    _write_jobs(jobs)
    return rec


def get_job(name):
    return _read_jobs().get(name)


def list_jobs(state=None):
    """Job records, newest first; optionally filtered by state."""
    jobs = list(_read_jobs().values())
    if state:
        want = str(state).upper()
        jobs = [j for j in jobs if str(j.get("state", "")).upper() == want]
    jobs.sort(key=lambda j: str(j.get("updated") or j.get("created") or ""), reverse=True)
    return jobs


def remove_job(name):
    jobs = _read_jobs()
    if name not in jobs:
        return False
    del jobs[name]
    _write_jobs(jobs)
    return True


def refresh_jobs():
    """Mark RUNNING jobs whose pid died as FAILED (or COMPLETED with exitCode)."""
    jobs = _read_jobs()
    changed = False
    for rec in jobs.values():
        if str(rec.get("state", "")).upper() != RUNNING:
            continue
        pid = rec.get("pid")
        if pid and not pid_alive(pid):
            code = rec.get("returncode")
            rec["state"] = COMPLETED if code == 0 else FAILED
            rec["updated"] = _now()
            changed = True
    if changed:
        _write_jobs(jobs)
    return jobs


# --------------------------------------------------------------------------- #
# CLI (troubleshooting)
# --------------------------------------------------------------------------- #

def _main(argv):
    if not argv or "--doctor" in argv or "-d" in argv:
        print(json.dumps(doctor(), indent=2, ensure_ascii=False))
        return 0
    if "--paths" in argv:
        for entry in list_installations():
            print("%-6s %s" % (entry.get("version") or "?", entry["binDir"]))
        print("config :", CONFIG_PATH)
        print("session:", SESSION_PATH)
        print("jobs   :", JOBS_PATH)
        print("workDir:", work_dir())
        return 0
    if "--jobs" in argv:
        print(json.dumps(list_jobs(), indent=2, ensure_ascii=False))
        return 0
    if "--version" in argv:
        print(detect_version() or "not installed")
        return 0
    print(__doc__.strip())
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
