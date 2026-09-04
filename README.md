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

## 文件结构（2026-09-05 实测）

```
hair_curve_pipe/
├── __init__.py          # 插件入口（61 行，带 _force_unregister_stale 容错）
├── preferences.py       # 偏好设置与快捷键（169 行）
├── properties.py        # 属性（351 行）
├── panel.py             # 右栏 UI（194 行）
├── handler.py           # 自动更新与选择重定向（290 行）
├── operators.py         # ★ 巨石剩余（4921 行 / 193 KB，待继续拆分）
├── cross_section.py     # 横截面拓扑（92 行）
├── curve_data.py        # 曲线读取与选择（83 行）
├── hair_lifecycle.py    # 头发对象族管理（149 行）
├── math_utils.py        # 数学工具（73 行）
├── interp.py            # 插值（56 行）
├── sampling.py          # 采样（227 行）
├── transition.py        # 过渡点（236 行）
├── frames.py            # 帧/环构建（184 行）
├── ghost.py             # 幽灵点（69 行）
├── selection.py         # 选择重定向（121 行，含框选重定向修复）
├── edit_utils.py        # 编辑工具（104 行）
├── pipe_generation.py   # 管线生成核心（219 行，已独立）
├── point_data.py        # 逐点数据同步（227 行，已独立）
├── widget_cache.py      # 管线网格缓存（55 行）
├── widget_geometry.py   # 几何/对齐/顶点操作（733 行）
├── widget_state.py      # 状态/PropertyGroup/undo（1156 行）
├── widget_draw.py       # 绘制回调（1107 行）
├── widget_interact.py   # 交互 Operator 与 modal（1305 行）
├── widget_operator.py   # 兼容垫片（8 行，转发到上述 5 个 widget_*）
└── README.md

合计 26 个 py 文件 / 约 490 KB，operators.py 仍占约 39%
```

> 统计命令：`python -c "import pathlib; base=pathlib.Path('.'); print(sum(p.stat().st_size for p in base.glob('*.py'))//1024)"`

## 模块化重构进度与后续计划

### 已完成

- [x] **第一阶段：基础模块安全迁移**
  - `curve_data.py` / `hair_lifecycle.py` 独立，`handler.py` / `panel.py` 已切换。

- [x] **第二阶段：头发生命周期正式切换**
  - `get_figuhair_root / ensure_figuhair_root`、管线查找、源曲线反查等已迁移到 `hair_lifecycle.py`。

- [x] **第三阶段：管线生成与 Widget 拆分（2026-09-04 — 2026-09-05）**
  - `cross_section.py` / `math_utils.py` / `ghost.py` / `interp.py` / `sampling.py` / `transition.py` / `frames.py` 独立；
  - `selection.py` 独立（单点与框选均重定向到曲线，`handler.selection_redirect_callback` 同步修复）；
  - `edit_utils.py` 独立；
  - `pipe_generation.py`（`generate_pipe_mesh` 真实实现，~219 行）与 `point_data.py`（`sync_point_settings / sync_active_point_from_selection`）独立，`operators.py` 改为委托；
  - `widget_operator.py`（原单文件约 180KB / 3500+ 行）按**定义顺序保留**显式拆为 5 模块：`widget_cache`（2 块）/ `widget_geometry`（41 块）/ `widget_state`（55 块）/ `widget_draw`（25 块）/ `widget_interact`（22 块），`widget_operator.py` 保留为兼容垫片：
    ```python
    from .widget_state import HairPipeWidgetSettings, refresh_widget_preview_from_property, ...
    from .widget_cache import get_cached_pipe_mesh, clear_pipe_mesh_cache
    from .widget_geometry import *
    from .widget_draw import *
    from .widget_interact import *
    ```
  - 修复拆分引入的 4 个启动/运行时回归（均已验证 `py_compile OK`）：
    1. `HairPipeWidgetSettings.update=refresh_widget_preview_from_property` 的 `NameError`（`*` 导出顺序导致）→ 改显式导入并保证 `refresh` 定义在类之前；
    2. `cannot import get_stable_widget_alignment from widget_state` → 改为 `from widget_geometry import get_stable_widget_alignment`；
    3. `_draw_handle is not defined` / `HairPipePreferences already registered` → 补 `_draw_handle / _PIPE_BASEMESH_STATE_KEY / _CURVE_OVERLAY_STATE_KEY` 全局、幂等 `register`、惰性 `ensure_draw_handler` 与 `__pycache__` 清理；
    4. `setup_widget: sync_point_settings is not defined` / `prepare_proportional_transform: get_active_curve_point_world_position is not defined` → 补 `point_data` 导入与 `get_active_curve_point_world_position` 惰性循环导入。

### 当前巨石

- `operators.py` 仍为 4921 行 / 193 KB，占仓库约 39%，是最后的巨石。其余模块均已 < 60 KB。
- 已采用**兼容层小步迁移**策略：新模块提供正式实现，`operators.py` 保留同名委托，`bl_idname` 与旧 `.blend` 保持不变，因此每轮拆分后可直接在 Blender 中测试。

### 下一步（第四/五阶段，计划按此顺序每轮一个小功能组）

- [ ] **第四阶段：生成与对象服务**
  - `pipe_service.py`：生成/更新预览管线（抽离 `generate_pipe_mesh` 的调用与容错）；
  - `tail_service.py`：末端网格（已停用，仅清理残留）；
  - `modifier_service.py`：细分/Geometry Nodes 修改器开关；
  - `mesh_service.py`：安全重建、法线与材质。

- [ ] **第五阶段：Operator 注册层整理**（`operators.py` 最终只保留注册）
  - 新建 `operators/` 包：
    ```
    operators/
    ├── __init__.py      # register / unregister 汇总
    ├── hair_objects.py  # hide/show/duplicate/delete/family_local_view
    ├── editing.py       # edge_flow / point edit
    ├── conversion.py    # curve <-> mesh 转换
    ├── generate.py      # generate_pipe Operator 本体
    └── merge_split.py   # 合并/分离（已移除，仅保留兼容空实现）
    ```
  - 每拆一个文件即：保留旧 `bl_idname` → `__init__.py` 重导出 → `operators.py` 改为 `from .operators.hair_objects import *` 委托 → Blender 测试 → 删除旧实现。

### 每一轮的固定流程

1. 只迁移一个小功能组。
2. 保留旧接口兼容层。
3. 检查导入和静态错误（`py_compile` + `ReadLints`）。
4. 你在 Blender 中测试实际操作。
5. 如有问题先修复，不继续拆分。
6. 确认稳定后再进入下一轮。
7. 最后才删除旧兼容代码。

### 重构完成的判断标准

- `operators.py` 不再包含大段几何算法（目标 < 300 行，仅注册）；
- handler 不再依赖 Operator 文件中的核心实现；
- 头发对象创建、查找、清理有唯一实现；
- 管线生成和 Blender 对象写入彻底分离；
- 所有现有 `bl_idname` 保持兼容；
- 合并、分离、复制、删除、隐藏、框选重定向均通过测试；
- 旧兼容入口可安全删除。
