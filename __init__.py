bl_info = {} 
 
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
 
def stable_cross_section_frame(tangent): 
    tangent = operators.safe_normalized(tangent) 
    if tangent.z < -0.999999: 
        normal = operators.Vector((0, -1, 0)) 
    else: 
        a = 1.0 / (1.0 + tangent.z) 
        b = -tangent.x * tangent.y * a 
        normal = operators.Vector((1.0 - tangent.x * tangent.x * a, b, -tangent.x)) 
        if normal.length < 1e-8: 
            normal = operators.Vector((1, 0, 0)) 
    normal = normal - tangent * normal.dot(tangent) 
    if normal.length < 1e-8: 
        normal = operators.Vector((1, 0, 0)) 
        normal = normal - tangent * normal.dot(tangent) 
    normal.normalize() 
    binormal = tangent.cross(normal).normalized() 
    return normal, binormal 
 
operators.get_cross_section_frame = stable_cross_section_frame
