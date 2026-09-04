import math
from mathutils import Vector
from .math_utils import lerp_angle, lerp_radians
from .transition import is_transition_point


def get_curve_point_by_global_index(curve_obj, target_index):
    if curve_obj is None or curve_obj.type != 'CURVE':
        return None
    global_point_idx = 0
    for spline in curve_obj.data.splines:
        points = spline.bezier_points if spline.type == 'BEZIER' else spline.points
        for point in points:
            if global_point_idx == target_index:
                return point
            global_point_idx += 1
    return None


def edge_flow_t(mode, t, power):
    t = max(0.0, min(1.0, t))
    if mode == 'EASE':
        return t * t * (3.0 - 2.0 * t)
    if mode == 'SMOOTHER':
        return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)
    if mode == 'START':
        return t ** max(0.1, power)
    if mode == 'END':
        return 1.0 - ((1.0 - t) ** max(0.1, power))
    if mode == 'SINE':
        return 0.5 - math.cos(t * math.pi) * 0.5
    return t


def find_previous_edge_flow_source_index(point_settings, idx, target_indices):
    for point_idx in range(idx - 1, -1, -1):
        if point_idx not in target_indices and not is_transition_point(point_settings[point_idx]):
            return point_idx
    return None


def find_next_edge_flow_source_index(point_settings, idx, target_indices):
    for point_idx in range(idx + 1, len(point_settings)):
        if point_idx not in target_indices and not is_transition_point(point_settings[point_idx]):
            return point_idx
    return None


def apply_edge_flow_to_target_indices(curve_obj, settings, target_indices, mode, power, blend):
    target_indices = sorted({idx for idx in target_indices if 0 <= idx < len(settings.point_settings)})
    if not target_indices:
        return 0
    target_set = set(target_indices)
    blend = max(0.0, min(1.0, blend))
    changed = 0
    for point_idx in target_indices:
        start_idx = find_previous_edge_flow_source_index(settings.point_settings, point_idx, target_set)
        end_idx = find_next_edge_flow_source_index(settings.point_settings, point_idx, target_set)
        if start_idx is None or end_idx is None or start_idx == end_idx:
            continue
        start_ps = settings.point_settings[start_idx]
        end_ps = settings.point_settings[end_idx]
        ps = settings.point_settings[point_idx]
        count = min(len(start_ps.cross_section_verts), len(end_ps.cross_section_verts))
        if count < 3:
            continue
        while len(ps.cross_section_verts) < count:
            v = ps.cross_section_verts.add()
            v.offset_x = 0.0
            v.offset_y = 0.0
            v.is_ghost = False
        while len(ps.cross_section_verts) > count and len(ps.cross_section_verts) > 3:
            ps.cross_section_verts.remove(len(ps.cross_section_verts) - 1)
        raw_t = (point_idx - start_idx) / max(1, end_idx - start_idx)
        t = edge_flow_t(mode, raw_t, power)
        for vert_idx in range(count):
            sv = start_ps.cross_section_verts[vert_idx]
            ev = end_ps.cross_section_verts[vert_idx]
            cv = ps.cross_section_verts[vert_idx]
            target_x = sv.offset_x * (1.0 - t) + ev.offset_x * t
            target_y = sv.offset_y * (1.0 - t) + ev.offset_y * t
            cv.offset_x = cv.offset_x * (1.0 - blend) + target_x * blend
            cv.offset_y = cv.offset_y * (1.0 - blend) + target_y * blend
            cv.is_ghost = False
        ps.scale = ps.scale * (1.0 - blend) + (start_ps.scale * (1.0 - t) + end_ps.scale * t) * blend
        target_rot = lerp_angle(start_ps.rotation, end_ps.rotation, t)
        ps.rotation = ps.rotation * (1.0 - blend) + target_rot * blend
        start_curve_point = get_curve_point_by_global_index(curve_obj, start_idx)
        end_curve_point = get_curve_point_by_global_index(curve_obj, end_idx)
        curve_point = get_curve_point_by_global_index(curve_obj, point_idx)
        if start_curve_point is not None and end_curve_point is not None and curve_point is not None:
            start_radius = getattr(start_curve_point, 'radius', 1.0)
            end_radius = getattr(end_curve_point, 'radius', 1.0)
            start_tilt = getattr(start_curve_point, 'tilt', 0.0)
            end_tilt = getattr(end_curve_point, 'tilt', 0.0)
            target_radius = start_radius * (1.0 - t) + end_radius * t
            target_tilt = lerp_radians(start_tilt, end_tilt, t)
            curve_point.radius = curve_point.radius * (1.0 - blend) + target_radius * blend
            curve_point.tilt = curve_point.tilt * (1.0 - blend) + target_tilt * blend
        if ps.active_vert_index >= len(ps.cross_section_verts):
            ps.active_vert_index = len(ps.cross_section_verts) - 1
        ps.use_transition = False
        changed += 1
    return changed
