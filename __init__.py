bl_info = {
    "name": "FiguHair - Hair Curve Pipe",
    "author": "Unknown",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > FiguHair",
    "description": "Generate pipe mesh from curves with per-point custom cross-sections",
    "category": "Add Curve",
}

from . import (
    cross_section,
    curve_data,
    edit_utils,
    frames,
    ghost,
    hair_lifecycle,
    interp,
    math_utils,
    operators,
    panel,
    properties,
    sampling,
    selection,
    transition,
    binding,
    handler,
    widget_operator,
    preferences,
)


def _force_unregister_stale():
    # Blender leaves classes registered if previous register() raised; clean them before re-register.
    for mod_name in ("preferences", "properties", "widget_operator", "widget_state", "widget_interact", "binding", "operators", "panel"):
        try:
            mod = __import__(f"hair_curve_pipe.{mod_name}", fromlist=["unregister"])
            # Only attempt if the classes are still registered; unregister is made tolerant.
            try:
                mod.unregister()
            except Exception:
                pass
        except Exception:
            pass

def register():
    _force_unregister_stale()
    preferences.register()
    properties.register()
    widget_operator.register()
    operators.register()
    panel.register()
    handler.register_handler()


def unregister():
    preferences.unregister()
    handler.unregister_handler()
    panel.unregister()
    operators.unregister()
    widget_operator.unregister()
    properties.unregister()
