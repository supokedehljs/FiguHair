import bpy
import math
from bpy.props import (
    FloatProperty, IntProperty, CollectionProperty,
    FloatVectorProperty, BoolProperty, PointerProperty, EnumProperty
)
from bpy.types import PropertyGroup


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
        description="Generated rings between neighboring curve control points; higher values make cross-section transitions smoother",
        default=1,
        min=1,
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
        default=True,
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
    default_subdiv: BoolProperty(
        name="Default Subdivision",
        description="Add a level 2 subdivision surface modifier when creating the pipe mesh",
        default=True,
    )
    redirect_selection: BoolProperty(
        name="Select Curve From Preview",
        description="Selecting the generated preview mesh automatically selects this source curve",
        default=True,
    )
    point_settings: CollectionProperty(type=HairPipePointSettings)
    active_point_index: IntProperty(
        name="Active Point",
        description="Index of the currently selected curve control point",
        default=0,
        min=0,
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
