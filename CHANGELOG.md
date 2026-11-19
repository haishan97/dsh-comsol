# dsh-comsol 变更记录

## 2026-11-19 · 注册 arc_figs 模块，新增 10 个电弧出图与后处理工具（189 → 199）

### 背景
电弧后处理是一条固定链路：**截面场数据导出 → Tecplot 云图 → 电流管守恒图 → 图面整形**。
此前每次都要临时写脚本，散落在各次会话里，重复且不可复用。这批工具把整条链路固化成 MCP 工具。

### 改动

`mcp-server/handlers.py`

1. `TOOL_MODULES` 增加 `"arc_figs"`，注册该模块的工具（实现在同机的 COMSOL MCP 包，
   由 `DSH_COMSOL_PACKAGE_ROOT` 解析，本仓库不重复托管）

`mcp-server/catalog.py`

2. 目录新增 10 条，工具总数 **189 → 199**：

| 工具 | 用途 |
|---|---|
| `plane_fields_export` | 导出 y=常数截面的场数据 npz（T/p/u/v/w/B/J/E/V/Ex/Ez/Fx/Fy/Fz），可插值补洞到 100% 覆盖 |
| `add_jx_jz` | 由 \|J\| 与 Ex/Ez 反推电流密度分量 Jx/Jz（J=σE） |
| `current_tubes_plot` | 电流管守恒图：弧柱截面撒种子正向积分到出口，统计进出条数 |
| `current_tubes_multi` | 多时刻电流管 2×2 面板，每帧自动定位弧柱核心撒种子 |
| `tecplot_render` | Tecplot 批处理渲染（生成宏 + `tec360 -b`，contour/stream/vector 组合） |
| `figure_style` | 图面后处理：裁坐标轴 / 顺时针 90° / 纵向色标 / 白底 / 金属描黑线框 |
| `domain_series_multi` | 逐时刻取域/边界平均（逐索引钉死 solnum），用于栅片电位、触头电位时间序列 |
| `domain_average_series` | 按域取体平均并返回整条时间序列（每域一个 AvVolume 节点） |
| `cpl_average_create` | 创建组件平均算子 `aveop`，用于 `aveop8(mef.V)` 这类体平均/面平均 |
| `study_set_genconv` | 设置求解器的广义收敛（genconv） |

### 同步

README 里的工具数一并更新为 **199**（原文写 179，已落后于目录实际条目）。

---

## 2026-11-15 · plot_set 支持 ArrowVolume 数值属性（箭头密度/比例）

### 问题
`plot_set` 对体箭头特征设 `xnumber` / `ynumber` / `znumber` / `scale` 时，
COMSOL 一律返回 `未知属性`（unknown property），看起来像属性名写错，实际是
**JPype 重载选错**：

- COMSOL 的 `ResultsFeature.set()` 有 int / double / String / array 多个重载
- JPype 按 Python 类型挑重载；挑到 `set(String, …)` 时 COMSOL 会去查"字符串属性"，
  查不到就报 `未知属性`——错误信息把人往"属性名"方向带
- `plot_group_build` 走的是 `pg.create(...)` 返回的 feature client，重载解析正常，
  所以**同一个属性名在 `plot_group_build` 的 `props` 里能用、在 `plot_set` 里不能用**

### 改动
`mcp-server/extra_tools.py`

1. 新增 `_coercion_candidates(value)`：按 JInt → JDouble → str（bool 走 on/off → bool；
   数值列表先 `_coerce` 再 `JArray(JDouble)`）给出候选强制转换序列
2. `_set_properties()` 改为逐候选重试，全部失败才记一条 failure

向后兼容：首个候选与旧行为一致，原来能设的属性行为不变。

### 验证
用"只接受 double 重载"的伪特征做单测（模拟 COMSOL 的失败模式）：

```
failures: []      # 旧实现会返回 4 条 failure
stored: {'xnumber': 8.0, 'ynumber': 4.0, 'znumber': 12.0, 'scale': 1.6e-07}
```

改动在 MCP server 重启后生效（stdio 进程重新加载模块）。

### 同时确认的可用路线（体箭头出图）

```python
plot_group_build(
  plotgroup_tag="pgB",
  dataset="mir1",
  features=[
    {"tag":"volCu","type":"Volume","props":{"color":"custom","coloring":"uniform",
      "customcolor":[1,0.6275,0.4784],"expr":"1","titletype":"none"},
     "attributes":[{"tag":"sel1","type":"Selection","selection":"selCu"}]},
    ...  # volFe / volPlastic 同理
    {"tag":"arr1","type":"ArrowVolume","props":{
      "arrowlength":"logarithmic",
      "expr":["mef.Bx","mef.By","mef.Bz"],   # 三分量数组
      "logrange":1000,
      "scale":55, "scaleactive":"on",
      "xnumber":8,"ynumber":4,"znumber":12}}  # 箭头数 = 三者乘积
  ],
  time="0.5", title="B")
```

要点：
- 特征类型名是 **`ArrowVolume`**（不是 `VolumeArrow`，后者报"这个情景中不能创建本操作"）
- 命名选择必须放在 `attributes` 的 `Selection` 子节点上；直接写 `selection` 会报"实体没有选择"
- **`plot_set(group, {"edges":"off"})`** 关掉数据集的黑色外框线（`plotdatasetedges` /
  `datasetedges` / `showedges` 都会被拒，只有 `edges` 生效）
- 逐时刻换帧：`plot_set(group, {"t":"1[ms]"})` + `plot_export(...)`
- 想让每帧箭头视觉一致：`plot_arrow_fit(factor=...)`（先读 autoscale 再乘系数）

### 本次成果
- A1 报告第 17 页 B 体箭头：24×8×34=6528 支 → **8×4×12=384 支**，比例放大，视觉变粗
- 第 19 页 F 体箭头：同密度，比例按 autoscale×3，整体变小
