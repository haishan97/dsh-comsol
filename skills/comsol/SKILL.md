---
name: comsol
description: "COMSOL Multiphysics 6.4 自动化技能。当任务涉及 COMSOL 建模、几何、材料/函数、物理场与多物理场耦合、网格、稳态/瞬态求解、参数扫描、后处理导出，或需要审计/重建/比对 .mph 模型时使用。通过 comsol MCP 的 search_tools + call_tool 按需检索执行；模型状态在单个 COMSOL 进程里，必须边做边读回、边做边存。触发词：COMSOL、mph、几何、网格、物理场、多物理场、耦合、求解、稳态、瞬态、参数扫描、电弧、等离子体、动网格、电池、后处理、导出、model_audit、comsol。"
metadata: { "os": ["win32"], "requires": { "anyBins": ["python"] } }
---

# COMSOL 多物理场自动化（comsol）

通过 `comsol` MCP 服务器驱动本机 **COMSOL Multiphysics 6.4**
（`C:\Program Files\COMSOL\COMSOL64\Multiphysics`），链路是
**MCP → MPh(Python) → JPype → comsolmphserver.exe**。

服务器处于 **discovery 模式**：会话里只有两个元工具，完整目录（157 条）不进上下文：

| 元工具 | 用途 |
|---|---|
| `search_tools {"query": "网格", "top_k": 6}` | 按意图检索，返回**精确工具名** + 一行说明 + 参数 |
| `call_tool {"name": "<精确名>", "arguments": {...}}` | 用检索到的名字执行 |

空闲会话约 250 token；一次 `physics_list_features` 就可能上万 token —— **这是设计如此，别试图一次拉全**。

## 铁律（违反会浪费整轮时间）

1. **先 `search_tools`，再 `call_tool`，绝不猜工具名。**
   名字是 `geometry_add_block` 还是 `geometry_add_feature`、是 `physics_configure_boundary`
   还是 `physics_boundary_selection`，一律以检索结果为准。猜错时服务器会返回近似名，
   但那已经是浪费。
2. **先 `comsol_status` 再动手。** 模型状态活在**单个 COMSOL 进程**里，不是本地文件：
   你不知道当前会话里有什么模型、什么当前模型，就不要 set 任何东西。
3. **边做边存。** 每个阶段结束 `model_save`；要做实验性改动前先
   `model_save_version`（自动带时间戳 + `_latest` 副本），失败可回退。
4. **每个 `*_set` / `*_configure` 之后读回。** 设置不报错 ≠ 生效：
   `physics_feature_info` / `physics_list_features` 读回属性与选择集；
   选择集为空（`entities: []`）是**硬错误**，不是警告。
5. **单位写在表达式里。** COMSOL 是量纲感知的：`"10[mm]"`、`"1e-3[S/m]"`、
   `"293.15[K]"`。裸数字按 SI 解释，`"10"` 会被当成 10 m。
6. **不确定就查离线目录，不查就开求解是赌博。** `static_catalog_*` 系列不需要会话，
   能验证物理接口名、特征类型名、属性名、变量名（见 `references/api-notes.md`）。

## 标准建模顺序（照抄这个次序）

| # | 阶段 | 代表工具 | 要点 |
|---|---|---|---|
| 1 | 会话 | `comsol_status` → `comsol_start` | 见下节；**一个进程只能有一个 client** |
| 2 | 模型 | `model_create` / `model_load` | 有现成 `.mph` 优先 `model_load`，不要重建 |
| 3 | 组件 | `model_create_component` | 决定空间维数（2/3/2D 轴对称） |
| 4 | 几何 | `geometry_create` → `geometry_add_*` → `geometry_build` | 不 `geometry_build` 就没有实体/边界编号 |
| 5 | 边界编号 | `geometry_get_boundaries` / `geometry_boundary_info` | **先拿到编号再写边界条件** |
| 6 | 参数/函数 | `param_set`、`function_create` | 材料曲线（σ(T)、OCV）用 Interpolation 函数 |
| 7 | 材料 | `material_create` / `material_set` | **每个域都要有材料**，否则求解时 undefined property |
| 8 | 物理场 | `physics_add` + `physics_feature_create/set` | 见 `references/api-notes.md` 的标签约定 |
| 9 | 多物理场 | `multiphysics_add` → **`multiphysics_set`** | `add` 只建节点；不 `set` 选择集与源/目标物理场 = 空耦合 |
| 10 | 网格 | `mesh_create_sequence` / `mesh_create` | 弧道区细、远场粗；增长率 1.15 起 |
| 11 | 研究 | `study_create` → `study_solve` | 长算例用 `study_solve_async` + `study_get_progress` |
| 12 | 后处理 | `results_evaluate` / `results_global_evaluate` / `results_export_*` | 见 `references/workflows.md` |
| 13 | 审计 | `model_audit` / `audit_model_config` | 交付前跑一次，把"以为设了"变成"确实设了" |

改已有模型时，**先审计再改**：`model_audit` → 改 → 再 `model_audit` → `model_diff`
（`audit_models_diff` 可直接比两个内存模型）。没有 before/after 的 diff，不要说"改好了"。

## 会话生命周期

```text
comsol_status {}                        # 先看：connected / models / current_model
comsol_start {"cores": 8}               # 或 comsol_connect {"port": 2036} 接已开的 server
comsol_status {}                        # 确认版本、核数
...建模/求解...
model_save {"file_path": "D:/work/x.mph"}
comsol_disconnect {}                    # 结束（清空内存模型）
```

- **一个 Python 进程只能实例化一个 COMSOL client**（JPype 限制）。本插件已做保护：
  会话存活时再调 `comsol_start` 会返回
  `{"success": false, "already_running": true, "error": ..., "session": {...}}`，
  **不是崩溃**。看到这个就 `comsol_status` 继续干活，别反复重试；真要重开先
  `comsol_disconnect`。
- 求解是**小时级**的：MCP 客户端超时 30 min。超过这个量级改用
  `study_solve_async`（后台线程 + `study_get_progress` / `study_wait`），
  或用 `remote_job_submit` 丢到远端 solver 机。
- 服务端在 MPh venv 里跑（`mph` + `jpype`）；若 `call_tool` 报
  "tool execution unavailable ... handlers.py could not be imported"，是解释器选错了，
  不是模型问题。

## 选择集：这个工具集最容易翻车的地方

COMSOL 的边界/域条件都靠**编号**选中。三条实操规则：

1. **编号只对当前几何有效。** 改了几何（加/删特征、改尺寸、重新 build）编号会变，
   必须重新 `geometry_get_boundaries`。
2. **物理场特征只能选到父特征激活集里的实体。** 父特征（如某个 `Wall`、
   某个接口的域选择）没覆盖的边界，子特征写了编号也不会生效 —— 设置后必须读回。
3. **能用命名选择就用命名选择。** `geometry_create_box_selection` /
   `geometry_create_side_selections` 生成稳定 tag，比裸编号抗几何改动。

```text
geometry_get_boundaries {"geometry_name": "geom1"}
geometry_boundary_info {"geom_tag": "geom1"}          # 边界长度 + 相邻域，判断"这是哪条边"
geometry_create_side_selections {"prefix": "side", "x_min": "0", "x_max": "10[mm]", ...}
physics_set_feature_selection {"physics_name": "ht", "feature_path": "hf1", "selection": [3, 5]}
physics_list_features {"physics_name": "ht"}          # 读回：每个特征的 selection 与启用状态
```

## 电弧 / 等离子体：不要从零试

这类模型（磁流体电弧、断路器、等离子体炬）有固定套路，且**失败模式非常特定**：
σ 常温被钳在下限 → 不点火；人工电导率 → 虚假焦耳热；全耦合牛顿 → 极限环；
动网格 → 时步塌到 1e-17。

完整配方（几何/材料 σ(T)/高斯种子/两步求解/分离式分组/动网格/重划网格/非均匀输出）
见 **`references/workflows.md`**；错误现象 → 原因 → 处置见
**`references/troubleshooting.md`**。开工前务必读这两份，能省几小时。

## 交付前自检

- [ ] `model_audit` 与 `audit_model_config` 里参数、物理场、耦合、网格、研究步**齐全**；
- [ ] 每个域都有材料，没有 "undefined property"；
- [ ] 求解真跑过：`solutions_list` 有解、`results_inner_values` 有时刻列表；
- [ ] 关键量有物理量级（电弧电压百 V 级、温度 ~1e4 K），不是 `1e-20` 这类"被短路"的值；
- [ ] 网格/时间步至少变一次，极值变化在可接受范围（`verify_mesh_independence_*` 可做流程化）；
- [ ] 交付物是 `.mph` + 明确的导出数据/图片路径，不是"我算过了"。

## 参考文件

| 文件 | 内容 |
|---|---|
| `references/api-notes.md` | 标签约定（comp1/geom1/mef/ht/spf…）、嵌套特征路径、属性名怎么查、边界/域编号、单位 |
| `references/workflows.md` | 通用多物理场配方、电弧/等离子体完整配方、电路耦合、网格独立性、远端求解 |
| `references/troubleshooting.md` | 真实错误字符串 → 诊断 → 处置（初始值、奇异、极限环、动网格、短路、空选择） |


## GUI 桥接：让用户看见模型

如果用户说「我想看界面」「在 COMSOL 窗口里看」「可视化」「桥接」，用：

```
comsol_start_gui(cores=4, port=2036, open_desktop=true)
```

它起 `comsolmphserver -multi on` 并把 COMSOL Desktop 连上去，之后
`comsol_connect(port=<返回的 port>)` 的 API 会话与 Desktop **共享同一个模型**——
用户在窗口里看到的就是你正在改的东西。

- 不要用普通的 `comsol_start` 再手动开 GUI：普通 server 是独占的，Desktop 一连上
  就会把 API 客户端踢掉（`Server is in use by another client`）。
- `comsol_gui_status()` 查状态（MCP 重启后也能靠端口探测给出结果）。
- `comsol_gui_close(close_desktop=true, stop_server=false)` 收尾：只关窗口、保留会话。
- 注意 `comsol.exe mphclient` 是启动器，立刻退出是正常的；真正进程是 `ComsolUI.exe`。
