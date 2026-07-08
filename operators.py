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


def make_cumulative_lengths(centers, is_cyclic=False):
    if not centers:
        return []
    distances = [0.0]
    for idx in range(1, len(centers)):
        distances.append(distances[-1] + (centers[idx] - centers[idx - 1]).length)
    return distances


def find_nearest_center_distance(centers, distances, co):
    if not centers or not distances:
        return 0.0
    best_idx = 0
    best_dist = (centers[0] - co).length_squared
    for idx in range(1, len(centers)):
        dist = (centers[idx] - co).length_squared
        if dist < best_dist:
            best_idx = idx
            best_dist = dist
    return distances[best_idx]


def interpolate_cross_sections_by_anchor_distance(point_settings, points, settings, global_point_idx, anchors, distance):
    num_points = len(points)
    if num_points < 2 or not anchors:
        return []
    if distance <= anchors[0]:
        idx0 = 0
        idx1 = 1
        local_t = 0.0
    elif distance >= anchors[-1]:
        idx0 = num_points - 2
        idx1 = num_points - 1
        local_t = 1.0
    else:
        idx0 = 0
        for anchor_idx in range(len(anchors) - 1):
            if anchors[anchor_idx] <= distance <= anchors[anchor_idx + 1]:
                idx0 = anchor_idx
                break
        idx1 = idx0 + 1
        span = max(anchors[idx1] - anchors[idx0], 1e-8)
        local_t = (distance - anchors[idx0]) / span

    idx_prev = idx0 - 1 if idx0 > 0 else idx0
    idx_next = idx1 + 1 if idx1 < num_points - 1 else idx1
    ps_prev = get_effective_point_setting(point_settings, global_point_idx + idx_prev, settings)
    ps0 = get_effective_point_setting(point_settings, global_point_idx + idx0, settings)
    ps1 = get_effective_point_setting(point_settings, global_point_idx + idx1, settings)
    ps_next = get_effective_point_setting(point_settings, global_point_idx + idx_next, settings)
    return interpolate_cross_sections_smooth(
        ps_prev, ps0, ps1, ps_next, local_t,
        points[idx_prev], points[idx0], points[idx1], points[idx_next],
        settings.transition_mode, settings.transition_strength,
    )


def distribute_steps_by_lengths(lengths, total_steps):
    if not lengths:
        return []
    positive_lengths = [max(length, 1e-8) for length in lengths]
    total_length = sum(positive_lengths)
    total_steps = max(len(positive_lengths), int(total_steps))
    raw_steps = [length / total_length * total_steps for length in positive_lengths]
    steps = [max(1, int(math.floor(raw))) for raw in raw_steps]
    remaining = total_steps - sum(steps)

    fractions = sorted(
        ((raw_steps[i] - math.floor(raw_steps[i]), i) for i in range(len(raw_steps))),
        reverse=True,
    )
    frac_idx = 0
    while remaining > 0 and fractions:
        steps[fractions[frac_idx % len(fractions)][1]] += 1
        remaining -= 1
        frac_idx += 1
    while remaining < 0:
        candidates = [i for i, count in enumerate(steps) if count > 1]
        if not candidates:
            break
        idx = min(candidates, key=lambda i: raw_steps[i] - steps[i])
        steps[idx] -= 1
        remaining += 1
    return steps


def bezier_arc_length_at_t(p0, h0_right, h1_left, p1, t, subdivisions=12):
    t = max(0.0, min(1.0, t))
    if t <= 0.0:
        return 0.0
    length = 0.0
    prev = evaluate_bezier_segment(p0, h0_right, h1_left, p1, 0.0)
    for k in range(1, subdivisions + 1):
        sample_t = t * k / subdivisions
        cur = evaluate_bezier_segment(p0, h0_right, h1_left, p1, sample_t)
        length += (cur - prev).length
        prev = cur
    return length


def invert_bezier_arc_length(p0, h0_right, h1_left, p1, target_length, total_length):
    if total_length <= 1e-8:
        return 0.0
    target_length = max(0.0, min(total_length, target_length))
    low = 0.0
    high = 1.0
    for _ in range(12):
        mid = (low + high) * 0.5
        length = bezier_arc_length_at_t(p0, h0_right, h1_left, p1, mid)
        if length < target_length:
            low = mid
        else:
            high = mid
    return (low + high) * 0.5


def catmull_rom_vector(p0, p1, p2, p3, t):
    t2 = t * t
    t3 = t2 * t
    return 0.5 * (
        (2.0 * p1)
        + (-p0 + p2) * t
        + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2
        + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3
    )


def catmull_rom_tangent_vector(p0, p1, p2, p3, t):
    t2 = t * t
    return 0.5 * (
        (-p0 + p2)
        + (2.0 * (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3)) * t
        + (3.0 * (-p0 + 3.0 * p1 - 3.0 * p2 + p3)) * t2
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
    if tangent.z < -0.999999:
        normal = Vector((0, -1, 0))
    else:
        a = 1.0 / (1.0 + tangent.z)
        b = -tangent.x * tangent.y * a
        normal = Vector((1.0 - tangent.x * tangent.x * a, b, -tangent.x))
        if normal.length < 1e-8:
            normal = Vector((1, 0, 0))
    normal = normal - tangent * normal.dot(tangent)
    if normal.length < 1e-8:
        normal = Vector((1, 0, 0))
        normal = normal - tangent * normal.dot(tangent)
    normal.normalize()
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


def get_effective_point_setting(point_settings, idx, settings):
    if idx < 0:
        return get_point_setting(point_settings, idx, settings)
    if idx >= len(point_settings):
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
    update_transition_point_values(curve_obj, settings)
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
        resolution = max(0, settings.pipe_resolution)
        is_cyclic = spline_data['cyclic']
        num_points = len(points)
        if num_points < 2:
            global_point_idx += num_points
            continue

        ring_specs = []
        if spline_data['type'] == 'BEZIER':
            seg_count = num_points if is_cyclic else num_points - 1

            # ── Step 1: estimate arc length of every segment ──────────────
            ARC_SUBDIV = 8
            seg_lengths = []
            for seg_idx in range(seg_count):
                idx0 = seg_idx
                idx1 = (seg_idx + 1) % num_points
                p0_  = points[idx0]['co']
                h0r_ = points[idx0]['handle_right']
                h1l_ = points[idx1]['handle_left']
                p1_  = points[idx1]['co']
                length = 0.0
                prev = evaluate_bezier_segment(p0_, h0r_, h1l_, p1_, 0.0)
                for k in range(1, ARC_SUBDIV + 1):
                    cur = evaluate_bezier_segment(p0_, h0r_, h1l_, p1_, k / ARC_SUBDIV)
                    length += (cur - prev).length
                    prev = cur
                seg_lengths.append(max(length, 1e-8))
            total_length = sum(seg_lengths)

            # ── Step 2: distribute sample steps proportionally ────────────
            # Total samples across the whole spline (same budget as before)
            total_steps = seg_count * max(1, resolution + 1)
            seg_steps = distribute_steps_by_lengths(seg_lengths, total_steps)

            # ── Step 3: sample each segment ───────────────────────────────
            for seg_idx in range(seg_count):
                idx0 = seg_idx
                idx1 = (seg_idx + 1) % num_points
                p0 = points[idx0]['co']
                h0r = points[idx0]['handle_right']
                h1l = points[idx1]['handle_left']
                p1 = points[idx1]['co']
                global_idx0 = global_point_idx + idx0
                global_idx1 = global_point_idx + idx1
                ps0 = get_effective_point_setting(point_settings, global_idx0, settings)
                ps1 = get_effective_point_setting(point_settings, global_idx1, settings)
                idx_prev = (idx0 - 1) % num_points if is_cyclic or idx0 > 0 else idx0
                idx_next = (idx1 + 1) % num_points if is_cyclic or idx1 < num_points - 1 else idx1
                ps_prev = get_effective_point_setting(point_settings, global_point_idx + idx_prev, settings)
                ps_next = get_effective_point_setting(point_settings, global_point_idx + idx_next, settings)
                steps = seg_steps[seg_idx]
                step_count = steps if (is_cyclic or seg_idx < seg_count - 1) else steps + 1
                segment_length = seg_lengths[seg_idx]
                for step in range(step_count):
                    if not is_cyclic and seg_idx == seg_count - 1 and step == step_count - 1:
                        distance_t = 1.0
                        shape_t = 1.0
                    else:
                        distance_t = step / steps
                        shape_t = invert_bezier_arc_length(p0, h0r, h1l, p1, segment_length * distance_t, segment_length)
                    pos = evaluate_bezier_segment(p0, h0r, h1l, p1, shape_t)
                    tan = evaluate_bezier_tangent(p0, h0r, h1l, p1, shape_t)
                    interp = interpolate_cross_sections_smooth(
                        ps_prev, ps0, ps1, ps_next, distance_t,
                        points[idx_prev], points[idx0], points[idx1], points[idx_next],
                        settings.transition_mode, settings.transition_strength
                    )
                    ring_specs.append((pos, tan, interp))
        elif spline_data['type'] == 'NURBS':
            seg_count = num_points if is_cyclic else num_points - 1
            seg_lengths = []
            for seg_idx in range(seg_count):
                idx0 = seg_idx
                idx1 = (seg_idx + 1) % num_points
                seg_lengths.append(max((points[idx1]['co'] - points[idx0]['co']).length, 1e-8))

            total_steps = seg_count * max(1, resolution + 1)
            seg_steps = distribute_steps_by_lengths(seg_lengths, total_steps)

            for seg_idx in range(seg_count):
                idx0 = seg_idx
                idx1 = (seg_idx + 1) % num_points
                idx_prev = (idx0 - 1) % num_points if is_cyclic or idx0 > 0 else idx0
                idx_next = (idx1 + 1) % num_points if is_cyclic or idx1 < num_points - 1 else idx1
                p_prev = points[idx_prev]['co']
                p0 = points[idx0]['co']
                p1 = points[idx1]['co']
                p_next = points[idx_next]['co']
                ps_prev = get_effective_point_setting(point_settings, global_point_idx + idx_prev, settings)
                ps0 = get_effective_point_setting(point_settings, global_point_idx + idx0, settings)
                ps1 = get_effective_point_setting(point_settings, global_point_idx + idx1, settings)
                ps_next = get_effective_point_setting(point_settings, global_point_idx + idx_next, settings)
                steps = seg_steps[seg_idx]
                step_count = steps if (is_cyclic or seg_idx < seg_count - 1) else steps + 1
                for step in range(step_count):
                    t = 1.0 if (not is_cyclic and seg_idx == seg_count - 1 and step == step_count - 1) else step / steps
                    pos = catmull_rom_vector(p_prev, p0, p1, p_next, t)
                    tan = safe_normalized(catmull_rom_tangent_vector(p_prev, p0, p1, p_next, t), p1 - p0)
                    interp = interpolate_cross_sections_smooth(
                        ps_prev, ps0, ps1, ps_next, t,
                        points[idx_prev], points[idx0], points[idx1], points[idx_next],
                        settings.transition_mode, settings.transition_strength,
                    )
                    ring_specs.append((pos, tan, interp))
        elif spline_data['type'] == 'POLY':
            seg_count = num_points if is_cyclic else num_points - 1

            # Arc lengths for POLY are just straight-line distances
            seg_lengths = []
            for seg_idx in range(seg_count):
                idx0 = seg_idx
                idx1 = (seg_idx + 1) % num_points
                seg_lengths.append(max((points[idx1]['co'] - points[idx0]['co']).length, 1e-8))
            total_steps = seg_count * max(1, resolution + 1)
            seg_steps = distribute_steps_by_lengths(seg_lengths, total_steps)

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
                steps = seg_steps[seg_idx]
                step_count = steps if (is_cyclic or seg_idx < seg_count - 1) else steps + 1
                for step in range(step_count):
                    t = 1.0 if (not is_cyclic and seg_idx == seg_count - 1 and step == step_count - 1) else step / steps
                    pos = p0.lerp(p1, t)
                    tan = safe_normalized(p1 - p0)
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
            all_faces.append(tuple(reversed(cap_s)))
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


def get_next_figuhair_base_name():
    used_names = {obj.name for obj in bpy.data.objects}
    index = 1
    while True:
        name = f"FiguHair {index:02d}"
        if name not in used_names:
            return name
        index += 1


def get_curve_from_figuhair_root(root_obj):
    if root_obj is None or root_obj.type != 'EMPTY':
        return None
    for child in root_obj.children:
        if child.type == 'CURVE':
            return child
    return None


def get_figuhair_root(curve_obj):
    if curve_obj is None:
        return None
    root_name = curve_obj.get("hair_pipe_root")
    root_obj = bpy.data.objects.get(root_name) if root_name else None
    if root_obj is not None and root_obj.type == 'EMPTY':
        return root_obj
    if curve_obj.parent is not None and curve_obj.parent.type == 'EMPTY':
        return curve_obj.parent
    return None


def ensure_figuhair_root(curve_obj):
    base_name = curve_obj.get("hair_pipe_base_name")
    if not base_name:
        base_name = get_next_figuhair_base_name()
        curve_obj["hair_pipe_base_name"] = base_name

    root_obj = get_figuhair_root(curve_obj)
    if root_obj is None:
        root_obj = bpy.data.objects.new(base_name, None)
        root_obj.empty_display_type = 'PLAIN_AXES'
        root_obj.empty_display_size = 0.35
        root_obj.matrix_world = Matrix.Identity(4)
        target_collection = curve_obj.users_collection[0] if curve_obj.users_collection else bpy.context.scene.collection
        target_collection.objects.link(root_obj)

    root_obj.name = base_name
    root_obj["hair_pipe_root"] = True
    curve_obj["hair_pipe_root"] = root_obj.name
    return root_obj


def get_pipe_mesh_name(curve_obj):
    return curve_obj.name + "_FiguHair"


def get_tail_mesh_name(curve_obj):
    return curve_obj.name + "_FiguHairTail"


def get_pipe_object_for_curve(curve_obj):
    root_obj = get_figuhair_root(curve_obj)
    if root_obj is not None:
        for child in root_obj.children:
            if child.type == 'MESH' and get_pipe_source_curve(child) == curve_obj:
                return child
            if child.type == 'MESH' and child.name.endswith(" Mesh"):
                return child
    mesh_name = get_pipe_mesh_name(curve_obj)
    obj = bpy.data.objects.get(mesh_name)
    if obj is not None and obj.type == 'MESH':
        return obj
    legacy_name = curve_obj.name + "_FiguHair"
    obj = bpy.data.objects.get(legacy_name)
    if obj is not None and obj.type == 'MESH':
        return obj
    return None


def get_tail_object_for_curve(curve_obj):
    root_obj = get_figuhair_root(curve_obj)
    if root_obj is not None:
        for child in root_obj.children:
            if child.type == 'MESH' and child.get("hair_pipe_tail_source_curve") == curve_obj.name:
                return child
            if child.type == 'MESH' and child.name.endswith(" Tail"):
                return child
    tail_name = get_tail_mesh_name(curve_obj)
    obj = bpy.data.objects.get(tail_name)
    if obj is not None and obj.type == 'MESH':
        return obj
    return None


def get_hair_root_object(curve_obj):
    root_obj = get_figuhair_root(curve_obj)
    if root_obj is not None:
        return root_obj
    if curve_obj is None:
        return None
    if curve_obj.parent is not None and curve_obj.parent.type == 'EMPTY' and curve_obj.parent.get("hair_pipe_root"):
        return curve_obj.parent
    root_name = curve_obj.name + "_FiguHair"
    obj = bpy.data.objects.get(root_name)
    if obj is not None and obj.type == 'EMPTY' and obj.get("hair_pipe_root"):
        return obj
    return None


def verts_to_world_space(verts, curve_obj):
    matrix = curve_obj.matrix_world
    return [matrix @ vert for vert in verts]


def get_pipe_source_curve(pipe_obj):
    if pipe_obj is None or pipe_obj.type != 'MESH':
        return None
    if pipe_obj.parent is not None and pipe_obj.parent.type == 'EMPTY':
        curve_obj = get_curve_from_figuhair_root(pipe_obj.parent)
        if curve_obj is not None:
            return curve_obj
    source_name = pipe_obj.get("hair_pipe_source_curve")
    if not source_name:
        return None
    curve_obj = bpy.data.objects.get(source_name)
    if curve_obj is not None and curve_obj.type == 'CURVE':
        return curve_obj
    return None


def get_tail_source_curve(tail_obj):
    if tail_obj is None or tail_obj.type != 'MESH':
        return None
    source_name = tail_obj.get("hair_pipe_tail_source_curve")
    if source_name:
        curve_obj = bpy.data.objects.get(source_name)
        if curve_obj is not None and curve_obj.type == 'CURVE':
            return curve_obj
    if tail_obj.parent is not None and tail_obj.parent.type == 'EMPTY':
        return get_curve_from_figuhair_root(tail_obj.parent)
    return None


def get_context_curve_object(context):
    view_layer = getattr(context, 'view_layer', None)
    active_obj = view_layer.objects.active if view_layer is not None else None
    candidates = (
        getattr(context, 'object', None),
        getattr(context, 'active_object', None),
        active_obj,
    )

    for obj in candidates:
        if obj is None:
            continue
        if obj.type == 'CURVE':
            return obj
        if obj.type == 'EMPTY':
            root_curve = get_curve_from_figuhair_root(obj)
            if root_curve is not None:
                return root_curve
        source_curve = get_pipe_source_curve(obj)
        if source_curve is not None:
            return source_curve
        source_curve = get_tail_source_curve(obj)
        if source_curve is not None:
            return source_curve

    for obj in getattr(context, 'selected_objects', ()):
        if obj.type == 'CURVE':
            return obj
        if obj.type == 'EMPTY':
            root_curve = get_curve_from_figuhair_root(obj)
            if root_curve is not None:
                return root_curve
        source_curve = get_pipe_source_curve(obj)
        if source_curve is not None:
            return source_curve
        source_curve = get_tail_source_curve(obj)
        if source_curve is not None:
            return source_curve

    return None


def parent_keep_world(obj, parent_obj):
    world_matrix = obj.matrix_world.copy()
    obj.parent = parent_obj
    obj.matrix_world = world_matrix


def ensure_tail_edit_proxy(tail_obj):
    proxy_name = tail_obj.name + " Edit"
    proxy_obj = bpy.data.objects.get(proxy_name)
    if proxy_obj is not None and proxy_obj.data == tail_obj.data:
        proxy_obj["hair_pipe_tail_edit_proxy_source"] = tail_obj.name
        proxy_obj.parent = None
        proxy_obj.matrix_world = Matrix.Identity(4)
        proxy_obj.display_type = 'TEXTURED'
        proxy_obj.show_in_front = False
        proxy_obj.hide_render = True
        return proxy_obj
    for obj in bpy.data.objects:
        if obj.get("hair_pipe_tail_edit_proxy_source") == tail_obj.name and obj.data == tail_obj.data:
            obj.name = proxy_name
            obj.parent = None
            obj.matrix_world = Matrix.Identity(4)
            obj.display_type = 'TEXTURED'
            obj.show_in_front = False
            obj.hide_render = True
            return obj
    proxy_obj = bpy.data.objects.new(proxy_name, tail_obj.data)
    target_collection = tail_obj.users_collection[0] if tail_obj.users_collection else bpy.context.scene.collection
    target_collection.objects.link(proxy_obj)
    proxy_obj["hair_pipe_tail_edit_proxy_source"] = tail_obj.name
    proxy_obj.parent = None
    proxy_obj.matrix_world = Matrix.Identity(4)
    proxy_obj.display_type = 'TEXTURED'
    proxy_obj.show_in_front = False
    proxy_obj.hide_render = True
    return proxy_obj


def ensure_pipe_subdivision_modifier(pipe_obj, show_viewport=True, levels=2):
    modifier = pipe_obj.modifiers.get("FiguHair Catmull-Clark")
    if modifier is None:
        modifier = pipe_obj.modifiers.new("FiguHair Catmull-Clark", 'SUBSURF')
    levels = max(0, min(int(levels), 6))
    modifier.subdivision_type = 'CATMULL_CLARK'
    modifier.levels = levels
    modifier.render_levels = levels
    modifier.show_viewport = show_viewport
    modifier.show_render = True
    return modifier


def move_modifier_before(pipe_obj, modifier, before_modifier):
    if modifier is None or before_modifier is None or modifier == before_modifier:
        return
    names = [mod.name for mod in pipe_obj.modifiers]
    if modifier.name not in names or before_modifier.name not in names:
        return
    from_index = names.index(modifier.name)
    to_index = names.index(before_modifier.name)
    if from_index > to_index:
        pipe_obj.modifiers.move(from_index, to_index)


def ensure_tail_join_geometry_nodes(pipe_obj, tail_obj):
    if pipe_obj is None or tail_obj is None:
        return None
    modifier = pipe_obj.modifiers.get("FiguHair Join Tail")
    if modifier is None:
        modifier = pipe_obj.modifiers.new("FiguHair Join Tail", 'NODES')

    group = modifier.node_group
    if group is None or not group.get("figuhair_tail_join") or group.get("figuhair_tail_join_version", 0) < 2:
        group = bpy.data.node_groups.new(pipe_obj.name + " Tail Join", 'GeometryNodeTree')
        group["figuhair_tail_join"] = True
        group["figuhair_tail_join_version"] = 2
        try:
            group.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
            group.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
        except Exception:
            pass

        nodes = group.nodes
        links = group.links
        nodes.clear()
        group_input = nodes.new('NodeGroupInput')
        group_input.location = (-520, 0)
        object_info = nodes.new('GeometryNodeObjectInfo')
        object_info.location = (-520, -180)
        join_geometry = nodes.new('GeometryNodeJoinGeometry')
        join_geometry.location = (-250, -70)
        merge_by_distance = nodes.new('GeometryNodeMergeByDistance')
        merge_by_distance.location = (40, -70)
        group_output = nodes.new('NodeGroupOutput')
        group_output.location = (340, -70)
        try:
            object_info.inputs['Object'].default_value = tail_obj
        except Exception:
            pass
        try:
            object_info.inputs['As Instance'].default_value = False
        except Exception:
            pass
        try:
            merge_by_distance.inputs['Distance'].default_value = 0.0001
        except Exception:
            pass
        try:
            links.new(group_input.outputs['Geometry'], join_geometry.inputs['Geometry'])
            links.new(object_info.outputs['Geometry'], join_geometry.inputs['Geometry'])
            links.new(join_geometry.outputs['Geometry'], merge_by_distance.inputs['Geometry'])
            links.new(merge_by_distance.outputs['Geometry'], group_output.inputs['Geometry'])
        except Exception:
            pass
        modifier.node_group = group
    else:
        for node in group.nodes:
            if node.bl_idname == 'GeometryNodeObjectInfo':
                try:
                    node.inputs['Object'].default_value = tail_obj
                except Exception:
                    pass
    return modifier


def ensure_tail_modifier_stack(pipe_obj, tail_obj, settings=None):
    join_modifier = ensure_tail_join_geometry_nodes(pipe_obj, tail_obj)
    show_viewport = True if settings is None else settings.default_subdiv
    levels = 2 if settings is None else settings.subdivision_levels
    subdiv_modifier = ensure_pipe_subdivision_modifier(pipe_obj, show_viewport, levels)
    move_modifier_before(pipe_obj, join_modifier, subdiv_modifier)
    return join_modifier, subdiv_modifier


def get_last_ring_from_pipe_vertices(verts, settings):
    if not verts or len(settings.point_settings) == 0:
        return None
    last_setting = settings.point_settings[-1]
    segments = len(last_setting.cross_section_verts)
    if segments < 3 or len(verts) < segments:
        return None
    return list(verts[-segments:]), segments


def estimate_tail_direction_from_vertices(verts, segments):
    if len(verts) >= segments * 2:
        last_center = sum((Vector(v) for v in verts[-segments:]), Vector((0.0, 0.0, 0.0))) / segments
        prev_center = sum((Vector(v) for v in verts[-segments * 2:-segments]), Vector((0.0, 0.0, 0.0))) / segments
        direction = last_center - prev_center
        if direction.length > 1e-8:
            return direction.normalized()
    return Vector((0.0, 0.0, 1.0))


def create_tail_mesh_geometry(last_ring, direction):
    segments = len(last_ring)
    center = sum((Vector(v) for v in last_ring), Vector((0.0, 0.0, 0.0))) / segments
    radius = max((Vector(v) - center).length for v in last_ring) if segments > 0 else 0.05
    length = max(radius * 1.8, 0.05)
    tip_ring = [Vector(v) + direction * length for v in last_ring]
    verts = [Vector(v) for v in last_ring] + tip_ring
    faces = []
    for i in range(segments):
        j = (i + 1) % segments
        faces.append((i, j, segments + j, segments + i))
    faces.append(tuple(range(segments, segments * 2)))
    return verts, faces


def flatten_ring_points(ring):
    values = []
    for point in ring:
        vector = Vector(point)
        values.extend((vector.x, vector.y, vector.z))
    return values


def get_stored_tail_connection_ring(tail_obj, segments):
    values = tail_obj.get("hair_pipe_tail_connection_ring")
    if values is None or len(values) != segments * 3:
        return None
    return [Vector((values[i], values[i + 1], values[i + 2])) for i in range(0, len(values), 3)]


def store_tail_connection_state(tail_obj, last_ring, direction, lower_ring_count=None):
    tail_obj["hair_pipe_tail_direction"] = tuple(direction)
    tail_obj["hair_pipe_tail_connection_ring"] = flatten_ring_points(last_ring)
    if lower_ring_count is not None:
        tail_obj["hair_pipe_tail_lower_ring_count"] = int(lower_ring_count)


def build_tail_connection_basis(ring, direction):
    count = len(ring)
    center = sum((Vector(v) for v in ring), Vector((0.0, 0.0, 0.0))) / count
    z_axis = direction.normalized() if direction.length > 1e-8 else Vector((0.0, 0.0, 1.0))
    x_axis = Vector(ring[0]) - center
    x_axis = x_axis - z_axis * x_axis.dot(z_axis)
    if x_axis.length < 1e-8:
        for point in ring[1:]:
            x_axis = Vector(point) - center
            x_axis = x_axis - z_axis * x_axis.dot(z_axis)
            if x_axis.length >= 1e-8:
                break
    if x_axis.length < 1e-8:
        x_axis = z_axis.cross(Vector((0.0, 0.0, 1.0)))
        if x_axis.length < 1e-8:
            x_axis = z_axis.cross(Vector((0.0, 1.0, 0.0)))
    x_axis.normalize()
    y_axis = z_axis.cross(x_axis)
    if y_axis.length < 1e-8:
        y_axis = Vector((0.0, 1.0, 0.0))
    y_axis.normalize()
    avg_radius = sum((Vector(v) - center).length for v in ring) / count
    return center, x_axis, y_axis, z_axis, max(avg_radius, 1e-8)


def transform_tail_vertices_by_connection(vertices, old_ring, new_ring, old_direction, new_direction):
    old_center, old_x, old_y, old_z, old_radius = build_tail_connection_basis(old_ring, old_direction)
    new_center, new_x, new_y, new_z, new_radius = build_tail_connection_basis(new_ring, new_direction)
    scale = new_radius / old_radius
    transformed = []
    for vertex in vertices:
        offset = Vector(vertex) - old_center
        local_x = offset.dot(old_x)
        local_y = offset.dot(old_y)
        local_z = offset.dot(old_z)
        transformed.append(new_center + new_x * local_x * scale + new_y * local_y * scale + new_z * local_z * scale)
    return transformed


def resample_ring_points(ring, new_count):
    old_count = len(ring)
    if old_count == new_count:
        return [Vector(v) for v in ring]
    result = []
    for i in range(new_count):
        pos = i * old_count / new_count
        idx0 = int(math.floor(pos)) % old_count
        idx1 = (idx0 + 1) % old_count
        t = pos - math.floor(pos)
        result.append(Vector(ring[idx0]).lerp(Vector(ring[idx1]), t))
    return result


def rebuild_tail_grid(mesh, transformed_vertices, old_segments, new_segments, last_ring):
    if old_segments < 3 or new_segments < 3:
        return False
    if len(transformed_vertices) % old_segments != 0:
        return False
    ring_count = len(transformed_vertices) // old_segments
    if ring_count < 2:
        return False

    new_verts = []
    for ring_idx in range(ring_count):
        old_ring = transformed_vertices[ring_idx * old_segments:(ring_idx + 1) * old_segments]
        if ring_idx == 0:
            new_ring = [Vector(v) for v in last_ring]
        else:
            new_ring = resample_ring_points(old_ring, new_segments)
        new_verts.extend(new_ring)

    faces = []
    for ring_idx in range(ring_count - 1):
        base = ring_idx * new_segments
        next_base = (ring_idx + 1) * new_segments
        for i in range(new_segments):
            j = (i + 1) % new_segments
            faces.append((base + i, base + j, next_base + j, next_base + i))
    faces.append(tuple(range((ring_count - 1) * new_segments, ring_count * new_segments)))
    rebuild_mesh_safely(mesh, new_verts, faces)
    return True


def get_tail_pose_rotation(tail_obj, mesh, old_segments, new_direction):
    old_direction = None
    stored_direction = tail_obj.get("hair_pipe_tail_direction")
    if stored_direction is not None and len(stored_direction) == 3:
        direction = Vector(stored_direction)
        if direction.length > 1e-8:
            old_direction = direction.normalized()
    if old_direction is None and len(mesh.vertices) > old_segments:
        old_center = sum((v.co.copy() for v in mesh.vertices[:old_segments]), Vector((0.0, 0.0, 0.0))) / old_segments
        tail_center = sum((v.co.copy() for v in mesh.vertices[old_segments:]), Vector((0.0, 0.0, 0.0))) / (len(mesh.vertices) - old_segments)
        direction = tail_center - old_center
        if direction.length > 1e-8:
            old_direction = direction.normalized()
    if old_direction is not None and new_direction.length > 1e-8:
        try:
            return old_direction.rotation_difference(new_direction.normalized()).to_matrix()
        except Exception:
            return None
    return None


def sanitize_faces(faces, vertex_count):
    clean_faces = []
    seen = set()
    for face in faces:
        clean = []
        for index in face:
            if isinstance(index, int) and 0 <= index < vertex_count and index not in clean:
                clean.append(index)
        if len(clean) < 3:
            continue
        key = tuple(clean)
        reverse_key = tuple(reversed(clean))
        if key in seen or reverse_key in seen:
            continue
        seen.add(key)
        clean_faces.append(tuple(clean))
    return clean_faces


def rebuild_mesh_safely(mesh, verts, faces):
    clean_verts = [Vector(v) for v in verts]
    clean_faces = sanitize_faces(faces, len(clean_verts))
    mesh.clear_geometry()
    mesh.from_pydata(clean_verts, [], clean_faces)
    try:
        mesh.validate(clean_customdata=False)
    except Exception:
        try:
            mesh.validate()
        except Exception:
            pass
    mesh.update()
    shade_mesh_smooth(mesh)


def shade_mesh_smooth(mesh):
    for polygon in mesh.polygons:
        polygon.use_smooth = True


def infer_inserted_ring_index(old_ring, new_ring):
    old_count = len(old_ring)
    new_count = len(new_ring)
    if new_count != old_count + 1:
        return None
    best_index = 0
    best_score = None
    for insert_index in range(new_count):
        score = 0.0
        for old_index in range(old_count):
            new_index = old_index if old_index < insert_index else old_index + 1
            score += (Vector(old_ring[old_index]) - Vector(new_ring[new_index])).length_squared
        if best_score is None or score < best_score:
            best_score = score
            best_index = insert_index
    return best_index


def infer_removed_ring_index(old_ring, new_ring):
    old_count = len(old_ring)
    new_count = len(new_ring)
    if new_count != old_count - 1:
        return None
    best_index = 0
    best_score = None
    for removed_index in range(old_count):
        score = 0.0
        for new_index in range(new_count):
            old_index = new_index if new_index < removed_index else new_index + 1
            score += (Vector(old_ring[old_index]) - Vector(new_ring[new_index])).length_squared
        if best_score is None or score < best_score:
            best_score = score
            best_index = removed_index
    return best_index


def make_tail_bridge_faces(new_segments, old_segments, old_ring=None, new_ring=None):
    faces = []
    lower_base = new_segments

    if new_segments == old_segments:
        for index in range(new_segments):
            next_index = (index + 1) % new_segments
            faces.append((index, next_index, lower_base + next_index, lower_base + index))
        return faces

    if new_segments == old_segments + 1 and old_ring is not None and new_ring is not None:
        inserted_index = infer_inserted_ring_index(old_ring, new_ring)
        before_index = (inserted_index - 1) % old_segments

        def map_old_to_new(old_index):
            return old_index if old_index < inserted_index else old_index + 1

        for old_index in range(old_segments):
            next_old = (old_index + 1) % old_segments
            lower_a = lower_base + old_index
            lower_b = lower_base + next_old
            upper_a = map_old_to_new(old_index)
            upper_b = map_old_to_new(next_old)
            if old_index == before_index:
                faces.append((upper_a, inserted_index, lower_b, lower_a))
                faces.append((inserted_index, upper_b, lower_b))
            else:
                faces.append((upper_a, upper_b, lower_b, lower_a))
        return [tuple(face) for face in faces if len(set(face)) >= 3]

    if new_segments == old_segments - 1 and old_ring is not None and new_ring is not None:
        removed_index = infer_removed_ring_index(old_ring, new_ring)
        before_index = (removed_index - 1) % old_segments
        after_index = (removed_index + 1) % old_segments

        def map_old_to_new(old_index):
            if old_index == removed_index:
                return None
            return old_index if old_index < removed_index else old_index - 1

        for old_index in range(old_segments):
            if old_index == removed_index:
                continue
            next_old = (old_index + 1) % old_segments
            if old_index == before_index:
                upper_a = map_old_to_new(before_index)
                upper_b = map_old_to_new(after_index)
                lower_before = lower_base + before_index
                lower_removed = lower_base + removed_index
                lower_after = lower_base + after_index
                faces.append((upper_a, upper_b, lower_removed, lower_before))
                faces.append((upper_b, lower_after, lower_removed))
                continue
            if next_old == removed_index:
                continue
            upper_a = map_old_to_new(old_index)
            upper_b = map_old_to_new(next_old)
            lower_a = lower_base + old_index
            lower_b = lower_base + next_old
            faces.append((upper_a, upper_b, lower_b, lower_a))
        return [tuple(face) for face in faces if None not in face and len(set(face)) >= 3]

    upper_idx = 0
    lower_idx = 0
    max_steps = new_segments + old_segments + 2
    steps = 0
    while (upper_idx < new_segments or lower_idx < old_segments) and steps < max_steps:
        steps += 1
        next_upper_t = (upper_idx + 1) / new_segments if upper_idx < new_segments else float('inf')
        next_lower_t = (lower_idx + 1) / old_segments if lower_idx < old_segments else float('inf')
        upper_a = upper_idx % new_segments
        lower_a = lower_base + (lower_idx % old_segments)

        if abs(next_upper_t - next_lower_t) < 1e-8 and upper_idx < new_segments and lower_idx < old_segments:
            upper_b = (upper_idx + 1) % new_segments
            lower_b = lower_base + ((lower_idx + 1) % old_segments)
            faces.append((upper_a, upper_b, lower_b, lower_a))
            upper_idx += 1
            lower_idx += 1
        elif next_upper_t < next_lower_t and upper_idx < new_segments:
            upper_b = (upper_idx + 1) % new_segments
            faces.append((upper_a, upper_b, lower_a))
            upper_idx += 1
        elif lower_idx < old_segments:
            lower_b = lower_base + ((lower_idx + 1) % old_segments)
            faces.append((upper_a, lower_b, lower_a))
            lower_idx += 1
        else:
            break
    return [tuple(face) for face in faces if len(set(face)) >= 3]


def remap_index_after_connection_change(index, old_segments, new_segments, inserted_index=None):
    if index >= old_segments:
        return index - old_segments + new_segments
    if inserted_index is None:
        return index
    return index if index < inserted_index else index + 1


def split_face_for_inserted_connection_point(face, before_new, after_new, inserted_index):
    count = len(face)
    if count < 3:
        return []
    for i, current in enumerate(face):
        nxt = face[(i + 1) % count]
        if current == before_new and nxt == after_new:
            expanded = list(face)
            expanded.insert(i + 1, inserted_index)
            if len(face) == 4:
                lower_a = face[(i - 1) % count]
                lower_b = face[(i + 2) % count]
                return [
                    (before_new, inserted_index, lower_a),
                    (inserted_index, after_new, lower_b, lower_a),
                ]
            return [tuple(expanded)]
        if current == after_new and nxt == before_new:
            expanded = list(face)
            expanded.insert(i + 1, inserted_index)
            if len(face) == 4:
                lower_a = face[(i - 1) % count]
                lower_b = face[(i + 2) % count]
                return [
                    (after_new, inserted_index, lower_a),
                    (inserted_index, before_new, lower_b, lower_a),
                ]
            return [tuple(expanded)]
    return [tuple(face)]


def remap_bridge_faces_for_single_insert(old_faces, old_segments, new_segments, old_ring, new_ring):
    inserted_index = infer_inserted_ring_index(old_ring, new_ring)
    before_old = (inserted_index - 1) % old_segments
    after_old = before_old + 1
    if after_old >= old_segments:
        after_old = 0
    before_new = remap_index_after_connection_change(before_old, old_segments, new_segments, inserted_index)
    after_new = remap_index_after_connection_change(after_old, old_segments, new_segments, inserted_index)

    faces = []
    for old_face in old_faces:
        remapped = []
        has_connection_vertex = False
        for index in old_face:
            if index < old_segments:
                has_connection_vertex = True
            remapped.append(remap_index_after_connection_change(index, old_segments, new_segments, inserted_index))
        if has_connection_vertex:
            faces.extend(split_face_for_inserted_connection_point(remapped, before_new, after_new, inserted_index))
        else:
            faces.append(tuple(remapped))
    return [tuple(face) for face in faces if len(set(face)) >= 3]


def face_uses_first_ring(face, old_segments):
    return any(index < old_segments for index in face)


def remap_tail_face_after_connection_change(face, old_segments, new_segments):
    remapped = []
    for index in face:
        if index < old_segments:
            return None
        remapped.append(index - old_segments + new_segments)
    return tuple(remapped) if len(set(remapped)) >= 3 else None


def infer_tail_lower_ring_count(mesh, connection_count):
    lower_indices = []
    seen = set()
    for polygon in mesh.polygons:
        face = tuple(polygon.vertices)
        if not any(index < connection_count for index in face):
            continue
        for index in face:
            if index >= connection_count and index not in seen:
                seen.add(index)
                lower_indices.append(index)
    if len(lower_indices) >= 3:
        return len(lower_indices)
    return connection_count


def retopologize_tail_connection(tail_obj, last_ring, old_segments, new_segments, new_direction):
    mesh = tail_obj.data
    if len(mesh.vertices) < old_segments or old_segments < 3 or new_segments < 3:
        return False
    old_ring = get_stored_tail_connection_ring(tail_obj, old_segments)
    if old_ring is None:
        old_ring = [v.co.copy() for v in mesh.vertices[:old_segments]]
    stored_direction = tail_obj.get("hair_pipe_tail_direction")
    old_direction = Vector(stored_direction) if stored_direction is not None and len(stored_direction) == 3 else new_direction
    transformed_old_vertices = transform_tail_vertices_by_connection(
        [v.co.copy() for v in mesh.vertices],
        old_ring,
        last_ring,
        old_direction,
        new_direction,
    )
    lower_segments = int(tail_obj.get("hair_pipe_tail_lower_ring_count", infer_tail_lower_ring_count(mesh, old_segments)))
    preserved_vertices = transformed_old_vertices[old_segments:]
    if len(preserved_vertices) < lower_segments:
        return False
    old_faces = [tuple(poly.vertices) for poly in mesh.polygons]
    new_verts = [Vector(v) for v in last_ring] + preserved_vertices
    if new_segments == old_segments + 1:
        new_faces = remap_bridge_faces_for_single_insert(old_faces, old_segments, new_segments, old_ring, last_ring)
    else:
        preserved_faces = []
        for face in old_faces:
            remapped = remap_tail_face_after_connection_change(face, old_segments, new_segments)
            if remapped is not None:
                preserved_faces.append(remapped)
        bridge_faces = make_tail_bridge_faces(new_segments, lower_segments)
        new_faces = bridge_faces + preserved_faces
    rebuild_mesh_safely(mesh, new_verts, new_faces)
    tail_obj["hair_pipe_tail_lower_ring_count"] = lower_segments
    return True


def update_tail_mesh_connection(tail_obj, last_ring, segments, new_direction):
    mesh = tail_obj.data
    if len(mesh.vertices) < segments or tail_obj.get("hair_pipe_tail_ring_count", 0) != segments:
        return False
    old_ring = get_stored_tail_connection_ring(tail_obj, segments)
    if old_ring is None:
        old_ring = [v.co.copy() for v in mesh.vertices[:segments]]
    stored_direction = tail_obj.get("hair_pipe_tail_direction")
    old_direction = Vector(stored_direction) if stored_direction is not None and len(stored_direction) == 3 else new_direction
    transformed = transform_tail_vertices_by_connection(
        [v.co.copy() for v in mesh.vertices],
        old_ring,
        last_ring,
        old_direction,
        new_direction,
    )
    for vertex, co in zip(mesh.vertices, transformed):
        vertex.co = co
    for idx, co in enumerate(last_ring):
        mesh.vertices[idx].co = Vector(co)
    try:
        mesh.validate(clean_customdata=False)
    except Exception:
        try:
            mesh.validate()
        except Exception:
            pass
    mesh.update()
    shade_mesh_smooth(mesh)
    return True


def update_tail_mesh_for_curve(curve_obj, settings, pipe_verts):
    ring_data = get_last_ring_from_pipe_vertices(pipe_verts, settings)
    if ring_data is None:
        return None
    last_ring, segments = ring_data
    root_obj = ensure_figuhair_root(curve_obj)
    base_name = curve_obj.get("hair_pipe_base_name", root_obj.name)
    tail_obj = get_tail_object_for_curve(curve_obj)
    direction = estimate_tail_direction_from_vertices(pipe_verts, segments)

    if tail_obj is not None:
        old_segments = int(tail_obj.get("hair_pipe_tail_ring_count", segments))
        if old_segments != segments:
            if retopologize_tail_connection(tail_obj, last_ring, old_segments, segments, direction):
                tail_obj.name = base_name + " Tail"
                tail_obj.data.name = tail_obj.name
                tail_obj["hair_pipe_tail_source_curve"] = curve_obj.name
                tail_obj["hair_pipe_tail_ring_count"] = segments
                store_tail_connection_state(
                    tail_obj,
                    last_ring,
                    direction,
                    tail_obj.get("hair_pipe_tail_lower_ring_count", old_segments),
                )
                tail_obj.display_type = 'TEXTURED'
                tail_obj.show_in_front = True
                tail_obj.hide_render = True
                parent_keep_world(tail_obj, root_obj)
                return tail_obj
            tail_obj.display_type = 'TEXTURED'
            tail_obj.show_in_front = True
            tail_obj.hide_render = True
            parent_keep_world(tail_obj, root_obj)
            return tail_obj

    if tail_obj is not None and update_tail_mesh_connection(tail_obj, last_ring, segments, direction):
        tail_obj.name = base_name + " Tail"
        tail_obj.data.name = tail_obj.name
        tail_obj["hair_pipe_tail_source_curve"] = curve_obj.name
        store_tail_connection_state(
            tail_obj,
            last_ring,
            direction,
            tail_obj.get("hair_pipe_tail_lower_ring_count", segments),
        )
        tail_obj.display_type = 'TEXTURED'
        tail_obj.show_in_front = True
        tail_obj.hide_render = True
        parent_keep_world(tail_obj, root_obj)
        return tail_obj

    verts, faces = create_tail_mesh_geometry(last_ring, direction)
    if tail_obj is None:
        mesh = bpy.data.meshes.new(base_name + " Tail")
        tail_obj = bpy.data.objects.new(base_name + " Tail", mesh)
        target_collection = curve_obj.users_collection[0] if curve_obj.users_collection else bpy.context.scene.collection
        target_collection.objects.link(tail_obj)
    else:
        mesh = tail_obj.data
    rebuild_mesh_safely(mesh, verts, faces)
    tail_obj.name = base_name + " Tail"
    tail_obj.data.name = tail_obj.name
    tail_obj["hair_pipe_tail_source_curve"] = curve_obj.name
    tail_obj["hair_pipe_tail_ring_count"] = segments
    store_tail_connection_state(tail_obj, last_ring, direction, segments)
    tail_obj.display_type = 'TEXTURED'
    tail_obj.show_in_front = True
    tail_obj.hide_render = True
    parent_keep_world(tail_obj, root_obj)
    return tail_obj


def configure_pipe_object(pipe_obj, curve_obj):
    root_obj = ensure_figuhair_root(curve_obj)
    base_name = curve_obj.get("hair_pipe_base_name", root_obj.name)

    root_obj.name = base_name
    curve_obj.name = base_name + " Curve"
    curve_obj.data.name = base_name + " Curve"
    pipe_obj.name = base_name + " Mesh"
    pipe_obj.data.name = pipe_obj.name

    pipe_obj["hair_pipe_source_curve"] = curve_obj.name
    parent_keep_world(curve_obj, root_obj)
    parent_keep_world(pipe_obj, root_obj)

    pipe_obj.show_in_front = False
    pipe_obj.hide_select = False
    ensure_pipe_subdivision_modifier(
        pipe_obj,
        curve_obj.hair_pipe_settings.default_subdiv,
        curve_obj.hair_pipe_settings.subdivision_levels,
    )
    pipe_obj.select_set(False)


def redirect_pipe_selection(context, pipe_obj=None):
    pipe_obj = pipe_obj or context.active_object
    active_curve = get_pipe_source_curve(pipe_obj)
    if active_curve is None:
        return False

    if not active_curve.hair_pipe_settings.redirect_selection:
        return False

    if context.view_layer.objects.get(active_curve.name) is None:
        return False

    if context.mode != 'OBJECT':
        return False

    selected_curves = []
    selected_meshes = []
    for obj in list(context.selected_objects):
        if obj.type == 'CURVE' and hasattr(obj, 'hair_pipe_settings'):
            selected_curves.append(obj)
        elif obj.type == 'MESH':
            source_curve = get_pipe_source_curve(obj)
            if source_curve is not None and source_curve.hair_pipe_settings.redirect_selection:
                selected_meshes.append(obj)
                selected_curves.append(source_curve)

    if active_curve not in selected_curves:
        selected_curves.append(active_curve)

    selected_curves = [curve for curve in dict.fromkeys(selected_curves) if context.view_layer.objects.get(curve.name) is not None]
    if not selected_curves:
        return False

    for mesh_obj in selected_meshes:
        mesh_obj.select_set(False)
    for curve in selected_curves:
        curve.hide_set(False)
        curve.select_set(True)
    context.view_layer.objects.active = active_curve
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
        existing_obj = get_pipe_object_for_curve(curve_obj)
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
        tail_obj = get_tail_object_for_curve(curve_obj)
        if tail_obj is not None:
            update_tail_mesh_for_curve(curve_obj, settings, verts)
            ensure_tail_modifier_stack(pipe_obj, tail_obj, settings)
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


class HAIRPIPE_OT_toggle_cross_section_transition(bpy.types.Operator):
    """Toggle transition mode for selected curve control points"""
    bl_idname = "hair_pipe.toggle_cross_section_transition"
    bl_label = "横截面过渡模式"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = get_context_curve_object(context)
        return obj is not None and obj.type == 'CURVE'

    def execute(self, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            self.report({'ERROR'}, "请选择曲线或 FiguHair 预览网格")
            return {'CANCELLED'}
        bpy.ops.ed.undo_push(message="截面边流")
        sync_point_settings(curve_obj)
        settings = curve_obj.hair_pipe_settings
        selected = get_selected_curve_point_indices(curve_obj) if is_curve_edit_mode(curve_obj) else []
        target_indices = selected if selected else [settings.active_point_index]
        target_indices = [idx for idx in target_indices if 0 <= idx < len(settings.point_settings)]
        if not target_indices:
            self.report({'ERROR'}, "没有可切换的曲线点")
            return {'CANCELLED'}

        should_enable = not all(settings.point_settings[idx].use_transition for idx in target_indices)
        changed = 0
        for idx in target_indices:
            prev_idx = find_previous_editable_point_index(settings.point_settings, idx)
            next_idx = find_next_editable_point_index(settings.point_settings, idx)
            if should_enable and (prev_idx is None or next_idx is None):
                continue
            settings.point_settings[idx].use_transition = should_enable
            changed += 1
        if changed == 0:
            self.report({'WARNING'}, "端点或没有前后正常横截面的点不能设为过渡模式")
            return {'CANCELLED'}
        update_transition_point_values(curve_obj, settings)
        update_all_ghost_vertices(settings)
        self.report({'INFO'}, "已开启横截面过渡模式" if should_enable else "已关闭横截面过渡模式")
        return {'FINISHED'}


class HAIRPIPE_OT_apply_edge_flow(bpy.types.Operator):
    """Rebuild selected curve control points from surrounding editable cross-sections"""
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
            self.report({'ERROR'}, "Enter curve Edit Mode and select one or more target control points")
            return {'CANCELLED'}

        sync_point_settings(curve_obj)
        settings = curve_obj.hair_pipe_settings
        selected = get_selected_curve_point_indices(curve_obj)
        target_indices = selected if selected else [settings.active_point_index]
        target_indices = [idx for idx in target_indices if 0 <= idx < len(settings.point_settings)]
        if not target_indices:
            self.report({'ERROR'}, "Select one or more target curve control points")
            return {'CANCELLED'}

        settings.edge_flow_mode = self.mode
        settings.edge_flow_power = self.power
        settings.edge_flow_blend = self.blend
        changed = apply_edge_flow_to_target_indices(
            curve_obj, settings, target_indices, self.mode, self.power, self.blend
        )
        if changed <= 0:
            self.report({'ERROR'}, "Selected targets need editable cross-sections before and after them")
            return {'CANCELLED'}
        settings.active_point_index = target_indices[-1]
        update_all_ghost_vertices(settings)
        self.report({'INFO'}, f"Rebuilt {changed} selected cross-sections")
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
        try:
            from .widget_operator import push_widget_undo
            push_widget_undo(context, "复制横截面")
        except Exception:
            pass
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
        try:
            from .widget_operator import push_widget_undo
            push_widget_undo(context, "粘贴横截面")
        except Exception:
            pass
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




def apply_global_mesh_selectability(enabled):
    for obj in bpy.data.objects:
        if _is_pipe_mesh_obj(obj):
            obj.hide_select = enabled


def sync_global_redirect_selection(source_curve):
    if source_curve is None or not hasattr(source_curve, 'hair_pipe_settings'):
        return
    enabled = bool(source_curve.hair_pipe_settings.redirect_selection)
    for obj in bpy.data.objects:
        if obj.type == 'CURVE' and hasattr(obj, 'hair_pipe_settings') and obj != source_curve:
            obj.hair_pipe_settings.redirect_selection = enabled
    apply_global_mesh_selectability(enabled)


class HAIRPIPE_OT_apply_global_mesh_selectability(bpy.types.Operator):
    """Apply global mesh selectability to all FiguHair pipe meshes"""
    bl_idname = "hair_pipe.apply_global_mesh_selectability"
    bl_label = "应用网格不可选模式"

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is not None:
            sync_global_redirect_selection(curve_obj)
        return {'FINISHED'}


class HAIRPIPE_OT_toggle_redirect_selection(bpy.types.Operator):
    """Toggle global curve-only and mesh-selectable mode"""
    bl_idname = "hair_pipe.toggle_redirect_selection"
    bl_label = "网格不可选模式"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return get_context_curve_object(context) is not None

    def execute(self, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            return {'CANCELLED'}
        settings = curve_obj.hair_pipe_settings
        settings.redirect_selection = not settings.redirect_selection
        sync_global_redirect_selection(curve_obj)
        return {'FINISHED'}


class HAIRPIPE_OT_equalize_point_distance(bpy.types.Operator):
    """Redistribute selected curve points to be equally spaced along the curve"""
    bl_idname = "hair_pipe.equalize_point_distance"
    bl_label = "\u8ddd\u79bb\u5e73\u5747\u5316"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE':
            return False
        if obj.mode != 'EDIT':
            return False
        return True

    def execute(self, context):
        curve_obj = context.active_object
        curve_data = curve_obj.data
        for spline in curve_data.splines:
            if spline.type == 'BEZIER':
                points = spline.bezier_points
                selected_indices = [i for i, p in enumerate(points) if p.select_control_point]
            else:
                points = spline.points
                selected_indices = [i for i, p in enumerate(points) if p.select]
            if len(selected_indices) < 3:
                continue
            selected_indices.sort()
            first = selected_indices[0]
            last = selected_indices[-1]
            if last - first < 2:
                continue
            segment_lengths = []
            total_length = 0.0
            for i in range(first, last):
                if spline.type == 'BEZIER':
                    p0 = points[i].co
                    p1 = points[i + 1].co
                else:
                    p0 = points[i].co.xyz
                    p1 = points[i + 1].co.xyz
                seg_len = (p1 - p0).length
                segment_lengths.append(seg_len)
                total_length += seg_len
            if total_length < 1e-8:
                continue
            num_segments = last - first
            target_spacing = total_length / num_segments
            cumulative = [0.0]
            for seg_len in segment_lengths:
                cumulative.append(cumulative[-1] + seg_len)
            for idx in range(first + 1, last):
                target_dist = (idx - first) * target_spacing
                seg_idx = 0
                for s in range(len(cumulative) - 1):
                    if cumulative[s + 1] >= target_dist - 1e-10:
                        seg_idx = s
                        break
                else:
                    seg_idx = len(cumulative) - 2
                local_t = 0.0
                seg_len = cumulative[seg_idx + 1] - cumulative[seg_idx]
                if seg_len > 1e-10:
                    local_t = (target_dist - cumulative[seg_idx]) / seg_len
                local_t = max(0.0, min(1.0, local_t))
                real_idx_a = first + seg_idx
                real_idx_b = first + seg_idx + 1
                if spline.type == 'BEZIER':
                    co_a = points[real_idx_a].co
                    co_b = points[real_idx_b].co
                    new_co = co_a.lerp(co_b, local_t)
                    old_co = points[idx].co.copy()
                    offset = new_co - old_co
                    points[idx].co = new_co
                    points[idx].handle_left += offset
                    points[idx].handle_right += offset
                else:
                    co_a = points[real_idx_a].co.xyz
                    co_b = points[real_idx_b].co.xyz
                    new_co = co_a.lerp(co_b, local_t)
                    points[idx].co.x = new_co.x
                    points[idx].co.y = new_co.y
                    points[idx].co.z = new_co.z
        curve_data.update_tag()
        self.report({'INFO'}, "\u5df2\u5e73\u5747\u5316\u66f2\u7ebf\u70b9\u8ddd\u79bb")
        return {'FINISHED'}


class HAIRPIPE_OT_create_tail_mesh(bpy.types.Operator):
    """Create a tail mesh at the end of the curve"""
    bl_idname = "hair_pipe.create_tail_mesh"
    bl_label = "\u751f\u6210\u672b\u7aef\u7f51\u683c"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            return False
        pipe_obj = get_pipe_object_for_curve(curve_obj)
        if pipe_obj is None:
            return False
        return get_tail_object_for_curve(curve_obj) is None

    def execute(self, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            self.report({'ERROR'}, "\u672a\u627e\u5230\u66f2\u7ebf")
            return {'CANCELLED'}
        settings = curve_obj.hair_pipe_settings
        ensure_curve_defaults(curve_obj)
        sync_point_settings(curve_obj)
        verts, faces = generate_pipe_mesh(curve_obj, settings)
        if verts is None:
            self.report({'ERROR'}, "\u8bf7\u5148\u751f\u6210\u7ba1\u7ebf")
            return {'CANCELLED'}
        verts = verts_to_world_space(verts, curve_obj)
        tail_obj = update_tail_mesh_for_curve(curve_obj, settings, verts)
        if tail_obj is None:
            self.report({'ERROR'}, "\u65e0\u6cd5\u521b\u5efa\u672b\u7aef\u7f51\u683c")
            return {'CANCELLED'}
        pipe_obj = get_pipe_object_for_curve(curve_obj)
        if pipe_obj is not None:
            ensure_tail_modifier_stack(pipe_obj, tail_obj, settings)
        self.report({'INFO'}, "\u5df2\u521b\u5efa\u672b\u7aef\u7f51\u683c")
        return {'FINISHED'}


class HAIRPIPE_OT_remove_tail_mesh(bpy.types.Operator):
    """Remove the tail mesh"""
    bl_idname = "hair_pipe.remove_tail_mesh"
    bl_label = "\u5220\u9664\u672b\u7aef\u7f51\u683c"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            return False
        return get_tail_object_for_curve(curve_obj) is not None

    def execute(self, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            return {'CANCELLED'}
        tail_obj = get_tail_object_for_curve(curve_obj)
        if tail_obj is None:
            return {'CANCELLED'}
        pipe_obj = get_pipe_object_for_curve(curve_obj)
        if pipe_obj is not None:
            modifier = pipe_obj.modifiers.get("FiguHair Join Tail")
            if modifier is not None:
                pipe_obj.modifiers.remove(modifier)
        mesh_data = tail_obj.data
        bpy.data.objects.remove(tail_obj, do_unlink=True)
        if mesh_data is not None and mesh_data.users == 0:
            bpy.data.meshes.remove(mesh_data)
        self.report({'INFO'}, "\u5df2\u5220\u9664\u672b\u7aef\u7f51\u683c")
        return {'FINISHED'}


class HAIRPIPE_OT_toggle_tail_visibility(bpy.types.Operator):
    """Toggle tail mesh visibility"""
    bl_idname = "hair_pipe.toggle_tail_visibility"
    bl_label = "隐藏/显示末端网格"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            return False
        return get_tail_object_for_curve(curve_obj) is not None

    def execute(self, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            return {'CANCELLED'}
        tail_obj = get_tail_object_for_curve(curve_obj)
        if tail_obj is None:
            return {'CANCELLED'}
        new_hidden = not tail_obj.hide_get()
        tail_obj.hide_set(new_hidden)
        if not new_hidden:
            tail_obj.hide_viewport = False
        tail_obj.hide_render = True
        tail_obj["hair_pipe_tail_user_hidden"] = new_hidden
        tail_obj.show_in_front = not new_hidden
        return {'FINISHED'}


class HAIRPIPE_OT_hide_all_tail_meshes(bpy.types.Operator):
    """Hide all FiguHair tail meshes"""
    bl_idname = "hair_pipe.hide_all_tail_meshes"
    bl_label = "隐藏所有末端网格"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(_is_tail_mesh_only_obj(obj) for obj in bpy.data.objects)

    def execute(self, context):
        count = 0
        for tail_obj in bpy.data.objects:
            if not _is_tail_mesh_only_obj(tail_obj):
                continue
            tail_obj.hide_set(True)
            tail_obj.hide_render = True
            tail_obj["hair_pipe_tail_user_hidden"] = True
            tail_obj.show_in_front = False
            count += 1
        self.report({'INFO'}, f"已隐藏 {count} 个末端网格")
        return {'FINISHED'}


class HAIRPIPE_OT_toggle_solo_display(bpy.types.Operator):
    """Toggle solo display for the active hair set"""
    bl_idname = "hair_pipe.toggle_solo_display"
    bl_label = "单独显示"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        curve_obj = get_context_curve_object(context)
        return curve_obj is not None and curve_obj.type == 'CURVE'

    def execute(self, context):
        curves = []
        for obj in getattr(context, 'selected_objects', ()):
            if obj is None:
                continue
            curve_obj = None
            if obj.type == 'CURVE':
                curve_obj = obj
            elif obj.type == 'EMPTY':
                curve_obj = get_curve_from_figuhair_root(obj)
            else:
                curve_obj = get_pipe_source_curve(obj) or get_tail_source_curve(obj)
            if curve_obj is not None and curve_obj not in curves:
                curves.append(curve_obj)
        if not curves:
            curve_obj = get_context_curve_object(context)
            if curve_obj is not None:
                curves = [curve_obj]
        if not curves:
            return {'CANCELLED'}

        roots = []
        family_ids = set()
        solo_enabled = True
        for curve_obj in curves:
            root_obj = get_hair_root_object(curve_obj)
            if root_obj is None:
                continue
            roots.append(root_obj)
            solo_enabled = solo_enabled and not bool(root_obj.get("hair_pipe_solo_active", False))
            family_ids.add(root_obj.name)
            family_ids.add(curve_obj.name)
            pipe_obj = get_pipe_object_for_curve(curve_obj)
            tail_obj = get_tail_object_for_curve(curve_obj)
            if pipe_obj is not None:
                family_ids.add(pipe_obj.name)
            if tail_obj is not None:
                family_ids.add(tail_obj.name)

        if not roots:
            return {'CANCELLED'}

        if solo_enabled:
            for obj in bpy.data.objects:
                if _is_figuhair_family_obj(obj):
                    obj["hair_pipe_solo_prev_hidden"] = obj.hide_get()
                    obj.hide_set(obj.name not in family_ids)
            for root_obj in roots:
                root_obj["hair_pipe_solo_active"] = True
            self.report({'INFO'}, "已单独显示选中的头发")
        else:
            for obj in bpy.data.objects:
                if not _is_figuhair_family_obj(obj):
                    continue
                prev_hidden = bool(obj.get("hair_pipe_solo_prev_hidden", False))
                obj.hide_set(prev_hidden)
                if "hair_pipe_solo_prev_hidden" in obj:
                    del obj["hair_pipe_solo_prev_hidden"]
            for root_obj in roots:
                if "hair_pipe_solo_active" in root_obj:
                    del root_obj["hair_pipe_solo_active"]
            self.report({'INFO'}, "已取消单独显示")
        return {'FINISHED'}


class HAIRPIPE_OT_edit_tail_mesh(bpy.types.Operator):
    """切换末端网格编辑模式与曲线编辑模式"""
    bl_idname = "hair_pipe.edit_tail_mesh"
    bl_label = "\u7f16\u8f91\u672b\u7aef\u7f51\u683c"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            return False
        return get_tail_object_for_curve(curve_obj) is not None

    def execute(self, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            return {'CANCELLED'}
        tail_obj = get_tail_object_for_curve(curve_obj)
        if tail_obj is None:
            return {'CANCELLED'}

        active = context.active_object
        mode = context.mode

        # Currently editing tail mesh -> return to curve edit mode
        if active == tail_obj and mode == 'EDIT_MESH':
            with context.temp_override(active_object=tail_obj, object=tail_obj):
                bpy.ops.object.mode_set(mode='OBJECT')
            # Restore user-intended hidden state
            user_hidden = bool(tail_obj.get("hair_pipe_tail_user_hidden", False))
            tail_obj.hide_viewport = False
            tail_obj.hide_set(user_hidden)
            tail_obj.show_in_front = not user_hidden
            for obj in list(context.selected_objects):
                obj.select_set(False)
            curve_obj.hide_set(False)
            curve_obj.select_set(True)
            context.view_layer.objects.active = curve_obj
            with context.temp_override(active_object=curve_obj, object=curve_obj):
                bpy.ops.object.mode_set(mode='EDIT')
            return {'FINISHED'}

        # Enter tail mesh edit mode
        if mode not in ('OBJECT',):
            bpy.ops.object.mode_set(mode='OBJECT')

        # Temporarily disable redirect_selection so handler does not fight us
        redirect_was = curve_obj.hair_pipe_settings.redirect_selection
        curve_obj.hair_pipe_settings.redirect_selection = False

        # Remember user-intended hidden state before revealing for edit
        tail_obj["hair_pipe_tail_user_hidden"] = bool(tail_obj.get("hair_pipe_tail_user_hidden", tail_obj.hide_get()))
        tail_obj.hide_set(False)
        tail_obj.hide_viewport = False
        # Ensure solid display, always in front
        tail_obj.display_type = 'TEXTURED'
        tail_obj.show_in_front = True
        for obj in list(context.selected_objects):
            obj.select_set(False)
        tail_obj.select_set(True)
        context.view_layer.objects.active = tail_obj
        with context.temp_override(active_object=tail_obj, object=tail_obj):
            bpy.ops.object.mode_set(mode='EDIT')

        curve_obj.hair_pipe_settings.redirect_selection = redirect_was
        return {'FINISHED'}



class HAIRPIPE_OT_duplicate_hair(bpy.types.Operator):
    """Duplicate the entire hair (root empty, curve, pipe mesh, tail mesh) and rename"""
    bl_idname = "hair_pipe.duplicate_hair"
    bl_label = "\u590d\u5236\u5934\u53d1"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return get_context_curve_object(context) is not None

    def execute(self, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            return {'CANCELLED'}

        root_obj = get_figuhair_root(curve_obj)
        pipe_obj = get_pipe_object_for_curve(curve_obj)
        tail_obj = get_tail_object_for_curve(curve_obj)

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # Capture world matrices NOW, before creating anything
        src_root_matrix  = root_obj.matrix_world.copy()  if root_obj  else Matrix.Identity(4)
        src_curve_matrix = curve_obj.matrix_world.copy()
        src_pipe_matrix  = pipe_obj.matrix_world.copy()  if pipe_obj  else None
        src_tail_matrix  = tail_obj.matrix_world.copy()  if tail_obj  else None

        new_base   = get_next_figuhair_base_name()
        target_col = (
            curve_obj.users_collection[0]
            if curve_obj.users_collection
            else context.scene.collection
        )

        # ── 1. Root empty ──────────────────────────────────────────────────
        new_root = bpy.data.objects.new(new_base, None)
        new_root.empty_display_type = 'PLAIN_AXES'
        new_root.empty_display_size = 0.35
        new_root["hair_pipe_root"] = True
        target_col.objects.link(new_root)
        new_root.matrix_world = src_root_matrix

        # ── 2. Curve (independent copy of curve data) ──────────────────────
        new_curve_data       = curve_obj.data.copy()
        new_curve_data.name  = new_base + " Curve"
        new_curve            = bpy.data.objects.new(new_base + " Curve", new_curve_data)
        new_curve["hair_pipe_base_name"] = new_base
        new_curve["hair_pipe_root"]      = new_root.name
        target_col.objects.link(new_curve)
        new_curve.parent      = new_root
        new_curve.matrix_world = src_curve_matrix

        # Deep-copy hair_pipe_settings
        src_s = curve_obj.hair_pipe_settings
        dst_s = new_curve.hair_pipe_settings
        for attr in (
            'default_radius', 'default_segments', 'pipe_resolution',
            'transition_mode', 'transition_strength',
            'strong_smoothing', 'strong_smoothing_iterations',
            'smooth_shading', 'auto_update', 'cap_ends', 'default_subdiv',
            'redirect_selection', 'edge_flow_mode', 'edge_flow_power',
            'edge_flow_blend', 'active_point_index',
        ):
            try:
                setattr(dst_s, attr, getattr(src_s, attr))
            except (AttributeError, TypeError):
                pass
        dst_s.point_settings.clear()
        for src_ps in src_s.point_settings:
            dst_ps = dst_s.point_settings.add()
            dst_ps.scale             = src_ps.scale
            dst_ps.rotation          = src_ps.rotation
            dst_ps.active_vert_index = src_ps.active_vert_index
            dst_ps.cross_section_verts.clear()
            for sv in src_ps.cross_section_verts:
                dv = dst_ps.cross_section_verts.add()
                dv.offset_x = sv.offset_x
                dv.offset_y = sv.offset_y
                dv.is_ghost  = sv.is_ghost

        # ── 3. Pipe mesh ──────────────────────────────────────────────────
        new_pipe = None
        if pipe_obj is not None:
            new_pipe_data       = pipe_obj.data.copy()
            new_pipe_data.name  = new_base + " Mesh"
            new_pipe            = bpy.data.objects.new(new_base + " Mesh", new_pipe_data)
            new_pipe["hair_pipe_source_curve"] = new_curve.name
            new_pipe.show_in_front = pipe_obj.show_in_front
            new_pipe.hide_select   = pipe_obj.hide_select
            new_pipe.hide_viewport = pipe_obj.hide_viewport
            new_pipe.display_type  = pipe_obj.display_type
            target_col.objects.link(new_pipe)
            new_pipe.parent       = new_root
            new_pipe.matrix_world = src_pipe_matrix

            # Copy modifiers except Join-Tail GeoNodes (rebuilt in step 4)
            for mod in pipe_obj.modifiers:
                if mod.name == "FiguHair Join Tail":
                    continue
                new_mod = new_pipe.modifiers.new(mod.name, mod.type)
                for attr in dir(mod):
                    if attr.startswith('_') or attr in {
                        'bl_rna', 'rna_type', 'name', 'type', 'node_group'
                    }:
                        continue
                    try:
                        setattr(new_mod, attr, getattr(mod, attr))
                    except (AttributeError, TypeError):
                        pass

        # ── 4. Tail mesh ──────────────────────────────────────────────────
        new_tail = None
        if tail_obj is not None:
            new_tail_data       = tail_obj.data.copy()
            new_tail_data.name  = new_base + " Tail"
            new_tail            = bpy.data.objects.new(new_base + " Tail", new_tail_data)
            new_tail["hair_pipe_tail_source_curve"] = new_curve.name
            new_tail["hair_pipe_tail_ring_count"]   = tail_obj.get("hair_pipe_tail_ring_count", 0)
            for key in (
                "hair_pipe_tail_direction", "hair_pipe_tail_connection_ring",
                "hair_pipe_tail_lower_ring_count", "hair_pipe_tail_user_hidden",
            ):
                val = tail_obj.get(key)
                if val is not None:
                    new_tail[key] = val
            new_tail.show_in_front = False
            new_tail.hide_render   = True
            new_tail.hide_viewport = tail_obj.hide_viewport
            new_tail.display_type  = tail_obj.display_type
            target_col.objects.link(new_tail)
            new_tail.parent       = new_root
            new_tail.matrix_world = src_tail_matrix

            if new_pipe is not None:
                ensure_tail_modifier_stack(new_pipe, new_tail, new_curve.hair_pipe_settings)

        # ── 5. Activate the new curve ─────────────────────────────────────
        for o in context.selected_objects:
            o.select_set(False)
        new_curve.select_set(True)
        context.view_layer.objects.active = new_curve

        self.report({'INFO'}, f"\u5df2\u590d\u5236\u5934\u53d1: {new_base}")
        return {'FINISHED'}


class HAIRPIPE_OT_merge_hair_for_export(bpy.types.Operator):
    """\u5c06\u6240\u6709\u5934\u53d1\u7f51\u683c\u5408\u5e76\u4e3a\u5355\u4e00\u7f51\u683c\u7528\u4e8e\u5bfc\u51fa\uff0c\u5e76\u9690\u85cf\u539f\u59cb\u5934\u53d1"""
    bl_idname = "hair_pipe.merge_hair_for_export"
    bl_label = "\u5408\u5e76\u5934\u53d1\u7f51\u683c"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(_is_hair_pipe_mesh_obj(o) for o in bpy.data.objects)

    def execute(self, context):
        import bmesh as _bmesh

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        pipe_objs = [o for o in bpy.data.objects if _is_pipe_mesh_obj(o)]

        if not pipe_objs:
            self.report({'ERROR'}, "\u573a\u666f\u4e2d\u672a\u627e\u5230\u4efb\u4f55\u5934\u53d1\u7f51\u683c")
            return {'CANCELLED'}

        all_verts = []
        all_faces = []

        for pipe_obj in pipe_objs:
            pipe_matrix = pipe_obj.matrix_world

            # ── pipe raw mesh (no modifiers) ──────────────────────────────
            pipe_mesh = pipe_obj.data
            base = len(all_verts)
            for v in pipe_mesh.vertices:
                all_verts.append(pipe_matrix @ v.co)
            for poly in pipe_mesh.polygons:
                all_faces.append(tuple(base + i for i in poly.vertices))

            # ── tail raw mesh (no modifiers, direct .data read) ───────────
            curve_obj = get_pipe_source_curve(pipe_obj)
            tail_obj  = get_tail_object_for_curve(curve_obj) if curve_obj else None
            if tail_obj is not None:
                tail_matrix = tail_obj.matrix_world
                tail_mesh = tail_obj.data
                tail_base = len(all_verts)
                for v in tail_mesh.vertices:
                    all_verts.append(tail_matrix @ v.co)
                for poly in tail_mesh.polygons:
                    all_faces.append(tuple(tail_base + i for i in poly.vertices))

        if not all_verts:
            self.report({'ERROR'}, "\u65e0\u6cd5\u6536\u96c6\u5230\u6709\u6548\u7684\u7f51\u683c\u6570\u636e")
            return {'CANCELLED'}

        # Build merged mesh directly from collected data
        merged_mesh = bpy.data.meshes.new("HairMerged")
        merged_mesh.from_pydata(all_verts, [], all_faces)
        try:
            merged_mesh.validate(clean_customdata=False)
        except Exception:
            try:
                merged_mesh.validate()
            except Exception:
                pass
        for poly in merged_mesh.polygons:
            poly.use_smooth = True
        merged_mesh.update()

        # Place merged object in the scene collection
        merged_obj = bpy.data.objects.new("HairMerged", merged_mesh)
        context.scene.collection.objects.link(merged_obj)

        for o in context.selected_objects:
            o.select_set(False)
        merged_obj.select_set(True)
        context.view_layer.objects.active = merged_obj

        self.report({'INFO'}, f"\u5df2\u5408\u5e76 {len(pipe_objs)} \u4e2a\u5934\u53d1\u7f51\u683c\u4e3a: {merged_obj.name}")
        return {'FINISHED'}


def _is_pipe_mesh_obj(obj):
    """True for FiguHair pipe mesh objects (the generated tube)."""
    if obj.type != 'MESH':
        return False
    if obj.get("hair_pipe_source_curve"):
        return True
    if obj.name.endswith(" Mesh") and obj.parent is not None and obj.parent.type == 'EMPTY':
        return bool(obj.parent.get("hair_pipe_root"))
    if obj.name.endswith("_FiguHair"):
        return True
    return False


def _is_hair_pipe_mesh_obj(obj):
    """True for any FiguHair mesh (pipe or tail)."""
    return _is_pipe_mesh_obj(obj) or _is_tail_mesh_only_obj(obj)


def _is_tail_mesh_only_obj(obj):
    """True for FiguHair tail mesh objects."""
    if obj.type != 'MESH':
        return False
    if obj.get("hair_pipe_tail_source_curve"):
        return True
    if obj.name.endswith(" Tail") and obj.parent is not None and obj.parent.type == 'EMPTY':
        return bool(obj.parent.get("hair_pipe_root"))
    if obj.name.endswith("_FiguHairTail"):
        return True
    return False


def _is_figuhair_family_obj(obj):
    """True for any object belonging to a FiguHair hair set."""
    if _is_pipe_mesh_obj(obj) or _is_tail_mesh_only_obj(obj):
        return True
    if obj.type == 'CURVE' and obj.get("hair_pipe_base_name"):
        return True
    if obj.type == 'EMPTY' and obj.get("hair_pipe_root"):
        return True
    return False


classes = (
    HAIRPIPE_OT_generate_pipe,
    HAIRPIPE_OT_sync_points,
    HAIRPIPE_OT_toggle_cross_section_transition,
    HAIRPIPE_OT_toggle_solo_display,
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
    HAIRPIPE_OT_apply_global_mesh_selectability,
    HAIRPIPE_OT_toggle_redirect_selection,
    HAIRPIPE_OT_equalize_point_distance,
    HAIRPIPE_OT_create_tail_mesh,
    HAIRPIPE_OT_remove_tail_mesh,
    HAIRPIPE_OT_toggle_tail_visibility,
    HAIRPIPE_OT_hide_all_tail_meshes,
    HAIRPIPE_OT_edit_tail_mesh,
    HAIRPIPE_OT_duplicate_hair,
    HAIRPIPE_OT_merge_hair_for_export,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
