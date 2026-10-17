bl_info = {
    "name": "FiguHair",
    "author": "Unknown",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > FiguHair",
    "description": "将管状网格按松散块转换为头发曲线，并忽略修改器",
    "category": "Add Curve",
}

from . import operators, panel, properties, handler, widget_operator, preferences


def register():
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
