import bpy
import math
from bpy.props import (
    FloatProperty, IntProperty, CollectionProperty,
    FloatVectorProperty, BoolProperty, PointerProperty
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
