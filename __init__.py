bl_info = {
    "name": "FiguHair",
    "author": "Cursor AI",
    "version": (1, 2, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > FiguHair",
    "description": "Create curve-based pipes with per-point cross-section control for hair modeling",
    "category": "Mesh",
}

import bpy
from . import operators
from . import panel
from . import properties
from . import handler
from . import widget_operator


def register():
    properties.register()
    widget_operator.register()
    operators.register()
    panel.register()
    handler.register_handler()


def unregister():
    handler.unregister_handler()
    panel.unregister()
    operators.unregister()
    widget_operator.unregister()
    properties.unregister()


if __name__ == "__main__":
    register()
