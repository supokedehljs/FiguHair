# FiguHair 功能总览（给右栏 UI 设计用）

> 版本：Blender 5.0 安装版，`bl_info` 1.0.0，要求 Blender 4.0+，分类 Add Curve
> 模块名：`figuhair`（文件夹 `scripts/addons/figuhair`）
> 规模：51 个已注册操作符、4 个属性组、1 个插件偏好、1 个浮动横截面编辑器、1 个工具栏工具
> 本文描述的是**功能与约束**，不是最终布局。右栏可以重新组织。

---

## 1. 一句话定位

用「曲线」控制发丝走向、用「逐点自定义横截面」控制截面形状，再生成带细分与可编辑末端的管道网格；支持发束级管理（复制/删除/隐藏/单独显示/合并导出）。

---

## 2. 核心概念与数据模型

### 2.1 对象层级（当前实现）

```
FiguHair 01 Curve        ← 曲线对象，就是「头发根」。所有截面数据都挂在它身上
├── FiguHair 01 Mesh     ← 生成的管道网格（子物体，带细分修改器）
└── FiguHair 01 Tail     ← 可选的末端网格（子物体，独立编辑）
```

- 曲线名 = `<base> Curve`，网格名 = `<base> Mesh`，末端 = `<base> Tail`；`base` 形如 `FiguHair 01`
- 旧命名兼容：`<曲线名>_FiguHair`、`<曲线名>_FiguHairTail`、`<曲线名>_FiguHairCurve`
- 合并导出后生成一个 `HairMerged` 网格，原头发被隐藏
- 曲线对象上的关键自定义属性：`hair_pipe_base_name`（是否属于本插件的判据）、`hair_pipe_source_curve`（网格指回曲线）、`hair_pipe_tail_source_curve`、`hair_pipe_solo_active`、`hair_pipe_solo_prev_hidden`、`hair_pipe_tail_user_hidden`、`hair_pipe_root`

### 2.2 数据存在哪里

| 属性组 | 挂在哪 | 作用 |
|---|---|---|
| `HairPipeSettings` | 每个 Curve 对象的 `obj.hair_pipe_settings` | 全局设置 + 每个控制点的截面数据集合 |
| `HairPipePointSettings` | 上面的 `point_settings` 集合 | 单个控制点：截面顶点集合、旋转、缩放、过渡模式、桥接错位 |
| `HairPipeCrossSectionVertex` | 每个点的 `cross_section_verts` | 单个截面顶点：局部 XY 偏移、是否幽灵点 |
| `HairPipeWidgetSettings` | WindowManager `wm.hair_pipe_widget` | 浮动编辑器与显示状态的运行时数据（窗口级，不是场景数据） |
| `HairPipePreferences` | 插件偏好 | 浮动编辑器的左右/上下偏移与整体大小 |

### 2.3 生成物与修改器

- 网格由代码实时生成（`generate_pipe_mesh`），不是几何节点
- 自动挂两个修改器：`FiguHair Catmull-Clark`（细分曲面，视图/渲染层级=细分层级）与 `FiguHair Join Tail`（把末端并进管道的几何节点组）
- 细分修改器始终存在，只是按「细分层级 / 显示细分修改器」控制是否显示

---

## 3. 典型工作流

1. **画头发**：点「添加头发」→ 在 3D 视口左键逐点落点（或拖出）→ 滚轮调截面宽度 → 空格/回车确认 → 自动生成管道网格并进入可编辑状态（这一步会同时建曲线 + 生成网格）。
2. **从管状网格反向**：选中现成的管状网格 → 「发管转曲线」→ 按松散块拆成多根，各自生成曲线 + 管道（忽略原物体的修改器）。
3. **改形状**：进曲线编辑模式 → 选控制点 → 打开横截面编辑器（浮动）改截面；或在右栏用平滑/简化/边流等命令。
4. **出片**：合并所有头发 → 得到 `HairMerged` 单一网格用于导出，原头发自动隐藏。

---

## 4. 功能清单

入口说明：**面板** = 当前右栏按钮；**快捷键** = 插件自带的键位；**F3** = 只能在菜单搜索里找到；**编辑器** = 浮动横截面编辑器内。

### 4.1 创建 / 转换

| 功能 | 操作符 | 入口 | 说明 |
|---|---|---|---|
| 添加头发 | `figuhair.draw_hair_curve` | 面板 / 工具栏工具 / 快捷位 | 左键逐点创建、滚轮调宽、空格或回车确认；结束后自动生成管道 |
| 发管转曲线 | `figuhair.mesh_to_hair_curve` | 面板 | 选中管状网格，按松散块拆分为多根曲线，并各自生成管道；删除原网格 |
| 生成 / 更新管道 | `figuhair.generate_pipe` | F3（原面板按钮已移除） | 手动重建当前曲线的管道网格；平时由自动更新代替 |
| 同步控制点设置 | `figuhair.sync_points` | F3 | 让 `point_settings` 与曲线实际控制点数量/顺序对齐 |

### 4.2 横截面编辑（核心）

每个曲线控制点都有**独立的横截面**（一圈顶点）。可以只改当前点，也可以把当前截面复制到其它选中的点。

| 功能 | 操作符 | 入口 | 说明 |
|---|---|---|---|
| 打开 / 关闭横截面编辑器 | `widget_interact` / `widget_stop` | 面板 | 浮动在视口里的 2D 截面编辑器；需要曲线编辑模式 |
| 添加截面顶点 | `widget_add_vertex` | F3 | 末尾追加一个顶点（±无 UI） |
| 删除截面顶点 | `widget_remove_vertex` / `widget_delete_selected_vertices` | F3 | 删除当前/选中的顶点（±无 UI）；最少保留 3 个正常点 |
| 在边上插入顶点 | （编辑器内中键） | 编辑器 | 命中最近的边并在该处插入 |
| 重置为圆形 | `reset_cross_section` / `reset_all_cross_sections` | F3 | 当前点 / 全部点恢复圆形 |
| 线性渐细 | `taper_linear` | F3 | 从根到梢做线性半径渐变 |
| 复制 / 粘贴横截面 | `copy_cross_section` / `paste_cross_section` | 快捷位 | 复制当前点截面；粘贴到当前或选中的多个点（可带旋转偏移） |
| 复制到全部点 | `copy_cs_to_all` | F3 | 当前截面覆盖所有点 |
| 截面边流 | `apply_edge_flow` | 面板 | 用两个可编辑截面重建中间截面；参数：模式/强度/混合 |
| 横截面传递 | `cross_section_spread` | 编辑器右键菜单 | 滚轮把当前截面沿相邻点往下传，左键确认 |
| 过渡点开关 | `toggle_cross_section_transition` | F3 | 把选中点标记为「过渡点」：不直接编辑，由相邻可编辑截面插值 |
| 上下桥接错位 | `widget_bridge_offset` | 编辑器右键菜单 | 当前截面与上一截面之间的顶点偏移（-64…64），模态滚轮调 |
| 设为幽灵点 / 恢复正常点 | `widget_toggle_ghost` / `widget_make_normal` | 面板 + 编辑器右键 + 快捷位 | 幽灵点保留拓扑但不直接参与编辑，用来简化截面 |
| 普通平滑 / 圆形平滑 | `widget_smooth_selected_vertices` | 面板 | 选中顶点向邻点平均（普通）或向平均半径的圆（圆形）；强度 0.5、1 次 |
| 曲线平滑（点） | `smooth_curve_points` | 面板 + 快捷位 | 选中控制点向相邻两点中点靠拢（每次 50%） |
| 自动简化 | `auto_simplify_cross_section` | 面板 + 快捷位 | 按影响程度把一部分顶点转成幽灵点（每次一半，可重复点） |
| 截面边流参数 | `edge_flow_mode` / `edge_flow_power` / `edge_flow_blend` | 面板（随按钮下发） | 模式：线性/缓入缓出/强平滑/偏起点/偏终点/正弦 |
| 每个点的旋转 / 缩放 | `PointSettings.rotation` / `.scale` | 面板/编辑器 | 整圈截面旋转（度，±360）、整体缩放（0.001…100） |
| 每个顶点的 XY | `CrossSectionVertex.offset_x / offset_y` | 编辑器 | 截面局部坐标 |

### 4.3 曲线控制点

| 功能 | 操作符 | 入口 | 说明 |
|---|---|---|---|
| 选择控制点 | `select_point` | F3 | 按序号把某个控制点设为活动点 |
| 距离平均化 | `equalize_point_distance` | F3 | 选中的控制点沿曲线等距重排 |
| 翻转方向 | `reverse_curve_direction` | 面板 + 快捷位 | 反转曲线方向，截面外观不变 |
| 活动点同步 | 自动 | 自动 | 在曲线编辑模式里改选择，会自动同步 `active_point_index` |

### 4.4 显示与检视

| 功能 | 实现 | 入口 | 说明 |
|---|---|---|---|
| 去细分显示 / 细分显示 | `preview_mode`（BASE / SUBDIV） | 面板（互斥两按钮） | BASE=去细分+平直着色+线框；SUBDIV=保留细分+平滑着色 |
| 显示在最前 | `preview_in_front` | 面板 | 让当前预览始终画在其他物体前面 |
| 单独显示（持久） | `toggle_solo_display` | 面板 + **Ctrl+F** | 只显示选中的整套头发（记录并恢复其它物体的可见性）；仅在选中 FiguHair 头发或进入其编辑模式时生效 |
| 单独显示（按住式） | 编辑器内 `E` / `solo_hold_active` | 编辑器 | 松开即恢复，和上面的持久版是两套行为 |
| 隐藏头发 / 显示全部 | `hide_hair` / `show_all_hair` | 快捷键 H / Alt+H | 按整套头发隐藏/显示 |
| 整套局部视图 | `family_local_view` | 快捷键 Numpad `/` | 用 Blender 局部视图只看整套头发 |
| 去细分显示、细分显示（旧属性） | `base_preview_enabled` / `subdiv_preview_enabled` | — | 是 `preview_mode` 的两个布尔视图，互斥 |

### 4.5 头发套装管理

| 功能 | 操作符 | 入口 | 说明 |
|---|---|---|---|
| 复制头发 | `duplicate_hair` | 快捷键 Shift+D | 整套复制（曲线+网格+末端）并自动改基名 |
| 删除头发 | `delete_hair` | 快捷键 X / Del | 删除整套（曲线+网格+末端） |
| 合并所有头发 | `merge_hair_for_export` | 面板 | 把当前所有头发网格合并成 `HairMerged`，隐藏原件 |
| 网格不可选模式 | `toggle_redirect_selection` / `redirect_selection` | F3 / 属性 | 开启时点管线网格会自动选中源曲线；全局同步到所有曲线 |
| 应用网格可选性 | `apply_global_mesh_selectability` | F3 | 内部维护用 |

### 4.6 末端网格（Tail）

末端网格是一段挂在曲线末端、可单独编辑的网格（用于发梢造型）。

| 功能 | 操作符 | 入口 |
|---|---|---|
| 生成末端网格 | `create_tail_mesh` | F3 |
| 删除末端网格 | `remove_tail_mesh` | F3 |
| 编辑末端网格（在网格编辑/曲线编辑之间切换） | `edit_tail_mesh` | F3 |
| 显示/隐藏末端网格 | `toggle_tail_visibility` | F3 |
| 隐藏所有末端网格 | `hide_all_tail_meshes` | F3 |

### 4.7 浮动横截面编辑器

- 打开条件：活动对象是曲线、处于曲线编辑模式、有 `point_settings`、当前点不是过渡点、截面 ≥3 个顶点
- 面板上的「打开/关闭横截面编辑器」；快捷键 Ctrl+Shift+X；`widget_hold`（F3）是按住式版本
- 打开时会临时隐藏曲线叠加显示（记录并恢复 `show_wire/show_in_front/display_type/hide_*`、网格线、法线显示）
- 在视口里绘制：截面圈、中心十字、顶点、幽灵点形态、索引、框选矩形、套索、比例编辑圆环、转向标记等

---

## 5. 参数清单（用户可调）

### 5.1 每个曲线（`HairPipeSettings`）

| 参数 | 类型/范围/默认 | 说明 |
|---|---|---|
| 材质选择 `shared_hair_material` | Material，默认空 | 所有 FiguHair 网格共用同一材质 |
| 默认半径 `default_radius` | 0.001…10，0.05 | 初始化圆形截面的半径 |
| 默认分段 `default_segments` | 3…64，8 | 默认圆形截面的顶点数 |
| 管道中间环 `pipe_resolution` | 0…0（已禁用），0 | 相邻截面之间的中间环数（当前被锁成 0） |
| 过渡模式 `transition_mode` | LINEAR / EASE / MONOTONE / CATMULL / BLEND，BLEND | 多点截面之间的插值方式 |
| 过渡强度 `transition_strength` | 0…2，2.0 | 相邻截面影响强度 |
| 强平滑 `strong_smoothing` | 开关，关 | 对整串环额外平滑 |
| 强平滑次数 `strong_smoothing_iterations` | 1…12，8 | 额外平滑遍数 |
| 滚转算法 `roll_mode` | START_FIXED / HYBRID_STABLE / START_PROJECTED / PARALLEL_TRANSPORT / WORLD_UP，START_FIXED | 曲线点移动时截面朝向如何保持 |
| 边流模式 `edge_flow_mode` | LINEAR / EASE / SMOOTHER / START / END / SINE，SMOOTHER | 截面边流的插入方式 |
| 边流强度 `edge_flow_power` | 0.1…8，2.0 | 偏起点/偏终点的力度 |
| 边流混合 `edge_flow_blend` | 0…1，1.0 | 重建结果替代原截面的程度 |
| 平滑着色 `smooth_shading` | 开 | 生成网格是否平滑着色 |
| 自动更新 `auto_update` | 开 | 曲线/参数变化时自动重建管道 |
| 封口 `cap_ends` | 关 | 管道两端是否封口 |
| 细分层级 `subdivision_levels` | 0…6，2 | Catmull-Clark 视图/渲染层级 |
| 显示细分修改器 `default_subdiv` | 开 | 视口里是否显示细分修改器 |
| 网格不可选 `redirect_selection` | 开 | 点网格自动选中源曲线 |
| 活动点 `active_point_index` | ≥0，0 | 当前编辑的控制点序号 |
| 编辑器旋转修正 `widget_correct_rotation` | 度，0 | 浮动编辑器里 2D 显示的手动旋转 |

### 5.2 每个控制点（`HairPipePointSettings`）

| 参数 | 类型/范围/默认 | 说明 |
|---|---|---|
| 截面顶点 `cross_section_verts` | 集合 | 每个顶点有 XY 偏移 + 是否幽灵点 |
| 活动顶点 `active_vert_index` | ≥0，0 | 当前顶点 |
| 旋转 `rotation` | ±360°，0 | 整圈截面旋转 |
| 缩放 `scale` | 0.001…100，1 | 整圈截面缩放 |
| 过渡点 `use_transition` | 关 | 该点由相邻可编辑截面插值，不直接编辑 |
| 桥接错位 `bridge_offset` | -64…64，0 | 与上一截面的顶点连接偏移 |

### 5.3 每个截面顶点（`HairPipeCrossSectionVertex`）

| 参数 | 说明 |
|---|---|
| `offset_x` / `offset_y` | 截面局部 XY 偏移 |
| `is_ghost` | 幽灵点：保留拓扑，不可直接拖拽，用来简化截面 |

### 5.4 插件偏好（`HairPipePreferences`）

| 参数 | 范围 | 说明 |
|---|---|---|
| 左右 `widget_offset_x` | -1…1 | 编辑器水平偏移 |
| 上下 `widget_offset_y` | -1…1 | 编辑器垂直偏移 |
| 大小 `widget_area_scale` | 0.35…1.8 | 编辑器整体尺寸 |

偏好设置里还有「常用命令快捷键」清单（14 条，可分配）与「打开键位映射」按钮。

---

## 6. 浮动编辑器交互全表

### 6.1 鼠标

| 操作 | 行为 |
|---|---|
| 左键点顶点 | 选中该顶点（Shift 加选/减选） |
| 左键拖拽（编辑器内） | 框选顶点 |
| 左键拖拽（编辑器外） | 在 3D 视口里框选管线上的截面环顶点 |
| 中键（编辑器内） | 在最近的边上插入截面顶点 |
| 右键（编辑器内） | 先选中最近顶点，再打开上下文菜单 |
| 右键（其它位置） | 打开上下文菜单：上下桥接错位 / 设为幽灵点 / 转换为正常点 / 横截面传递 |
| 滚轮（非拖拽状态，按住 Ctrl） | 上一个 / 下一个控制点（保持选中顶点的对应关系） |
| 滚轮（移动顶点时） | 调「纵向半径」（比例编辑的影响范围，1…1000，默认 3） |

### 6.2 键盘

| 键 | 行为 |
|---|---|
| Ctrl+Z | 撤销（插件自己的截面撤销栈，最多 64 步） |
| G | 移动选中顶点（带比例编辑，滚轮调范围） |
| R | 旋转选中顶点 |
| S | 缩放选中顶点 |
| Alt+S | 缩放编辑器显示区域 |
| A | 全选 / 取消全选 |
| Q | 切换 去细分 / 细分 显示 |
| W | 切换 显示在最前 |
| E | 切换「按住式」单独显示 |
| Ctrl+T | 拖动做旋转修正（写入 `widget_correct_rotation`） |
| ESC | 关闭编辑器 |
| X / Delete | 透传给 Blender（注意：在曲线编辑模式下会删曲线控制点） |

> 旧版编辑器上还有一排图形按钮（添加/删除/幽灵/预览/翻转/网格索引/旋转修正），本版按钮矩形被清零，实际不显示；对应操作改由面板、右键菜单、中键插入和上面的快捷键承担。

---

## 7. 自动行为（用户看不见但会影响 UI 的）

- **自动重建**：`depsgraph_update_post` 回调检测曲线/截面签名变化 → `rebuild_existing_pipe`（对象模式直接重建、编辑模式走队列；带节流）
- **活动点同步**：曲线编辑模式下改选择会同步 `active_point_index` 与 `point_settings`
- **选择重定向**：对象模式点管线/末端网格会转成选源曲线（受 `redirect_selection` 控制）
- **可见性同步**：曲线/网格/末端/根之间的隐藏状态联动，末端有独立的「用户手动隐藏」记忆
- **末端更新**：末端网格跟着曲线更新，`FiguHair Join Tail` 修改器始终保证并入管道
- **载入后修复**：`load_post` 重新挂 handler、修末端、同步激活点
- **定时器**：约 50ms 的选择/可见性同步

---

## 8. 当前右栏结构（现状，供参考/重排）

```
FiguHair（3D 视图侧栏，分类 FiguHair）
├── 创建
│   ├── 添加头发（主按钮，较宽）
│   └── 发管转曲线
├── 显示
│   ├── 预览模式：去细分（平直着色 · 线框）/ 细分（平滑着色）  ← 互斥
│   ├── 细分层级 + 显示细分修改器（缩进在预览模式下方）
│   ├── 单独显示（右侧显示当前快捷键，默认 Ctrl+F）
│   └── 显示在最前
├── 编辑（标题右侧显示「曲线编辑模式」或「需进入曲线编辑模式」）
│   ├── 打开 / 关闭横截面编辑器（主按钮）
│   ├── 横截面：普通平滑 | 圆形平滑；自动简化 | 截面边流
│   ├── 曲线：曲线平滑 | 翻转方向
│   └── 自动更新管线（勾选）
├── 输出
│   └── 合并所有头发
└── 设置（不常改动，可折叠，默认折叠）
    ├── 材质
    ├── 滚转算法
    └── 平滑着色（勾选）
```

未选中头发时：不再显示灰色占位版，而是同一套结构、编辑相关按钮置灰、细分层级行隐藏。

---

## 9. 可达性缺口（右栏设计时最值得处理的部分）

以下功能**已经实现但当前没有任何面板入口**，只能 F3 搜索或需要先选中再按序号调用：

| 分组 | 功能 | 操作符 |
|---|---|---|
| 截面 | 加点 / 删点 / 删除选中顶点 | `widget_add_vertex` / `widget_remove_vertex` / `widget_delete_selected_vertices` |
| 截面 | 重置圆形 / 全部重置 | `reset_cross_section` / `reset_all_cross_sections` |
| 截面 | 线性渐细 / 复制到全部点 | `taper_linear` / `copy_cs_to_all` |
| 截面 | 过渡点开关 | `toggle_cross_section_transition` |
| 截面 | 桥接错位（只能右键菜单） | `widget_bridge_offset` |
| 截面 | 横截面传递（只能右键菜单） | `cross_section_spread` |
| 曲线 | 距离平均化 | `equalize_point_distance` |
| 曲线 | 按序号选点 | `select_point` |
| 末端 | 生成 / 删除 / 编辑 / 显示隐藏 / 全部隐藏 | `create_tail_mesh`、`remove_tail_mesh`、`edit_tail_mesh`、`toggle_tail_visibility`、`hide_all_tail_meshes` |
| 套装 | 隐藏 / 显示全部 / 整套局部视图 | `hide_hair`、`show_all_hair`、`family_local_view`（有快捷键） |
| 套装 | 复制 / 删除 | `duplicate_hair`、`delete_hair`（有快捷键） |
| 维护 | 手动生成 / 同步点设置 | `generate_pipe` / `sync_points` |
| 编辑器 | 按住式编辑器 / 平滑预览 / 水平翻转 / 网格索引 | `widget_hold`、`widget_toggle_smooth_preview`、`widget_toggle_flip`、`widget_toggle_grid` |

另外 `hair_library.py` 里还有 13 个「横截面素材库」操作符（保存/导入/缩略图/覆盖层等），**整个模块没有被导入**，属于未接入的遗留功能；`figuhair_library/` 里有 6 组素材。设计右栏时不要把这块当成现有功能。

---

## 10. 快捷键现状

### 10.1 默认绑定

| 键 | 命令 | 上下文 |
|---|---|---|
| Ctrl+F | 单独显示 | 仅 FiguHair 曲线/网格/末端被选中，或在其编辑模式 |
| Ctrl+Shift+X | 打开/关闭横截面编辑器 | 曲线编辑模式 |
| H / Alt+H | 隐藏头发 / 显示全部 | 对象模式 |
| Shift+D | 复制整套头发 | 对象模式 |
| X / Del | 删除整套头发 | 对象模式 |
| Numpad / | 整套局部视图 | 对象模式 |
| 左键 | 用工具栏「新建头发曲线」工具画头发 | 工具栏工具激活时 |

### 10.2 可分配（已注册为 3D 视图下的未分配键位，在 键位映射 里搜索命令名即可设键）

添加头发、横截面编辑器、单独显示、合并所有头发、发管转曲线、截面边流、翻转方向、曲线平滑、自动简化、平滑横截面顶点、复制横截面、粘贴横截面、设置为幽灵点、设置为正常点。

---

## 11. 给 UI 设计的约束（重要）

1. **上下文依赖**：横截面相关命令都要求「曲线处于编辑模式 + 有 point_settings + 当前点不是过渡点 + 至少 3 个顶点」。UI 上应能显示禁用态并说明原因。
2. **两套界面**：右栏（持久、可放很多参数）和浮动编辑器（视口内、只放最常用的操作）。两者操作的是同一份数据。
3. **必须有「活动点」概念**：所有截面操作都作用于 `active_point_index`；多选曲线点时部分命令会一次作用到多个点（复制/粘贴、边流、简化）。
4. **撤销**：数据修改类操作符都带 UNDO；但浮动编辑器内部走插件自己的撤销栈（Ctrl+Z 只在编辑器里生效）。
5. **两套单独显示**：面板/Ctrl+F 是持久版，编辑器里的 E 是按住版，行为不同，不要混为一谈。
6. **生成时机**：`添加头发` 会自动生成网格；改参数后靠自动更新重建，`generate_pipe` 只是手动兜底。
7. **顶部开关已移除**：没有「启用/关闭插件」的场景级开关，关闭插件只能去偏好设置禁用插件。
8. **不要依赖 hair_library**：素材库那套没有接入。
9. **语言**：现有界面中英混排，命名以中文为主；bl_idname 全是 `figuhair.*`。

---

## 12. 已知限制 / 坑

- `pipe_resolution` 被锁成 0（禁用状态），没有中间环。
- 编辑器里按 X/Delete 会透传给 Blender，可能误删曲线控制点。
- 浮动编辑器上的图形按钮（加/删/幽灵/预览/翻转/索引）在本版不显示，相关操作只能走面板或 F3。
- 「网格不可选模式」的语义是：网格保持可点选（否则会点到后面的物体），点击后由选择处理器重定向到曲线。
- 撤销/重做后自动重建依赖 handler；后台无界面时部分绘制函数会静默跳过。
