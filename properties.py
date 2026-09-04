import bpy
import math
from bpy.props import (
    FloatProperty, IntProperty, CollectionProperty,
    FloatVectorProperty, BoolProperty, PointerProperty, EnumProperty, StringProperty
)
from bpy.types import PropertyGroup


def update_plugin_enabled(self, context):
    try:
        from .operators import apply_plugin_enabled_state
        apply_plugin_enabled_state(bool(self.plugin_enabled))
    except (ImportError, AttributeError, RuntimeError):
        pass


def apply_shared_hair_material(material):
    for obj in bpy.data.objects:
        if obj.type != 'MESH' or not obj.get("hair_pipe_source_curve"):
            continue
        obj.data.materials.clear()
        if material is not None:
            obj.data.materials.append(material)


def update_shared_hair_material(self, context):
    apply_shared_hair_material(self.shared_hair_material)


def update_subdivision_modifier_settings(self, context):
    owner = getattr(self, "id_data", None)
    if owner is None or getattr(owner, "type", None) != 'CURVE':
        return
    for obj in bpy.data.objects:
        if obj.type != 'MESH' or obj.get("hair_pipe_source_curve") != owner.name:
            continue
        modifier = obj.modifiers.get("FiguHair Catmull-Clark")
        if modifier is None:
            modifier = obj.modifiers.new("FiguHair Catmull-Clark", 'SUBSURF')
            modifier.subdivision_type = 'CATMULL_CLARK'
            modifier.show_render = True
        modifier.subdivision_type = 'CATMULL_CLARK'
        modifier.levels = self.subdivision_levels
        modifier.render_levels = self.subdivision_levels
        modifier.show_viewport = self.default_subdiv


class HairPipeCrossSectionVertex(PropertyGroup):
    """A single vertex on the cross-section profile (2D local coordinates)"""
    offset_x: FloatProperty(
        name="X",
        description="Local X offset of this cross-section vertex",
        default=0.0,
        precision=4,
    )
    offset_y: FloatProperty(
        name="Y",
        description="Local Y offset of this cross-section vertex",
        default=0.0,
        precision=4,
    )
    is_ghost: BoolProperty(
        name="Ghost",
        description="Ghost vertices keep topology without being directly editable",
        default=False,
    )


class HairPipePointSettings(PropertyGroup):
    """Per-curve-point cross-section: a collection of vertices forming the profile shape"""
    cross_section_verts: CollectionProperty(type=HairPipeCrossSectionVertex)
    active_vert_index: IntProperty(
        name="Active Vertex",
        description="Currently selected cross-section vertex",
        default=0,
        min=0,
    )
    rotation: FloatProperty(
        name="Rotation",
        description="Rotation of the entire cross-section at this point (degrees)",
        default=0.0,
        min=-360.0,
        max=360.0,
    )
    scale: FloatProperty(
        name="Scale",
        description="Uniform scale of the entire cross-section at this point",
        default=1.0,
        min=0.001,
        max=100.0,
    )
    use_transition: BoolProperty(
        name="横截面过渡模式",
        description="This point is automatically interpolated from neighboring editable cross-sections and cannot be edited directly",
        default=False,
    )
    bridge_offset: IntProperty(
        name="上下桥接错位",
        description="当前横截面与上一个横截面之间的桥接顶点偏移量；正负值控制错位方向",
        default=0,
        min=-64,
        max=64,
    )


def update_one_shot_slider(self, context, slider_name):
    owner = getattr(self, "id_data", None)
    if owner is None or getattr(owner, "type", None) != 'CURVE':
        return
    try:
        from .operators import ensure_one_shot_slider_gesture, update_one_shot_slider_value
        update_one_shot_slider_value(owner, self, slider_name)
        ensure_one_shot_slider_gesture(owner, slider_name)
    except (ImportError, AttributeError, RuntimeError):
        pass


def update_auto_ghost_tolerance(self, context):
    update_one_shot_slider(self, context, 'auto_ghost_tolerance')


def update_curve_smooth_slider(self, context):
    update_one_shot_slider(self, context, 'curve_smooth_slider')


def update_neighbor_smooth_slider(self, context):
    update_one_shot_slider(self, context, 'neighbor_smooth_slider')


def update_circular_smooth_slider(self, context):
    update_one_shot_slider(self, context, 'circular_smooth_slider')


class HairPipeSettings(PropertyGroup):
    """Global settings for the hair pipe"""
    plugin_enabled: BoolProperty(
        name="启用 FiguHair",
        description="开启时锁定头发网格并使用 FiguHair 编辑；关闭时允许直接选择头发网格",
        default=True,
        update=update_plugin_enabled,
    )
    shared_hair_material: PointerProperty(
        name="材质选择",
        description="为所有 FiguHair 头发网格使用同一个材质",
        type=bpy.types.Material,
        update=update_shared_hair_material,
    )
    default_radius: FloatProperty(
        name="Default Radius",
        description="Default radius when initializing cross-section to a circle",
        default=0.05,
        min=0.001,
        max=10.0,
        step=1,
        precision=4,
    )
    default_segments: IntProperty(
        name="Default Segments",
        description="Number of vertices in the default circular cross-section",
        default=8,
        min=3,
        max=64,
    )
    pipe_resolution: IntProperty(
        name="管线细分",
        description="相邻控制点之间的中间环数。0 = 1个控制点对应1个横截面（6点=6环），不插入过渡环。增大仅在需要时手补环",
        default=0,
        min=0,
        max=12,
    )
    adaptive_resolution: BoolProperty(
        name="自适应补环（可选）",
        description="关闭时严格 1点=1环。开启时才按段长/半径自动在长段中插入过渡环以改善长宽比（会改变环数，仅在长段鼓包严重时开启）",
        default=False,
    )
    adaptive_max_steps: IntProperty(
        name="自适应单段上限",
        description="开启自适应补环时，单段最多补多少环",
        default=4,
        min=1,
        max=32,
    )
    transition_mode: EnumProperty(
        name="Transition Mode",
        description="How cross-section shapes blend across multiple curve points",
        items=(
            ('LINEAR', "线性", "Direct interpolation between neighboring cross-sections"),
            ('EASE', "缓入缓出", "Smooth ease interpolation without overshoot"),
            ('MONOTONE', "单调平滑", "Multi-section Hermite interpolation with overshoot limiting"),
            ('CATMULL', "柔性样条", "Catmull-Rom interpolation using neighboring cross-sections"),
            ('BLEND', "混合", "Blend between monotone and Catmull-Rom styles"),
        ),
        default='BLEND',
    )
    transition_strength: FloatProperty(
        name="Transition Strength",
        description="Controls how strongly neighboring cross-sections influence the blend",
        default=2.0,
        min=0.0,
        max=2.0,
        precision=3,
    )
    strong_smoothing: BoolProperty(
        name="Strong Smoothing",
        description="Apply additional smoothing across the whole generated ring sequence",
        default=False,
    )
    strong_smoothing_iterations: IntProperty(
        name="Strong Smoothing Iterations",
        description="Number of smoothing passes applied to generated cross-section rings",
        default=8,
        min=1,
        max=12,
    )
    roll_mode: StringProperty(
        name="Roll Mode",
        description="START 绝对锁定",
        default='START_FIXED',
        options={'HIDDEN'},
    )
    edge_flow_mode: EnumProperty(
        name="Edge Flow Mode",
        description="How intermediate cross-sections are rebuilt between two selected curve points",
        items=(
            ('LINEAR', "线性", "Even transition from first selected section to second selected section"),
            ('EASE', "缓入缓出", "Smoothstep transition"),
            ('SMOOTHER', "强平滑", "Smoother S-curve transition"),
            ('START', "偏向起点", "Stay closer to the first selected section for longer"),
            ('END', "偏向终点", "Move toward the second selected section earlier"),
            ('SINE', "正弦", "Soft sine based transition"),
        ),
        default='SMOOTHER',
    )
    edge_flow_power: FloatProperty(
        name="Edge Flow Power",
        description="Controls bias strength for start/end weighted edge flow modes",
        default=2.0,
        min=0.1,
        max=8.0,
        precision=2,
    )
    edge_flow_blend: FloatProperty(
        name="Edge Flow Blend",
        description="How strongly intermediate sections are replaced by the rebuilt transition",
        default=1.0,
        min=0.0,
        max=1.0,
        precision=3,
    )
    smooth_shading: BoolProperty(
        name="Smooth Shading",
        description="Apply smooth shading to the generated mesh",
        default=True,
    )
    auto_update: BoolProperty(
        name="Auto Update",
        description="Automatically update the pipe mesh when curve or settings change",
        default=True,
    )
    cap_ends: BoolProperty(
        name="Cap Ends",
        description="Close the ends of the pipe",
        default=False,
    )
    subdivision_levels: IntProperty(
        name="细分层级",
        description="Viewport and render levels for the FiguHair subdivision surface modifier",
        default=2,
        min=0,
        max=6,
        update=update_subdivision_modifier_settings,
    )
    default_subdiv: BoolProperty(
        name="显示细分修改器",
        description="Show or hide the FiguHair subdivision surface modifier in the viewport. The modifier is always created for hair pipe meshes.",
        default=True,
        update=update_subdivision_modifier_settings,
    )
    redirect_selection: BoolProperty(
        name="网格不可选模式",
        description="让所有 FiguHair 头发网格不可选，点击预览网格时自动选择源曲线",
        default=True,
    )
    auto_ghost_tolerance: FloatProperty(
        name="自动简化",
        description="根据横截面变化程度，将选中横截面中影响较小的顶点转换为幽灵点",
        default=0.0,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
        precision=3,
        update=update_auto_ghost_tolerance,
    )
    curve_smooth_slider: FloatProperty(
        name="曲线平滑",
        description="将选中的曲线控制点向相邻点连线平滑",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', precision=3,
        update=update_curve_smooth_slider,
    )
    neighbor_smooth_slider: FloatProperty(
        name="普通平滑",
        description="将横截面编辑器中选中的正常点向相邻点平均位置平滑",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', precision=3,
        update=update_neighbor_smooth_slider,
    )
    circular_smooth_slider: FloatProperty(
        name="圆形平滑",
        description="将横截面编辑器中选中的正常点向平均圆周平滑",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', precision=3,
        update=update_circular_smooth_slider,
    )
    point_settings: CollectionProperty(type=HairPipePointSettings)
    active_point_index: IntProperty(
        name="Active Point",
        description="Index of the currently selected curve control point",
        default=0,
        min=0,
    )
    widget_correct_rotation: FloatProperty(
        name="Rotation Correction",
        description="Manual rotation correction for the cross-section display on this curve (degrees)",
        default=0.0,
        precision=1,
    )
    widget_offset_x: FloatProperty(
        name="左右",
        description="横截面编辑器显示区域的水平偏移",
        default=0.0,
        min=-1.0,
        max=1.0,
        precision=2,
    )
    widget_offset_y: FloatProperty(
        name="上下",
        description="横截面编辑器显示区域的垂直偏移",
        default=0.0,
        min=-1.0,
        max=1.0,
        precision=2,
    )
    widget_area_scale: FloatProperty(
        name="大小",
        description="横截面编辑器显示区域的整体大小",
        default=1.0,
        min=0.35,
        max=1.8,
        precision=2,
    )


def register():
    bpy.utils.register_class(HairPipeCrossSectionVertex)
    bpy.utils.register_class(HairPipePointSettings)
    bpy.utils.register_class(HairPipeSettings)
    bpy.types.Object.hair_pipe_settings = PointerProperty(type=HairPipeSettings)


def unregister():
    del bpy.types.Object.hair_pipe_settings
    bpy.utils.unregister_class(HairPipeSettings)
    bpy.utils.unregister_class(HairPipePointSettings)
    bpy.utils.unregister_class(HairPipeCrossSectionVertex)
