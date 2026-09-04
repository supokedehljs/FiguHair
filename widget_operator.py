"""Compatibility shim: forwards to split modules while preserving class update references."""
from .widget_state import (
    HairPipeWidgetSettings,
    refresh_widget_preview_from_property,
    get_base_preview_enabled, set_base_preview_enabled,
    get_subdiv_preview_enabled, set_subdiv_preview_enabled,
    get_solo_display_enabled, set_solo_display_enabled,
    push_widget_undo, pop_widget_undo,
    redraw_view3d, get_selected_widget_verts, set_selected_widget_verts,
    serialize_cross_section_undo_state, restore_cross_section_undo_state,
    get_widget_undo_stack, set_widget_undo_stack,
)
from .widget_cache import get_cached_pipe_mesh, clear_pipe_mesh_cache
from .widget_geometry import *
from .widget_draw import *
from .widget_interact import *
# Re-export for old imports: operators.py and cross_section_ops.py do `from .widget_operator import push_widget_undo`
__all__ = [x for x in dir() if not x.startswith("_")]
