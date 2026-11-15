# -*- coding: utf-8 -*-
"""GUI bridge tools for dsh-comsol.

`comsol_start_gui` brings up an mphserver in multi-client mode and attaches the
COMSOL Desktop to it, so the user watches the live model in the COMSOL window
while the MCP server drives it through the Java API.

Verified on this machine (see gui_bridge.py for the evidence and the manual
references):
  * `comsol mphclient -server localhost -port <p>` opens the Desktop attached to
    that server.
  * a plain mphserver is exclusive — the Desktop evicts the API client with
    "Server is in use by another client".
  * `comsolmphserver -multi on -port <p>` accepts repeated clients, and then the
    API client keeps seeing AND driving the model the Desktop displays.
"""
import json

import gui_bridge

#: The running GUI session, so comsol_gui_status / comsol_gui_stop can report it.
_GUI_STATE = {"server": None, "port": None, "launcher_pid": None, "desktops": 0}


def _comsol_root():
    """Resolve the COMSOL install root the same way the rest of the server does."""
    import os
    root = os.environ.get("COMSOL_INSTALL_ROOT") or os.environ.get("COMSOL_ROOT")
    if root and os.path.isdir(root):
        return root
    exe = os.environ.get("COMSOL_EXE") or ""
    if exe:
        # ...\COMSOL64\Multiphysics\bin\win64\comsol.exe -> ...\COMSOL64\Multiphysics
        here = os.path.dirname(os.path.abspath(exe))
        for _ in range(3):
            here = os.path.dirname(here)
        if os.path.isdir(here):
            return here
    for cand in (
        r"C:\Program Files\COMSOL\COMSOL64\Multiphysics",
        r"C:\Program Files\COMSOL\COMSOL63\Multiphysics",
    ):
        if os.path.isdir(cand):
            return cand
    raise gui_bridge.GuiBridgeError("cannot locate a COMSOL install root")


def register_gui_tools(mcp):
    """Register the GUI bridge tools on a FastMCP instance."""

    @mcp.tool()
    def comsol_start_gui(cores: int = 4, port: int = 2036, open_desktop: bool = True) -> dict:
        """
        启动带 GUI 桥接的 COMSOL 会话：以多客户端模式起 mphserver，并把 COMSOL Desktop
        连上去。这样你在 COMSOL 窗口里看到的就是 MCP 正在操作的同一个模型。

        为什么必须多客户端：普通 mphserver 只接受一个客户端，Desktop 连上会把 API
        客户端踢掉（"Server is in use by another client"）。`-multi on` 才能两者共存。

        Args:
            cores: 计算核数（默认 4）
            port: 首选端口（默认 2036；被占用时自动换空闲端口）
            open_desktop: 是否同时打开 COMSOL Desktop（默认 True）

        Returns:
            {success, port, server_pid, desktop_pid, desktops, note}
        """
        try:
            root = _comsol_root()
            server, chosen = gui_bridge.start_server(root, port=port)
            _GUI_STATE["server"] = server
            _GUI_STATE["port"] = chosen
            result = {
                "success": True,
                "port": chosen,
                "server_pid": server.pid,
                "standalone": False,
                "multi_client": True,
            }
            if open_desktop:
                launcher, desktops = gui_bridge.launch_desktop(root, chosen)
                _GUI_STATE["launcher_pid"] = launcher.pid
                _GUI_STATE["desktops"] = desktops
                result["desktop_launcher_pid"] = launcher.pid
                result["desktops"] = desktops
                if desktops == 0:
                    result["warning"] = (
                        "Desktop launcher returned but no ComsolUI process appeared; "
                        "the server is still usable headlessly"
                    )
            result["note"] = (
                "mphserver is running with -multi on: connect the API with "
                "comsol_connect(port=%d) and the Desktop stays attached. "
                "IMPORTANT: the Desktop does NOT automatically switch to a model the API "
                "creates or edits - it stays on its welcome screen. It DOES show live "
                "changes to the model the user has open. So the reliable workflow is: the "
                "user opens/creates the model in the Desktop first, then the agent attaches "
                "to that same model; or the agent saves the model and the user opens the "
                "file (File > Open) in the Desktop." % chosen
            )
            return result
        except Exception as exc:
            return {"success": False, "error": "%s: %s" % (type(exc).__name__, exc)}

    @mcp.tool()
    def comsol_gui_status() -> dict:
        """
        查询 GUI 桥接状态：mphserver 是否在跑、端口、Desktop 窗口数量。

        即使 MCP 服务重启过（进程内状态丢失），也会通过探测端口与 Desktop 进程
        给出真实结果。

        Returns:
            {server_alive, port, server_pid, desktops, port_open}
        """
        import os
        server = _GUI_STATE.get("server")
        port = _GUI_STATE.get("port")
        alive = False
        if server is not None:
            try:
                alive = server.poll() is None
            except Exception:
                alive = False
        # Fall back to probing when this process did not start the server itself.
        if not alive:
            probe = port or int(os.environ.get("COMSOL_MCP_PORT") or 2036)
            if gui_bridge.port_open(probe):
                port = probe
                alive = True
        desktops = gui_bridge.count_desktops()
        return {
            "server_alive": alive,
            "port": port,
            "server_pid": getattr(server, "pid", None),
            "desktops": desktops,
            "port_open": gui_bridge.port_open(port) if port else False,
            "tracked_by_this_process": server is not None,
        }

    @mcp.tool()
    def comsol_gui_close(close_desktop: bool = True, stop_server: bool = False) -> dict:
        """
        关闭 GUI 桥接：可选关闭 COMSOL Desktop 窗口、可选停掉 mphserver。

        Args:
            close_desktop: 关闭所有 ComsolUI 窗口（默认 True）
            stop_server: 同时停掉 mphserver（默认 False；停了 API 会话也会断）

        Returns:
            {desktops_remaining, server_stopped}
        """
        desktops = gui_bridge.stop_desktops() if close_desktop else gui_bridge.count_desktops()
        stopped = False
        server = _GUI_STATE.get("server")
        if stop_server and server is not None:
            try:
                server.terminate()
                server.wait(timeout=15)
                stopped = True
            except Exception:
                try:
                    server.kill()
                    stopped = True
                except Exception:
                    stopped = False
            _GUI_STATE["server"] = None
            _GUI_STATE["port"] = None
        return {"desktops_remaining": desktops, "server_stopped": stopped}
