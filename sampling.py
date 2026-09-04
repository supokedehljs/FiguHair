import math
from mathutils import Vector
from .math_utils import safe_normalized


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


def distribute_steps_by_lengths(lengths, total_steps):
    if not lengths:
        return []
    total = sum(lengths) or 1.0
    raw = [length / total * total_steps for length in lengths]
    steps = [max(1, int(round(value))) for value in raw]
    diff = total_steps - sum(steps)
    order = sorted(range(len(lengths)), key=lambda i: raw[i] - steps[i], reverse=True)
    idx = 0
    while diff != 0 and order:
        i = order[idx % len(order)]
        if diff > 0:
            steps[i] += 1
            diff -= 1
        else:
            if steps[i] > 1:
                steps[i] -= 1
                diff += 1
        idx += 1
        if idx > 10000:
            break
    return steps


def bezier_arc_length_at_t(p0, h0_right, h1_left, p1, t, subdivisions=12):
    prev = evaluate_bezier_segment(p0, h0_right, h1_left, p1, 0.0)
    length = 0.0
    steps = max(1, subdivisions)
    for k in range(1, steps + 1):
        tk = t * k / steps
        cur = evaluate_bezier_segment(p0, h0_right, h1_left, p1, tk)
        length += (cur - prev).length
        prev = cur
    return length


def invert_bezier_arc_length(p0, h0_right, h1_left, p1, target_length, total_length):
    if total_length < 1e-8 or target_length <= 0.0:
        return 0.0
    if target_length >= total_length:
        return 1.0
    low, high = 0.0, 1.0
    for _ in range(18):
        mid = (low + high) * 0.5
        length = bezier_arc_length_at_t(p0, h0_right, h1_left, p1, mid)
        if length < target_length:
            low = mid
        else:
            high = mid
    return (low + high) * 0.5


def make_cumulative_lengths(centers, is_cyclic=False):
    lengths = [0.0]
    for i in range(1, len(centers)):
        lengths.append(lengths[-1] + (centers[i] - centers[i-1]).length)
    if is_cyclic and len(centers) > 1:
        lengths[-1] = lengths[-1] + (centers[0] - centers[-1]).length
    return lengths


def find_nearest_center_distance(centers, distances, co):
    best_idx = 0
    best_dist = None
    for idx, center in enumerate(centers):
        d = (center - co).length_squared
        if best_dist is None or d < best_dist:
            best_dist = d
            best_idx = idx
    return distances[best_idx] if distances else 0.0


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
