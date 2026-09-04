import math
from .interp import interpolate_section_value
from .math_utils import lerp_angle, lerp_radians


def is_transition_point(point_setting):
    return bool(getattr(point_setting, 'use_transition', False))


def find_previous_editable_point_index(point_settings, idx):
    for point_idx in range(idx - 1, -1, -1):
        if not is_transition_point(point_settings[point_idx]):
            return point_idx
    return None


def find_next_editable_point_index(point_settings, idx):
    for point_idx in range(idx + 1, len(point_settings)):
        if not is_transition_point(point_settings[point_idx]):
            return point_idx
    return None


def get_transition_source_indices(point_settings, idx):
    if idx < 0 or idx >= len(point_settings):
        return None, None
    if not is_transition_point(point_settings[idx]):
        return idx, idx
    return find_previous_editable_point_index(point_settings, idx), find_next_editable_point_index(point_settings, idx)


def get_point_setting(point_settings, idx, settings):
    if idx < len(point_settings):
        return point_settings[idx]

    class DefaultPointSetting:
        def __init__(self, s):
            self.rotation = 0.0
            self.scale = 1.0
            self.cross_section_verts = self._make_circle(s.default_radius, s.default_segments)
        def _make_circle(self, radius, segments):
            class FakeVert:
                def __init__(self, x, y):
                    self.offset_x = x
                    self.offset_y = y
            verts = []
            for i in range(segments):
                angle = 2.0 * math.pi * i / segments
                verts.append(FakeVert(math.cos(angle)*radius, math.sin(angle)*radius))
            return verts
    return DefaultPointSetting(settings)


def get_effective_point_setting(point_settings, idx, settings):
    if idx < 0 or idx >= len(point_settings):
        return get_point_setting(point_settings, idx, settings)
    prev_idx, next_idx = get_transition_source_indices(point_settings, idx)
    if prev_idx is None and next_idx is None:
        return point_settings[idx]
    if prev_idx is None:
        return point_settings[next_idx]
    if next_idx is None:
        return point_settings[prev_idx]
    if prev_idx == next_idx:
        return point_settings[prev_idx]
    return point_settings[idx]


def get_cross_section_sample(point_setting, point=None, vert_idx=0):
    verts = point_setting.cross_section_verts
    if len(verts) == 0:
        return 0.0, 0.0, 0.0
    curve_radius = point.get('radius', 1.0) if point else 1.0
    curve_tilt = point.get('tilt', 0.0) if point else 0.0
    scale = point_setting.scale * curve_radius
    rotation = math.radians(point_setting.rotation) + curve_tilt
    vert = verts[vert_idx % len(verts)]
    return vert.offset_x * scale, vert.offset_y * scale, rotation


def interpolate_cross_sections(ps0, ps1, t, point0=None, point1=None):
    verts0 = ps0.cross_section_verts
    verts1 = ps1.cross_section_verts
    if len(verts0) == 0 or len(verts1) == 0:
        return []
    num_verts = min(len(verts0), len(verts1))
    _, _, rot0 = get_cross_section_sample(ps0, point0)
    _, _, rot1 = get_cross_section_sample(ps1, point1)
    interp_rot = rot0 * (1.0 - t) + rot1 * t
    cos_r = math.cos(interp_rot)
    sin_r = math.sin(interp_rot)
    result = []
    for i in range(num_verts):
        x0, y0, _ = get_cross_section_sample(ps0, point0, i)
        x1, y1, _ = get_cross_section_sample(ps1, point1, i)
        lx = x0 * (1.0 - t) + x1 * t
        ly = y0 * (1.0 - t) + y1 * t
        rx = lx * cos_r - ly * sin_r
        ry = lx * sin_r + ly * cos_r
        result.append((rx, ry))
    return result


def interpolate_cross_sections_smooth(
    ps_prev, ps0, ps1, ps_next, t,
    point_prev=None, point0=None, point1=None, point_next=None,
    mode='MONOTONE', strength=1.0,
):
    verts0 = ps0.cross_section_verts
    verts1 = ps1.cross_section_verts
    if len(verts0) == 0 or len(verts1) == 0:
        return []
    t = max(0.0, min(1.0, t))
    num_verts = min(len(verts0), len(verts1))
    _, _, rot_prev = get_cross_section_sample(ps_prev, point_prev)
    _, _, rot0 = get_cross_section_sample(ps0, point0)
    _, _, rot1 = get_cross_section_sample(ps1, point1)
    _, _, rot_next = get_cross_section_sample(ps_next, point_next)
    interp_rot = interpolate_section_value(rot_prev, rot0, rot1, rot_next, t, mode, strength)
    cos_r = math.cos(interp_rot)
    sin_r = math.sin(interp_rot)
    result = []
    for i in range(num_verts):
        x_prev, y_prev, _ = get_cross_section_sample(ps_prev, point_prev, i)
        x0, y0, _ = get_cross_section_sample(ps0, point0, i)
        x1, y1, _ = get_cross_section_sample(ps1, point1, i)
        x_next, y_next, _ = get_cross_section_sample(ps_next, point_next, i)
        lx = interpolate_section_value(x_prev, x0, x1, x_next, t, mode, strength)
        ly = interpolate_section_value(y_prev, y0, y1, y_next, t, mode, strength)
        rx = lx * cos_r - ly * sin_r
        ry = lx * sin_r + ly * cos_r
        result.append((rx, ry))
    return result


def interpolate_transition_cross_section(point_settings, idx, settings, point=None):
    prev_idx, next_idx = get_transition_source_indices(point_settings, idx)
    if prev_idx is None and next_idx is None:
        return []
    if prev_idx is None:
        source = point_settings[next_idx]
        return interpolate_cross_sections(source, source, 0.0, point, point)
    if next_idx is None:
        source = point_settings[prev_idx]
        return interpolate_cross_sections(source, source, 0.0, point, point)
    if prev_idx == next_idx:
        source = point_settings[prev_idx]
        return interpolate_cross_sections(source, source, 0.0, point, point)
    prev_ps = point_settings[prev_idx]
    next_ps = point_settings[next_idx]
    t = (idx - prev_idx) / max(1, next_idx - prev_idx)
    return interpolate_cross_sections_smooth(
        prev_ps, prev_ps, next_ps, next_ps, t,
        point, point, point, point,
        settings.transition_mode, settings.transition_strength,
    )


def update_transition_point_values(curve_obj, settings):
    from .edit_utils import get_curve_point_by_global_index, edge_flow_t
    point_settings = settings.point_settings
    if len(point_settings) < 3:
        return 0
    changed = 0
    for idx, ps in enumerate(point_settings):
        if not is_transition_point(ps):
            continue
        prev_idx = find_previous_editable_point_index(point_settings, idx)
        next_idx = find_next_editable_point_index(point_settings, idx)
        if prev_idx is None or next_idx is None or prev_idx == next_idx:
            continue
        prev_ps = point_settings[prev_idx]
        next_ps = point_settings[next_idx]
        count = min(len(prev_ps.cross_section_verts), len(next_ps.cross_section_verts))
        if count < 3:
            continue
        while len(ps.cross_section_verts) < count:
            v = ps.cross_section_verts.add()
            v.offset_x = 0.0
            v.offset_y = 0.0
            v.is_ghost = False
        while len(ps.cross_section_verts) > count and len(ps.cross_section_verts) > 3:
            ps.cross_section_verts.remove(len(ps.cross_section_verts) - 1)
        raw_t = (idx - prev_idx) / max(1, next_idx - prev_idx)
        t = edge_flow_t('SMOOTHER', raw_t, 2.0)
        for vert_idx in range(count):
            prev_v = prev_ps.cross_section_verts[vert_idx]
            next_v = next_ps.cross_section_verts[vert_idx]
            v = ps.cross_section_verts[vert_idx]
            v.offset_x = prev_v.offset_x * (1.0 - t) + next_v.offset_x * t
            v.offset_y = prev_v.offset_y * (1.0 - t) + next_v.offset_y * t
            v.is_ghost = False
        ps.scale = prev_ps.scale * (1.0 - t) + next_ps.scale * t
        ps.rotation = lerp_angle(prev_ps.rotation, next_ps.rotation, t)
        prev_point = get_curve_point_by_global_index(curve_obj, prev_idx)
        next_point = get_curve_point_by_global_index(curve_obj, next_idx)
        curve_point = get_curve_point_by_global_index(curve_obj, idx)
        if prev_point is not None and next_point is not None and curve_point is not None:
            prev_radius = getattr(prev_point, 'radius', 1.0)
            next_radius = getattr(next_point, 'radius', 1.0)
            prev_tilt = getattr(prev_point, 'tilt', 0.0)
            next_tilt = getattr(next_point, 'tilt', 0.0)
            curve_point.radius = prev_radius * (1.0 - t) + next_radius * t
            curve_point.tilt = lerp_radians(prev_tilt, next_tilt, t)
        if ps.active_vert_index >= len(ps.cross_section_verts):
            ps.active_vert_index = len(ps.cross_section_verts) - 1
        changed += 1
    return changed


def interpolate_nurbs_cross_sections(point_settings, points, weighted, total, settings, global_point_idx):
    if total < 1e-8 or not weighted:
        return []
    first_idx = weighted[0][0]
    return interpolate_transition_cross_section(point_settings, global_point_idx + first_idx, settings, points[first_idx])


def interpolate_nurbs_cross_sections_by_control_range(point_settings, points, settings, global_point_idx, sample_t, is_cyclic):
    num_points = len(points)
    if num_points == 0:
        return []
    idx0 = int(sample_t * (num_points - 1)) if not is_cyclic else int(sample_t * num_points) % num_points
    return interpolate_transition_cross_section(point_settings, global_point_idx + idx0, settings, points[idx0])


def interpolate_cross_sections_by_anchor_distance(point_settings, points, settings, global_point_idx, anchors, distance):
    if not anchors or not points:
        return []
    best_idx = 0
    best_dist = None
    for idx, anchor in enumerate(anchors):
        d = abs(anchor - distance)
        if best_dist is None or d < best_dist:
            best_dist = d
            best_idx = idx
    return interpolate_transition_cross_section(point_settings, global_point_idx + best_idx, settings, points[best_idx])
