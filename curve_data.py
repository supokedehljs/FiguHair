import bpy
from mathutils import Vector


def is_curve_edit_mode(curve_obj):
    return getattr(curve_obj, 'mode', '') in {'EDIT', 'EDIT_CURVE'}


def ensure_curve_defaults(curve_obj):
    if curve_obj is None or curve_obj.type != 'CURVE':
        return
    curve_obj.data.dimensions = '3D'
    curve_obj.data.resolution_u = max(getattr(curve_obj.data, 'resolution_u', 0), 16)
    curve_obj.data.render_resolution_u = max(getattr(curve_obj.data, 'render_resolution_u', 0), 16)
    for spline in curve_obj.data.splines:
        spline.resolution_u = max(getattr(spline, 'resolution_u', 0), 16)


def get_curve_points_data(curve_obj):
    ensure_curve_defaults(curve_obj)
    if is_curve_edit_mode(curve_obj):
        try:
            curve_obj.update_from_editmode()
        except (AttributeError, RuntimeError):
            pass

    all_splines_data = []
    for spline in curve_obj.data.splines:
        points_data = []
        if spline.type == 'BEZIER':
            for point in spline.bezier_points:
                points_data.append({
                    'co': point.co.copy(),
                    'handle_left': point.handle_left.copy(),
                    'handle_right': point.handle_right.copy(),
                    'radius': point.radius,
                    'tilt': point.tilt,
                })
        elif spline.type in {'POLY', 'NURBS'}:
            for point in spline.points:
                points_data.append({
                    'co': Vector(point.co[:3]),
                    'weight': point.co[3],
                    'radius': point.radius,
                    'tilt': point.tilt,
                })
        all_splines_data.append({
            'points': points_data,
            'type': spline.type,
            'cyclic': spline.use_cyclic_u,
            'resolution': spline.resolution_u,
            'order_u': getattr(spline, 'order_u', 4),
            'use_endpoint_u': getattr(spline, 'use_endpoint_u', False),
        })
    return all_splines_data


def get_selected_curve_point_index(curve_obj):
    indices = get_selected_curve_point_indices(curve_obj)
    return indices[-1] if indices else None


def get_selected_curve_point_indices(curve_obj):
    if curve_obj is None or curve_obj.type != 'CURVE':
        return []
    if is_curve_edit_mode(curve_obj):
        try:
            curve_obj.update_from_editmode()
        except (AttributeError, RuntimeError):
            pass

    selected = []
    global_index = 0
    for spline in curve_obj.data.splines:
        points = spline.bezier_points if spline.type == 'BEZIER' else spline.points
        for point in points:
            is_selected = (
                point.select_control_point if spline.type == 'BEZIER' else point.select
            )
            if is_selected:
                selected.append(global_index)
            global_index += 1
    return selected
