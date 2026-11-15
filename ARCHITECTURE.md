# dsh-comsol 架构设计（源自 dsh-abaqus-cad 的知识逻辑）

日期：2026-11-12
参考实现：`Polymerizedcat/dsh-abaqus-cad` v0.4.0（"A DeepSeek Harness Plugin for Abaqus/CAE"，MIT）
本地副本：`E:\ICE\_tools\dsh-comsol\_contract\dsh-abaqus-cad-main\`

---

## 一、这个插件的核心思想：渐进披露（Progressive Disclosure）

这是整个设计里**最值得抄的一点**。

Abaqus 插件有 21 个工具。如果把 21 个工具的完整 JSON Schema 全部塞给模型，每次会话开头就要吃掉几千 token，而且模型面对一堆相似工具容易选错。

它的解法是：**MCP 只暴露 2 个工具**

```
search_tools(query, top_k)   →  按意图检索目录，返回精确工具名 + 一行说明 + 参数
call_tool(name, arguments)   →  用精确名字执行
```

完整目录（`catalog.py` 里的 `TOOLS` 列表）**不进上下文**，只在被检索时才出现。

效果（README 原文）：空闲会话从「整套 schema」降到 **约 250 token**。

对我们的意义：COMSOL 有 **155 个工具**，比 Abaqus 多 7 倍。如果直接暴露，光工具定义就能撑爆上下文——事实上我这几轮用 MCP 时，`physics_list_features` 一个返回就上万 token。**这个设计对 COMSOL 比 Abaqus 更必要。**

### 搜索打分算法（`catalog.py: search()`）

```python
score = 0
if query in tool_name:            score += 8    # 名字子串命中
for kw in keywords:
    if query == kw or query in kw or kw in query:
        score += 6                              # 关键词命中
    for tok in tokens(query):
        if tok in kw or kw in tok:
            score += 2
if query in summary:              score += 3
for tok in tokens(query):
    if tok in summary:            score += 1
for alias, names in ALIASES:
    if alias in query and tool_name in names:
        score += 7                              # 意图别名（"算一下"→求解）
if score == 0: 不入选
按 (score, -index) 排序，取 top_k；全不中则回退 TOOLS[:top_k]
```

分词特别处理了中文：**ASCII 连续字符成词，CJK 逐字成 token**（因为中文没有空格）。

→ 迁移到 COMSOL 的关键工作就是给 155 个工具写**中英双语 keywords**，这决定了检索质量。

---

## 二、四层架构

```
┌─────────────────────────────────────────────┐
│ DSH (DeepSeek Harness)                      │
│   cordis.patch.yml  →  插入一行插件          │
└────────────────┬────────────────────────────┘
                 │ import lib/index.js
┌────────────────▼────────────────────────────┐
│ lib/index.js  —— cordis 插件入口             │
│   1. detect.mjs 探测安装（版本/路径/python）  │
│   2. paths.mjs  解析布局 + 写 ~/.dsh/*.json   │
│   3. 安装 skill 到 ~/.dsh/skills/            │
│   4. ctx.plugin(McpClient, serverConfig)     │
└────────────────┬────────────────────────────┘
                 │ stdio (JSON-RPC 2.0)
┌────────────────▼────────────────────────────┐
│ mcp-server/server.py  —— 只暴露 2 个工具     │
│   catalog.py  179 条目录 + 检索              │
│   handlers.py 按名字分发到真实实现            │
│   bridge.py   会话/作业生命周期               │
└────────────────┬────────────────────────────┘
                 │
┌────────────────▼────────────────────────────┐
│ 真实求解器（Abaqus: CAE 内核 TCP              │
│            COMSOL: MPh/JPype → mphserver）   │
└─────────────────────────────────────────────┘
```

### 各层职责

| 文件 | 职责 | 关键点 |
|---|---|---|
| `package.json` | DSH bundle 清单 | `dsh.bundle.patch: "./cordis.patch.yml"` 是注册入口 |
| `cordis.patch.yml` | 向 DSH 插件树插入一行 | 极简，只有 `- insert: - id/name` |
| `lib/detect.mjs` | 探测本机安装 | 返回 `{found, version, command, python, supported}` |
| `lib/paths.mjs` | 解析全部运行时路径 | 不写死任何机器路径，从自身位置 + `~/.dsh/*.json` 推导 |
| `lib/index.js` | cordis 插件 `apply(ctx)` | 探测→配置→装 skill→注册 MCP |
| `bin/*.mjs` | `doctor` / `where` CLI | 排障用，独立于 DSH 运行 |
| `mcp-server/server.py` | stdio MCP 服务 | **只用标准库**，无第三方依赖 |
| `mcp-server/catalog.py` | 工具目录 + 检索 | 渐进披露的数据源 |
| `mcp-server/handlers.py` | 按名分发 | 真正调求解器的地方 |
| `mcp-server/bridge.py` | 会话/作业管理 | 进程生命周期、端口、job 记账 |
| `skills/*/SKILL.md` | 教 agent 正确工作流 | 安装到 `~/.dsh/skills/`，自动被 DSH 发现 |

---

## 三、值得抄的工程细节

### 1. MCP 服务端只用标准库
`server.py` 自己实现 JSON-RPC 2.0 分帧（newline-delimited + Content-Length 两种都支持），不依赖 `mcp` 包。好处：裸 Python 3.8+ 就能跑，不需要虚拟环境。

> **COMSOL 的差异**：我们没法完全做到——COMSOL 要通过 MPh+JPype 驱动，必须有 venv。所以 dsh-comsol 的 `server.py`/`catalog.py`/`bridge.py` 保持纯标准库，但 `handlers.py` 需要 MPh 环境；插件用 **MPh venv 的 python** 启动服务端。

### 2. 工具失败是"结果"不是"传输错误"
```python
except Exception as exc:
    return {"jsonrpc":"2.0","id":rid,"result":{
        "content":[{"type":"text","text":f"{type(exc).__name__}: {exc}"}],
        "isError": True}}
```
绝不让一个工具抛异常打断整个 MCP 连接。**模型能看到错误并自我修正**。

### 3. 未知工具名给出近似建议
```python
near = catalog.search(name, top_k=4)
raise ToolError(f"unknown tool {name!r}. Close matches:\n" + describe(near))
```
模型打错名字时不会被卡死。

### 4. 超时给足
```js
toolCallTimeoutMs: 900000   // Abaqus 15 分钟
```
COMSOL 求解可能跑几小时 → 我们设 **1800000（30 分钟）**，并优先用异步/job 类工具。

### 5. 启动即失败（fail fast）
```js
failOnStartupError: true
```
探测不到安装就抛明确错误，附带 `node bin/xxx.mjs doctor` 提示，而不是静默降级。

### 6. skill 随插件安装
`lib/index.js` 把 `skills/abaqus-fea` 复制到 `~/.dsh/skills/`。这样 agent 一装上插件就知道正确工作流，不靠用户教。

### 7. 配置与状态分离
- `~/.dsh/abaqus-cad.json` —— 用户配置（workDir、python、port、mode）
- `~/.dsh/abaqus-cad/session.json` —— 会话状态（pid、port）
- `~/.dsh/abaqus-cad/jobs.json` —— 作业记账

---

## 四、COMSOL 的差异（不能照抄的地方）

| | Abaqus | COMSOL |
|---|---|---|
| 内核形态 | CAE GUI 进程 + `*_plugin.py` 自动加载 | `comsolmphserver.exe`，通过 **MPh/JPype** 连接 |
| GUI 桥接 | 需要往 `%USERPROFILE%\abaqus_plugins` 装 loader | **不需要**（COMSOL 无此机制） |
| Python 环境 | CAE 自带 `tools/SMApy` | 需要外部 venv（`mph`+`jpype`） |
| 进程单例 | 可多开 | **每进程只能一个 client**（`Only one client can be instantiated per Python session`） |
| 中文路径 | Abaqus C++ 层打不开 → 需要 ASCII junction | COMSOL 支持 UTF-8，不需要 |
| 求解时长 | 分钟级 | **小时级** → 超时要更大、要能后台跑 |
| 工具数 | 21 | **155**（更依赖渐进披露） |

---

## 五、复用策略：不重写 155 个工具

现有 `E:\ICE\_tools\COMSOL_Multiphysics_MCP` 已有 155 个可用工具，实现方式是 FastMCP 装饰器。

**关键发现**：这些工具是 `register_*_tools(mcp)` 里的**嵌套函数**，无法直接 import 单个函数。但可以：

```python
from mcp.server.fastmcp import FastMCP
m = FastMCP("dsh-comsol")
# 调用每个模块的 register_*_tools(m)
from src.tools import geometry
geometry.register_geometry_tools(m)

# 内省拿到名字+schema
tools = asyncio.run(m.list_tools())      # → 155 个
# 按名字分发
await m.call_tool(name, args)
```

**已实测验证**：部分模块注册即得 88 个工具，名称与 inputSchema 均可导出。

→ 所以 `handlers.py` 只做「注册 + 分发 + 结果规范化」，**零重复实现**。

### 一个必须绕开的坑
`src/server.py` 有 `from comsol_kb import register_tools`，而 `comsol_kb` 在本机**不存在**（`ModuleNotFoundError`）。
→ 绝不能 import `src.server`，要直接 import `src.tools.*`。

---

## 六、实现清单

```
E:\ICE\_tools\dsh-comsol\
├── package.json              [plugin-scaffold]
├── cordis.patch.yml          [plugin-scaffold]
├── lib/
│   ├── index.js              [plugin-scaffold]
│   ├── paths.mjs             [plugin-scaffold]
│   └── detect.mjs            [plugin-scaffold]
├── bin/dsh-comsol.mjs        [plugin-scaffold]
├── assets/icon.svg           [plugin-scaffold]
├── README.md CHANGELOG.md NOTICE.md LICENSE   [plugin-scaffold]
├── mcp-server/
│   ├── server.py             [mcp-core]
│   ├── catalog.py            [mcp-core]  ← 179 条 + 双语 keywords
│   ├── bridge.py             [mcp-core]
│   ├── handlers.py           [handlers-skill]  ← 复用 157 个实现
│   └── extra_tools.py        [gap-filler]  ← 新增 22 个（选择集/变量/探针/导出/绘图）
├── skills/comsol/
│   ├── SKILL.md              [handlers-skill]
│   └── references/*.md       [handlers-skill]
└── _contract/
    ├── tools_inventory.json      155 个工具的名称/描述/参数
    └── dsh-abaqus-cad-main/      参考实现全文
```
