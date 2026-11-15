# COMSOL API 细节：标签、路径、属性、编号

本文件是 `SKILL.md` 的补充。所有结论都对应这套 MCP 工具的真实行为；
写脚本前先在这里找对应的名字，比在 `call_tool` 里试错快得多。

## 1. 标签（tag）命名约定

COMSOL 里每个节点都有两层身份：**tag**（程序用，如 `mef1`）和 **label**（界面显示，
如 `Electric Currents`）。本工具集两种都接受，但**优先用 tag**：label 会随语言/版本变。

| 层级 | 典型 tag | 说明 |
|---|---|---|
| 组件 | `comp1` | `model_create_component` 生成 |
| 几何 | `geom1` | `geometry_create` 生成，挂在组件下 |
| 网格 | `mesh1` | `mesh_create_sequence` 生成 |
| 物理场（电磁） | `mef` / `ec` / `es` | Magnetic and Electric Fields / Electric Currents / Electrostatics |
| 物理场（传热） | `ht` | Heat Transfer in Fluids/Solids |
| 物理场（流动） | `spf` | Laminar Flow；高马赫用 `hmnf` |
| 物理场（等离子体） | `phs` | Plasma, Equilibrium Discharges |
| 多物理场耦合 | `mhd1` / `mef1`… | 磁流体、电磁热等；**编号看实际返回** |
| 电路 | `cir` / `ec` | Electrical Circuit 接口 |
| 研究/解 | `std1` / `time1` / `sol1` / `sol3` | Study / Solution；重划网格后是 `sol3` 一类的新解 |
| 全局方程 | `ode1` / `ge1` | 电路或端子电压的 ODE 变量 |

物理场名在工具里既可以是 tag（`"mef"`）也可以是 label（`"Magnetic and Electric Fields"`），
但**属性名只能用 COMSOL 的原名**，不要翻译。

## 2. 嵌套特征路径

物理场特征是可以嵌套的（子特征挂在父特征下）。本工具集用 **`/` 分隔的路径**：

```text
physics_feature_info  {"physics_name": "es2", "feature_path": "es2/er1"}
physics_feature_set   {"physics_name": "es2", "feature_path": "es2/er1",
                       "properties": {"i0": "1e-3[A/m^2]"}}
physics_feature_toggle{"physics_name": "ht",  "feature_path": "ht/hs1", "enabled": false}
```

- 只写一层（`"hf1"`）= 直接子特征；写两层（`"es2/er1"`）= 父特征 `es2` 下的 `er1`。
- 电化学、PorousElectrode、ElectrodeSurface 这类**子特征必须给 `parent_feature`**
  （创建时）或路径（修改时），否则会建在接口根上，不生效。
- 被禁用的特征仍在树里但**不参与求解** —— 这是"为什么这个边界条件没起作用"的第一嫌疑。
  `model_audit` 会把禁用特征标成 ⛔。

## 3. 属性名怎么查（不要猜）

三条路，按代价从低到高：

1. **离线静态目录**（不需要会话，最快）
   ```text
   static_catalog_search        {"query": "LithiumIonBatteryMPH", "kind": "interface"}
   static_catalog_features      {"interface_id": "LithiumIonBatteryMPH"}   # 特征类型 + 全部属性名
   static_catalog_properties    {"layer": "mesh", "type_name": "Size"}     # 某类型的属性 schema
   static_catalog_variables     {"query": "eta", "module": "bfc"}          # 变量定义（~19000 条）
   static_catalog_layer         {"layer": "solver"}                        # 合法类型名清单
   static_catalog_discretization{"interface_id": "LaminarFlow"}            # 默认形函数阶数
   ```
2. **读回已存在的特征**（已有模型/官方例子里有正确写法）
   ```text
   physics_feature_info         {"physics_name": "ht", "feature_path": "hf1"}
   physics_list_features        {"physics_name": "ht", "include_details": true}
   electrochemistry_list_feature_properties {"physics_name": "tcd", "feature_tag": "es2/er1"}
   ```
3. **导出 Java**（GUI 里点过的每个设置都有对应 API 调用）
   ```text
   model_export_java {"decode_unicode": true}    # 得到 *_readable.java
   ```
   注意 `.java` 导出是**历史 set 回放**（同一属性可能被设多次，最后一次生效），
   读当前状态要用 `model_audit`，不要用 `.java`。

## 4. 常用属性名速查

| 物理场 | 条件/特征 | 属性 |
|---|---|---|
| Heat Transfer | Temperature / HeatFlux / ConvectiveHeatFlux | `T0` / `q0` / `h`+`Text` |
| Laminar Flow | InletBoundary / OutletBoundary | `U0`（或 `NormalInflowVelocity`）/ `p0` |
| Electric Currents | Terminal / Ground / ElectricInsulation | `V0`（或 `I0`）/ — / — |
| Magnetic and Electric Fields | Terminal / Ground | `V0` / — |
| Solid Mechanics | Fixed / BoundaryLoad | — / `Fx,Fy,Fz` 或 `FAx,FAy,FAz` |
| Pressure Acoustics | Pressure / Impedance / NormalVelocity | `p0` / `Zn` / `nvel` |
| PDE | DirichletBoundary / FluxBoundary | `r` / `g`,`q` |

温度场初值不是边界条件，是**域的 Initial Values**（`init1`，属性 `T`）。
电弧模型的点火种子就写在这里（见 `workflows.md`）。

## 5. 边界 / 域编号

编号是几何的产物，**只在当前几何版本内有效**：

```text
geometry_build                    {}                                  # 必须先 build
geometry_get_boundaries           {"geometry_name": "geom1"}         # 边界 + 面积/长度
geometry_boundary_info            {"geom_tag": "geom1"}              # 包围盒 + 每条边界的长度 + 相邻域
geometry_create_box_selection     {"selection_name": "arc_zone", "x_min": "-5[mm]", ...}
```

`geometry_boundary_info` 的用法：先看包围盒判断哪条边是"左/右/上/下/对称面"，
再用长度和相邻域确认（例如"只邻接域 1、长度等于总高的那条"就是对称面）。

常见陷阱：

- 布尔操作默认**保留内部边界**（`intbnd`）。合并后仍看到多条域 = 忘了关：
  `geometry_feature_set {"feature_tag": "uni1", "properties": {"intbnd": false}}`。
- 边界编号在 `geometry_build` 之前不存在，之后每次改几何都可能变 → 改完重查。
- 2D 模型 `entity_dimension=1` 选边界，3D 模型 `entity_dimension=2` 选面。

## 6. 单位

COMSOL 表达式是量纲感知的，工具把字符串原样传给它：

| 写法 | 含义 |
|---|---|
| `"10[mm]"` | 10 毫米 |
| `"1e-3[S/m]"` | 电导率下限 |
| `"293.15[K]"` | 20 °C |
| `"1[atm]"` | 101325 Pa |
| `"range(0,0.05,2)[ms]"` | 0–2 ms 每 0.05 ms（研究输出时刻） |
| `"max(sig_T(T), 1e-3[S/m])"` | 材料属性写成表达式，可用函数 |

裸数字 = SI（`"10"` 是 10 m，`"1000"` 是 1000 Pa）。**报错先查单位，不要先怀疑物理。**

## 7. 材料与函数

```text
material_create {"label": "Air (arc)",
                 "property_groups": {"def": {"density": "rho(p,T)", "thermalconductivity": "k(T)"},
                                     "electricconductivity": {"sigma": "max(sig_T(T), 1e-3[S/m])"}}}
function_create {"func_type": "Interpolation", "funcname": "sig_T",
                 "table": [[300, 1e-3], [3000, 10], [10000, 3000]],
                 "properties": {"fununit": "S/m", "interp": "cubicspline"}}
```

- 属性组名（`def`、`electricconductivity`、`liion`…）必须与 COMSOL 一致；
  不确定就用 `model_export_java` 看一个 GUI 建好的材料。
- 插值函数 `table` 的 x 必须**升序**；曲线要光滑用 `cubicspline`（C2），
  不要用分段常数（求解器会抖）。
- 材料选择集默认"所有域"；只给部分域时务必确认**没被漏掉的域**（见 troubleshooting）。

## 8. MPh / Java 层

如果目录工具确实覆盖不到某个操作，才考虑直接写 Java API（通过现有工具的
`model_export_java` 学写法，不要凭记忆写）：

```python
jm = model.java                 # 是属性，不是方法：model.java() 会报错
comp = jm.component().create('comp1', True)
geom = comp.geom().create('geom1', 3)
phys = comp.physics().create('spf', 'LaminarFlow', 'geom1')
bc = phys.create('inl1', 'InletBoundary')
bc.selection().set([1, 2, 3])
bc.set('U0', '1[mm/s]')
```

`bc.selection().set([...])` 的编号若超出父特征的激活集，COMSOL **不报错但不生效** ——
回到第 5 节的"读回"规则。
