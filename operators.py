import bpy
import math
from mathutils import Matrix, Vector
from bpy.props import IntProperty, FloatProperty, EnumProperty, BoolProperty


def ensure_curve_defaults(curve_obj):
    if curve_obj is None or curve_obj.type != 'CURVE':
        return
    curve_obj.data.dimensions = '3D'
    curve_obj.data.resolution_u = 1
    for spline in curve_obj.data.splines:
        spline.resolution_u = 1


def get_curve_points_data(curve_obj):
    """Extract control points from a curve object"""
    ensure_curve_defaults(curve_obj)
    if is_curve_edit_mode(curve_obj):
        try:
            curve_obj.update_from_editmode()
        except Exception:
            pass

    splines = curve_obj.data.splines
    all_splines_data = []

    for spline in splines:
        points_data = []
        if spline.type == 'BEZIER':
            for bp in spline.bezier_points:
                points_data.append({
                    'co': bp.co.copy(),
                    'handle_left': bp.handle_left.copy(),
                    'handle_right': bp.handle_right.copy(),
                    'radius': bp.radius,
                    'tilt': bp.tilt,
                })
        elif spline.type in ('POLY', 'NURBS'):
            for p in spline.points:
                co = Vector(p.co[:3])
                points_data.append({
                    'co': co,
                    'weight': p.co[3],
                    'radius': p.radius,
                    'tilt': p.tilt,
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


def evaluate_bezier_segment(p0, h0_right, h1_left, p1, t):
    u = 1.0 - t
    return (u**3)*p0 + 3*(u**2)*t*h0_right + 3*u*(t**2)*h1_left + (t**3)*p1


def evaluate_bezier_tangent(p0, h0_right, h1_left, p1, t):
    u = 1.0 - t
    tangent = 3*(u**2)*(h0_right-p0) + 6*u*t*(h1_left-h0_right) + 3*(t**2)*(p1-h1_left)
    if tangent.length < 1e-8:
        tangent = p1 - p0
    return tangent.normalized()


def make_nurbs_knot_vector(num_points, degree, is_cyclic, use_endpoint):
    if is_cyclic:
        return [float(i) for i in range(num_points + 2 * degree + 1)]

    knot_count = num_points + degree + 1
    if use_endpoint:
        interior_count = knot_count - 2 * (degree + 1)
        knots = [0.0] * (degree + 1)
        if interior_count > 0:
            for i in range(1, interior_count + 1):
                knots.append(float(i) / float(interior_count + 1))
        knots.extend([1.0] * (degree + 1))
        return knots

    return [float(i) for i in range(knot_count)]


def find_nurbs_span(num_eval_points, degree, u, knots):
    last_span = num_eval_points - 1
    if u >= knots[last_span + 1]:
        return last_span
    if u <= knots[degree]:
        return degree

    low = degree
    high = last_span + 1
    mid = (low + high) // 2
    while u < knots[mid] or u >= knots[mid + 1]:
        if u < knots[mid]:
            high = mid
        else:
            low = mid
        mid = (low + high) // 2
    return mid


def nurbs_basis_values(span, degree, u, knots):
    values = [0.0] * (degree + 1)
    left = [0.0] * (degree + 1)
    right = [0.0] * (degree + 1)
    values[0] = 1.0

    for j in range(1, degree + 1):
        left[j] = u - knots[span + 1 - j]
        right[j] = knots[span + j] - u
        saved = 0.0
        for r in range(j):
            denominator = right[r + 1] + left[j - r]
            temp = values[r] / denominator if abs(denominator) > 1e-8 else 0.0
            values[r] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        values[j] = saved

    return values


def get_nurbs_weighted_controls(points, degree, u, knots, is_cyclic):
    eval_points = points + points[:degree] if is_cyclic else points
    span = find_nurbs_span(len(eval_points), degree, u, knots)
    basis_values = nurbs_basis_values(span, degree, u, knots)

    weighted = []
    total = 0.0
    point_count = len(points)
    for local_idx, basis in enumerate(basis_values):
        eval_idx = span - degree + local_idx
        if eval_idx < 0 or eval_idx >= len(eval_points):
            continue
        control_idx = eval_idx % point_count
        point = eval_points[eval_idx]
        weight = basis * point.get('weight', 1.0)
        if weight > 1e-8:
            weighted.append((control_idx, weight))
            total += weight

    return weighted, total


def evaluate_nurbs_from_weighted(points, weighted, total):
    if total < 1e-8 or not weighted:
        return points[0]['co'].copy()

    numerator = Vector((0, 0, 0))
    for idx, weight in weighted:
        numerator += points[idx]['co'] * weight
    return numerator / total


def get_nurbs_domain(num_points, degree, knots, is_cyclic):
    if is_cyclic:
        return knots[degree], knots[num_points]
    return knots[degree], knots[num_points]


def interpolate_nurbs_cross_sections(point_settings, points, weighted, total, settings, global_point_idx):
    if total < 1e-8 or not weighted:
        return []

    max_count = 0
    cached_offsets = []
    for idx, weight in weighted:
        ps = get_point_setting(point_settings, global_point_idx + idx, settings)
        local_offsets = interpolate_cross_sections(ps, ps, 0.0, points[idx], points[idx])
        if local_offsets:
            cached_offsets.append((local_offsets, weight))
            max_count = max(max_count, len(local_offsets))
    if max_count == 0:
        return []

    accum = [(0.0, 0.0) for _ in range(max_count)]
    for local_offsets, weight in cached_offsets:
        normalized_weight = weight / total
        for i in range(max_count):
            ox, oy = local_offsets[i % len(local_offsets)]
            ax, ay = accum[i]
            accum[i] = (ax + ox * normalized_weight, ay + oy * normalized_weight)

    return accum


def interpolate_nurbs_cross_sections_by_control_range(point_settings, points, settings, global_point_idx, sample_t, is_cyclic):
    num_points = len(points)
    if num_points < 2:
        return []
    span_count = num_points if is_cyclic else num_points - 1
    span_pos = sample_t * span_count
    idx0 = int(math.floor(span_pos))
    local_t = span_pos - idx0
    if not is_cyclic and idx0 >= span_count:
        idx0 = span_count - 1
        local_t = 1.0
    idx1 = (idx0 + 1) % num_points
    idx_prev = (idx0 - 1) % num_points if is_cyclic or idx0 > 0 else idx0
    idx_next = (idx1 + 1) % num_points if is_cyclic or idx1 < num_points - 1 else idx1
    ps_prev = get_point_setting(point_settings, global_point_idx + idx_prev, settings)
    ps0 = get_point_setting(point_settings, global_point_idx + idx0, settings)
    ps1 = get_point_setting(point_settings, global_point_idx + idx1, settings)
    ps_next = get_point_setting(point_settings, global_point_idx + idx_next, settings)
    return interpolate_cross_sections_smooth(
        ps_prev, ps0, ps1, ps_next, local_t,
        points[idx_prev], points[idx0], points[idx1], points[idx_next],
        settings.transition_mode, settings.transition_strength
    )


def safe_normalized(vector, fallback=None):
    if vector.length >= 1e-8:
        return vector.normalized()
    if fallback is not None and fallback.length >= 1e-8:
        return fallback.normalized()
    return Vector((0, 0, 1))


def average_tangents(prev_tangent, next_tangent):
    prev_dir = safe_normalized(prev_tangent)
    next_dir = safe_normalized(next_tangent, prev_dir)
    averaged = prev_dir + next_dir
    if averaged.length < 1e-8:
        return next_dir
    return averaged.normalized()


def get_bezier_control_tangent(points, idx, is_cyclic):
    num_points = len(points)
    point = points[idx]
    prev_tangent = None
    next_tangent = None

    if is_cyclic or idx > 0:
        prev_tangent = point['co'] - point['handle_left']
        if prev_tangent.length < 1e-8:
            prev_idx = (idx - 1) % num_points
            prev_tangent = point['co'] - points[prev_idx]['co']
    if is_cyclic or idx < num_points - 1:
        next_tangent = point['handle_right'] - point['co']
        if next_tangent.length < 1e-8:
            next_idx = (idx + 1) % num_points
            next_tangent = points[next_idx]['co'] - point['co']

    if prev_tangent is not None and next_tangent is not None:
        return average_tangents(prev_tangent, next_tangent)
    if next_tangent is not None:
        return safe_normalized(next_tangent)
    if prev_tangent is not None:
        return safe_normalized(prev_tangent)
    return Vector((0, 0, 1))


def get_poly_control_tangent(points, idx, is_cyclic):
    num_points = len(points)
    point = points[idx]['co']
    prev_tangent = None
    next_tangent = None

    if is_cyclic or idx > 0:
        prev_idx = (idx - 1) % num_points
        prev_tangent = point - points[prev_idx]['co']
    if is_cyclic or idx < num_points - 1:
        next_idx = (idx + 1) % num_points
        next_tangent = points[next_idx]['co'] - point

    if prev_tangent is not None and next_tangent is not None:
        return average_tangents(prev_tangent, next_tangent)
    if next_tangent is not None:
        return safe_normalized(next_tangent)
    if prev_tangent is not None:
        return safe_normalized(prev_tangent)
    return Vector((0, 0, 1))


def get_cross_section_frame(tangent):
    tangent = safe_normalized(tangent)
    up = Vector((0, 0, 1))
    if abs(tangent.dot(up)) > 0.999:
        up = Vector((1, 0, 0))
    normal = tangent.cross(up).normalized()
    binormal = tangent.cross(normal).normalized()
    return normal, binormal


def catmull_rom_value(v0, v1, v2, v3, t):
    t2 = t * t
    t3 = t2 * t
    return 0.5 * (
        (2.0 * v1)
        + (-v0 + v2) * t
        + (2.0 * v0 - 5.0 * v1 + 4.0 * v2 - v3) * t2
        + (-v0 + 3.0 * v1 - 3.0 * v2 + v3) * t3
    )


def ease_value(v0, v1, t):
    t = max(0.0, min(1.0, t))
    eased_t = t * t * (3.0 - 2.0 * t)
    return v0 * (1.0 - eased_t) + v1 * eased_t


def lerp_value(v0, v1, t):
    return v0 * (1.0 - t) + v1 * t


def mix_value(a, b, factor):
    factor = max(0.0, min(1.0, factor))
    return a * (1.0 - factor) + b * factor


def monotone_tangent(prev_value, value, next_value):
    left = value - prev_value
    right = next_value - value
    if left * right <= 0.0:
        return 0.0
    tangent = 0.5 * (left + right)
    limit = 2.0 * min(abs(left), abs(right))
    return max(-limit, min(limit, tangent))


def hermite_value(v0, v1, m0, m1, t):
    t2 = t * t
    t3 = t2 * t
    h00 = 2.0 * t3 - 3.0 * t2 + 1.0
    h10 = t3 - 2.0 * t2 + t
    h01 = -2.0 * t3 + 3.0 * t2
    h11 = t3 - t2
    return h00 * v0 + h10 * m0 + h01 * v1 + h11 * m1


def interpolate_section_value(prev_value, value0, value1, next_value, t, mode, strength):
    t = max(0.0, min(1.0, t))
    linear = lerp_value(value0, value1, t)
    if mode == 'LINEAR':
        return linear
    if mode == 'EASE':
        return mix_value(linear, ease_value(value0, value1, t), strength)

    m0 = monotone_tangent(prev_value, value0, value1)
    m1 = monotone_tangent(value0, value1, next_value)
    monotone = hermite_value(value0, value1, m0, m1, t)
    if mode == 'MONOTONE':
        return mix_value(linear, monotone, strength)

    catmull = catmull_rom_value(prev_value, value0, value1, next_value, t)
    if mode == 'CATMULL':
        return mix_value(linear, catmull, strength)
    if mode == 'BLEND':
        return mix_value(monotone, catmull, strength)
    return monotone


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
    """Interpolate cross-section vertex positions between two point settings"""
    verts0 = ps0.cross_section_verts
    verts1 = ps1.cross_section_verts
    n0 = len(verts0)
    n1 = len(verts1)
    if n0 == 0 or n1 == 0:
        return []

    num_verts = min(n0, n1)
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


def smooth_ring_offsets(ring_specs, iterations=2, factor=0.5, is_cyclic=False):
    if len(ring_specs) < 3:
        return ring_specs

    smoothed = list(ring_specs)
    for _ in range(max(1, iterations)):
        next_specs = list(smoothed)
        start = 0 if is_cyclic else 1
        end = len(smoothed) if is_cyclic else len(smoothed) - 1
        for i in range(start, end):
            prev_spec = smoothed[(i - 1) % len(smoothed)]
            center, tangent, offsets = smoothed[i]
            next_spec = smoothed[(i + 1) % len(smoothed)]
            prev_offsets = prev_spec[2]
            next_offsets = next_spec[2]
            if not offsets or not prev_offsets or not next_offsets:
                continue
            count = min(len(offsets), len(prev_offsets), len(next_offsets))
            new_offsets = []
            for j in range(count):
                ox, oy = offsets[j]
                px, py = prev_offsets[j]
                nx, ny = next_offsets[j]
                avg_x = (px + nx) * 0.5
                avg_y = (py + ny) * 0.5
                new_offsets.append((
                    ox * (1.0 - factor) + avg_x * factor,
                    oy * (1.0 - factor) + avg_y * factor,
                ))
            next_specs[i] = (center, tangent, new_offsets)
        smoothed = next_specs
    return smoothed


def make_ring_from_frame(center, normal, binormal, interp_offsets):
    verts = []
    for rx, ry in interp_offsets:
        point = center + normal * rx + binormal * ry
        verts.append(point)
    return verts


def make_ring_from_interpolated(center, tangent, interp_offsets):
    normal, binormal = get_cross_section_frame(tangent)
    return make_ring_from_frame(center, normal, binormal, interp_offsets)


def build_minimal_twist_rings(ring_specs, is_cyclic=False):
    if not ring_specs:
        return []

    rings = []
    first_center, first_tangent, first_offsets = ring_specs[0]
    tangent = safe_normalized(first_tangent)
    normal, binormal = get_cross_section_frame(tangent)

    if first_offsets:
        rings.append(make_ring_from_frame(first_center, normal, binormal, first_offsets))
    else:
        rings.append([first_center])

    prev_tangent = tangent
    for center, raw_tangent, offsets in ring_specs[1:]:
        tangent = safe_normalized(raw_tangent, prev_tangent)
        if prev_tangent.length >= 1e-8 and tangent.length >= 1e-8:
            try:
                transport = prev_tangent.rotation_difference(tangent)
                normal = transport @ normal
            except ValueError:
                pass
        normal = normal - tangent * normal.dot(tangent)
        if normal.length < 1e-8:
            normal, binormal = get_cross_section_frame(tangent)
        else:
            normal.normalize()
            binormal = tangent.cross(normal).normalized()
        if offsets:
            rings.append(make_ring_from_frame(center, normal, binormal, offsets))
        else:
            rings.append([center])
        prev_tangent = tangent

    return rings


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


def init_cross_section_circle(point_setting, radius, segments):
    point_setting.cross_section_verts.clear()
    for i in range(segments):
        angle = 2.0 * math.pi * i / segments
        v = point_setting.cross_section_verts.add()
        v.offset_x = math.cos(angle) * radius
        v.offset_y = math.sin(angle) * radius
        v.is_ghost = False


def catmull_rom_2d(p0, p1, p2, p3, t):
    t2 = t * t
    t3 = t2 * t
    x = 0.5 * (
        2.0 * p1[0]
        + (-p0[0] + p2[0]) * t
        + (2.0 * p0[0] - 5.0 * p1[0] + 4.0 * p2[0] - p3[0]) * t2
        + (-p0[0] + 3.0 * p1[0] - 3.0 * p2[0] + p3[0]) * t3
    )
    y = 0.5 * (
        2.0 * p1[1]
        + (-p0[1] + p2[1]) * t
        + (2.0 * p0[1] - 5.0 * p1[1] + 4.0 * p2[1] - p3[1]) * t2
        + (-p0[1] + 3.0 * p1[1] - 3.0 * p2[1] + p3[1]) * t3
    )
    return x, y


def update_ghost_vertices(point_setting):
    verts = point_setting.cross_section_verts
    count = len(verts)
    if count < 3:
        return
    real_indices = [i for i, v in enumerate(verts) if not getattr(v, 'is_ghost', False)]
    real_count = len(real_indices)
    if real_count < 2:
        return
    for real_pos, start_idx in enumerate(real_indices):
        end_idx = real_indices[(real_pos + 1) % real_count]
        gap = (end_idx - start_idx - 1) % count
        if gap <= 0:
            continue
        prev_idx = real_indices[(real_pos - 1) % real_count]
        next_idx = real_indices[(real_pos + 2) % real_count]
        p0 = (verts[prev_idx].offset_x, verts[prev_idx].offset_y)
        p1 = (verts[start_idx].offset_x, verts[start_idx].offset_y)
        p2 = (verts[end_idx].offset_x, verts[end_idx].offset_y)
        p3 = (verts[next_idx].offset_x, verts[next_idx].offset_y)
        for step in range(1, gap + 1):
            ghost_idx = (start_idx + step) % count
            ghost_vert = verts[ghost_idx]
            if not getattr(ghost_vert, 'is_ghost', False):
                continue
            t = step / (gap + 1)
            ghost_vert.offset_x, ghost_vert.offset_y = catmull_rom_2d(p0, p1, p2, p3, t)


def update_all_ghost_vertices(settings):
    for point_setting in settings.point_settings:
        update_ghost_vertices(point_setting)


def add_cross_section_vertex_after(point_setting, idx, is_ghost=False):
    csv = point_setting.cross_section_verts
    n = len(csv)
    if n < 2:
        return False
    idx = max(0, min(idx, n - 1))
    idx_next = (idx + 1) % n
    v = csv.add()
    v.offset_x = (csv[idx].offset_x + csv[idx_next].offset_x) * 0.5
    v.offset_y = (csv[idx].offset_y + csv[idx_next].offset_y) * 0.5
    v.is_ghost = is_ghost
    target = idx + 1
    for i in range(len(csv) - 1, target, -1):
        csv.move(i, i - 1)
    point_setting.active_vert_index = target
    return True


def add_cross_section_vertex_after_all(settings, idx):
    active_idx = min(settings.active_point_index, len(settings.point_settings) - 1)
    for point_idx, point_setting in enumerate(settings.point_settings):
        add_cross_section_vertex_after(point_setting, idx, point_idx != active_idx)


def remove_cross_section_vertex_all(settings, idx):
    if any(len(point_setting.cross_section_verts) <= 3 for point_setting in settings.point_settings):
        return False
    for point_setting in settings.point_settings:
        csv = point_setting.cross_section_verts
        remove_idx = max(0, min(idx, len(csv) - 1))
        csv.remove(remove_idx)
        point_setting.active_vert_index = min(remove_idx, len(csv) - 1)
    return True


def normalize_cross_section_topology(settings):
    if len(settings.point_settings) == 0:
        return
    active_idx = min(settings.active_point_index, len(settings.point_settings) - 1)
    target_count = len(settings.point_settings[active_idx].cross_section_verts)
    if target_count < 3:
        return

    for point_setting in settings.point_settings:
        csv = point_setting.cross_section_verts
        while len(csv) < target_count and len(csv) >= 2:
            insert_idx = max(0, len(csv) - 1)
            add_cross_section_vertex_after(point_setting, insert_idx)
        while len(csv) > target_count and len(csv) > 3:
            csv.remove(len(csv) - 1)
        if point_setting.active_vert_index >= len(csv):
            point_setting.active_vert_index = len(csv) - 1


def generate_pipe_mesh(curve_obj, settings):
    update_all_ghost_vertices(settings)
    splines_data = get_curve_points_data(curve_obj)
    if not splines_data:
        return None, None

    all_verts = []
    all_faces = []
    vert_offset = 0
    point_settings = settings.point_settings
    global_point_idx = 0

    for spline_data in splines_data:
        points = spline_data['points']
        resolution = max(1, settings.pipe_resolution)
        is_cyclic = spline_data['cyclic']
        num_points = len(points)
        if num_points < 2:
            global_point_idx += num_points
            continue

        ring_specs = []
        if spline_data['type'] == 'BEZIER':
            seg_count = num_points if is_cyclic else num_points - 1
            for seg_idx in range(seg_count):
                idx0 = seg_idx
                idx1 = (seg_idx + 1) % num_points
                p0 = points[idx0]['co']
                h0r = points[idx0]['handle_right']
                h1l = points[idx1]['handle_left']
                p1 = points[idx1]['co']
                ps0 = get_point_setting(point_settings, global_point_idx + idx0, settings)
                ps1 = get_point_setting(point_settings, global_point_idx + idx1, settings)
                idx_prev = (idx0 - 1) % num_points if is_cyclic or idx0 > 0 else idx0
                idx_next = (idx1 + 1) % num_points if is_cyclic or idx1 < num_points - 1 else idx1
                ps_prev = get_point_setting(point_settings, global_point_idx + idx_prev, settings)
                ps_next = get_point_setting(point_settings, global_point_idx + idx_next, settings)
                steps = max(1, resolution)
                end_inc = 1 if (seg_idx == seg_count - 1 and not is_cyclic) else 0
                for step in range(steps + end_inc):
                    t = step / steps
                    pos = evaluate_bezier_segment(p0, h0r, h1l, p1, t)
                    tan0 = get_bezier_control_tangent(points, idx0, is_cyclic)
                    tan1 = get_bezier_control_tangent(points, idx1, is_cyclic)
                    tan = safe_normalized(tan0.lerp(tan1, t), evaluate_bezier_tangent(p0, h0r, h1l, p1, t))
                    interp = interpolate_cross_sections_smooth(
                        ps_prev, ps0, ps1, ps_next, t,
                        points[idx_prev], points[idx0], points[idx1], points[idx_next],
                        settings.transition_mode, settings.transition_strength
                    )
                    ring_specs.append((pos, tan, interp))
        elif spline_data['type'] == 'NURBS':
            order = max(2, min(spline_data.get('order_u', 4), num_points))
            degree = order - 1
            use_endpoint = spline_data.get('use_endpoint_u', False)
            knots = make_nurbs_knot_vector(num_points, degree, is_cyclic, use_endpoint)
            u_start, u_end = get_nurbs_domain(num_points, degree, knots, is_cyclic)
            sample_count = max(2, (num_points if is_cyclic else num_points - 1) * max(4, resolution * 2))
            ring_count = sample_count if is_cyclic else sample_count + 1
            u_range = u_end - u_start
            centers = []
            interp_offsets = []

            for sample_idx in range(ring_count):
                if is_cyclic:
                    t = sample_idx / ring_count
                else:
                    t = sample_idx / (ring_count - 1)
                u = u_start + u_range * t
                if is_cyclic and sample_idx == ring_count - 1:
                    u = u_end - 1e-8

                weighted, total = get_nurbs_weighted_controls(points, degree, u, knots, is_cyclic)
                centers.append(evaluate_nurbs_from_weighted(points, weighted, total))
                interp_offsets.append(interpolate_nurbs_cross_sections_by_control_range(
                    point_settings, points, settings, global_point_idx, t, is_cyclic
                ))

            for sample_idx, pos in enumerate(centers):
                if is_cyclic:
                    prev_pos = centers[(sample_idx - 1) % ring_count]
                    next_pos = centers[(sample_idx + 1) % ring_count]
                else:
                    prev_pos = centers[max(0, sample_idx - 1)]
                    next_pos = centers[min(ring_count - 1, sample_idx + 1)]
                tan = safe_normalized(next_pos - prev_pos)
                interp = interp_offsets[sample_idx]
                ring_specs.append((pos, tan, interp))
        elif spline_data['type'] == 'POLY':
            seg_count = num_points if is_cyclic else num_points - 1
            for seg_idx in range(seg_count):
                idx0 = seg_idx
                idx1 = (seg_idx + 1) % num_points
                p0 = points[idx0]['co']
                p1 = points[idx1]['co']
                ps0 = get_point_setting(point_settings, global_point_idx + idx0, settings)
                ps1 = get_point_setting(point_settings, global_point_idx + idx1, settings)
                idx_prev = (idx0 - 1) % num_points if is_cyclic or idx0 > 0 else idx0
                idx_next = (idx1 + 1) % num_points if is_cyclic or idx1 < num_points - 1 else idx1
                ps_prev = get_point_setting(point_settings, global_point_idx + idx_prev, settings)
                ps_next = get_point_setting(point_settings, global_point_idx + idx_next, settings)
                steps = max(1, resolution)
                end_inc = 1 if (seg_idx == seg_count - 1 and not is_cyclic) else 0
                for step in range(steps + end_inc):
                    t = step / steps
                    pos = p0.lerp(p1, t)
                    tan0 = get_poly_control_tangent(points, idx0, is_cyclic)
                    tan1 = get_poly_control_tangent(points, idx1, is_cyclic)
                    tan = safe_normalized(tan0.lerp(tan1, t), p1 - p0)
                    interp = interpolate_cross_sections_smooth(
                        ps_prev, ps0, ps1, ps_next, t,
                        points[idx_prev], points[idx0], points[idx1], points[idx_next],
                        settings.transition_mode, settings.transition_strength
                    )
                    ring_specs.append((pos, tan, interp))

        if settings.strong_smoothing:
            ring_specs = smooth_ring_offsets(
                ring_specs,
                settings.strong_smoothing_iterations,
                0.45,
                is_cyclic,
            )

        rings = build_minimal_twist_rings(ring_specs, is_cyclic)
        global_point_idx += num_points
        if not rings:
            continue

        segments = len(rings[0])
        for ring in rings:
            all_verts.extend(ring)
        num_rings = len(rings)
        ring_count = num_rings if is_cyclic else num_rings - 1
        for i in range(ring_count):
            i_next = (i + 1) % num_rings
            for j in range(segments):
                j_next = (j + 1) % segments
                v0 = vert_offset + i * segments + j
                v1 = vert_offset + i * segments + j_next
                v2 = vert_offset + i_next * segments + j_next
                v3 = vert_offset + i_next * segments + j
                all_faces.append((v0, v1, v2, v3))
        if settings.cap_ends and not is_cyclic and num_rings > 0:
            cap_s = list(range(vert_offset, vert_offset + segments))
            cap_e = list(range(vert_offset + (num_rings-1)*segments, vert_offset + num_rings*segments))
            all_faces.append(tuple(reversed(cap_s)))
            all_faces.append(tuple(cap_e))
        vert_offset += num_rings * segments

    return all_verts, all_faces


def sync_point_settings(curve_obj):
    settings = curve_obj.hair_pipe_settings
    total_points = 0
    for spline in curve_obj.data.splines:
        if spline.type == 'BEZIER':
            total_points += len(spline.bezier_points)
        else:
            total_points += len(spline.points)
    current = len(settings.point_settings)
    if current < total_points:
        template = settings.point_settings[settings.active_point_index] if current > 0 else None
        for _ in range(total_points - current):
            ps = settings.point_settings.add()
            ps.scale = 1.0
            ps.rotation = 0.0
            if template is not None and len(template.cross_section_verts) > 0:
                for sv in template.cross_section_verts:
                    v = ps.cross_section_verts.add()
                    v.offset_x = sv.offset_x
                    v.offset_y = sv.offset_y
                    v.is_ghost = getattr(sv, 'is_ghost', False)
            else:
                init_cross_section_circle(ps, settings.default_radius, settings.default_segments)
    elif current > total_points:
        for _ in range(current - total_points):
            settings.point_settings.remove(len(settings.point_settings) - 1)

    if total_points > 0 and settings.active_point_index >= total_points:
        settings.active_point_index = total_points - 1
    normalize_cross_section_topology(settings)
    update_all_ghost_vertices(settings)


def is_curve_edit_mode(curve_obj):
    return getattr(curve_obj, 'mode', '') in {'EDIT', 'EDIT_CURVE'}


def get_selected_curve_point_index(curve_obj):
    if curve_obj is None or curve_obj.type != 'CURVE':
        return None

    if is_curve_edit_mode(curve_obj):
        try:
            curve_obj.update_from_editmode()
        except Exception:
            pass

    selected_index = None
    global_point_idx = 0
    for spline in curve_obj.data.splines:
        if spline.type == 'BEZIER':
            for point in spline.bezier_points:
                if point.select_control_point:
                    selected_index = global_point_idx
                global_point_idx += 1
        else:
            for point in spline.points:
                if point.select:
                    selected_index = global_point_idx
                global_point_idx += 1

    return selected_index


def get_selected_curve_point_indices(curve_obj):
    if curve_obj is None or curve_obj.type != 'CURVE':
        return []

    if is_curve_edit_mode(curve_obj):
        try:
            curve_obj.update_from_editmode()
        except Exception:
            pass

    selected = []
    global_point_idx = 0
    for spline in curve_obj.data.splines:
        if spline.type == 'BEZIER':
            for point in spline.bezier_points:
                if point.select_control_point:
                    selected.append(global_point_idx)
                global_point_idx += 1
        else:
            for point in spline.points:
                if point.select:
                    selected.append(global_point_idx)
                global_point_idx += 1
    return selected


def sync_active_point_from_selection(curve_obj):
    settings = curve_obj.hair_pipe_settings
    selected_index = get_selected_curve_point_index(curve_obj)
    if selected_index is None:
        return False

    sync_point_settings(curve_obj)
    if selected_index >= len(settings.point_settings):
        return False

    if settings.active_point_index != selected_index:
        settings.active_point_index = selected_index
    return True


def get_pipe_mesh_name(curve_obj):
    return curve_obj.name + "_FiguHair"


def verts_to_world_space(verts, curve_obj):
    matrix = curve_obj.matrix_world
    return [matrix @ vert for vert in verts]


def get_pipe_source_curve(pipe_obj):
    if pipe_obj is None or pipe_obj.type != 'MESH':
        return None
    source_name = pipe_obj.get("hair_pipe_source_curve")
    if not source_name:
        return None
    curve_obj = bpy.data.objects.get(source_name)
    if curve_obj is not None and curve_obj.type == 'CURVE':
        return curve_obj
    return None


def get_context_curve_object(context):
    candidates = (
        getattr(context, 'object', None),
        getattr(context, 'active_object', None),
        getattr(getattr(context, 'view_layer', None), 'objects', None).active
        if getattr(context, 'view_layer', None) is not None else None,
    )

    for obj in candidates:
        if obj is None:
            continue
        if obj.type == 'CURVE':
            return obj
        source_curve = get_pipe_source_curve(obj)
        if source_curve is not None:
            return source_curve

    for obj in getattr(context, 'selected_objects', ()):
        if obj.type == 'CURVE':
            return obj
        source_curve = get_pipe_source_curve(obj)
        if source_curve is not None:
            return source_curve

    return None


def configure_pipe_object(pipe_obj, curve_obj):
    pipe_obj["hair_pipe_source_curve"] = curve_obj.name
    pipe_obj.parent = None
    pipe_obj.matrix_parent_inverse.identity()
    pipe_obj.matrix_world = Matrix.Identity(4)
    pipe_obj.show_in_front = False
    pipe_obj.hide_select = False
    pipe_obj.select_set(False)


def redirect_pipe_selection(context, pipe_obj=None):
    pipe_obj = pipe_obj or context.active_object
    curve_obj = get_pipe_source_curve(pipe_obj)
    if curve_obj is None:
        return False

    if not curve_obj.hair_pipe_settings.redirect_selection:
        return False

    if context.view_layer.objects.get(curve_obj.name) is None:
        return False

    if context.mode != 'OBJECT':
        return False

    for obj in context.selected_objects:
        obj.select_set(False)
    curve_obj.hide_set(False)
    curve_obj.select_set(True)
    context.view_layer.objects.active = curve_obj
    return True


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


def lerp_angle(a, b, t):
    delta = (b - a + 180.0) % 360.0 - 180.0
    return a + delta * t


def lerp_radians(a, b, t):
    delta = (b - a + math.pi) % (2.0 * math.pi) - math.pi
    return a + delta * t


def rebuild_cross_section_between(curve_obj, settings, start_idx, end_idx, mode, power, blend):
    if start_idx == end_idx:
        return 0
    if start_idx > end_idx:
        start_idx, end_idx = end_idx, start_idx
    if end_idx - start_idx < 2:
        return 0

    start_ps = settings.point_settings[start_idx]
    end_ps = settings.point_settings[end_idx]
    start_curve_point = get_curve_point_by_global_index(curve_obj, start_idx)
    end_curve_point = get_curve_point_by_global_index(curve_obj, end_idx)
    start_radius = getattr(start_curve_point, 'radius', 1.0) if start_curve_point is not None else 1.0
    end_radius = getattr(end_curve_point, 'radius', 1.0) if end_curve_point is not None else 1.0
    start_tilt = getattr(start_curve_point, 'tilt', 0.0) if start_curve_point is not None else 0.0
    end_tilt = getattr(end_curve_point, 'tilt', 0.0) if end_curve_point is not None else 0.0
    count = min(len(start_ps.cross_section_verts), len(end_ps.cross_section_verts))
    if count < 3:
        return 0

    blend = max(0.0, min(1.0, blend))
    changed = 0
    span = end_idx - start_idx
    for point_idx in range(start_idx + 1, end_idx):
        ps = settings.point_settings[point_idx]
        while len(ps.cross_section_verts) < count:
            v = ps.cross_section_verts.add()
            v.offset_x = 0.0
            v.offset_y = 0.0
            v.is_ghost = False
        while len(ps.cross_section_verts) > count and len(ps.cross_section_verts) > 3:
            ps.cross_section_verts.remove(len(ps.cross_section_verts) - 1)
        raw_t = (point_idx - start_idx) / span
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
        curve_point = get_curve_point_by_global_index(curve_obj, point_idx)
        if curve_point is not None:
            target_radius = start_radius * (1.0 - t) + end_radius * t
            target_tilt = lerp_radians(start_tilt, end_tilt, t)
            curve_point.radius = curve_point.radius * (1.0 - blend) + target_radius * blend
            curve_point.tilt = curve_point.tilt * (1.0 - blend) + target_tilt * blend
        if ps.active_vert_index >= len(ps.cross_section_verts):
            ps.active_vert_index = len(ps.cross_section_verts) - 1
        changed += 1
    return changed


class HAIRPIPE_OT_generate_pipe(bpy.types.Operator):
    """Generate pipe mesh from curve with per-point custom cross-sections"""
    bl_idname = "hair_pipe.generate_pipe"
    bl_label = "Generate Hair Pipe"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return get_context_curve_object(context) is not None

    def execute(self, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            self.report({'ERROR'}, "Select a curve or its FiguHair preview mesh")
            return {'CANCELLED'}
        settings = curve_obj.hair_pipe_settings
        ensure_curve_defaults(curve_obj)
        sync_point_settings(curve_obj)
        verts, faces = generate_pipe_mesh(curve_obj, settings)
        if verts is None:
            self.report({'ERROR'}, "Could not generate pipe from curve")
            return {'CANCELLED'}
        verts = verts_to_world_space(verts, curve_obj)
        mesh_name = get_pipe_mesh_name(curve_obj)
        existing_obj = bpy.data.objects.get(mesh_name)
        if existing_obj:
            mesh = existing_obj.data
            mesh.clear_geometry()
            mesh.from_pydata(verts, [], faces)
            mesh.update()
            pipe_obj = existing_obj
        else:
            mesh = bpy.data.meshes.new(mesh_name)
            mesh.from_pydata(verts, [], faces)
            mesh.update()
            pipe_obj = bpy.data.objects.new(mesh_name, mesh)
            context.collection.objects.link(pipe_obj)
        if settings.smooth_shading:
            for poly in mesh.polygons:
                poly.use_smooth = True
        configure_pipe_object(pipe_obj, curve_obj)
        self.report({'INFO'}, f"Generated pipe with {len(verts)} vertices")
        return {'FINISHED'}


class HAIRPIPE_OT_sync_points(bpy.types.Operator):
    """Sync point settings with curve control points"""
    bl_idname = "hair_pipe.sync_points"
    bl_label = "Sync Point Settings"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'CURVE'

    def execute(self, context):
        sync_point_settings(context.active_object)
        self.report({'INFO'}, "Point settings synced")
        return {'FINISHED'}


class HAIRPIPE_OT_apply_edge_flow(bpy.types.Operator):
    """Rebuild intermediate cross-sections between exactly two selected curve control points"""
    bl_idname = "hair_pipe.apply_edge_flow"
    bl_label = "Apply Edge Flow"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        name="模式",
        description="How intermediate cross-sections are rebuilt",
        items=(
            ('LINEAR', "线性", "Even transition from first selected section to second selected section"),
            ('EASE', "缓入缓出", "Smoothstep transition"),
            ('SMOOTHER', "强平滑", "Smoother S-curve transition"),
            ('START', "偏向起点", "Stay closer to the first selected section for longer"),
            ('END', "偏向终点", "Move toward the second selected section earlier"),
            ('SINE', "正弦", "Soft sine based transition"),
        ),
        default='SMOOTHER',
    )
    power: FloatProperty(
        name="偏向强度",
        description="Controls bias strength for start/end weighted modes",
        default=2.0,
        min=0.1,
        max=8.0,
        precision=2,
    )
    blend: FloatProperty(
        name="重建强度",
        description="How strongly intermediate sections are replaced by the rebuilt transition",
        default=1.0,
        min=0.0,
        max=1.0,
        precision=3,
    )

    @classmethod
    def poll(cls, context):
        obj = get_context_curve_object(context)
        return obj is not None and obj.type == 'CURVE'

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "mode")
        if self.mode in {'START', 'END'}:
            layout.prop(self, "power")
        layout.prop(self, "blend")

    def execute(self, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            self.report({'ERROR'}, "Select a curve or its FiguHair preview mesh")
            return {'CANCELLED'}
        if not is_curve_edit_mode(curve_obj):
            self.report({'ERROR'}, "Enter curve Edit Mode and select exactly two control points")
            return {'CANCELLED'}

        sync_point_settings(curve_obj)
        selected = get_selected_curve_point_indices(curve_obj)
        if len(selected) != 2:
            self.report({'ERROR'}, "Select exactly two curve control points")
            return {'CANCELLED'}

        settings = curve_obj.hair_pipe_settings
        settings.edge_flow_mode = self.mode
        settings.edge_flow_power = self.power
        settings.edge_flow_blend = self.blend
        start_idx, end_idx = sorted(selected)
        if end_idx >= len(settings.point_settings):
            self.report({'ERROR'}, "Selected point index is out of range")
            return {'CANCELLED'}
        changed = rebuild_cross_section_between(
            curve_obj, settings, start_idx, end_idx, self.mode, self.power, self.blend
        )
        if changed <= 0:
            self.report({'ERROR'}, "Selected points must have at least one point between them")
            return {'CANCELLED'}
        settings.active_point_index = end_idx
        update_all_ghost_vertices(settings)
        self.report({'INFO'}, f"Rebuilt {changed} intermediate cross-sections")
        return {'FINISHED'}


class HAIRPIPE_OT_reset_cross_section(bpy.types.Operator):
    """Reset active point's cross-section to a circle"""
    bl_idname = "hair_pipe.reset_cross_section"
    bl_label = "Reset to Circle"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE':
            return False
        s = obj.hair_pipe_settings
        return s.active_point_index < len(s.point_settings)

    def execute(self, context):
        settings = context.active_object.hair_pipe_settings
        ps = settings.point_settings[settings.active_point_index]
        init_cross_section_circle(ps, settings.default_radius, settings.default_segments)
        ps.scale = 1.0
        ps.rotation = 0.0
        return {'FINISHED'}


class HAIRPIPE_OT_reset_all_cross_sections(bpy.types.Operator):
    """Reset ALL points' cross-sections to circles"""
    bl_idname = "hair_pipe.reset_all_cross_sections"
    bl_label = "Reset All to Circle"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'CURVE'

    def execute(self, context):
        settings = context.active_object.hair_pipe_settings
        for ps in settings.point_settings:
            init_cross_section_circle(ps, settings.default_radius, settings.default_segments)
            ps.scale = 1.0
            ps.rotation = 0.0
        return {'FINISHED'}


class HAIRPIPE_OT_taper_linear(bpy.types.Operator):
    """Apply linear taper from root to tip"""
    bl_idname = "hair_pipe.taper_linear"
    bl_label = "Linear Taper"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'CURVE'

    def execute(self, context):
        curve_obj = context.active_object
        settings = curve_obj.hair_pipe_settings
        sync_point_settings(curve_obj)
        num = len(settings.point_settings)
        if num < 2:
            return {'CANCELLED'}
        for i, ps in enumerate(settings.point_settings):
            ps.scale = 1.0 - (i / (num - 1)) * 0.95
        self.report({'INFO'}, "Applied linear taper")
        return {'FINISHED'}


class HAIRPIPE_OT_add_cs_vert(bpy.types.Operator):
    """Add a vertex to the active point's cross-section"""
    bl_idname = "hair_pipe.add_cs_vert"
    bl_label = "Add Vertex"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE':
            return False
        s = obj.hair_pipe_settings
        return s.active_point_index < len(s.point_settings)

    def execute(self, context):
        settings = context.active_object.hair_pipe_settings
        ps = settings.point_settings[settings.active_point_index]
        csv = ps.cross_section_verts
        n = len(csv)
        if n < 2:
            for point_idx, point_setting in enumerate(settings.point_settings):
                v = point_setting.cross_section_verts.add()
                v.offset_x = settings.default_radius
                v.offset_y = 0.0
                v.is_ghost = point_idx != settings.active_point_index
                point_setting.active_vert_index = len(point_setting.cross_section_verts) - 1
        else:
            add_cross_section_vertex_after_all(settings, ps.active_vert_index)
        update_all_ghost_vertices(settings)
        return {'FINISHED'}


class HAIRPIPE_OT_remove_cs_vert(bpy.types.Operator):
    """Remove the active vertex from the cross-section"""
    bl_idname = "hair_pipe.remove_cs_vert"
    bl_label = "Remove Vertex"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE':
            return False
        s = obj.hair_pipe_settings
        if s.active_point_index >= len(s.point_settings):
            return False
        return all(len(ps.cross_section_verts) > 3 for ps in s.point_settings)

    def execute(self, context):
        settings = context.active_object.hair_pipe_settings
        ps = settings.point_settings[settings.active_point_index]
        remove_cross_section_vertex_all(settings, ps.active_vert_index)
        return {'FINISHED'}


class HAIRPIPE_OT_select_point(bpy.types.Operator):
    """Select a control point for editing"""
    bl_idname = "hair_pipe.select_point"
    bl_label = "Select Point"
    point_index: IntProperty()

    def execute(self, context):
        context.active_object.hair_pipe_settings.active_point_index = self.point_index
        return {'FINISHED'}


def copy_point_cross_section(src, dst, rotation_offset=0.0):
    dst.cross_section_verts.clear()
    angle = math.radians(rotation_offset)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    for sv in src.cross_section_verts:
        v = dst.cross_section_verts.add()
        x = sv.offset_x
        y = sv.offset_y
        v.offset_x = x * cos_a - y * sin_a
        v.offset_y = x * sin_a + y * cos_a
        v.is_ghost = getattr(sv, 'is_ghost', False)
    dst.active_vert_index = min(src.active_vert_index, max(0, len(dst.cross_section_verts) - 1))
    dst.scale = src.scale
    dst.rotation = src.rotation


_HAIRPIPE_CROSS_SECTION_CLIPBOARD = None


class HAIRPIPE_OT_copy_cross_section(bpy.types.Operator):
    """Copy the active point cross-section to the FiguHair clipboard"""
    bl_idname = "hair_pipe.copy_cross_section"
    bl_label = "复制横截面"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE':
            return False
        s = obj.hair_pipe_settings
        return s.active_point_index < len(s.point_settings)

    def execute(self, context):
        global _HAIRPIPE_CROSS_SECTION_CLIPBOARD
        settings = context.active_object.hair_pipe_settings
        src = settings.point_settings[settings.active_point_index]
        _HAIRPIPE_CROSS_SECTION_CLIPBOARD = {
            "verts": [
                (v.offset_x, v.offset_y, getattr(v, 'is_ghost', False))
                for v in src.cross_section_verts
            ],
            "scale": src.scale,
            "rotation": src.rotation,
            "active_vert_index": src.active_vert_index,
        }
        self.report({'INFO'}, "已复制横截面")
        return {'FINISHED'}


class HAIRPIPE_OT_paste_cross_section(bpy.types.Operator):
    """Paste the copied cross-section to active or selected curve points"""
    bl_idname = "hair_pipe.paste_cross_section"
    bl_label = "粘贴横截面"
    bl_options = {'REGISTER', 'UNDO'}

    rotation_offset: FloatProperty(
        name="粘贴后旋转",
        description="Rotate pasted cross-section around its center in degrees",
        default=0.0,
        min=-360.0,
        max=360.0,
        precision=2,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE':
            return False
        if _HAIRPIPE_CROSS_SECTION_CLIPBOARD is None:
            return False
        s = obj.hair_pipe_settings
        return s.active_point_index < len(s.point_settings)

    def draw(self, context):
        self.layout.prop(self, "rotation_offset")

    def execute(self, context):
        settings = context.active_object.hair_pipe_settings
        sync_point_settings(context.active_object)
        selected = get_selected_curve_point_indices(context.active_object) if is_curve_edit_mode(context.active_object) else []
        target_indices = selected if selected else [settings.active_point_index]
        target_indices = [idx for idx in target_indices if idx < len(settings.point_settings)]
        if not target_indices:
            return {'CANCELLED'}

        class ClipboardPointSetting:
            pass

        src = ClipboardPointSetting()
        src.cross_section_verts = []
        for x, y, is_ghost in _HAIRPIPE_CROSS_SECTION_CLIPBOARD["verts"]:
            class ClipboardVert:
                pass
            v = ClipboardVert()
            v.offset_x = x
            v.offset_y = y
            v.is_ghost = is_ghost
            src.cross_section_verts.append(v)
        src.scale = _HAIRPIPE_CROSS_SECTION_CLIPBOARD["scale"]
        src.rotation = _HAIRPIPE_CROSS_SECTION_CLIPBOARD["rotation"]
        src.active_vert_index = _HAIRPIPE_CROSS_SECTION_CLIPBOARD["active_vert_index"]

        for idx in target_indices:
            copy_point_cross_section(src, settings.point_settings[idx], self.rotation_offset)
        update_all_ghost_vertices(settings)
        self.report({'INFO'}, f"已粘贴到 {len(target_indices)} 个曲线点")
        return {'FINISHED'}


class HAIRPIPE_OT_copy_cs_to_all(bpy.types.Operator):
    """Copy active point's cross-section to all other points"""
    bl_idname = "hair_pipe.copy_cs_to_all"
    bl_label = "Copy to All Points"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE':
            return False
        s = obj.hair_pipe_settings
        return s.active_point_index < len(s.point_settings)

    def execute(self, context):
        settings = context.active_object.hair_pipe_settings
        src = settings.point_settings[settings.active_point_index]
        for i, ps in enumerate(settings.point_settings):
            if i == settings.active_point_index:
                continue
            copy_point_cross_section(src, ps)
        update_all_ghost_vertices(settings)
        self.report({'INFO'}, "Cross-section copied to all points")
        return {'FINISHED'}


classes = (
    HAIRPIPE_OT_generate_pipe,
    HAIRPIPE_OT_sync_points,
    HAIRPIPE_OT_apply_edge_flow,
    HAIRPIPE_OT_reset_cross_section,
    HAIRPIPE_OT_reset_all_cross_sections,
    HAIRPIPE_OT_taper_linear,
    HAIRPIPE_OT_add_cs_vert,
    HAIRPIPE_OT_remove_cs_vert,
    HAIRPIPE_OT_select_point,
    HAIRPIPE_OT_copy_cross_section,
    HAIRPIPE_OT_paste_cross_section,
    HAIRPIPE_OT_copy_cs_to_all,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
