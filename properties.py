import bpy
import math
from bpy.props import (
    FloatProperty, IntProperty, CollectionProperty,
    FloatVectorProperty, BoolProperty, PointerProperty, EnumProperty
)
from bpy.types import PropertyGroup


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


class HairPipeSettings(PropertyGroup):
    """Global settings for the hair pipe"""
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
        name="Pipe Resolution",
        description="Intermediate rings between neighboring cross-sections. 0 = sections connect directly, 1 = one ring in between, etc.",
        default=1,
        min=0,
        max=64,
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
