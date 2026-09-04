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
5. 在 **Cross-Section Editor** 中调整横截面顶点位置
6. 点击 **Generate Hair Pipe** 生成管道网格

### Cross-Section Editor 说明

选中某个曲线控制点后，面板会显示该点的横截面：
- 横截面是一个由多个顶点围成的闭合轮廓（默认是圆形）
- 每个顶点显示 X / Y 坐标，直接修改数值即可改变形状
- **Add Vertex**：在当前顶点和下一个顶点之间插入新顶点
- **Remove Vertex**：删除当前选中的顶点（最少保留 3 个）
- **Reset to Circle**：将当前点的横截面恢复为圆形
- **Copy to All Points**：将当前横截面形状应用到所有控制点
- **Scale**：整体缩放横截面
- **Rotation**：整体旋转横截面

### 典型工作流：制作一根头发

1. 添加 Bezier 曲线，编辑模式下调整形状
2. 回到物体模式，Hair Pipe 面板 → Sync Point Settings
3. 点击 Linear Taper 应用渐细效果
4. 选择某个特定的点，手动拖动横截面顶点做出扁平或不规则形状
5. Generate Hair Pipe 生成最终网格

## 兼容性

- Blender 3.6+
- 支持 Bezier、Poly、NURBS 曲线
- 支持环形（Cyclic）曲线

## 文件结构

```
hair_curve_pipe/
├── __init__.py       # 插件入口
├── properties.py     # 属性（横截面顶点、逐点设置、全局设置）
├── operators.py      # 操作符（现阶段保留兼容层，逐步瘦身，约 200k -> 持续下降）
├── panel.py          # 右栏 UI 面板（通用区已移除 生成/更新管线）
├── handler.py        # 自动更新与可见性同步（0.25s 定时 + depsgraph，含框选重定向修复）
├── curve_data.py     # 曲线读取与控制点选择
├── hair_lifecycle.py # 头发对象族与预览网格管理
├── cross_section.py  # 横截面拓扑（添加/删除/对齐与 spline 范围）
├── math_utils.py     # 向量/切线/横截面坐标系/基础数学
├── interp.py         # 数值插值（ease/lerp/hermite/section）
├── sampling.py       # 采样（Bezier/NURBS/弧长/分布/切线）
├── transition.py     # 横截面过渡与平滑插值、过渡点更新
├── frames.py         # 帧/环构建、最小扭转与平滑
├── ghost.py          # 幽灵点插值与同步
├── selection.py      # 选择重定向与选中高亮（单点/框选均重定向到曲线）
├── edit_utils.py     # 边流/点编辑工具（edge_flow、全局点索引等）
└── README.md
```

## 模块化重构进度与后续计划

### 当前阶段

- [x] 第一阶段：基础模块安全迁移

当前处于**第一轮安全迁移阶段**。目标不是一次性重写插件，而是在保持 Blender 操作 ID、旧 `.blend` 文件兼容性和现有功能的前提下，逐步降低 `operators.py` 的职责。

目前已经完成：

- 新增 `curve_data.py`，承接曲线默认值、曲线点读取和控制点选择。
- 新增 `hair_lifecycle.py`，承接 FiguHair 曲线、预览管线和末端网格的查找与对象关系管理。
- `handler.py` 已经改为直接使用拆分后的曲线数据和生命周期模块。
- `panel.py` 已经直接使用拆分后的基础模块。
- `operators.py` 保留兼容入口，因此现有功能和外部导入不会突然失效。
- 自动更新定时器已经从约每秒 10 次降低为约每秒 4 次，并增加选择状态缓存。
- 合并 spline 的默认点问题已经修复，避免产生原点控制点和错误连线。

### 已经简化了多少

目前是**架构职责开始分离，但核心代码体积还没有大幅减少**的阶段。

按功能计算，已经迁移了两类基础职责：

- [x] 曲线数据层：已迁移。
- [x] 头发对象生命周期层：已建立独立实现，并开始被 handler 使用。

尚未完全迁移的部分仍然主要集中在 `operators.py`：

- 管线和横截面生成算法；
- Bezier、NURBS、Poly 采样；
- frame、ring 和 mesh 拓扑计算；
- 尾部网格生成与重拓扑；
- 曲线编辑操作；
- 合并、分离、复制、删除和转换操作；
- Widget 交互和相关辅助逻辑。

因此当前可以理解为：**运行时耦合已经开始降低，但 `operators.py` 的文件行数暂时不会明显下降**。这是有意的安全策略，不是拆分没有生效。

### 为什么拆分后测试没有问题

这是因为本轮采用了兼容层迁移，而不是直接删除旧代码：

1. 新模块提供新的正式实现。
2. `operators.py` 暂时保留同名函数作为兼容入口。
3. 旧的操作 ID 没有改变。
4. `handler.py` 和 `panel.py` 只迁移了已经确认安全的调用。
5. 尚未迁移的模块仍然可以从 `operators.py` 获取旧接口。

所以测试没有问题是预期结果：外部行为保持不变，内部调用逐步转向新模块。等所有调用者完成迁移后，才会删除兼容实现。

### 接下来需要拆分的主要部分

后续还有 **4 个主要模块阶段**，每个阶段仍然会拆成多个小轮次，并在每轮后进行 Blender 测试。

- [x] 第二阶段：头发生命周期正式切换

已完成：`get_figuhair_root / ensure_figuhair_root`、管线与尾部网格查找、源曲线反查、预览网格父子关系与变换、头发对象族查找与清理已迁移到 `hair_lifecycle.py`，`operators.py` 保留兼容层，上层模块已切换到新入口；旧版末端网格功能已停用。

- [ ] 第三阶段：管线生成核心（进行中，2026-09-04）

已完成：`cross_section.py` 已独立；`math_utils.py` 已独立（`safe_normalized / get_cross_section_frame / Catmull-Rom / lerp_angle`）；`ghost.py` 已独立；`interp.py` 已独立；`sampling.py` 已独立（Bezier/NURBS 评估、弧长、分布、切线）；`transition.py` 已独立（横截面采样、过渡与 NURBS 插值）；`frames.py` 已独立（最小扭转环与平滑）；`selection.py` 已独立（选择重定向，单点与**框选**均重定向到曲线，修复框选能选到头发网格的 bug）；`edit_utils.py` 已独立（`get_curve_point_by_global_index / edge_flow_t / apply_edge_flow_to_target_indices` 等）；`operators.py` 中多头发合并/分离已移除，右栏通用区已隐藏 `生成 / 更新管线`，`添加头发` 为创建入口；`handler.py` 的 `selection_redirect_callback` 与 `selection_sync_timer` 已改为同时处理 `selected_objects` 框选集合。主线保持小步迁移与可测试策略。

- [ ] 第四阶段：生成与对象服务

目标：把“生成几何”和“写入 Blender 对象”分开。

计划新增：

- `pipe_service.py`：生成或更新预览管线；
- `tail_service.py`：末端网格创建、连接和重拓扑；
- `modifier_service.py`：细分和 Geometry Nodes 修改器；
- `mesh_service.py`：安全重建、清理面和法线处理。

这样 `generate_pipe` Operator 只负责检查上下文、调用服务和显示报告。

- [ ] 第五阶段：Operator 和注册层整理

目标：让 `operators.py` 最终只负责 Blender 操作符注册和少量上下文转换。

计划按功能拆出：

- `operators/generate.py`；
- `operators/editing.py`；
- `operators/hair_objects.py`；
- `operators/conversion.py`；
- `operators/merge_split.py`；
- `operators/register.py`。

所有现有 `bl_idname` 会保持不变，避免旧快捷键、面板和用户文件失效。

### 每一轮的固定流程

后续每次重构都遵循以下流程：

1. 只迁移一个小功能组。
2. 保留旧接口兼容层。
3. 检查导入和静态错误。
4. 你在 Blender 中测试实际操作。
5. 如果有问题，先修复，不继续拆分。
6. 确认稳定后再进入下一轮。
7. 最后才删除旧兼容代码。

### 重构完成的判断标准

只有满足以下条件，才认为模块化重构完成：

- `operators.py` 不再包含大段几何算法；
- handler 不再依赖 Operator 文件中的核心实现；
- 头发对象创建、查找、清理有唯一实现；
- 管线生成和 Blender 对象写入彻底分离；
- 所有现有操作 ID 保持兼容；
- 合并、分离、复制、删除、隐藏、尾部编辑和网格转换均通过测试；
- 旧兼容入口可以安全删除。

