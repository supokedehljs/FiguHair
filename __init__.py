bl_info = {
    "name": "FiguHair - Hair Curve Pipe",
    "author": "Unknown",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > FiguHair",
    "description": "Generate pipe mesh from curves with per-point custom cross-sections",
    "category": "Add Curve",
}

from . import operators, panel, properties, handler, widget_operator, preferences, hair_library


def register():
    preferences.register()
    properties.register()
    widget_operator.register()
    operators.register()
    hair_library.register()
    panel.register()
    handler.register_handler()


def unregister():
    preferences.unregister()
    handler.unregister_handler()
    panel.unregister()
    hair_library.unregister()
    operators.unregister()
    widget_operator.unregister()
    properties.unregister()
