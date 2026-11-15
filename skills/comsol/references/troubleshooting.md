# COMSOL 排障：错误字符串 → 原因 → 处置

原则：**先定位在哪一层**（MCP 分发 / COMSOL API / 物理设置 / 求解器 / 网格），
再改一个变量重跑。一次改三处，成功了也不知道是哪一处起的作用。

## 0. 五步定位

1. `comsol_status` —— 会话活着吗？版本/核数/模型列表对不对？
2. `model_audit` / `audit_model_config` —— 你以为设了的，树里真的有吗？（禁用特征、空选择集）
3. `model_export_java` —— 拿 GUI 等价代码对照，确认属性名/特征类型名没写错。
4. 单独跑一个**更小的子问题**（只电磁、粗网格、短时长）—— 能不能收敛？
5. 再回到全模型，一次只改一个设置。

---

## 1. 求解器类

| 现象（英文原文关键词） | 原因 | 处置 |
|---|---|---|
| `Failed to find consistent initial values` / 找不到一致的初始值 | 初始场与边界条件/材料自相矛盾；或强耦合一上来就解全系统 | ①先用**只解一个物理场**的 Stationary 起步；②检查初始值是否与固定边界冲突（例如初值 300 K 但某壁面 T0=2000 K 且无梯度过渡）；③瞬态先给极小 initial step；④用分离式而非全耦合 |
| `重复误差测试失败，可能已达到奇点；最后一个时步不收敛`（时步塌到 1e-17 s） | 局部出现真奇点：网格退化、几何自交、边界条件互相矛盾、状态量越界 | ①看失败时刻的场（COMSOL 会存 `*_Model.mph`）；②检查动网格是否自交；③把出口/入口边界类型换成不矛盾的组合；④降 initial step、加网格质量约束 |
| 全耦合牛顿残差**振荡不下降**（如 24→970 来回，150 次不收敛） | 强耦合系统的极限环，典型于电弧/等离子体 | 换 **Segregated**，并按耦合强度分组（见 `workflows.md` B.5）；组内 Jacobian update = Once per time step |
| 残差量级 1e21 / 解出现 1e300 | 方程退化：零电流、零压力参考、除零 | 电弧：I0=0 时 `ec` 退化 → 用**续算链** 1→5→10→30→100→300 A；流动：闭合域加压力点约束；传热：检查是否所有边界都绝热且无源 |
| `Undefined variable` / `undefined property` 在求解时爆 | 某域**没有材料**，或材料缺少该物理场需要的属性 | `material_set` 覆盖所有域；`material_create` 的属性组要含物理场真正读的键（用 `model_export_java` 对照） |
| 压力/密度漂移不收敛（闭合空腔） | 压力无参考点 | 加 Pressure Point Constraint（点选择），或把某边界设为压力边界 |
| 时间步一直缩、最后放弃 | 刚性太强 / 输出时刻太密 / 重划网格太频繁 | 放宽容差到 0.005、降低输出密度、重划只放在运动段 |

## 2. 电磁 / 电路类

| 现象 | 原因 | 处置 |
|---|---|---|
| 端子电压 ≈ `1e-20`（"被短路"） | 默认的 `Ground (gnd1)` 覆盖了本该绝缘的面（全局面），把电极短路了 | `physics_feature_info` 看 `gnd1` 的 selection；把 `gnd1` 限定到真正的接地极，其余面加 **ElectricInsulation**（Zero Charge）；再 `results_global_evaluate` 复核端子电压量级 |
| 电流/电压不随激励变化 | 激励加在了被绝缘/被覆盖的边界上；或 Terminal 特征选到了内部边界 | 读回 Terminal/Ground 的 selection 与相邻域 |
| 磁场为 0 / 洛伦兹力为 0 | 耦合节点 `multiphysics_add` 只建了节点，**没 `multiphysics_set` 选择集与源/目标物理场** | `multiphysics_set {"coupling_tag": ..., "selection": "all", "properties": {...}}` 后读回 |
| 冷气区被"烤热"（虚假焦耳热） | σ 被钳在下限，`σE²` 在非弧区也加热 | 温度门控弱表达式 `*(T>3000[K])`（见 `workflows.md` B.6） |
| 电路接口报缺节点/悬空 | 电路图有浮空节点或缺少接地 | 电路必须至少一个地；端子变量名用 `mef.V0_1` 形式，编号按实际 |

## 3. 选择集 / 几何类

| 现象 | 原因 | 处置 |
|---|---|---|
| 设置成功但完全不生效 | **边界特征被父特征的激活集裁剪**：父特征（接口域选择、某 Wall 组）没覆盖该实体 | `physics_list_features` 读回 selection；先修父特征的选择集，再设子特征 |
| 选择集是 `[]` / `entities: []` | 编号在当前几何里不存在，或几何未 build | `geometry_build` → `geometry_get_boundaries` 重查编号；空选择集是**硬错误**，必须修 |
| 改了选择后编号又不对 | 几何改动后编号重排 | 每次改几何后重查；优先用命名选择（`geometry_create_box_selection`） |
| 布尔合并后仍有内部边界/多域 | 布尔操作默认 `intbnd=true` | `geometry_feature_set {"properties": {"intbnd": false}}` |
| 几何自交 / 网格崩在运动后 | 转动/平动没有停 | ω 用布尔因子门控（`alpha*(t<=2[ms])`）；或用行程插值函数 |
| `geometry_build` 失败 | 特征参数为 0/负、坐标写错单位（`"10"` = 10 m） | 看返回的 error；`geometry_list_features` 逐个核参数 |

## 4. 网格类

| 现象 | 原因 | 处置 |
|---|---|---|
| 网格生成失败 | 几何有极小面/短边、倒角、自交 | 简化几何；加 Size 限制；先 `mesh_create` 用默认尺寸验证几何可网格化 |
| 单元数爆炸（内存） | 全域统一细尺寸 | 分区：弧道/间隙细（0.5–1 mm），远场粗（10 mm），增长率 1.15 |
| 结果对网格敏感 | 未做无关性 | `verify_mesh_independence_setup/analyze`；最细两档关键量差 < 2% |
| 边界层网格导致负体积 | 边界层与几何冲突 | 用户控制网格，删默认 Boundary Layers 后重建 |

## 5. MCP / 环境类（不是模型问题）

| 现象 | 原因 | 处置 |
|---|---|---|
| `{"success": false, "already_running": true, ...}` 调 `comsol_start` | **JPype 每进程只允许一个 COMSOL client**；本插件在第二次调用时直接拒绝（否则会清掉已加载模型） | 用 `comsol_status` / `model_list` 继续；真要重开先 `comsol_disconnect` |
| `tool execution unavailable: handlers.py could not be imported` | MCP 服务端不是用 MPh venv 的解释器启动的（缺 `mph`/`jpype`） | 用 `E:/ICE/_tools/COMSOL_Multiphysics_MCP/.venv/Scripts/python.exe` 启动；`node bin/dsh-comsol.mjs doctor` 查 |
| `unknown tool 'xxx'. Close matches: ...` | 工具名猜错 | 按提示名重试；正规做法是先 `search_tools` |
| 第一次调用很慢（数秒） | 首次 `call_tool` 才 import handlers 并注册 157 个工具（约 0.9 s），COMSOL 本身另算 | 正常现象；长会话无感 |
| `static_catalog_info` 报 6.3 而不是 6.4 | 离线静态目录是**打包数据集**（抽取自 6.3 安装），不是活体探测 | 类型/属性名可用；关键名字用 `model_export_java` 或 `physics_feature_info` 在活会话里复核 |
| `call_tool` 返回一长串文本而不是 JSON | 该工具本身返回字符串 | 正常；按内容读，不要 json 解析 |
| 求解卡住超过 30 min 被客户端断开 | 同步 `study_solve` 阻塞太久 | 用 `study_solve_async` + `study_get_progress`，或 `remote_job_submit` |
| 中文路径/乱码 | Windows 控制台编码 | 服务端已把 stdio 重配为 UTF-8；模型路径尽量用 ASCII 工作目录 |

## 6. "找不到一致的初始值"专项

这是最容易被误判成"模型坏了"的一类。按概率排序检查：

1. **初始值与边界条件冲突**（最高频）：初值 300 K、壁面 3000 K，而传热没给过渡；
   → 用阶跃/斜坡把边界条件从初值爬上去（`function_create` 建 ramp，或
   `T0 = 293.15[K] + (Tw-293.15[K])*min(t/1[ms],1)`）。
2. **初始值给了一个"没有解"的场**：例如 σ(T) 初值处在不导电区，电磁方程没有非零解
   → 先跑 Stationary 电磁-only，或把点火热点放进初值。
3. **多个边界条件在同一实体上冲突**：入口 + 壁面、两个 Terminal、Ground 与 Terminal 重叠
   → 读回所有特征的 selection，确认互斥。
4. **材料属性在初值温度处未定义**（插值表越界）→ 插值函数端点外推/夹取
   （`properties` 里加 `extrap: "constant"` 或把表端点拓宽）。
5. **初始步太大**：`Initial step` 默认自动，起弧/相变类问题要显式给 0.01–0.1 µs。

改完一处就重跑一次。**不要同时改 5 个设置然后宣称"修好了"** —— 那样下一个模型还得再踩一遍。
