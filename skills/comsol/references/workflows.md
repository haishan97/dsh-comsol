# COMSOL 工作流配方

两个层级：先给**通用多物理场配方**（多数任务够用），再给**电弧/等离子体配方**
（磁流体 + 传热 + 电路 + 动网格，是这个工具集最常被用来干的重活）。

---

## A. 通用多物理场配方

### A.1 从零建一个耦合模型

```text
comsol_status {}
comsol_start  {"cores": 8}
model_create  {"name": "my_model"}
model_create_component {"component_name": "comp1", "space_dimension": 3}

# 1) 几何：先参数化，再画
param_set {"name": "gap",  "value": "8[mm]"}
param_set {"name": "r_rod","value": "2[mm]"}
geometry_create {"geometry_name": "geom1", "space_dimension": 3}
geometry_add_block    {"size": ["20[mm]", "20[mm]", "20[mm]"]}
geometry_add_cylinder {"position": ["10[mm]", "10[mm]", "0"], "radius": "2[mm]", "height": "20[mm]"}
geometry_boolean_difference {"input_object": "blk1", "objects_to_subtract": ["cyl1"]}
geometry_build {"geometry_name": "geom1"}

# 2) 编号：这一步不能跳
geometry_get_boundaries {"geometry_name": "geom1"}

# 3) 材料/函数
function_create {"func_type": "Interpolation", "funcname": "k_T", "table": [[300, 0.026], [1000, 0.06]]}
material_create {"label": "Air", "property_groups": {"def": {"thermalconductivity": "k_T(T)"}}}

# 4) 物理场
physics_add {"physics_type": "HeatTransfer"}       # 或 physics_add_heat_transfer
physics_set_material {"physics_name": "ht", "material_name": "Air"}
physics_configure_boundary {"physics_name": "ht", "boundary_condition": "Temperature",
                            "boundary_selection": [1], "properties": {"T0": "293.15[K]"}}
physics_configure_boundary {"physics_name": "ht", "boundary_condition": "HeatFlux",
                            "boundary_selection": [3], "properties": {"q0": "1e5[W/m^2]"}}

# 5) 多物理场（如果需要）
multiphysics_add {"coupling_type": "ElectromagneticHeating", "physics_list": ["ec", "ht"]}
multiphysics_set {"coupling_tag": "emh1", "selection": "all"}   # ← 不 set 就是空耦合

# 6) 网格
mesh_create_sequence {"mesh_name": "mesh1"}
mesh_create {"mesh_name": "mesh1"}

# 7) 研究
study_create {"study_type": "Stationary"}
study_solve  {"study_name": "std1"}

# 8) 后处理
results_global_evaluate {"expression": "maxop1(T)", "unit": "K"}
model_save {"file_path": "D:/work/my_model.mph"}
```

### A.2 打开/重建已有模型

| 目标 | 做法 |
|---|---|
| 直接用现成 `.mph` | `model_load` → `model_inspect` → `model_audit` |
| 想"照着重建一遍" | `model_audit` 导出 JSON/MD → 在**新模型**里逐步建 → `audit_models_diff {"model_a": "orig", "model_b": "rebuild"}` 逐项比对 |
| 想核对论文里写的参数 | `audit_paper_checklist {"paper_facts": {...}}`（参数/计数/选择集/网格/时间终点逐条判 match/mismatch/missing） |
| 只想看结构 | `model_inspect`（轻）/ `model_audit`（全量，写文件） |

**重建的验收标准**是 `audit_models_diff` 返回空差异列表，不是"看起来一样"。

### A.3 参数扫描

```text
param_sweep_setup {"parameter_name": "gap", "values": ["6[mm]", "8[mm]", "10[mm]"], "study_name": "std1"}
study_solve {"study_name": "std1"}
results_outer_values {"dataset": "dset1"}          # 扫描参数列表
results_evaluate {"expression": "maxop1(T)", "outer": [0, 1, 2]}
```

### A.4 后处理与导出

| 需求 | 工具 |
|---|---|
| 全域/表达式求值 | `results_evaluate {"expression": ["x","y","T"]}` |
| 单个标量（积分/最大值） | `results_global_evaluate {"expression": "intop1(T)"}` |
| 任意坐标点探针（mphinterp 等价） | `results_interpolate {"expressions": ["T"], "coords": [[0.001, 0, 0]]}`（**坐标单位 m**） |
| 时间步列表 / 参数列表 | `results_inner_values` / `results_outer_values` |
| 出图 | 先 `results_plots_list` 看有哪些图；`results_export_image {"node_name": "pg1", "file_path": "D:/work/t.png"}` |
| 导数据 | `results_node_create`（Export→Data 节点）→ `results_export_data` |
| 数值节点 | `results_node_create {"group": "numerical", "node_type": "MaxLine", "properties": {...}}` → `results_numerical_evaluate` |

`results_interpolate` 的 `coords` 是 **SI 米**：几何用 mm 建模时 `[0.001, 0]` 才是 1 mm。

### A.5 网格无关性（流程化）

```text
verify_mesh_scaling_preview   {"factor": 0.5}                 # 先看会改哪些尺寸（只读）
verify_mesh_independence_setup{"factors": [2.0, 1.0, 0.5],
                               "metrics": [{"name": "Tmax", "expr": "maxop1(T)", "key": true}]}
verify_mesh_independence_analyze {"group": "<setup 返回的 group>", "tol": 0.02}
```

判据：**最细两档**的关键量相对差 < `tol`。远程模式下 `transport` 由 `remote_configure` 决定。

---

## B. 电弧 / 等离子体配方（磁流体 + 传热 + 电路 + 动网格）

这是一套被真实调试过的路线（断路器电弧、自由燃烧电弧、等离子体炬都适用）。
核心难点不是"会不会点工具"，而是**数值上让电弧点得着、稳得住、不假热**。

### B.1 物理场组合

| 角色 | 接口 | 典型 tag |
|---|---|---|
| 电磁（电流/磁场） | Magnetic and Electric Fields（或 Electric Currents） | `mef` / `ec` |
| 传热 | Heat Transfer in Fluids | `ht` |
| 层流 | Laminar Flow | `spf` |
| 平衡态等离子体 | Plasma, Equilibrium Discharges | `phs` |
| 电路 | Electrical Circuit | `cir` / `ec` |
| 耦合 | Magnetic–Electric–Thermal + 等离子体热源 + 洛伦兹力 | `mhd1`、`phs1` 等 |
| 动网格 | Moving Mesh（Rotating/Translating/Deforming Domain） | `mm1` |

**顺序**：电磁 → 传热 → 流动 → 等离子体 → 电路 → 多物理场耦合。
每加一个接口就 `physics_list_features` 确认默认特征真的挂在了预期域上。

### B.2 材料：σ(T) 与"下限"陷阱

常温空气 σ≈1e-15 S/m，会让电磁方程病态。做法是给**下限**：

```text
material_create {"label": "Air (arc)",
                 "property_groups": {
                   "def": {"density": "rho_ideal(p,T)", "thermalconductivity": "k_air(T)",
                           "dynamicviscosity": "mu_air(T)"},
                   "electricconductivity": {"sigma": "max(sig_air(T), 1e-3[S/m])"}}}
```

`sigma` 用插值函数（`function_create`，x 升序、`cubicspline`），典型表：
300 K→1e-3、3000 K→10、6000 K→1e3、10000 K→3e3、20000 K→1e4（S/m，量级即可，
关键是单调与量级正确）。

**副作用（必读）**：冷气区被凭空赋予 σ，会产生 `σE²` 的**虚假焦耳热**，
把整个腔体慢慢烤热。处置见 B.6 的温度门控。

### B.3 初始条件：高斯热点"点火"

不模拟击穿过程，直接用热点把电弧种出来（放在域的 Initial Values 里，属性 `T`）：

```text
T0 = (14e3*exp(-((x-24[mm])/2.5[mm])^2
               -((z-27[mm])/1.5[mm])^2
               -((y-0[mm])/2[mm])^2) + 293.15)[K]
```

- 峰值 **10–15 kK**，位置 = 触头间隙中心；
- 三方向宽度按间隙尺度给（各向异性椭球：沿运动方向可放宽）；
- 没有这个热通道，回路等效开路、永远不起弧；
- 点火后靠焦耳热自持，所以峰值别给太高（>20 kK 会数值冲击）。

### B.4 两步求解（关键）

**Step 1 — Stationary，只解电磁 + 电路**
在 `Physics and Variables Selection` 里把传热、流动、等离子体、多物理场、动网格的
`Solve for` 全部取消，只留 `mef` + 电路。目的：先拿到自洽的"冷态电磁场 + 回路电流"初值。
→ 工具侧：`study_create {"study_type": "Stationary"}`，用
`physics_feature_toggle` / 研究步的变量选择（`study_create` 的 `step_properties`）实现。

**Step 2 — Time Dependent，全耦合**
- Time unit = ms；
- **非均匀输出**：起弧段密、冷却段疏，例如
  `range(0,0.05,2) range(2.1,0.1,5) range(5.2,0.2,10)`（ms，共 ~96 个时刻）；
- **Initial step = 0.01 µs（1e-8 s）**：起弧瞬间极陡，初始步长必须极小；
  取 0.1 µs 也能起步，但一旦报"重复误差测试失败"就降到 0.01 µs；
- 时间积分 BDF2（最大阶 2）、相对容差 ~0.005；
- 线性求解器：Direct + **PARDISO**（`solver_feature_set`）。

### B.5 分离式分组（能收敛的关键）

全耦合牛顿在电弧模型上极易进**极限环**（残差 24→970 振荡，150 次不收敛）。
改成 Segregated 并**按物理耦合强度分组**：

| 组 | 成员 | 理由 |
|---|---|---|
| 1 | `Terminal Voltage (mef.mi1.term1.V0_ode)` **+ `Temperature (comp1.T)`** | 电压与温度强耦合，必须同组 |
| 2 | `Spatial Mesh Displacement` **+ `Rotation Angle (comp1.ode1)`** | 网格位移与转角同组 |
| 3 | 其余（压力、速度、磁场…） | 按接口分 |

- 删掉自动生成的 `Temperature` 组和 `Angular Displacement` 组再重排；
- 组 1 的 Jacobian update 设 **Once per time step**（每步更新一次，省时间且稳）；
- 工具侧：`solver_feature_list {"solution_tag": "sol1"}` 看树 →
  `solver_feature_set {"solution_tag": "sol1", "feature_path": "t1", "properties": {...}}`。

### B.6 人工电导率的虚假热源：温度门控

打开 `Equation View`（Show More Options），在等离子体热源的 **Weak Expressions** 里把
平衡态放电热源用温度门控：

| Weak expression | Integration order | Selection |
|---|---|---|
| `phs1.Q*test(T)*ht.d*(T>3000[K])` | 2 | 弧区域 |

含义：只有 ≥3000 K 的真实弧柱区才加热，冷气区由人工 σ 造出来的热全部不计。

> **迁移规则**：任何用"电导率下限/人工电导率"稳定电磁计算的模型，都要检查人工项
> 带来的虚假源，并用温度（或相分数）门控切除。
> ⚠️ 门控表达式是"替换"还是"追加"取决于默认项，换模型必须对照默认弱表达式确认，
> 并用已知解验证（门控前后同一时刻弧压应基本不变）。

### B.7 动网格（触头运动）

三个节点：

1. **Rotating Domain**：作用域 = 动触头所在域；Rotation type = Specified rotational
   velocity；**ω = `alpha*(t<=2[ms])`** —— 布尔因子让转动在 2 ms 后停止。
   不加这个因子，触头会一直转、几何自交、网格崩。
2. **Deforming Domain**：除旋转域外的所有空气域，允许变形。
3. **Symmetry/Roller**：对称面/外边界，让网格滑移而不是拉伸畸变。

**Automatic Remeshing**：Time-Dependent Solver 里设 Condition = Specified times，
Remeshing times = `range(0,0.1,0.6)`（每 0.1 ms 强制重划）。只在触头运动段重划；
全程重划会严重拖慢并引入插值误差。后处理记得用**重划后的解**（如 `sol3`，
数据集 `Remeshed Solution 1`）。

### B.8 电路耦合

- 端子用 `Terminal` 特征 + 外部电路 `Electrical Circuit` 接口；回路方程通过
  `ode1`/`ge1` 全局方程引入；
- 端子电压/电流变量名形如 `mef.V0_1`、`mef.I0_1`（编号看实际接口）；
- **I0=0 时 `ec` 会退化**（零电流奇异，残差 1e21 级）→ 用**续算链**起步：
  `1 → 5 → 10 → 30 → 100 → 300 A`，每级以上一级的解为初值；
- 闭合空腔必须加**压力点约束**（Pressure Point Constraint），否则压力漂移不收敛。

### B.9 电弧模型自检清单

- [ ] σ 下限生效且**有温度门控**切除虚假热源；
- [ ] 初始场有 10–15 kK 高斯热点，位置在间隙中心；
- [ ] 先跑通 Stationary 电磁-only，再进瞬态；
- [ ] 瞬态 initial step ≤ 0.1 µs，BDF2，PARDISO；
- [ ] 分离式分组：端子电压 + 温度同组，网格位移 + 转角同组；
- [ ] 动网格有停转因子 + 分段重划；
- [ ] 弧压/弧流/电源电压三曲线量级对（弧压百 V 级，弧流按设定）；
- [ ] 温度场不是 293.15 K 一片（那是"没起弧"）也不是 1e5 K（那是"数值爆了"）；
- [ ] 网格/时间步各变一次，弧压变化在可接受范围。

---

## C. 远端求解（小时级算例）

```text
remote_config_get {}                                    # 先看当前配置
remote_probe {}                                         # SSH 可达性 + comsolbatch + 磁盘
remote_job_submit {"job_name": "arc_run1", "model_name": "arc_model",
                   "study": "time1",
                   "metrics": [{"name": "Uarc", "expr": "mef.V0_1", "unit": "V", "mode": "time_series"},
                               {"name": "Tmax", "expr": "maxop1(T)", "unit": "K", "mode": "max"}]}
remote_job_status {"job_id": "<id>"}
remote_job_fetch  {"job_id": "<id>"}
remote_metrics_extract {"job_id": "<id>"}               # 本地只求值，不重算
```

拿到结果后做论文比对：

```text
repro_compare_scalars {"items": [{"name": "arc voltage peak", "sim": 97.2, "ref": 110, "rel_tol": 0.1}]}
repro_compare_curves  {"sim": "sim.csv", "ref": "digitized.csv",
                       "feature_defs": [{"type": "threshold", "name": "ignition", "level": 1000}]}
repro_compare_job_metric {"job_id": "<id>", "metric_name": "Uarc", "ref": "paper_fig3.csv"}
```

**不要**把"远端跑完 = 结果可信"当结论：`repro_*` 给的是误差与特征时刻，
物理量级和网格无关性仍要自己判。
