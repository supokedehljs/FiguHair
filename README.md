# FiguHair - Blender 插件

一个 Blender 插件，用于从曲线创建管道（管状网格），支持**逐点自定义横截面形状**。每个曲线控制点的横截面都可以通过拖动顶点来自由编辑形状，非常适合制作头发、触须、藤蔓等造型。

## 核心功能

- 每个曲线控制点拥有独立的横截面形状
- 横截面由多个顶点组成，每个顶点的 X/Y 位置可单独调整
- 相邻控制点之间的横截面自动平滑插值过渡
- NURBS / Path 曲线会按 NURBS/B-spline 参数曲线采样生成管线，横截面沿评估后的曲线分布，不强制落在控制点位置
- Poly 曲线保持折线生成，适合需要硬边路径的情况
- 支持添加/删除横截面顶点，自由塑造任意截面形状
- 内置圆形重置、线性渐细预设
- 将某个点的横截面复制到所有点
- 自动更新：编辑参数后管道实时重新生成
- 横截面编辑器支持 G/R/S（移动/旋转/缩放）、比例编辑、纵向联动、中键插入、右键框选

## 安装方法

1. 将 `hair_curve_pipe` 文件夹复制到 Blender 插件目录：
   - Windows: `%APPDATA%\Blender Foundation\Blender\<version>\scripts\addons\`
   - macOS: `~/Library/Application Support/Blender/<version>/scripts/addons/`
   - Linux: `~/.config/blender/<version>/scripts/addons/`
2. 打开 Blender → `Edit > Preferences > Add-ons`
3. 搜索 "FiguHair"，勾选启用

## 使用方法

### 基本流程

1. 创建一条曲线（Bezier / Poly / NURBS）
2. 选中曲线，在 3D 视图右侧边栏找到 **FiguHair** 标签
3. 点击 **Sync Point Settings** 同步控制点
4. 在 **Curve Points** 子面板选择要编辑的控制点
5. 按 `C` 进入横截面编辑器，拖动顶点调整形状（`G` 移动 / `R` 旋转 / `S` 缩放 / 滚轮切换控制点）
6. 退出编辑器后管线自动更新，无需手动 Generate

### Cross-Section Editor 说明

选中某个曲线控制点后按 `C` 进入编辑器：
- 横截面是一个由多个顶点围成的闭合轮廓（默认是圆形）
- 拖动顶点或框选多点后 `G/R/S` 变换
- **中键**：在边上插入新顶点
- **右键拖拽**：框选顶点；`Shift` 追加选择
- **Ctrl+滚轮**：切换控制点
- **X / Delete**：删除选中顶点（最少保留 3 个）
- **面板内按钮**：添加/删除顶点、幽灵点切换、平滑预览、翻转

## 兼容性

- Blender 4.0+（`bl_info.blender = (4,0,0)`，实测 5.1 可用）
- 支持 Bezier、Poly、NURBS 曲线
- 支持环形（Cyclic）曲线

## 文件结构（2026-09-05 实测，全量 33 py / 约 530 KB）

```
hair_curve_pipe/
├── __init__.py          # 插件入口（61 行）
├── preferences.py       # 偏好设置（169 行）
├── properties.py        # 属性（351 行）
├── panel.py             # 右栏 UI（194 行）
├── handler.py           # 自动更新与选择重定向（290 行）
├── operators.py         # ★ 兼容转发层（2075 行 / 84 KB，原 4921 行 / 193 KB，-57%）
│                        #   顶层仅保留转发与 198 个 def 的 alias，无大段算法
├── cross_section.py     # 横截面拓扑（92 行）
├── curve_data.py        # 曲线读取与选择（83 行）
├── hair_lifecycle.py    # 头发对象族管理（149 行）
├── math_utils.py        # 数学工具（73 行）
├── interp.py            # 插值（56 行）
├── sampling.py          # 采样（227 行）
├── transition.py        # 过渡点（236 行）
├── frames.py            # 帧/环构建（184 行）
├── ghost.py             # 幽灵点（69 行）
├── selection.py         # 选择重定向（121 行）
├── edit_utils.py        # 编辑工具（104 行）
├── pipe_generation.py   # 管线生成核心（219 行）
├── point_data.py        # 逐点数据同步（227 行）
├── mesh_utils.py        # 网格工具（52 行，sanitize/rebuild/shade/flatten/resample）
├── tail_utils.py        # 末端连接（~280 行，已停用功能仅保留委托）
├── hair_ops.py          # 头发对象族（~410 行：hide/show/local_view/delete/duplicate/merge）
├── cross_section_ops.py # 横截面 Operator（378 行：toggle/reset/taper/add/remove/select/copy/paste）
├── pipe_ops.py          # 管线/转换（996 行：tube 环提取 + mesh_to_curve + generate_pipe）
├── edit_ops.py          # 编辑（291 行：edge_flow/reverse/equalize + _reverse_*）
├── view_ops.py          # 视图/尾部（341 行：selectability/redirect/solo + 5 个 tail 遗留）
├── interactive_ops.py   # 交互（411 行：cross_section_spread/draw_hair_curve）
├── widget_cache.py      # 管线网格缓存（55 行）
├── widget_geometry.py   # 几何/对齐/顶点操作（733 行）
├── widget_state.py      # 状态/PropertyGroup/undo（1156 行）
├── widget_draw.py       # 绘制回调（1107 行）
├── widget_interact.py   # 交互 modal（1305 行）
└── widget_operator.py   # 兼容垫片（8 行）
```

> 统计：`ls *.py | % { $l=(Get-Content $_.Name).Count; "$($_.Name) $l 行 $($_.Length/1KB) KB" }`
> 本轮后 `operators.py 2075 行` 较峰值 `4921 行` **减少 2846 行（58%）**，剩余仅为转发层。全量 `py_compile OK`（33 文件）已验证。

## 模块化重构进度

### 已完成

- [x] **第一阶段：基础迁移** — `curve_data / hair_lifecycle` 独立。
- [x] **第二阶段：生命周期切换** — `hair_lifecycle` 全面接管。
- [x] **第三阶段：管线与 Widget 拆分（2026-09-04 — 2026-09-05 上午）**
  - `cross_section / math_utils / ghost / interp / sampling / transition / frames / selection / edit_utils` 独立；
  - `pipe_generation.generate_pipe_mesh` / `point_data.sync_point_settings` 独立；
  - `widget_operator` 按定义顺序拆为 5 模块，修复 4 个 `NameError / already registered` 回归；`__pycache__` 清理与 `_force_unregister_stale`。

- [x] **第四阶段：巨石持续瘦身（2026-09-05 下午）**
  - 清理 389 行 `return alias` 后死代码；
  - `mesh_utils.py`（6 函数）与 `tail_utils.py`（16 函数）抽离，`operators.py 4921→4113`；
  - `hair_ops.py`（6 个头发族 Operator + 4 helpers）抽离，`4113→3635`；
  - `cross_section_ops.py`（10 个横截面 Operator）抽离，`3635→3287`；
  - `pipe_ops.py`（管状网格环提取 + `mesh_to_hair_curve / generate_pipe / sync_points`）抽离，`3287→2996`；
  - `edit_ops / view_ops / interactive_ops`（剩余 15 个 Operator）抽离，`2996→2075`；
  - 每步均保留 `bl_idname` 与旧 `.blend` 兼容，`operators.py` 改为 `from .hair_ops import ... as alias` / `HAIRPIPE_OT_* = alias` 转发，`py_compile` 33 文件全绿。

### 当前巨石

- `operators.py` **2075 行 / 84 KB**，仍占约 16%，但已无大段算法，仅为：
  - 顶层 `math / interp / sampling / transition / frames` 等 198 个小 `def foo: return alias(...)` 转发；
  - 尾部 `classes` 元组与 `register_keymaps`；
  - 22 个 `tail/mesh` 的 `*args` 委托与 6 个 `hair_ops` 别名。
- 其余模块均 < 60 KB，无第二巨石。

### 下一步（第五阶段收尾）

- 将剩余 198 个 `def alias` 按源模块合并为 `from .sampling import ...` / `from .transition import ...` 直接重导出，删除 `operators.py` 中的转发函数，使其仅保留 `classes + register`（目标 < 250 行）；
- 可选：新建 `operators/` 包汇总 `hair_ops / cross_section_ops / pipe_ops / edit_ops / view_ops / interactive_ops` 的 `register`，`operators.py` 最终仅 `from .operators import register`。

### 固定流程

1. 只迁移一个小功能组；2. 保留旧接口兼容层；3. `py_compile + ReadLints`；4. Blender 实测；5. 有问题先修复；6. 稳定后再下一轮；7. 最后删除旧兼容代码。

### 完成标准

- `operators.py < 250 行，仅注册`；handler 不再依赖 Operator 核心；对象生命周期唯一；管线生成与对象写入分离；`bl_idname` 兼容；合并/复制/删除/隐藏/框选重定向均通过。
