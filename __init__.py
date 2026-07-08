bl_info = {
    "name": "FiguHair - Hair Curve Pipe",
    "author": "Unknown",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > FiguHair",
    "description": "Generate pipe mesh from curves with per-point custom cross-sections",
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
 

