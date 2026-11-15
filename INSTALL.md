# dsh-comsol 安装与切换指南

> ⚠️ **本插件尚未装入你正在用的 profile。** 因为现在会话里已经有一个 `comsol` MCP 在跑，
> 直接装会重名冲突，可能打断当前会话。下面给的是「随时可执行」的切换步骤。

---

## 现状：你机器上有两个 comsol MCP 候选

| | 现有 `mcp-comsol` | 新的 `dsh-comsol` |
|---|---|---|
| 注册位置 | `C:\Users\86180\.dsh\cordis.patch.yml` 第 14 行 | 待安装（bundle） |
| 形态 | 裸 `@deepseek-ai/dsh-mcp-client` 一行 | 完整 DSH bundle（含 skill、doctor、配置） |
| 暴露工具 | **155 个全部直接暴露** | **2 个入口**（search_tools / call_tool） |
| 空闲上下文开销 | 全部 schema（几千 token） | 约几百 token |
| 工具总数 | 155 | **179**（157 + 22 新增） |
| 版本探测 | 无 | `doctor` / `where` / `check-python` |
| 技能 | 无 | 自动装到 `~/.dsh/skills/comsol` |

两者的 `serverName` 都是 `comsol` —— **不能同时启用**。

---

## 切换步骤（3 步，约 2 分钟）

### 1. 禁用旧的 mcp-comsol

编辑 `C:\Users\86180\.dsh\cordis.patch.yml`，找到第 14 行附近：

```yaml
    - id: mcp-comsol
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: comsol
        ...
```

在 `- id: mcp-comsol` 这一行下面加一行：

```yaml
      disabled: true
```

（或者整段注释掉。想回退就把这行删掉。）

### 2. 安装 dsh-comsol

在 DSH 里执行（或让我执行）：

```
plugin_manager action=install_bundle target=link:E:\ICE\_tools\dsh-comsol
```

装完**必须重启 DSH**（bundle 的 cordis 补丁只在启动时加载）。

### 3. 验证

```bash
cd E:\ICE\_tools\dsh-comsol
node bin/dsh-comsol.mjs doctor     # 应全部 green
```

重启后新会话里应该**只剩 2 个 comsol 工具**（`search_tools` / `call_tool`），
而不是原来的 155 个。试着说「用 comsol 搜一下网格相关的工具」。

---

## 回退

1. 把 `~/.dsh/cordis.patch.yml` 里 `disabled: true` 删掉
2. `plugin_manager action=remove_bundle target=dsh-comsol`
3. 重启 DSH

原有的 `mcp-comsol` 配置一行没动，回退后立刻恢复原状。

---

## 为什么值得换

现在这个会话里，我每次调用 COMSOL 工具时，模型上下文里都挂着 155 个工具的完整 schema；
而 `physics_list_features` 这种工具**单次返回就上万 token**（第 2 轮我就被撑爆过）。

换成 dsh-comsol 后：
- 工具定义从「155 个 schema」降到「2 个入口」
- 需要哪个工具，`search_tools` 按中英文意图检索出来（157+22 条目录，~1390 个双语关键词）
- 工具本身还多了 22 个（选择集 / 变量 / 探针 / 导出 / 绘图），这些原来根本没有

---

## 已知限制（不藏）

1. **优化工具没做**：COMSOL 6.4 的优化接口是 `model.opt().objective()/constr()/gconstr()`，
   每个有意义的验证都要跑求解，无法在不求解的前提下验证。入口点已写在 `extra_tools.py` 末尾。
2. **静态目录 5 个文件来自 6.3**：`physics_variables` / `discretization_index` / `coupling_wiring` /
   `expression_functions` / `mesh_map` 由一个不在两个仓库里的反编译提取器生成，已从 6.3 沿用，
   `meta.json` 里逐文件记录了来源。其余全部是 6.4.0.429。
3. **`serverName` 固定为 `comsol`**：所以必须先禁用旧的（见步骤 1）。
