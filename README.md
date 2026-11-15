# dsh-comsol

把 **COMSOL Multiphysics 6.4** 接到 [DeepSeek Harness](https://github.com/deepseek-ai)（dsh）：
插件加载时先探测本机 COMSOL 安装与 **MPh/JPype 解释器**，再注册一个 stdio MCP 服务端，
用 **179 个工具**（渐进披露，只暴露 `search_tools` / `call_tool`）完成
“几何 → 物理场 → 多物理场耦合 → 网格 → 求解 → 后处理”，全程不离开对话。

![COMSOL](https://img.shields.io/badge/COMSOL-6.4-1f6feb)
![Windows](https://img.shields.io/badge/platform-Windows-0078d4)
![MPh](https://img.shields.io/badge/MPh-1.4-3776ab)
![License](https://img.shields.io/badge/license-MIT-green)

![icon](assets/icon.svg)

## 它是什么

一个 **dsh bundle**（不是独立服务）：`cordis.patch.yml` 往 dsh 的插件树里插入一行，
`lib/index.js` 是一个真正的 cordis 插件，被 dsh 按包名 `import` 后：

1. **探测** 本机 COMSOL（版本 / `comsol.exe` / `comsolmphserver.exe` / `comsolbatch.exe`）
   和能 `import mph` 的 Python 解释器；
2. **解析** 全部运行时路径，写出 `~/.dsh/comsol.json`；
3. **安装** `comsol` skill 到 `~/.dsh/skills/comsol`（agent 一装上就知道正确工作流）；
4. **注册** 一个 stdio MCP 服务端（`serverName: comsol`），用 **MPh venv 的 python** 启动。

### 与 dsh-abaqus-cad 的关键差异

Abaqus 插件要往 `%USERPROFILE%\abaqus_plugins` 塞一个 `*_plugin.py`，让 CAE 启动时加载
GUI 桥接。**COMSOL 没有这种机制**，也不应该有：COMSOL 由 **MPh（Python）→ JPype →
`comsolmphserver.exe`** 在进程外驱动。所以：

- 没有 GUI bridge、没有插件目录、没有 `*_plugin.py`；
- MCP 服务端**必须**用装了 `mph` + `jpype` 的解释器启动（`layout.python`），
  裸 Python 会在启动时 `ModuleNotFoundError`；
- 求解是小时级的，`toolCallTimeoutMs` 因此设成 **1800000（30 分钟）**。

## 环境要求

| 项 | 要求 |
|---|---|
| 操作系统 | Windows 10/11 |
| COMSOL | **6.4**（`C:\Program Files\COMSOL\COMSOL64\Multiphysics`） |
| MPh 解释器 | 任意 venv，`import mph` 与 `import jpype` 成功（本机：`E:\ICE\_tools\COMSOL_Multiphysics_MCP\.venv\Scripts\python.exe`，Python 3.11 + mph 1.4.0） |
| dsh | 支持 `plugin_manager` / `dsh-mcp-client` 的版本 |
| Node | 20+（dsh 自带运行时即可） |

## 先自检

`doctor` 只读文件系统 + 在候选解释器里跑一次 `import mph` 探针，**不启动 COMSOL、不求解**：

```powershell
node bin/dsh-comsol.mjs doctor
```

本机实测输出（COMSOL 6.4 + MPh venv）：

```text
dsh-comsol 0.1.0
COMSOL found : yes
Version      : 6.4 (requires 6.4+)
Supported    : yes
Install root : C:\Program Files\COMSOL\COMSOL64\Multiphysics
comsol.exe   : C:\Program Files\COMSOL\COMSOL64\Multiphysics\bin\win64\comsol.exe
mphserver    : C:\Program Files\COMSOL\COMSOL64\Multiphysics\bin\win64\comsolmphserver.exe
comsolbatch  : C:\Program Files\COMSOL\COMSOL64\Multiphysics\bin\win64\comsolbatch.exe
MPh python   : 3.11.7 (E:\ICE\_tools\COMSOL_Multiphysics_MCP\.venv\Scripts\python.exe)
MPh import   : OK - mph 1.4.0, jpype 1.7.1 [known MPh venv]
Work dir     : E:\COMSOL\work
Port / mode  : 2036 / mphserver
MCP server   : E:\ICE\_tools\dsh-comsol\mcp-server\server.py
Skill        : E:\ICE\_tools\dsh-comsol\skills\comsol -> C:\Users\86180\.dsh\skills\comsol
Config       : C:\Users\86180\.dsh\comsol.json  (not written yet)
Config state : workDir=E:\COMSOL\work python=set port=2036 mode=mphserver  (defaults, would be written on first load)
```

其他命令：

```powershell
node bin/dsh-comsol.mjs where               # 打印全部解析后的路径（JSON）
node bin/dsh-comsol.mjs doctor --json       # 机器可读
node bin/dsh-comsol.mjs check-python <exe>  # 探测任意解释器的 mph/jpype
node bin/dsh-comsol.mjs version
```

`doctor` 退出码：`0` = COMSOL 已找到、版本达标、MPh 解释器可用；否则 `1`。

## 安装

```powershell
# 已发布到 npm 后
npx dsh-comsol doctor

# 本地目录 / 开发态
node bin/dsh-comsol.mjs doctor
```

作为 bundle 安装（`package.json` 里的注册入口）：

```json
"dsh": { "bundle": { "patch": "./cordis.patch.yml" } }
```

`cordis.patch.yml` 只做一件事：

```yaml
- insert:
    - id: dsh-comsol
      name: 'dsh-comsol'
```

## 工具面：渐进披露

## GUI 桥接（在 COMSOL 窗口里看 agent 改模型）

```
comsol_start_gui(cores=4, port=2036, open_desktop=true)
```

它会以 **多客户端模式** 起 `comsolmphserver`，再把 COMSOL Desktop 连上去。
之后 `comsol_connect(port=...)` 的 API 客户端和你的 Desktop **共享同一个会话** ——
你在窗口里看到的就是 agent 正在操作的模型。

**为什么必须多客户端**：普通 mphserver 只接受一个客户端。Desktop 先连上会把 API
客户端踢掉，报 `Server is in use by another client`（已实测）。官方手册
`comsol_ref_running.38.31.html` 里的 `-multi {auto|on|off}`（"Accept repeated
client connections"）就是为此。

**Desktop 侧语法**（手册 `comsol_ref_running.38.31/33.html`）：

```
comsol mphclient -server <host> -port <port>
```

注意 `comsol.exe mphclient` 是个启动器，会立刻退出（code 0），真正的进程是
`ComsolUI.exe` —— 不要把启动器的退出当成失败。


### 实测到的三个行为（重要，别按想象用）

| 问题 | 实测结果 |
|---|---|
| **GUI 会自动显示我用 API 建的模型吗？** | **不会**。GUI 连上服务器后停在「新建」起始页；我通过 API 往服务器上的模型加了几何并重建成功，GUI 仍停在起始页（状态栏显示 `localhost: 2036`，客户端内存从 660 MB 涨到 731 MB，说明连着、也在收数据，但没进入模型视图）。 |
| **API 能改 GUI 里打开的模型吗？** | **能**。GUI 自己建的 `Untitled` 存在于服务器上，API 可以 `model_set_current` 选中它、加几何、重建，全部成功。 |
| **两个客户端会互相踢掉吗？** | **不会**。`-multi on` 下两个 API 客户端都能连、都能看到同一份模型列表。但 COMSOL 客户端/服务器模式**没有事务或锁**，所以不要两个客户端同时改同一个属性——后写的会覆盖先写的。 |


### `-open` 自动加载：能，但不稳定

手册里 `mphclient` 支持 `-open <file>`（启动 Desktop 并打开文件）。实测两次：

- ✅ 成功一次：`comsol mphclient -server localhost -port 2036 -open gui_open_test.mph`
  → 窗口标题 `gui_open_test.mph - COMSOL Multiphysics`，图形窗口里 **40×40×40 方块已渲染**
- ❌ 失败一次（先开服务器、再单独 launch 带 `-open`）：Desktop 弹出
  **「与服务器的连接已丢失，正在尝试自动重新连接」**，标题停在 `Untitled.mph`，API 侧也报
  `Not connected to a server`

结论：**不要依赖它**。可靠做法仍是「用户打开模型」或「agent 存盘、用户 File > Open」。

### 因此推荐的两种工作流

**A. 用户在 GUI 里先开模型（推荐，能实时看到我改什么）**
1. `comsol_start_gui()` 起服务器 + Desktop
2. 用户在 COMSOL 里新建或打开模型（比如 File > Open）
3. 我 `comsol_connect(port=...)` → `model_set_current("你的模型名")` → 开始改
4. **你在窗口里实时看到改动**

**B. 我先建好模型，你再看**
1. `comsol_start_gui()` + 我建模型
2. 我 `model_save(path)` 存成 .mph
3. 你在 COMSOL 里 File > Open 打开那个文件

> 之所以没有自动同步，是因为 COMSOL 的客户端/服务器模型里，每个客户端有自己的「当前模型」，
> 服务器不会主动把某个客户端的模型视图推给另一个客户端。这不是配置问题，是架构如此。


配套工具：
- `comsol_gui_status()` — server 是否在跑、端口、Desktop 窗口数（MCP 重启后也能探测）
- `comsol_gui_close(close_desktop=true, stop_server=false)` — 关窗口，可选停 server

实测记录（本机）：
```
start_gui -> server_pid 51876, port 2036, desktops 1, multi_client true
connect   -> 连上同一 port
create    -> gui_shared
block+build -> 20x20x20 mm
model_list -> [gui_shared (API 建的), Untitled (GUI 的)]   ← 两个客户端共享
```

## 项目工作台面板

侧栏里有一个 **COMSOL 项目** 面板（`dsh-comsol-workbench` 独立插件行），四个页签：

| 页签 | 内容 |
|---|---|
| **项目进度** | 扫描项目根目录，逐个模型文件夹列出模型（名称/大小/修改时间）、报告文件数、结果图数量 |
| **结果图** | 导出图的缩略图墙，点开看大图（经 `/image` 路由，路径逃逸返回 404） |
| **工具检索** | 用 `search_tools` 检索 179 个工具 |
| **会话** | MCP 入口状态 + 温度 + 向当前会话下达指令的输入框 |

头部实时显示 CPU 温度（≥85 °C 变橙色）。

项目根目录可通过 `~/.dsh/comsol.json` 的 `workbenchProjectRoot` 或环境变量
`COMSOL_PROJECT_ROOT` 配置，默认 `E:\ICE\COMSOL-Arc-Reproduction\03_Models\arc model`。

> 工作台与 MCP 服务是**两个独立的插件行**：工作台需要 `webServer`/`tools`/`agents`，
> 无头环境没有这些服务。拆开之后，无头环境仍能拿到 MCP 服务，而不是整个插件加载失败。

MCP 服务端**只广告两个工具**，179 个工具的完整 schema 不进上下文（空闲会话约几百 token）：

```
search_tools(query, top_k)   →  按意图检索目录，返回精确工具名 + 一行说明 + 参数
call_tool(name, arguments)   →  用精确名字执行
```

- 目录（`mcp-server/catalog.py`）带中英双语 keywords，中文按字切词（`CJK` 无空格）；
- 工具失败是**结果**不是传输错误（`isError: true`），模型能看到错误并自我修正；
- 打错工具名会返回近似候选，不会卡死；
- 长求解请优先用作业类工具（后台跑 + 轮询），不要占住一次工具调用。

> 具体工具名与参数以 `mcp-server/catalog.py` 为准，本 README 不复制目录。

## 配置文件

首次加载会写 `~/.dsh/comsol.json`（`DSH_HOME` 可覆盖 `~/.dsh`）：

```json
{
  "workDir": "E:\\COMSOL\\work",
  "python": "E:\\ICE\\_tools\\COMSOL_Multiphysics_MCP\\.venv\\Scripts\\python.exe",
  "comsolExe": "C:\\Program Files\\COMSOL\\COMSOL64\\Multiphysics\\bin\\win64\\comsol.exe",
  "mphserverExe": "C:\\Program Files\\COMSOL\\COMSOL64\\Multiphysics\\bin\\win64\\comsolmphserver.exe",
  "batchExe": "C:\\Program Files\\COMSOL\\COMSOL64\\Multiphysics\\bin\\win64\\comsolbatch.exe",
  "port": 2036,
  "mode": "mphserver",
  "comsolVersion": "6.4",
  "comsolInstallRoot": "C:\\Program Files\\COMSOL\\COMSOL64\\Multiphysics",
  "minVersion": "6.4",
  "mphVersion": "1.4.0",
  "pythonVersion": "3.11.7"
}
```

| 键 | 含义 |
|---|---|
| `workDir` | `.mph` 模型与导出的工作目录（默认 `E:\COMSOL\work`，其次 `D:\COMSOL\work`） |
| `python` | **MPh 解释器**，MCP 服务端用它启动 |
| `comsolExe` / `mphserverExe` / `batchExe` | COMSOL 可执行文件 |
| `port` | COMSOL server 端口，默认 `2036` |
| `mode` | `mphserver`（连/起一个 server）或 `client`（由 MPh 自行管理） |
| `comsolVersion` | 探测到的版本快照（与检测不一致时 `doctor` 会提示 drift） |

## 环境变量

| 变量 | 作用 |
|---|---|
| `COMSOL_HOME` | COMSOL 安装根（`…\COMSOL64\Multiphysics`） |
| `COMSOL_EXE` | 显式 `comsol.exe` |
| `COMSOL_MPHSERVER_EXE` | 显式 `comsolmphserver.exe` |
| `COMSOL_MCP_PYTHON` | **MPh 解释器**（优先级最高） |
| `COMSOL_MCP_WORKDIR` | 默认工作目录 |
| `COMSOL_MCP_PORT` | COMSOL server 端口（默认 2036） |
| `COMSOL_MCP_MODE` | `mphserver` / `client` |
| `COMSOL_MIN_VERSION` | 最低可接受版本（默认 `6.4`） |
| `COMSOL_ALLOW_UNSUPPORTED=1` | 低于基线也强行加载（仅实验） |
| `DSH_HOME` | dsh 主目录（默认 `~/.dsh`） |

服务端进程会收到：`COMSOL_MCP_WORKDIR`、`COMSOL_EXE`、`COMSOL_MPHSERVER_EXE`、
`COMSOL_BATCH_EXE`、`COMSOL_VERSION`、`COMSOL_MIN_VERSION`、`COMSOL_MCP_PORT`、
`COMSOL_MCP_MODE`，以及 `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8` / `PYTHONUNBUFFERED=1`。

## 故障排查

| 现象 | 处理 |
|---|---|
| `COMSOL Multiphysics was not found` | 设 `COMSOL_HOME` 或 `COMSOL_EXE`；跑 `doctor` 看搜索到哪一步 |
| `no Python interpreter with the MPh package was found` | 设 `COMSOL_MCP_PYTHON` 指向 `…\.venv\Scripts\python.exe`；用 `check-python` 验证 |
| 启动即 `ModuleNotFoundError: mph` | 服务端被裸 Python 启动了 —— 检查 `~/.dsh/comsol.json` 的 `python` |
| `Only one client can be instantiated per Python session` | MPh 每个 Python 进程只允许一个 client；别在同一进程里反复 `Client()` |
| 求解很久后工具超时 | 用后台作业类工具；`toolCallTimeoutMs` 已是 30 分钟 |
| 端口被占用 | 改 `COMSOL_MCP_PORT` / `comsol.json` 的 `port` |

## 目录结构

```
dsh-comsol/
├── package.json          # dsh bundle 清单（dsh.bundle.patch 是注册入口）
├── cordis.patch.yml      # 插入一行插件
├── lib/
│   ├── index.js          # cordis 插件 apply(ctx)
│   ├── paths.mjs         # 路径解析 + ~/.dsh/comsol.json
│   └── detect.mjs        # COMSOL / MPh 解释器探测
├── bin/dsh-comsol.mjs    # doctor / where / check-python / version
├── assets/icon.svg
├── mcp-server/           # server.py · catalog.py · bridge.py · handlers.py（只暴露 2 个工具）
└── skills/comsol/        # SKILL.md + references/，安装到 ~/.dsh/skills/comsol
```

## 许可

MIT，见 `LICENSE`；第三方说明见 `NOTICE.md`。
COMSOL Multiphysics 是 COMSOL AB 的商标，本仓库不包含任何 COMSOL 代码。
