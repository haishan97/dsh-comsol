# -*- coding: utf-8 -*-
"""Tool catalogue + on-demand search for the COMSOL MCP server.

Only two tools are advertised to the client (`search_tools`, `call_tool`), so a
session pays a few hundred tokens instead of the full tool schemas. The
catalogue below is the search index; `handlers.py` implements every name.

Design copied from dsh-abaqus-cad (MIT): the catalogue never enters the model
context, it is searched on demand. Search quality lives in the bilingual
keywords, so every entry carries the English API vocabulary AND the Chinese
words a user actually types (网格 / 求解 / 温度 / 电场 / 导出 ...).

Keyword tokens are deliberately 2+ characters: the scorer also fires on
`keyword in query`, so a single character like 场 or 解 would match every
query containing it. One-character intents still work -- "热" hits 传热 via
`query in keyword`.

Entries follow tools_inventory.json order (the contract), which is already
grouped by modelling area: session -> model -> parameters -> geometry ->
physics -> electrochemistry -> static catalog -> physics builder -> mesh ->
study -> results -> audit -> functions/materials -> solver -> remote ->
repro -> verify. The two entries after verify_* are implemented by
handlers.py but absent from the inventory, so they are appended last.
"""

import difflib

TOOLS = [
    {
        "name": "plane_fields_export",
        "summary": "导出 COMSOL 解到 y=常数截面的场数据 npz（T/p/u/v/w/B/J/E/V/Ex/Ez/Fx/Fy/Fz），可选插值补洞把覆盖率提到 100%",
        "args": "model_path*, out_dir*, times=0.5, plane_y=0, step_mm=0.5, fill=true",
        "keywords": ["导出", "export", "截面", "plane", "场数据", "npz", "tecplot", "y=0", "覆盖率"],
    },
    {
        "name": "add_jx_jz",
        "summary": "由 |J| 与 Ex/Ez 反推电流密度分量 Jx/Jz（J=sigma*E），供流线/电流管使用",
        "args": "npz_path*, out_npz",
        "keywords": ["Jx", "Jz", "电流密度", "分量", "矢量", "sigma"],
    },
    {
        "name": "current_tubes_plot",
        "summary": "电流管守恒图：弧柱截面撒 n 条种子正向积分到出口，统计进出条数（进 n 出 n 即守恒）",
        "args": "npz_path*, out_png*, n=20, inlet=31,26,28.9, count=x<2, step_mm=0.3, rotate",
        "keywords": ["电流管", "守恒", "conservation", "流线", "streamline", "弧柱", "进出"],
    },
    {
        "name": "current_tubes_multi",
        "summary": "多时刻电流管图 2x2 面板，每个时刻自动定位弧柱核心并撒种子",
        "args": "npz_dir*, out_png*, n=20, half_mm=1.2, xprobe_mm=31, count, labels, step_mm",
        "keywords": ["多时刻", "电流管", "面板", "2x2", "演化", "守恒"],
    },
    {
        "name": "tecplot_render",
        "summary": "Tecplot 批处理渲染：生成宏 + tec360 -b，支持 contour/stream/vector 组合模式",
        "args": "dat_dir*, out_dir*, mode=contour, width=1600, frame=4.20x7.25, dfmt",
        "keywords": ["tecplot", "渲染", "云图", "流线", "矢量", "macro", "批处理"],
    },
    {
        "name": "figure_style",
        "summary": "图面后处理：裁坐标轴/顺时针90°/加纵向色标(Times New Roman)/白底/金属描黑线框",
        "args": "src_png*, out_png*, crop_axes, rotate, colorbar_label, colorbar_min, colorbar_max, colorbar_ticks, white_bg, wireframe",
        "keywords": ["后处理", "裁剪", "旋转", "色标", "colorbar", "白底", "线框", "出图"],
    },
    {
        "name": "domain_series_multi",
        "summary": "逐时刻取域/边界平均（逐索引钉死 solnum），用于栅片电位、触头电位等时间序列",
        "args": "domains*, indices*, expression=V, unit, dataset, node_type",
        "keywords": ["时间序列", "域平均", "栅片电位", "触头电位", "series", "solnum", "V"],
    },
    {
        "name": "domain_average_series",
        "summary": "按域取体平均并返回整条时间序列（每个域一个 AvVolume 节点，绕过算子限制）",
        "args": "domains*, expression=mef.V, dataset, tag_prefix",
        "keywords": ["域平均", "体平均", "电压", "电位", "栅片", "series", "时间序列", "AvVolume"],
    },
    {
        "name": "cpl_average_create",
        "summary": "创建组件平均算子(aveop)，用于取某个域/边界的体平均/面平均，如 aveop8(mef.V)",
        "args": "tag*, entities*, component_name=comp1",
        "keywords": ["average", "平均", "aveop", "算子", "operator", "域平均", "电位", "电压"],
    },
    {
        "name": "study_set_genconv",
        "summary": "开启研究的自动收敛图生成（必须在求解前设置），用于保存残差收敛曲线",
        "args": "enabled=true, study_name, model_name",
        "keywords": ["收敛图", "convergence", "genconv", "残差", "residual", "求解", "日志"],
    },
    {
        "name": "multiphysics_add_boundary",
        "summary": "在边界维度(edim=2)创建多物理场耦合，如平衡放电边界热源，并设边界选择",
        "args": "coupling_type*, boundaries*, tag, physics_list",
        "keywords": ["multiphysics", "多物理场", "边界", "boundary", "bphs", "平衡放电", "热源", "耦合"],
    },
    {
        "name": "plot_camera",
        "summary": "设置三维视图相机（位置/目标/投影）并绑定到绘图组，用于放大/换角度细节图",
        "args": "plotgroup_tag*, position*, target*, up, projection, view_tag",
        "keywords": ["camera", "相机", "视角", "视图", "view", "放大", "zoom", "细节", "角度", "截图"],
    },
    {
        "name": "plot_arrow_fit",
        "summary": "逐时刻自动拟合体箭头比例并批量导出（先量 COMSOL 自动比例再乘系数）",
        "args": "plotgroup_tag*, feature_tag*, times*, file_prefix*, factor=3, width, height",
        "keywords": ["arrow", "箭头", "比例", "scale", "逐时刻", "批量", "export", "导出", "拟合", "auto"],
    },
    {
        "name": "dataset_mirror_create",
        "summary": "建镜像三维数据集（关于 xy/yz/zx 平面镜像解数据），用于半模型显示全场",
        "args": "tag*, source*, plane=zx, offset=0, model_name",
        "keywords": ["mirror", "镜像", "镜像三维", "dataset", "数据集", "对称", "全场", "对称面", "half"],
    },
    {
        "name": "plot_group_build",
        "summary": "按声明式特征表建三维绘图组：材质体(Volume)+体箭头/等值面，含选择集与时刻",
        "args": "plotgroup_tag*, dataset*, features*, time, title, model_name",
        "keywords": [
            "plot", "绘图组", "三维", "3D", "volume", "体", "arrow", "体箭头", "材质",
            "material", "颜色", "coloring", "selection", "选择", "图", "figure", "镜像", "mirror"
        ],
    },
    {
        "name": "plot_frame_export",
        "summary": "把三维绘图组按指定时刻导出为 PNG（宽高可设）",
        "args": "plotgroup_tag*, file_path*, time, width, height, model_name",
        "keywords": [
            "export", "导出", "图片", "image", "png", "截图", "时刻", "time", "帧", "frame",
            "绘图", "figure"
        ],
    },
    {
        "name": "plot_selection_create",
        "summary": "建命名选择（Explicit）供绘图组的体/箭头引用",
        "args": "tag*, entities*, dim, label, model_name",
        "keywords": ["selection", "选择", "命名选择", "named", "explicit", "域", "domain", "材料", "material"],
    },
    {
        "name": "comsol_start",
        "summary": "启动本地 COMSOL 客户端会话（可指定 cores / version / products，默认全部产品）",
        "args": "cores, version, products",
        "keywords": [
            "start", "启动", "开启", "新建", "会话", "session", "client", "连接", "comsol", "内核", "实例",
            "引擎", "launch", "打开", "初始化"
        ],
    },
    {
        "name": "comsol_connect",
        "summary": "连接已运行的远程 COMSOL 服务器（host + port），接管该会话",
        "args": "port*, host=localhost",
        "keywords": [
            "connect", "连接", "远程", "remote", "server", "服务器", "端口", "port", "host", "attach",
            "连上", "接入", "客户端"
        ],
    },
    {
        "name": "comsol_disconnect",
        "summary": "断开 COMSOL 连接并清空内存中所有模型",
        "args": "",
        "keywords": [
            "disconnect", "断开", "关闭", "退出", "close", "释放", "清空", "停止", "卸载", "会话结束"
        ],
    },
    {
        "name": "comsol_status",
        "summary": "会话状态：是否已连接、版本、已加载模型、可用核数",
        "args": "",
        "keywords": [
            "status", "状态", "连接", "会话", "session", "version", "版本", "在线", "健康", "检查", "已加载",
            "信息", "环境"
        ],
    },
    {
        "name": "model_load",
        "summary": "从 .mph 文件加载模型并设为当前模型",
        "args": "file_path*, set_current=true",
        "keywords": [
            "load", "加载", "打开", "读取", "载入", "mph", "文件", "模型", "open", "导入", "现有模型"
        ],
    },
    {
        "name": "model_create",
        "summary": "新建空 COMSOL 模型（并设为当前模型）",
        "args": "name, set_current=true",
        "keywords": [
            "create", "新建", "创建", "空模型", "new", "model", "建模", "从头", "初始化", "新模型"
        ],
    },
    {
        "name": "model_create_component",
        "summary": "创建组件（space_dimension=1/2/3/20 轴对称），几何与物理场的前置",
        "args": "component_name=comp1, space_dimension=3, model_name",
        "keywords": [
            "component", "组件", "新建", "创建", "维度", "dimension", "2d", "3d", "轴对称", "axisymmetric",
            "comp1", "空间维度"
        ],
    },
    {
        "name": "model_list_components",
        "summary": "列出模型中所有组件 tag",
        "args": "model_name",
        "keywords": [
            "components", "组件", "列表", "list", "有哪些", "列出", "组件名"
        ],
    },
    {
        "name": "model_save",
        "summary": "保存模型到 .mph（可另存为；format=Comsol/Java/Matlab/VBA）",
        "args": "model_name, file_path, format",
        "keywords": [
            "save", "保存", "另存", "存盘", "mph", "导出", "代码", "java", "matlab", "vba", "落盘"
        ],
    },
    {
        "name": "model_save_version",
        "summary": "带时间戳版本化保存到 comsol_models/<name>/，并留 latest 副本",
        "args": "model_name, description",
        "keywords": [
            "version", "版本", "快照", "备份", "保存", "snapshot", "时间戳", "latest", "历史", "存档"
        ],
    },
    {
        "name": "model_list",
        "summary": "列出当前会话中所有已加载模型",
        "args": "",
        "keywords": [
            "models", "模型", "列表", "list", "已加载", "会话", "有哪些", "全部模型", "内存"
        ],
    },
    {
        "name": "model_set_current",
        "summary": "切换当前活动模型（后续所有操作作用于它）",
        "args": "model_name*",
        "keywords": [
            "current", "当前", "切换", "设置", "活动", "active", "选择模型", "switch", "指定", "激活"
        ],
    },
    {
        "name": "model_clone",
        "summary": "克隆模型生成副本（改造前先备份、对比用）",
        "args": "model_name, new_name, set_current=false",
        "keywords": [
            "clone", "克隆", "复制", "副本", "copy", "duplicate", "备份", "对比", "派生", "另存一份"
        ],
    },
    {
        "name": "model_remove",
        "summary": "从内存移除模型（不删除磁盘文件）",
        "args": "model_name*",
        "keywords": [
            "remove", "移除", "删除", "卸载", "close", "释放", "内存", "delete", "清理", "关掉"
        ],
    },
    {
        "name": "model_inspect",
        "summary": "模型结构概览：参数 / 物理场 / 研究 / 网格等（轻量摘要）",
        "args": "model_name",
        "keywords": [
            "inspect", "检查", "概览", "结构", "摘要", "info", "模型树", "详情", "有什么", "内容", "一览"
        ],
    },
    {
        "name": "param_get",
        "summary": "读取单个参数值（evaluate=true 返回数值而非表达式）",
        "args": "name*, model_name, evaluate=false",
        "keywords": [
            "param", "参数", "获取", "读取", "get", "value", "查询", "取值", "表达式"
        ],
    },
    {
        "name": "param_set",
        "summary": "设置或新建参数，可带单位如 5[V]、1.5[mm]",
        "args": "name*, value*, model_name, description",
        "keywords": [
            "param", "参数", "设置", "修改", "set", "赋值", "单位", "mm", "定义", "改参数", "全局参数"
        ],
    },
    {
        "name": "param_list",
        "summary": "列出模型全部参数（evaluate=true 给数值）",
        "args": "model_name, evaluate=false",
        "keywords": [
            "params", "参数", "列表", "全部", "list", "一览", "变量", "有哪些", "参数表"
        ],
    },
    {
        "name": "param_sweep_setup",
        "summary": "为参数设置参数化扫描，挂到指定研究",
        "args": "parameter_name*, values*, model_name, study_name",
        "keywords": [
            "sweep", "扫描", "参数化", "parametric", "批量", "变参数", "工况", "研究", "study", "遍历", "系列"
        ],
    },
    {
        "name": "param_description",
        "summary": "读取或设置参数的描述文字",
        "args": "name*, text, model_name",
        "keywords": [
            "description", "描述", "说明", "注释", "备注", "参数", "注释文字"
        ],
    },
    {
        "name": "geometry_list",
        "summary": "列出模型的几何序列 tag",
        "args": "model_name",
        "keywords": [
            "geometry", "几何", "列表", "list", "序列", "有哪些", "几何序列"
        ],
    },
    {
        "name": "geometry_create",
        "summary": "新建几何序列（space_dimension=2/3）",
        "args": "geometry_name, space_dimension=3, component_name=comp1, model_name",
        "keywords": [
            "geometry", "几何", "新建", "创建", "序列", "2d", "3d", "空间维度", "建模开始"
        ],
    },
    {
        "name": "geometry_add_feature",
        "summary": "通用几何特征：Block/Cylinder/Sphere/Rectangle/Circle/WorkPlane/Polygon/Import/Union 等",
        "args": "feature_type*, geometry_name, component_name=comp1, feature_name, model_name, properties",
        "keywords": [
            "geometry", "几何", "特征", "feature", "block", "长方体", "圆柱", "cylinder", "sphere", "矩形",
            "rectangle", "circle", "多边形", "polygon", "导入", "import", "union", "布尔", "工作平面",
            "workplane"
        ],
    },
    {
        "name": "geometry_add_block",
        "summary": "加长方体块（position 角点 + size 尺寸，单位 m）",
        "args": "position, size, geometry_name, component_name=comp1, feature_name, model_name",
        "keywords": [
            "block", "长方体", "立方体", "box", "立方", "cuboid", "几何", "建模", "实体"
        ],
    },
    {
        "name": "geometry_add_cylinder",
        "summary": "加圆柱（position 底面圆心 + radius + height）",
        "args": "position, radius=0.5, height=1.0, geometry_name, component_name=comp1, feature_name, model_name",
        "keywords": [
            "cylinder", "圆柱", "柱体", "几何", "建模", "回转体"
        ],
    },
    {
        "name": "geometry_add_sphere",
        "summary": "加球体（position 球心 + radius）",
        "args": "position, radius=0.5, geometry_name, component_name=comp1, feature_name, model_name",
        "keywords": [
            "sphere", "球体", "几何", "建模", "球面", "ball"
        ],
    },
    {
        "name": "geometry_add_rectangle",
        "summary": "在 2D 几何或工作平面加矩形",
        "args": "position, size, geometry_name, component_name=comp1, feature_name, model_name",
        "keywords": [
            "rectangle", "矩形", "长方形", "2d", "平面", "几何", "二维"
        ],
    },
    {
        "name": "geometry_add_circle",
        "summary": "在 2D 几何或工作平面加圆",
        "args": "position, radius=0.5, geometry_name, component_name=comp1, feature_name, model_name",
        "keywords": [
            "circle", "圆形", "2d", "平面", "几何", "二维"
        ],
    },
    {
        "name": "geometry_boolean_union",
        "summary": "布尔并集：合并多个对象（注意 intbnd 内边界开关）",
        "args": "input_objects*, geometry_name, component_name=comp1, feature_name, model_name",
        "keywords": [
            "union", "并集", "合并", "boolean", "布尔", "组合", "相加", "融合", "unite"
        ],
    },
    {
        "name": "geometry_boolean_difference",
        "summary": "布尔差集：从主体扣除若干对象（打孔 / 挖槽 / 减料）",
        "args": "input_object*, objects_to_subtract*, geometry_name, component_name=comp1, feature_name, model_name",
        "keywords": [
            "difference", "差集", "减去", "扣除", "打孔", "挖孔", "挖槽", "布尔", "subtract", "cut"
        ],
    },
    {
        "name": "geometry_import",
        "summary": "导入 CAD 几何（STEP / IGES / STL 等）",
        "args": "file_path*, geometry_name, import_type=CAD, component_name=comp1, feature_name, model_name",
        "keywords": [
            "import", "导入", "cad", "step", "iges", "stl", "文件", "几何", "读入", "外部模型", "装配"
        ],
    },
    {
        "name": "geometry_build",
        "summary": "构建几何序列生成实际几何（改完特征必须 build）",
        "args": "geometry_name, component_name=comp1, model_name",
        "keywords": [
            "build", "构建", "生成", "建几何", "更新", "rebuild", "编译", "生效", "几何完成"
        ],
    },
    {
        "name": "geometry_list_features",
        "summary": "列出几何序列中所有特征及 tag",
        "args": "geometry_name, component_name=comp1, model_name",
        "keywords": [
            "features", "特征", "列表", "几何", "序列", "有哪些", "特征名"
        ],
    },
    {
        "name": "geometry_create_box_selection",
        "summary": "按坐标包围盒创建命名选择（选边界 / 域 / 点，供物理场引用）",
        "args": "selection_name*, x_min*, x_max*, y_min*, y_max*, z_min, z_max, entity_dimension=1, condition=intersects, geometry_name, component_name=comp1, model_name",
        "keywords": [
            "selection", "选择", "命名选择", "box", "包围盒", "坐标", "框选", "named", "边界", "选区", "区域"
        ],
    },
    {
        "name": "geometry_create_side_selections",
        "summary": "批量创建 left/right/bottom/top 四个命名边界选择（矩形域常用）",
        "args": "x_min*, x_max*, y_min*, y_max*, prefix=side, tolerance=1e-9[m], entity_dimension=1, geometry_name, component_name=comp1, model_name",
        "keywords": [
            "selection", "选择", "边界", "左右", "上下", "left", "right", "bottom", "top", "矩形", "批量",
            "进出口", "四面"
        ],
    },
    {
        "name": "physics_list",
        "summary": "列出模型中的物理场接口",
        "args": "model_name",
        "keywords": [
            "physics", "物理场", "列表", "list", "接口", "有哪些", "已加物理场"
        ],
    },
    {
        "name": "physics_get_available",
        "summary": "按类别列出可添加的物理场接口（含所属模块）",
        "args": "",
        "keywords": [
            "available", "可用", "物理场", "列表", "接口", "目录", "有哪些", "支持", "模块", "能加什么"
        ],
    },
    {
        "name": "physics_get_acoustic_boundary_conditions",
        "summary": "声学边界条件类型与属性参考（SoundHard / Impedance / Radiation 等）",
        "args": "",
        "keywords": [
            "acoustic", "声学", "边界", "条件", "参考", "类型", "impedance", "阻抗", "声压", "辐射", "硬声场"
        ],
    },
    {
        "name": "physics_get_pde_boundary_conditions",
        "summary": "PDE 边界条件类型参考（Dirichlet / Flux / Periodic 等）",
        "args": "",
        "keywords": [
            "pde", "边界", "条件", "参考", "类型", "dirichlet", "通量", "flux", "periodic", "周期", "狄利克雷"
        ],
    },
    {
        "name": "physics_add",
        "summary": "添加物理场接口（Electrostatics / ElectricCurrents / HeatTransfer / LaminarFlow 等）",
        "args": "physics_type*, component_name, model_name",
        "keywords": [
            "physics", "物理场", "添加", "接口", "add", "电场", "静电场", "电流", "传热", "流体", "固体力学", "声学",
            "新增物理场"
        ],
    },
    {
        "name": "physics_add_electrostatics",
        "summary": "加静电场 es（电场 / 电势 / 电容分析）",
        "args": "domain_selection, model_name",
        "keywords": [
            "electrostatics", "静电场", "电场", "es", "电势", "电压", "电容", "电荷", "静电"
        ],
    },
    {
        "name": "physics_add_solid_mechanics",
        "summary": "加固体力学 solid（应力 / 变形 / 结构）",
        "args": "domain_selection, model_name",
        "keywords": [
            "solid", "固体力学", "结构", "应力", "变形", "力学", "弹性", "位移", "强度"
        ],
    },
    {
        "name": "physics_add_heat_transfer",
        "summary": "加传热 ht（温度场 / 热传导 / 散热）",
        "args": "domain_selection, model_name",
        "keywords": [
            "heat", "传热", "温度", "ht", "热传导", "散热", "热分析", "温升", "热场"
        ],
    },
    {
        "name": "physics_add_laminar_flow",
        "summary": "加层流 spf（流体流动 / 速度 / 压力场）",
        "args": "domain_selection, model_name",
        "keywords": [
            "laminar", "层流", "流体", "流动", "流场", "spf", "cfd", "速度", "压力", "湍流", "气流"
        ],
    },
    {
        "name": "physics_add_pressure_acoustics",
        "summary": "加压力声学 acpr（频域声场分析）",
        "args": "domain_selection, component_name, geometry_name, physics_tag=acpr, model_name",
        "keywords": [
            "acoustics", "声学", "声压", "频域", "acpr", "声场", "声波", "噪声", "频率"
        ],
    },
    {
        "name": "physics_add_acoustics",
        "summary": "按 COMSOL 类型名加声学接口（如 ThermoacousticsSinglePhysics）",
        "args": "physics_type*, physics_tag, domain_selection, component_name, geometry_name, model_name",
        "keywords": [
            "acoustics", "声学", "接口", "类型", "热声", "thermoacoustics", "声固", "指定类型"
        ],
    },
    {
        "name": "physics_add_coefficient_form_pde",
        "summary": "加系数型 PDE（c / a / f / da 系数）",
        "args": "dependent_variables, equation_properties, domain_selection, component_name, physics_tag=c, model_name",
        "keywords": [
            "pde", "系数", "coefficient", "方程", "自定义", "偏微分", "输运", "扩散"
        ],
    },
    {
        "name": "physics_add_general_form_pde",
        "summary": "加一般型 PDE（Ga / f / da）",
        "args": "dependent_variables, equation_properties, domain_selection, component_name, physics_tag=g, model_name",
        "keywords": [
            "pde", "general", "一般", "方程", "自定义", "偏微分", "通用形式"
        ],
    },
    {
        "name": "physics_add_weak_form_pde",
        "summary": "加弱形式 PDE（weak 表达式）",
        "args": "dependent_variables, equation_properties, domain_selection, component_name, physics_tag=w, model_name",
        "keywords": [
            "pde", "weak", "弱形式", "方程", "自定义", "变分", "弱解"
        ],
    },
    {
        "name": "physics_configure_boundary",
        "summary": "给物理场配置边界条件（Temperature / HeatFlux / Inlet / Wall / Fixed / Ground…）",
        "args": "physics_name*, boundary_condition*, boundary_selection*, properties, model_name",
        "keywords": [
            "boundary", "边界", "条件", "bc", "配置", "温度", "热流", "入口", "出口", "壁面", "固定", "电压", "接地",
            "绝热", "对流"
        ],
    },
    {
        "name": "physics_configure_acoustic_boundary",
        "summary": "配置单个声学边界条件",
        "args": "physics_name*, boundary_condition*, boundary_selection, properties, selection_name, boundary_dimension, model_name",
        "keywords": [
            "acoustic", "声学", "边界", "条件", "配置", "阻抗", "辐射", "硬声场", "声压", "单个"
        ],
    },
    {
        "name": "physics_setup_acoustic_boundaries",
        "summary": "一次配置多个声学边界条件",
        "args": "physics_name*, boundary_conditions*, boundary_dimension, model_name",
        "keywords": [
            "acoustic", "声学", "边界", "条件", "批量", "多个", "一次", "配置", "声场"
        ],
    },
    {
        "name": "physics_configure_pde_boundary",
        "summary": "配置单个 PDE 边界条件（可绑命名选择）",
        "args": "physics_name*, boundary_condition*, boundary_selection, properties, selection_name, boundary_dimension, model_name",
        "keywords": [
            "pde", "边界", "条件", "配置", "dirichlet", "通量", "命名选择", "单个"
        ],
    },
    {
        "name": "physics_setup_pde_boundaries",
        "summary": "一次配置多个 PDE 边界条件",
        "args": "physics_name*, boundary_conditions*, boundary_dimension, model_name",
        "keywords": [
            "pde", "边界", "条件", "批量", "多个", "一次", "配置"
        ],
    },
    {
        "name": "physics_set_material",
        "summary": "把材料指派到物理场域（自动从材料库导入）",
        "args": "physics_name*, material_name*, domain_selection, model_name",
        "keywords": [
            "material", "材料", "指派", "赋材料", "assign", "空气", "指定材料"
        ],
    },
    {
        "name": "multiphysics_add",
        "summary": "加多物理场耦合（ThermalExpansion / ElectromagneticHeating / NonIsothermalFlow…）",
        "args": "coupling_type*, physics_list*, model_name",
        "keywords": [
            "multiphysics", "多物理场", "耦合", "coupling", "热电", "焦耳热", "热应力", "流固", "压电", "电磁热",
            "共轭传热"
        ],
    },
    {
        "name": "physics_list_features",
        "summary": "列出物理场全部特征（含嵌套子特征、几何选择、启用状态）",
        "args": "physics_name*, model_name, recursive=true, include_details=false",
        "keywords": [
            "features", "特征", "列表", "边界条件", "子特征", "嵌套", "选择", "启用", "禁用", "明细", "物理场细节"
        ],
    },
    {
        "name": "physics_remove",
        "summary": "删除物理场接口",
        "args": "physics_name*, model_name",
        "keywords": [
            "remove", "删除", "移除", "物理场", "接口", "去掉"
        ],
    },
    {
        "name": "geometry_get_boundaries",
        "summary": "列出几何边界编号与面积（判断哪条边对应哪个面）",
        "args": "geometry_name, component_name=comp1, model_name",
        "keywords": [
            "boundaries", "边界", "编号", "面积", "几何", "识别", "面号", "哪条边", "尺寸"
        ],
    },
    {
        "name": "physics_interactive_setup_flow",
        "summary": "层流边界条件交互式设置向导",
        "args": "physics_name=Laminar Flow, model_name",
        "keywords": [
            "flow", "流动", "向导", "wizard", "入口", "出口", "交互", "层流", "引导"
        ],
    },
    {
        "name": "physics_setup_flow_boundaries",
        "summary": "一次设置层流入口速度与出口压力",
        "args": "physics_name*, inlet_boundaries*, outlet_boundaries*, inlet_velocity=1[mm/s], outlet_pressure=0, model_name",
        "keywords": [
            "flow", "流动", "入口", "出口", "inlet", "outlet", "速度", "压力", "层流", "边界", "进出口"
        ],
    },
    {
        "name": "physics_interactive_setup_heat",
        "summary": "传热边界条件交互式设置向导",
        "args": "physics_name=Heat Transfer in Solids, model_name",
        "keywords": [
            "heat", "传热", "温度", "向导", "wizard", "交互", "边界", "引导"
        ],
    },
    {
        "name": "physics_setup_heat_boundaries",
        "summary": "一次设置传热边界：热流 / 定温 / 对流散热",
        "args": "physics_name*, heat_flux_boundaries, temperature_boundaries, convection_boundaries, heat_flux_value=1e6[W/m^2], temperature_value=293.15[K], convection_coeff=10[W/(m^2*K)], ambient_temp=293.15[K], model_name",
        "keywords": [
            "heat", "传热", "温度", "热流", "对流", "边界", "批量", "convection", "散热", "恒温"
        ],
    },
    {
        "name": "physics_boundary_selection",
        "summary": "通用边界条件设置（按边界号 + 属性字典）",
        "args": "physics_name*, boundary_condition_type*, boundary_numbers*, properties, model_name",
        "keywords": [
            "boundary", "边界", "条件", "通用", "选择", "批量", "边界号", "任意条件"
        ],
    },
    {
        "name": "electrochemistry_get_interfaces",
        "summary": "列出已验证的电化学接口（锂电池 / 燃料电池 / 腐蚀 / 电沉积…）",
        "args": "category",
        "keywords": [
            "electrochemistry", "电化学", "电池", "battery", "燃料电池", "fuel", "cell", "腐蚀",
            "corrosion", "电沉积", "接口", "类别"
        ],
    },
    {
        "name": "electrochemistry_get_feature_types",
        "summary": "列出电化学接口的特征类型（含子特征与维度）",
        "args": "physics_type*, include_subfeatures=true",
        "keywords": [
            "electrochemistry", "电化学", "特征", "类型", "feature", "子特征", "维度", "支持哪些"
        ],
    },
    {
        "name": "electrochemistry_add_interface",
        "summary": "加电化学物理场接口（LithiumIonBatteryMPH / LumpedBattery 等）",
        "args": "physics_type*, physics_tag, component_name, geometry_name, domain_selection, model_name",
        "keywords": [
            "electrochemistry", "电化学", "电池", "添加", "接口", "battery", "锂离子", "集总", "二次电流"
        ],
    },
    {
        "name": "electrochemistry_list_features",
        "summary": "列出物理场特征及其真实 COMSOL 类型（任意接口通用）",
        "args": "physics_name*, model_name",
        "keywords": [
            "electrochemistry", "电化学", "特征", "列表", "类型", "反射", "通用", "真实类型", "诊断"
        ],
    },
    {
        "name": "electrochemistry_add_feature",
        "summary": "加电化学特征（ElectrodeSurface / PorousElectrode / ElectrodeReaction 等，可挂父特征）",
        "args": "physics_name*, feature_type*, physics_type_hint, parent_feature, boundaries, domains, edges, points, selection_name, dimension, properties, feature_tag, label, model_name",
        "keywords": [
            "electrochemistry", "电化学", "特征", "添加", "电极", "多孔", "反应", "双电层", "电极面", "嵌套", "子特征"
        ],
    },
    {
        "name": "electrochemistry_set_feature_selection",
        "summary": "修改电化学特征的几何选择",
        "args": "physics_name*, feature_tag*, boundaries, domains, edges, points, selection_name, model_name",
        "keywords": [
            "electrochemistry", "电化学", "选择", "几何", "边界", "设置", "改选择"
        ],
    },
    {
        "name": "electrochemistry_list_interface_properties",
        "summary": "列出接口级属性组（如 BatterySettings）的属性名与当前值",
        "args": "physics_name*, property_group*, model_name",
        "keywords": [
            "electrochemistry", "电化学", "属性", "battery", "settings", "容量", "soc", "电流", "接口属性"
        ],
    },
    {
        "name": "electrochemistry_set_interface_properties",
        "summary": "设置接口级属性（Q_cell0 / SOC_cell0 / I_app 等电池主参数）",
        "args": "physics_name*, property_group*, properties*, model_name",
        "keywords": [
            "electrochemistry", "电化学", "属性", "设置", "容量", "soc", "电流", "充放电", "电池", "额定", "初始"
        ],
    },
    {
        "name": "electrochemistry_set_feature_properties",
        "summary": "设置电化学特征属性（epsilons / Ds 等，逐项返回校验结果）",
        "args": "physics_name*, feature_tag*, properties*, parent_tag, model_name",
        "keywords": [
            "electrochemistry", "电化学", "属性", "设置", "特征", "参数", "校验", "孔隙率", "扩散系数"
        ],
    },
    {
        "name": "electrochemistry_list_feature_properties",
        "summary": "列出某特征合法的属性名（设属性前先查）",
        "args": "physics_name*, feature_tag*, parent_tag, model_name",
        "keywords": [
            "electrochemistry", "电化学", "属性", "名称", "列表", "合法", "字段", "可用属性"
        ],
    },
    {
        "name": "static_catalog_info",
        "summary": "离线静态目录的覆盖范围（版本 / 条目数 / 来源），无需会话",
        "args": "",
        "keywords": [
            "static", "静态", "离线", "目录", "catalog", "信息", "版本", "覆盖", "无需会话", "数据来源"
        ],
    },
    {
        "name": "static_catalog_search",
        "summary": "离线搜索物理场接口与多物理场耦合（验证类型名与许可证需求）",
        "args": "query*, kind",
        "keywords": [
            "static", "静态", "搜索", "离线", "接口", "耦合", "类型", "名称", "验证", "许可证", "查名字"
        ],
    },
    {
        "name": "static_catalog_features",
        "summary": "列出接口的特征类型及其属性 schema（无需会话）",
        "args": "interface_id*",
        "keywords": [
            "static", "静态", "特征", "属性", "schema", "接口", "列表", "默认值", "结构"
        ],
    },
    {
        "name": "static_catalog_properties",
        "summary": "查某特征类型的属性 schema（名称 / 类型 / 默认值）",
        "args": "layer*, type_name*",
        "keywords": [
            "static", "静态", "属性", "schema", "类型", "默认值", "字段", "属性表"
        ],
    },
    {
        "name": "static_catalog_variables",
        "summary": "搜索物理场变量字典（约 19000 条定义表达式）",
        "args": "query*, module, name_only=false",
        "keywords": [
            "static", "静态", "变量", "variable", "字典", "表达式", "定义", "搜索", "后处理", "变量名", "公式"
        ],
    },
    {
        "name": "static_catalog_discretization",
        "summary": "查接口默认离散化（各场单元阶数、边界通量开关）",
        "args": "interface_id*",
        "keywords": [
            "static", "静态", "离散化", "discretization", "单元阶数", "order", "形函数", "插值阶次"
        ],
    },
    {
        "name": "static_catalog_layer",
        "summary": "列出某建模层（geometry/mesh/solver/study/function/plot…）的已知类型名",
        "args": "layer*",
        "keywords": [
            "static", "静态", "layer", "类型", "名称", "校验", "geometry", "mesh", "solver", "study",
            "合法类型"
        ],
    },
    {
        "name": "physicsbuilder_generate",
        "summary": "用模板生成自定义物理场接口 .mphphb（弱形式 + 域/边界输入）",
        "args": "filepath*, typename*, label*, field_variable*, weak_expression*, diffusivity_param=D, source_param=f, boundary_param=u0, extra_substitutions",
        "keywords": [
            "physicsbuilder", "物理场", "builder", "自定义", "生成", "弱形式", "模板", "接口", "mphphb", "自建"
        ],
    },
    {
        "name": "physicsbuilder_register",
        "summary": "注册 .mphphb 为开发文件（写 comsol.prefs，需重启会话生效）",
        "args": "filepath*",
        "keywords": [
            "physicsbuilder", "注册", "register", "开发", "文件", "自定义", "接口", "重启", "生效"
        ],
    },
    {
        "name": "physicsbuilder_status",
        "summary": "查看 Physics Builder 注册状态（开发文件与开关）",
        "args": "",
        "keywords": [
            "physicsbuilder", "状态", "注册", "开发", "文件", "开关", "检查"
        ],
    },
    {
        "name": "mesh_list",
        "summary": "列出网格序列及其组件 / 几何（稳定 tag）",
        "args": "component_name, model_name",
        "keywords": [
            "mesh", "网格", "列表", "序列", "list", "有哪些", "网格序列"
        ],
    },
    {
        "name": "mesh_create_sequence",
        "summary": "新建绑定几何的网格序列",
        "args": "mesh_name=mesh1, geometry_name, component_name, model_name",
        "keywords": [
            "mesh", "网格", "新建", "序列", "创建", "建网格序列"
        ],
    },
    {
        "name": "mesh_create",
        "summary": "生成网格（可指定序列；无序列时自动建默认序列并划分）",
        "args": "mesh_name, geometry_name, component_name, auto_create=true, model_name",
        "keywords": [
            "mesh", "网格", "划分", "生成", "建网格", "remesh", "剖分", "加密", "网格化", "划分网格"
        ],
    },
    {
        "name": "mesh_info",
        "summary": "查网格信息（tag / 组件 / 几何 / 特征、单元统计）",
        "args": "mesh_name, component_name, model_name",
        "keywords": [
            "mesh", "网格", "信息", "info", "统计", "单元", "数量", "质量", "详情"
        ],
    },
    {
        "name": "study_list",
        "summary": "列出模型中的研究",
        "args": "model_name",
        "keywords": [
            "study", "研究", "列表", "list", "分析", "有哪些", "研究步骤"
        ],
    },
    {
        "name": "study_create",
        "summary": "新建研究（Stationary / TimeDependent / Eigenfrequency / Frequency…，可设 tlist）",
        "args": "study_type=Stationary, study_name, step_properties, model_name",
        "keywords": [
            "study", "研究", "新建", "创建", "稳态", "瞬态", "时变", "特征频率", "频域", "模态", "时间步", "tlist",
            "分析类型"
        ],
    },
    {
        "name": "study_solve",
        "summary": "求解研究（默认同步等待，timeout 可调）",
        "args": "study_name, model_name, wait=true, timeout",
        "keywords": [
            "solve", "求解", "计算", "run", "提交", "求解器", "解算", "算一下", "开始计算"
        ],
    },
    {
        "name": "study_solve_async",
        "summary": "后台异步求解（长时求解首选，不阻塞会话）",
        "args": "study_name, model_name",
        "keywords": [
            "solve", "求解", "异步", "async", "后台", "并行", "不阻塞", "长时", "排队", "挂后台"
        ],
    },
    {
        "name": "study_get_progress",
        "summary": "查当前求解进度与耗时",
        "args": "",
        "keywords": [
            "progress", "进度", "求解", "状态", "耗时", "百分比", "跑到哪", "还要多久"
        ],
    },
    {
        "name": "study_cancel",
        "summary": "取消当前求解",
        "args": "",
        "keywords": [
            "cancel", "取消", "中断", "停止", "终止", "求解", "打断"
        ],
    },
    {
        "name": "study_wait",
        "summary": "等待求解完成（可设 timeout）",
        "args": "timeout",
        "keywords": [
            "wait", "等待", "求解", "阻塞", "完成", "等它跑完", "收尾"
        ],
    },
    {
        "name": "solutions_list",
        "summary": "列出模型的解与求解器序列",
        "args": "model_name",
        "keywords": [
            "solutions", "求解器", "列表", "solution", "序列", "有哪些解"
        ],
    },
    {
        "name": "datasets_list",
        "summary": "列出数据集（可求值 / 可视化的解数据）",
        "args": "model_name",
        "keywords": [
            "datasets", "数据集", "列表", "数据", "结果", "可求值"
        ],
    },
    {
        "name": "results_evaluate",
        "summary": "在数据集上求表达式值（inner=时间步，outer=参数扫描）",
        "args": "expression*, unit, dataset, inner, outer, model_name",
        "keywords": [
            "evaluate", "求值", "表达式", "数据集", "提取", "数值", "探针", "后处理", "取值"
        ],
    },
    {
        "name": "results_global_evaluate",
        "summary": "全局标量求值（积分 / 最大值等算子表达式）",
        "args": "expression*, unit, dataset, model_name",
        "keywords": [
            "global", "全局", "标量", "求值", "积分", "intop", "最大值", "maxop", "派生值", "总量", "平均"
        ],
    },
    {
        "name": "results_inner_values",
        "summary": "取内层解索引与值（瞬态时间步列表）",
        "args": "dataset, model_name",
        "keywords": [
            "inner", "时间步", "索引", "瞬态", "列表", "time", "输出时刻"
        ],
    },
    {
        "name": "results_outer_values",
        "summary": "取外层解索引与值（参数扫描的参数值）",
        "args": "dataset, model_name",
        "keywords": [
            "outer", "参数扫描", "参数值", "索引", "列表", "工况"
        ],
    },
    {
        "name": "results_export_data",
        "summary": "导出数据节点数据（表格 / CSV 等）",
        "args": "node_name, file_path, model_name",
        "keywords": [
            "export", "导出", "数据", "data", "表格", "csv", "保存", "落盘", "文本"
        ],
    },
    {
        "name": "results_export_image",
        "summary": "导出绘图为图片（PNG 等）",
        "args": "node_name, file_path, model_name",
        "keywords": [
            "export", "导出", "图片", "图像", "image", "png", "截图", "绘图", "云图", "出图"
        ],
    },
    {
        "name": "results_exports_list",
        "summary": "列出模型的导出节点",
        "args": "model_name",
        "keywords": [
            "exports", "导出", "节点", "列表", "有哪些", "已定义导出"
        ],
    },
    {
        "name": "results_plots_list",
        "summary": "列出模型的绘图节点",
        "args": "model_name",
        "keywords": [
            "plots", "绘图", "列表", "云图", "有哪些", "已定义绘图", "图组"
        ],
    },
    {
        "name": "model_audit",
        "summary": "全量审计模型：每个节点 / 属性 / 嵌套子特征 / 选择 / 禁用标记，输出 JSON + MD 报告",
        "args": "model_name, output_dir, sections",
        "keywords": [
            "audit", "审计", "全量", "检查", "模型", "报告", "属性", "节点", "禁用", "完整", "体检", "盲点"
        ],
    },
    {
        "name": "model_diff",
        "summary": "对比两次审计 JSON，列出增删节点 / 属性与变更值",
        "args": "audit_file_old*, audit_file_new*, max_items=100",
        "keywords": [
            "diff", "对比", "差异", "比较", "审计", "变更", "前后", "改了什么"
        ],
    },
    {
        "name": "model_export_java",
        "summary": "导出模型 Java API 源码（GUI 每个设置对应一行调用，便于复现）",
        "args": "model_name, output_path, decode_unicode=true",
        "keywords": [
            "java", "导出", "代码", "api", "源码", "复现", "脚本", "代码化"
        ],
    },
    {
        "name": "audit_model_config",
        "summary": "导出模型完整配置（参数 / 函数 / 选择 / 几何 / 物理场 / 材料 / 网格 / 研究 / 求解器 / 探针）",
        "args": "model_name, out_dir",
        "keywords": [
            "audit", "审计", "配置", "导出", "全量", "参数", "物理场", "网格", "研究", "报告", "建模检查"
        ],
    },
    {
        "name": "audit_paper_checklist",
        "summary": "按论文陈述逐条核对模型配置（参数 / 计数 / 选择 / 网格 / 研究）",
        "args": "paper_facts*, model_name, rel_tol=1e-06, out_dir",
        "keywords": [
            "audit", "审计", "论文", "paper", "核对", "复现", "清单", "checklist", "验证", "对得上"
        ],
    },
    {
        "name": "audit_models_diff",
        "summary": "对比两个在会话模型的配置结构（重建 vs 原始）",
        "args": "model_a*, model_b*, out_dir",
        "keywords": [
            "audit", "审计", "对比", "diff", "模型", "重建", "结构", "差异", "两个模型"
        ],
    },
    {
        "name": "function_create",
        "summary": "建模型级函数（Interpolation 插值表 / OCV 曲线、Analytic、Step…）",
        "args": "func_type=Interpolation, tag, funcname, table, properties, model_name",
        "keywords": [
            "function", "函数", "插值", "interpolation", "ocv", "曲线", "analytic", "解析", "step",
            "阶跃", "定义", "曲线数据"
        ],
    },
    {
        "name": "function_set",
        "summary": "修改已有函数的属性或插值表",
        "args": "tag*, properties, table, funcname, model_name",
        "keywords": [
            "function", "函数", "修改", "设置", "插值表", "属性", "更新"
        ],
    },
    {
        "name": "material_create",
        "summary": "建材料并写属性组（def / liion 等，可引用插值函数）",
        "args": "tag, label, component_tag, selection, selection_all=true, property_groups, model_name",
        "keywords": [
            "material", "材料", "新建", "创建", "属性", "密度", "导热", "电导", "自定义", "物性"
        ],
    },
    {
        "name": "material_set",
        "summary": "改材料标签 / 选择 / 属性组（缺的组自动创建）",
        "args": "material_tag*, label, component_tag, selection, property_groups, model_name",
        "keywords": [
            "material", "材料", "修改", "设置", "属性", "选择", "指派", "更新", "物性"
        ],
    },
    {
        "name": "material_delete",
        "summary": "删除组件中的材料",
        "args": "material_tag*, component_tag, model_name",
        "keywords": [
            "material", "材料", "删除", "移除", "去掉"
        ],
    },
    {
        "name": "physics_feature_info",
        "summary": "读单个物理场特征的完整信息（任意嵌套深度：属性 / 选择 / 子特征）",
        "args": "physics_name*, feature_path*, model_name",
        "keywords": [
            "feature", "特征", "信息", "读取", "嵌套", "属性", "选择", "子特征", "详情", "某个特征"
        ],
    },
    {
        "name": "physics_feature_create",
        "summary": "建物理场特征（可挂父特征，如电极反应挂电极面）",
        "args": "physics_name*, feature_type*, tag, parent, dim, selection, selection_all=false, properties, model_name",
        "keywords": [
            "feature", "特征", "新建", "创建", "边界条件", "嵌套", "父特征", "加特征"
        ],
    },
    {
        "name": "physics_feature_set",
        "summary": "改物理场特征属性（任意嵌套路径，逐项回读校验）",
        "args": "physics_name*, feature_path*, properties*, model_name",
        "keywords": [
            "feature", "特征", "设置", "属性", "修改", "校验", "嵌套", "改参数"
        ],
    },
    {
        "name": "physics_feature_toggle",
        "summary": "启用 / 禁用物理场特征（排查条件为什么没生效）",
        "args": "physics_name*, feature_path*, enabled*, model_name",
        "keywords": [
            "toggle", "启用", "禁用", "开关", "特征", "生效", "排查", "屏蔽", "打开关闭"
        ],
    },
    {
        "name": "physics_feature_delete",
        "summary": "删除物理场特征（含嵌套路径）",
        "args": "physics_name*, feature_path*, model_name",
        "keywords": [
            "delete", "删除", "移除", "特征", "去掉"
        ],
    },
    {
        "name": "physics_set_feature_selection",
        "summary": "改物理场特征的几何选择（边界 / 域 / 命名选择）",
        "args": "physics_name*, feature_path*, selection*, model_name",
        "keywords": [
            "selection", "选择", "特征", "几何", "边界", "命名", "改选择", "重新选"
        ],
    },
    {
        "name": "physics_set_interface_selection",
        "summary": "改物理场接口的域选择（例如流体只算流体域）",
        "args": "physics_name*, selection*, model_name",
        "keywords": [
            "interface", "接口", "选择", "限定", "范围", "物理场", "只算", "作用域"
        ],
    },
    {
        "name": "geometry_feature_delete",
        "summary": "删除几何特征并重建（撤销误建的特征）",
        "args": "feature_tag*, component_name, geometry_name, model_name",
        "keywords": [
            "geometry", "几何", "删除", "特征", "撤销", "移除", "去掉"
        ],
    },
    {
        "name": "geometry_set_feature_selection",
        "summary": "设置几何特征的实体选择（Chamfer / Fillet / Delete Entities 用）",
        "args": "feature_tag*, selection*, selection_group, component_name, geometry_name, model_name",
        "keywords": [
            "geometry", "几何", "选择", "特征", "倒角", "圆角", "fillet", "chamfer", "顶点", "实体选择"
        ],
    },
    {
        "name": "multiphysics_set",
        "summary": "设置多物理场耦合的域选择与源 / 目标物理场",
        "args": "coupling_tag*, selection, properties, model_name",
        "keywords": [
            "multiphysics", "多物理场", "耦合", "设置", "选择", "修复", "关联", "源目标"
        ],
    },
    {
        "name": "component_delete",
        "summary": "删除整个组件及其全部内容",
        "args": "component_tag*, model_name",
        "keywords": [
            "component", "组件", "删除", "移除", "清掉"
        ],
    },
    {
        "name": "geometry_feature_set",
        "summary": "改几何特征属性（如 Union 的 intbnd 内边界开关）",
        "args": "feature_tag*, properties*, component_name, geometry_name, model_name",
        "keywords": [
            "geometry", "几何", "特征", "属性", "设置", "intbnd", "内边界", "开关", "修改"
        ],
    },
    {
        "name": "multiphysics_delete",
        "summary": "删除多物理场耦合",
        "args": "coupling_tag*, model_name",
        "keywords": [
            "multiphysics", "多物理场", "耦合", "删除", "移除", "去掉"
        ],
    },
    {
        "name": "solver_feature_list",
        "summary": "列求解器配置树（时间步 / 容差 / 线性求解器 / 延拓）",
        "args": "solution_tag*, model_name",
        "keywords": [
            "solver", "求解器", "配置", "时间步", "容差", "线性", "列表", "求解设置"
        ],
    },
    {
        "name": "solver_feature_set",
        "summary": "改求解器树特征属性（时间步列表 / 最大步长 / 容差）",
        "args": "solution_tag*, feature_path*, properties*, model_name",
        "keywords": [
            "solver", "求解器", "设置", "时间步", "tlist", "容差", "最大步长", "收敛", "调求解器"
        ],
    },
    {
        "name": "solver_feature_toggle",
        "summary": "启用 / 禁用求解器树特征",
        "args": "solution_tag*, feature_path*, enabled*, model_name",
        "keywords": [
            "solver", "求解器", "启用", "禁用", "开关", "特征"
        ],
    },
    {
        "name": "results_node_create",
        "summary": "建结果节点（Global / IntSurface / AveBoundary 数值节点，或 Surface / Export）",
        "args": "group*, node_type*, tag, properties, selection, model_name",
        "keywords": [
            "results", "结果", "节点", "新建", "数值", "积分", "平均", "导出", "绘图", "后处理节点"
        ],
    },
    {
        "name": "results_node_set",
        "summary": "改结果节点属性",
        "args": "group*, tag*, properties*, model_name",
        "keywords": [
            "results", "结果", "节点", "设置", "属性", "修改"
        ],
    },
    {
        "name": "results_node_delete",
        "summary": "删除结果节点",
        "args": "group*, tag*, model_name",
        "keywords": [
            "results", "结果", "节点", "删除", "移除"
        ],
    },
    {
        "name": "results_numerical_evaluate",
        "summary": "求值数值节点（需已有解）",
        "args": "numerical_tag*, unit, model_name",
        "keywords": [
            "results", "结果", "数值", "求值", "节点", "计算", "取值"
        ],
    },
    {
        "name": "remote_configure",
        "summary": "配置远程求解（SSH 别名 / 远程根目录 / comsolbatch / 传输方式）",
        "args": "ssh_alias, ssh_cmd, remote_root, comsolbatch, launch_method, transport",
        "keywords": [
            "remote", "远程", "配置", "ssh", "求解", "集群", "服务器", "传输", "设置", "远程机"
        ],
    },
    {
        "name": "remote_config_get",
        "summary": "读当前远程求解配置",
        "args": "",
        "keywords": [
            "remote", "远程", "配置", "读取", "查看", "当前设置"
        ],
    },
    {
        "name": "remote_probe",
        "summary": "探测远程求解机（SSH 连通性 / comsolbatch / CPU / 内存 / 磁盘）",
        "args": "",
        "keywords": [
            "remote", "远程", "探测", "probe", "连通", "检查", "服务器", "环境", "能不能用"
        ],
    },
    {
        "name": "remote_job_submit",
        "summary": "打包模型提交远程求解（可带参数覆盖与指标提取规格）",
        "args": "job_name*, mph_path, model_name, study, param_overrides, metrics, transport",
        "keywords": [
            "remote", "远程", "提交", "作业", "job", "求解", "打包", "指标", "metrics", "远端"
        ],
    },
    {
        "name": "remote_job_status",
        "summary": "查远程作业状态（注册表 + 远端标记 + 日志尾部）",
        "args": "job_id*",
        "keywords": [
            "remote", "远程", "作业", "状态", "status", "日志", "进度", "跑完没"
        ],
    },
    {
        "name": "remote_job_fetch",
        "summary": "拉回远程作业结果（job_solved.mph / 日志 / 状态标记）",
        "args": "job_id*, check_remote=true",
        "keywords": [
            "remote", "远程", "作业", "取回", "下载", "fetch", "结果", "拉回", "回收"
        ],
    },
    {
        "name": "remote_job_ingest",
        "summary": "手工传输：登记带回的作业 zip 或目录",
        "args": "source*",
        "keywords": [
            "remote", "远程", "作业", "登记", "导入", "ingest", "手工", "离线", "拷贝回来"
        ],
    },
    {
        "name": "remote_job_list",
        "summary": "列出本地作业注册表（可按状态 / 组过滤）",
        "args": "state, group",
        "keywords": [
            "remote", "远程", "作业", "列表", "list", "注册表", "状态", "有哪些作业"
        ],
    },
    {
        "name": "remote_job_delete",
        "summary": "从注册表移除作业（可选删除文件）",
        "args": "job_id*, remove_files=false",
        "keywords": [
            "remote", "远程", "作业", "删除", "移除", "清理", "归档"
        ],
    },
    {
        "name": "remote_watcher_package",
        "summary": "生成求解机侧 watcher 目录（轮询 inbox 自动跑作业）",
        "args": "dest",
        "keywords": [
            "remote", "远程", "watcher", "监听", "轮询", "inbox", "打包", "自动", "无人值守"
        ],
    },
    {
        "name": "remote_metrics_extract",
        "summary": "在已求解 .mph 上求值指标规格并写 metrics.json",
        "args": "job_id*",
        "keywords": [
            "remote", "远程", "指标", "metrics", "提取", "求值", "结果", "汇总", "曲线"
        ],
    },
    {
        "name": "repro_compare_curves",
        "summary": "仿真曲线 vs 参考曲线多角度比对（RMSE / R² / 峰值 / 特征点）并出报告",
        "args": "sim*, ref*, name=curve_cmp, sim_x_col=0, sim_y_col=1, ref_x_col=0, ref_y_col=1, peak_rel_tol=0.05, rmse_rel_tol=0.08, r2_min=0.98, feature_defs, feature_time_tol, out_dir",
        "keywords": [
            "repro", "复现", "对比", "曲线", "参考", "rmse", "r2", "峰值", "论文", "验证", "误差", "拟合"
        ],
    },
    {
        "name": "repro_compare_scalars",
        "summary": "标量结果 vs 论文值逐项比对（相对误差 / 通过判定）",
        "args": "items*, name=scalar_cmp, default_rel_tol=0.05, out_dir",
        "keywords": [
            "repro", "复现", "标量", "对比", "论文", "误差", "验证", "通过", "数值核对"
        ],
    },
    {
        "name": "repro_compare_job_metric",
        "summary": "远程作业某指标时间序列 vs 参考曲线比对",
        "args": "job_id*, metric_name*, ref*, ref_x_col=0, ref_y_col=1, peak_rel_tol=0.05, rmse_rel_tol=0.08, r2_min=0.98, feature_defs, feature_time_tol, out_dir",
        "keywords": [
            "repro", "复现", "作业", "指标", "时间序列", "对比", "曲线", "验证"
        ],
    },
    {
        "name": "verify_mesh_scaling_preview",
        "summary": "预览网格加密会缩放哪些尺寸设置（不改模型）",
        "args": "model_name, factor=0.5",
        "keywords": [
            "verify", "验证", "网格", "加密", "缩放", "预览", "尺寸", "无关性", "影响"
        ],
    },
    {
        "name": "verify_mesh_independence_setup",
        "summary": "建网格无关性研究组（每个加密因子一个远程作业）",
        "args": "factors, model_name, study, param_overrides, metrics, scale_param, transport",
        "keywords": [
            "verify", "验证", "网格无关性", "independence", "加密", "收敛", "研究", "网格敏感性"
        ],
    },
    {
        "name": "verify_mesh_independence_analyze",
        "summary": "分析网格无关性组：相邻加密级差值与判定",
        "args": "group*, tol=0.02",
        "keywords": [
            "verify", "验证", "网格无关性", "分析", "判定", "差值", "收敛", "是否无关"
        ],
    },
    {
        "name": "verify_self_sustain_setup",
        "summary": "建自保持性验证组（rerun 重复性 / sustain 尾部平台）",
        "args": "mode=rerun, runs=2, model_name, study, metrics, param_overrides, extend_tlist, transport",
        "keywords": [
            "verify", "验证", "自保持", "重复性", "rerun", "稳定性", "平台", "延续", "持续", "电弧"
        ],
    },
    {
        "name": "verify_self_sustain_analyze",
        "summary": "分析自保持性组：尾部漂移与重复性判定",
        "args": "group*, tail_frac=0.3, drift_tol=0.05, pairwise_tol=0.001",
        "keywords": [
            "verify", "验证", "自保持", "分析", "漂移", "重复", "判定", "稳定性"
        ],
    },
    {
        "name": "geometry_boundary_info",
        "summary": "边界号的空间上下文：包围盒、每条边界长度、相邻域（判断哪条边是哪个面，别猜编号）",
        "args": "geom_tag, component_tag, model_name",
        "keywords": [
            "boundary", "边界", "编号", "信息", "包围盒", "长度", "相邻域", "识别", "哪个面", "几何", "尺寸", "定位"
        ],
    },
    {
        "name": "results_interpolate",
        "summary": "在任意坐标点求表达式值（mphinterp 等价，探针/剖面采样，坐标为 SI 米）",
        "args": "expressions*, coords*, dataset, unit, inner, model_name",
        "keywords": [
            "interpolate", "插值", "探针", "probe", "坐标", "采样", "剖面", "取值", "任意位置", "mphinterp",
            "数据点"
        ],
    },
    # ------------------------------------------------------------------ #
    # extra_tools.py — the five model-operation groups the inherited 157
    # tools never exposed (named selections / variables / probes / export
    # nodes / plot groups). Appended last on purpose: they are implemented by
    # this plugin, not by the reused src/tools package.
    # ------------------------------------------------------------------ #
    {
        "name": "selection_create",
        "summary": "新建命名选择集（选择集 / 命名选择）：Explicit 显式实体、Box 框选、Ball、Cylinder、Union 并集、Intersection 交集、Difference 差集、Complement、Adjacent、Disk、LogicalExpression",
        "args": "tag*, selection_type=Explicit, geometry, entity_dim=3, entities, all_entities=false, properties, label, component_name=comp1, model_name",
        "keywords": [
            "selection", "选择", "选择集", "命名选择", "命名选择集", "选区", "框选", "显式选择", "域选择",
            "边界选择", "selection set", "named", "explicit", "box", "包围盒", "ball", "cylinder", "union",
            "intersection", "difference", "adjacent", "新建选择"
        ],
    },
    {
        "name": "selection_list",
        "summary": "列出所有命名选择集（tag / 类型 / 维度 / 实体数），可选带实体编号",
        "args": "component_name=comp1, include_entities=false, max_entities=200, model_name",
        "keywords": [
            "选择集", "命名选择", "选择", "列表", "列出", "查看选择", "selection", "list", "named", "选区",
            "有几个选择", "全部选择"
        ],
    },
    {
        "name": "selection_info",
        "summary": "读取单个命名选择集详情：类型、维度、几何、实体编号、可设属性",
        "args": "tag*, component_name=comp1, model_name",
        "keywords": [
            "选择集", "命名选择", "选择", "详情", "信息", "实体编号", "entities", "selection", "info", "读取选择",
            "选区"
        ],
    },
    {
        "name": "selection_set_entities",
        "summary": "修改已有命名选择集的实体：set 覆盖 / add 追加 / remove 移除 / clear 清空",
        "args": "tag*, entities, all_entities=false, mode=set, component_name=comp1, model_name",
        "keywords": [
            "选择集", "命名选择", "修改选择", "实体编号", "entities", "添加", "移除", "清空", "selection",
            "set", "add", "remove", "clear", "选区"
        ],
    },
    {
        "name": "selection_delete",
        "summary": "删除一个命名选择集",
        "args": "tag*, component_name=comp1, model_name",
        "keywords": [
            "选择集", "命名选择", "删除选择", "删除", "delete", "remove", "selection", "移除选择", "选区"
        ],
    },
    {
        "name": "variable_create",
        "summary": "新建组件变量（变量 / 表达式定义）——comp.variable().create(tag)，可绑定命名选择集",
        "args": "tag*, expr, unit, descr, selection, label, component_name=comp1, model_name",
        "keywords": [
            "变量", "组件变量", "定义变量", "变量定义", "表达式", "自定义变量", "新建变量", "variable",
            "expression", "expr", "定义", "component variable"
        ],
    },
    {
        "name": "variable_list",
        "summary": "列出组件变量（tag / 表达式 / 单位 / 描述）",
        "args": "component_name=comp1, model_name",
        "keywords": [
            "变量", "组件变量", "查看变量", "列出变量", "列表", "variable", "list", "表达式", "有哪些变量"
        ],
    },
    {
        "name": "variable_set",
        "summary": "修改已有组件变量的表达式 / 单位 / 描述 / 绑定选择集",
        "args": "tag*, expr, unit, descr, selection, label, component_name=comp1, model_name",
        "keywords": [
            "变量", "修改变量", "设置变量", "更新变量", "表达式", "variable", "set", "expression", "改表达式"
        ],
    },
    {
        "name": "variable_delete",
        "summary": "删除一个组件变量",
        "args": "tag*, component_name=comp1, model_name",
        "keywords": [
            "变量", "删除变量", "移除变量", "variable", "delete", "remove"
        ],
    },
    {
        "name": "probe_create",
        "summary": "新建探针（探针 / 监测点）：DomainPoint / BoundaryPoint / Domain / Boundary / Edge / Point / GlobalVariable，点探针坐标用 coords 矩阵",
        "args": "tag*, probe_type=DomainPoint, expr, coords, selection, probename, descr, properties, model_name",
        "keywords": [
            "探针", "探针点", "监测点", "测点", "监测", "全局探针", "点探针", "probe", "point probe",
            "globalvariable", "domainpoint", "boundarypoint", "coords", "新建探针", "监控点"
        ],
    },
    {
        "name": "probe_list",
        "summary": "列出模型中的所有探针（tag / 类型 / 表达式 / 坐标 / 探针变量名）",
        "args": "model_name",
        "keywords": [
            "探针", "监测点", "查看探针", "列出探针", "列表", "probe", "list", "有哪些探针"
        ],
    },
    {
        "name": "probe_evaluate",
        "summary": "求探针值（probe.genResult 生成结果特征后读 numerical.getReal；无解时返回空数组）",
        "args": "tag, sol, model_name",
        "keywords": [
            "探针", "探针值", "监测值", "求值", "读取探针", "评估", "probe", "evaluate", "getreal",
            "numerical", "监测结果", "probe value"
        ],
    },
    {
        "name": "probe_delete",
        "summary": "删除一个探针",
        "args": "tag*, model_name",
        "keywords": [
            "探针", "删除探针", "监测点", "probe", "delete", "remove"
        ],
    },
    {
        "name": "export_create",
        "summary": "新建结果导出节点：Data / Image / Animation 动画 / Table 表格 / Mesh / Plot，可绑定绘图组",
        "args": "tag*, export_type=Data, plotgroup, filename, expr, properties, model_name",
        "keywords": [
            "导出", "导出节点", "结果导出", "新建导出", "输出文件", "保存结果", "export", "data", "image",
            "animation", "动画", "table", "表格", "mesh", "plotgroup", "写文件"
        ],
    },
    {
        "name": "export_list",
        "summary": "列出所有结果导出节点（tag / 类型 / 文件名）",
        "args": "model_name",
        "keywords": [
            "导出", "导出节点", "查看导出", "列出导出", "列表", "export", "list", "有哪些导出"
        ],
    },
    {
        "name": "export_set",
        "summary": "修改已有导出节点的属性 / 文件名 / 表达式",
        "args": "tag*, properties, filename, expr, model_name",
        "keywords": [
            "导出", "设置导出", "修改导出", "导出属性", "文件名", "export", "set", "filename", "imagetype"
        ],
    },
    {
        "name": "export_run",
        "summary": "执行导出节点写文件（tag 留空则运行全部导出节点）",
        "args": "tag, model_name",
        "keywords": [
            "导出", "执行导出", "运行导出", "写文件", "输出", "保存", "export", "run", "导出结果"
        ],
    },
    {
        "name": "export_delete",
        "summary": "删除一个导出节点",
        "args": "tag*, model_name",
        "keywords": [
            "导出", "删除导出", "导出节点", "export", "delete", "remove"
        ],
    },
    {
        "name": "plot_create",
        "summary": "新建绘图组（绘图 / 云图）：PlotGroup3D / PlotGroup2D / PlotGroup1D，可一次挂 Surface 等绘图特征",
        "args": "tag*, plot_group_type=PlotGroup3D, features, title, properties, model_name",
        "keywords": [
            "绘图", "绘图组", "云图", "出图", "可视化", "新建绘图", "plot", "plotgroup", "surface",
            "曲线", "彩色图", "画图", "场图"
        ],
    },
    {
        "name": "plot_set",
        "summary": "修改绘图组或其中某个绘图特征（给特征设表达式 / 属性，特征不存在可按类型创建）",
        "args": "tag*, properties, title, feature_tag, feature_type, expr, model_name",
        "keywords": [
            "绘图", "绘图组", "设置绘图", "修改绘图", "云图", "表达式", "plot", "set", "surface", "画什么"
        ],
    },
    {
        "name": "plot_delete",
        "summary": "删除一个绘图组（连同其绘图特征）",
        "args": "tag*, model_name",
        "keywords": [
            "绘图", "绘图组", "删除绘图", "云图", "plot", "delete", "remove"
        ],
    },
    {
        "name": "plot_export",
        "summary": "把绘图组导出成图片（云图 / 曲线出图）：临时建 Image 导出节点并 run",
        "args": "tag*, filename*, image_type=png, width=800, height=600, properties, keep_export=false, model_name",
        "keywords": [
            "绘图", "出图", "导出图片", "云图", "截图", "保存图片", "图片", "plot", "export", "image",
            "png", "jpeg", "画图导出"
        ],
    },
    {
        "name": "comsol_start_gui",
        "summary": "启动带 GUI 桥接的会话：多客户端 mphserver + 自动连上 COMSOL Desktop，你在窗口里看到的就是 MCP 正在改的模型",
        "args": "cores=4, port=2036, open_desktop=true",
        "keywords": ["gui", "desktop", "界面", "窗口", "可视化", "图形界面", "桥接", "bridge",
                     "start_gui", "看模型", "同步", "multi", "多客户端", "打开界面", "live", "实时"],
    },
    {
        "name": "comsol_gui_status",
        "summary": "查询 GUI 桥接状态：mphserver 是否在跑、端口、Desktop 窗口数量",
        "args": "",
        "keywords": ["gui", "status", "界面状态", "窗口", "desktop", "桥接状态", "gui_status"],
    },
    {
        "name": "comsol_gui_close",
        "summary": "关闭 GUI 桥接：关掉 Desktop 窗口，可选同时停掉 mphserver",
        "args": "close_desktop=true, stop_server=false",
        "keywords": ["gui", "close", "关闭界面", "关窗口", "退出界面", "desktop", "gui_close",
                     "停止桥接", "关闭桌面"],
    },
]

# Bilingual intent -> tool names. Users type intents, not API names.
ALIASES = {
    "启动": ["comsol_start"],
    "开始": ["comsol_start", "study_solve"],
    "连接": ["comsol_connect", "comsol_status"],
    "断开": ["comsol_disconnect"],
    "状态": ["comsol_status", "remote_job_status", "physicsbuilder_status"],
    "会话": ["comsol_status", "comsol_start", "comsol_connect"],
    "加载": ["model_load"],
    "打开模型": ["model_load"],
    "新建模型": ["model_create"],
    "保存": ["model_save", "model_save_version", "results_export_data"],
    "备份": ["model_save_version", "model_clone"],
    "克隆": ["model_clone"],
    "复制模型": ["model_clone"],
    "切换": ["model_set_current"],
    "模型": ["model_inspect", "model_list", "model_create"],
    "检查模型": ["model_inspect", "model_audit"],
    "参数": ["param_list", "param_set", "param_get"],
    "扫描": ["param_sweep_setup", "verify_mesh_independence_setup"],
    "参数化": ["param_sweep_setup"],
    "几何": ["geometry_list", "geometry_add_feature", "geometry_build", "geometry_create"],
    "建模": ["geometry_add_feature", "geometry_add_block", "model_create"],
    "长方体": ["geometry_add_block"],
    "方块": ["geometry_add_block"],
    "立方体": ["geometry_add_block"],
    "圆柱": ["geometry_add_cylinder"],
    "矩形": ["geometry_add_rectangle"],
    "并集": ["geometry_boolean_union"],
    "合并": ["geometry_boolean_union"],
    "差集": ["geometry_boolean_difference"],
    "打孔": ["geometry_boolean_difference"],
    "导入": ["geometry_import"],
    "step文件": ["geometry_import"],
    "iges": ["geometry_import"],
    "构建": ["geometry_build"],
    "布尔": ["geometry_boolean_union", "geometry_boolean_difference"],
    "倒角": ["geometry_set_feature_selection"],
    "圆角": ["geometry_set_feature_selection"],
    "选择": [
        "selection_create",
        "selection_list",
        "selection_set_entities",
        "geometry_create_box_selection",
        "physics_set_feature_selection",
        "physics_set_interface_selection",
    ],
    "命名选择": [
        "selection_create",
        "selection_list",
        "selection_info",
        "selection_set_entities",
        "selection_delete",
        "geometry_create_box_selection",
    ],
    "选择集": [
        "selection_create",
        "selection_list",
        "selection_info",
        "selection_set_entities",
        "selection_delete",
    ],
    "框选": ["selection_create", "geometry_create_box_selection"],
    "边界号": ["geometry_get_boundaries"],
    "物理场": ["physics_list", "physics_add", "physics_get_available"],
    "加物理场": ["physics_add"],
    "电场": ["physics_add_electrostatics", "physics_add"],
    "静电场": ["physics_add_electrostatics"],
    "电势": ["physics_add_electrostatics"],
    "电压": ["physics_configure_boundary", "physics_add_electrostatics"],
    "温度": [
        "physics_add_heat_transfer",
        "physics_setup_heat_boundaries",
        "physics_configure_boundary",
    ],
    "传热": ["physics_add_heat_transfer", "physics_setup_heat_boundaries"],
    "散热": ["physics_setup_heat_boundaries"],
    "流体": ["physics_add_laminar_flow"],
    "流动": ["physics_add_laminar_flow", "physics_setup_flow_boundaries"],
    "层流": ["physics_add_laminar_flow", "physics_setup_flow_boundaries"],
    "流速": ["physics_setup_flow_boundaries"],
    "声学": ["physics_add_pressure_acoustics", "physics_add_acoustics"],
    "声压": ["physics_add_pressure_acoustics"],
    "结构": ["physics_add_solid_mechanics"],
    "应力": ["physics_add_solid_mechanics"],
    "固体力学": ["physics_add_solid_mechanics"],
    "边界": [
        "physics_configure_boundary",
        "physics_boundary_selection",
        "geometry_get_boundaries",
    ],
    "边界条件": ["physics_configure_boundary", "physics_boundary_selection"],
    "入口": ["physics_setup_flow_boundaries"],
    "出口": ["physics_setup_flow_boundaries"],
    "接地": ["physics_configure_boundary"],
    "绝热": ["physics_configure_boundary"],
    "对流": ["physics_setup_heat_boundaries"],
    "热流": ["physics_setup_heat_boundaries"],
    "pde": [
        "physics_add_coefficient_form_pde",
        "physics_add_general_form_pde",
        "physics_add_weak_form_pde",
    ],
    "弱形式": ["physics_add_weak_form_pde"],
    "自定义方程": ["physics_add_coefficient_form_pde", "physics_add_general_form_pde"],
    "耦合": ["multiphysics_add", "multiphysics_set"],
    "多物理场": ["multiphysics_add", "multiphysics_set", "multiphysics_delete"],
    "焦耳热": ["multiphysics_add"],
    "热应力": ["multiphysics_add"],
    "热电": ["multiphysics_add"],
    "材料": ["material_create", "material_set", "physics_set_material"],
    "赋材料": ["physics_set_material"],
    "物性": ["material_create", "material_set"],
    "特征": ["physics_list_features", "physics_feature_info", "physics_feature_set"],
    "启用": ["physics_feature_toggle", "solver_feature_toggle"],
    "禁用": ["physics_feature_toggle", "solver_feature_toggle"],
    "电池": ["electrochemistry_add_interface", "electrochemistry_set_interface_properties"],
    "电化学": ["electrochemistry_get_interfaces", "electrochemistry_add_interface"],
    "锂电池": ["electrochemistry_add_interface"],
    "电极": ["electrochemistry_add_feature"],
    "燃料电池": ["electrochemistry_add_interface"],
    "腐蚀": ["electrochemistry_add_interface"],
    "离线": ["static_catalog_search", "static_catalog_info"],
    "目录": ["static_catalog_info", "static_catalog_search"],
    "变量": [
        "variable_create",
        "variable_list",
        "variable_set",
        "variable_delete",
        "static_catalog_variables",
        "param_list",
    ],
    "表达式": ["variable_create", "variable_set", "variable_list"],
    "探针": [
        "probe_create",
        "probe_list",
        "probe_evaluate",
        "probe_delete",
        "results_interpolate",
    ],
    "监测点": ["probe_create", "probe_list", "probe_evaluate"],
    "离散化": ["static_catalog_discretization"],
    "自定义物理场": ["physicsbuilder_generate", "physicsbuilder_register"],
    "插件物理场": ["physicsbuilder_generate"],
    "网格": ["mesh_create", "mesh_list", "mesh_info", "mesh_create_sequence"],
    "划分": ["mesh_create"],
    "剖分": ["mesh_create"],
    "加密": ["mesh_create", "verify_mesh_scaling_preview"],
    "单元": ["mesh_info", "mesh_create"],
    "研究": ["study_list", "study_create"],
    "求解": ["study_solve", "study_solve_async"],
    "计算": ["study_solve", "results_global_evaluate"],
    "算一下": ["study_solve"],
    "异步": ["study_solve_async"],
    "后台": ["study_solve_async", "remote_job_submit"],
    "进度": ["study_get_progress"],
    "取消": ["study_cancel"],
    "等待": ["study_wait"],
    "稳态": ["study_create"],
    "瞬态": ["study_create"],
    "时变": ["study_create"],
    "频域": ["study_create"],
    "模态": ["study_create"],
    "特征频率": ["study_create"],
    "求解器": ["solver_feature_list", "solver_feature_set", "solver_feature_toggle"],
    "时间步": ["solver_feature_set", "results_inner_values"],
    "容差": ["solver_feature_set"],
    "结果": ["results_evaluate", "results_plots_list", "datasets_list"],
    "后处理": ["results_evaluate", "results_global_evaluate", "results_node_create"],
    "求值": ["results_evaluate", "results_global_evaluate", "results_numerical_evaluate"],
    "积分": ["results_global_evaluate", "results_node_create"],
    "最大值": ["results_global_evaluate"],
    "数据集": ["datasets_list"],
    "绘图": [
        "plot_create",
        "plot_set",
        "plot_export",
        "plot_delete",
        "results_plots_list",
        "results_node_create",
    ],
    "云图": ["plot_create", "plot_export", "results_plots_list", "results_export_image"],
    "出图": ["plot_export", "plot_create", "results_export_image", "results_plots_list"],
    "截图": ["results_export_image"],
    "图片": ["results_export_image"],
    "导出": [
        "export_create",
        "export_list",
        "export_set",
        "export_run",
        "export_delete",
        "results_export_data",
        "results_export_image",
        "model_export_java",
    ],
    "动画": ["export_create", "export_run"],
    "csv": ["results_export_data"],
    "png": ["results_export_image"],
    "审计": ["model_audit", "audit_model_config", "audit_paper_checklist"],
    "体检": ["model_audit", "audit_model_config"],
    "配置": ["audit_model_config", "remote_configure"],
    "对比": ["model_diff", "audit_models_diff", "repro_compare_curves"],
    "差异": ["model_diff", "audit_models_diff"],
    "论文": ["audit_paper_checklist", "repro_compare_scalars"],
    "复现": ["repro_compare_curves", "repro_compare_scalars", "audit_paper_checklist"],
    "java": ["model_export_java"],
    "函数": ["function_create", "function_set"],
    "插值": ["function_create", "results_interpolate"],
    "ocv": ["function_create"],
    "组件": ["model_create_component", "model_list_components", "component_delete"],
    "远程": ["remote_configure", "remote_job_submit", "remote_probe"],
    "ssh": ["remote_configure", "remote_probe"],
    "集群": ["remote_configure", "remote_job_submit"],
    "服务器": ["remote_configure", "remote_probe", "comsol_connect"],
    "作业": ["remote_job_submit", "remote_job_status", "remote_job_list"],
    "提交": ["remote_job_submit", "study_solve"],
    "取回": ["remote_job_fetch"],
    "下载": ["remote_job_fetch"],
    "指标": ["remote_metrics_extract", "repro_compare_job_metric"],
    "验证": [
        "verify_mesh_independence_setup",
        "verify_self_sustain_setup",
        "repro_compare_scalars",
    ],
    "网格无关性": ["verify_mesh_independence_setup", "verify_mesh_independence_analyze"],
    "无关性": ["verify_mesh_independence_setup"],
    "收敛": ["verify_mesh_independence_analyze", "solver_feature_set"],
    "自保持": ["verify_self_sustain_setup", "verify_self_sustain_analyze"],
    "稳定性": ["verify_self_sustain_analyze"],
    "重复性": ["verify_self_sustain_setup", "verify_self_sustain_analyze"],
    "曲线": ["repro_compare_curves", "results_plots_list"],
    "误差": ["repro_compare_curves", "repro_compare_scalars"],
    "标量": ["repro_compare_scalars"],
    "球体": ["geometry_add_sphere"],
    "圆形": ["geometry_add_circle"],
    "网格划分": ["mesh_create"],
    "物理场接口": ["physics_add", "physics_list"],
    "远程作业": ["remote_job_submit", "remote_job_status"],
    "参数扫描": ["param_sweep_setup"],
    "探针": ["results_interpolate"],
    "边界信息": ["geometry_boundary_info"],
}


_CJK_SPLIT = " ,，。；;:：/|()（）[]【】\t\n"


def _tokens(text):
    """Split a query: ASCII runs stay words, CJK splits into single chars.

    Chinese has no spaces, so 温度 -> ["温", "度"]; that is what lets a two
    character query match a keyword like 温度 or 温升 without a segmenter.
    """
    text = (text or "").lower()
    out = []
    buf = ""
    for ch in text:
        if ch in _CJK_SPLIT:
            if buf:
                out.append(buf)
                buf = ""
        elif "\u4e00" <= ch <= "\u9fff":
            if buf:
                out.append(buf)
                buf = ""
            out.append(ch)
        else:
            buf += ch
    if buf:
        out.append(buf)
    return [t for t in out if t]


def search_scored(query, top_k=25):
    """[(score, tool)] best first. The scoring itself is the reference one:
    name substring +8, keyword hit +6, keyword/token overlap +2, summary
    +3/+1, intent alias +7; ties break by catalogue order (stable).
    """
    q = (query or "").strip().lower()
    qtok = [t for t in _tokens(q) if len(t) > 1]
    scored = []
    for idx, tool in enumerate(TOOLS):
        score = 0.0
        name = tool["name"].lower()
        if q and q in name:
            score += 8
        for kw in tool["keywords"]:
            kwl = kw.lower()
            if q and (q == kwl or q in kwl or kwl in q):
                score += 6
            for t in qtok:
                if t in kwl or kwl in t:
                    score += 2
        if q and q in tool["summary"].lower():
            score += 3
        for t in qtok:
            if t in tool["summary"].lower():
                score += 1
        for alias, names in ALIASES.items():
            if alias in q and tool["name"] in names:
                score += 7
        if score:
            scored.append((score, -idx, tool))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [(row[0], row[2]) for row in scored[:top_k]]


def search(query, top_k=6):
    """Rank the catalogue by intent (see search_scored for the weights).

    Falls back to the first `top_k` entries when nothing matches at all.
    """
    picked = [tool for _, tool in search_scored(query, top_k=top_k)]
    if not picked:
        picked = TOOLS[:top_k]
    return picked


def close_matches(query, top_k=4):
    """Suggestions for a mistyped tool name.

    Name similarity first (difflib), because a typo is usually a mangled name:
    geometry_blok -> geometry_add_block, result_export_imag ->
    results_export_image. The semantic search is merged in second, which also
    covers the case where someone passes a Chinese intent to call_tool.
    """
    q = (query or "").strip()
    picked = []
    seen = set()
    if q:
        for name in difflib.get_close_matches(q.lower(), names(), n=top_k,
                                              cutoff=0.55):
            tool = by_name(name)
            if tool is not None and name not in seen:
                seen.add(name)
                picked.append(tool)
    # One name hit is often not enough (heattransfer -> only one tool), so top
    # up from the semantic search; two or more name hits already describe the
    # typo and semantic matches would only add noise.
    if len(picked) < 2:
        scored = search_scored(q, top_k=25)
        if scored:
            best = scored[0][0]
            for score, tool in scored:
                if len(picked) >= top_k:
                    break
                if score >= best * 0.75 and tool["name"] not in seen:
                    seen.add(tool["name"])
                    picked.append(tool)
    if not picked:
        picked = TOOLS[:top_k]
    return picked[:top_k]


def describe(tool):
    line = "%s — %s" % (tool["name"], tool["summary"])
    if tool["args"]:
        line += "\n  args: " + tool["args"]
    return line


def by_name(name):
    for tool in TOOLS:
        if tool["name"] == name:
            return tool
    return None


def names():
    return [t["name"] for t in TOOLS]


def groups():
    """Rough grouping by name prefix (session/model/geometry/...)."""
    out = {}
    for tool in TOOLS:
        prefix = tool["name"].split("_")[0]
        out.setdefault(prefix, []).append(tool["name"])
    return out
