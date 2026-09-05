import math
import bpy
import blf
import gpu
from mathutils import Vector
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
from .cross_section import add_cross_section_vertex_after, remove_cross_section_vertex_all, get_curve_spline_point_ranges, get_active_spline_point_range
from .curve_data import get_curve_points_data, is_curve_edit_mode, get_selected_curve_point_indices
from .hair_lifecycle import get_pipe_object_for_curve, get_pipe_source_curve
from .ghost import update_all_ghost_vertices, update_ghost_vertices
from .math_utils import catmull_rom_2d, get_cross_section_frame, safe_normalized
from .pipe_generation import generate_pipe_mesh
from .widget_cache import get_cached_pipe_mesh
from .point_data import sync_point_settings

def fit_widget_scale_to_cross_section(wd, verts, half, alignment_angle, flip_h):
    points = []
    for vert in verts:
        x, y = rotate_2d(vert.offset_x, vert.offset_y, alignment_angle)
        if flip_h:
            x = -x
        points.append((x, y))
    if not points:
        return

    max_x = max(abs(x) for x, _y in points)
    max_y = max(abs(y) for _x, y in points)
    max_extent = max(max_x, max_y, 1e-6)
    wd.widget_scale_factor = max(8.0, min(50000.0, half * 0.76 / max_extent))


def is_inside_rect(x, y, x0, y0, x1, y1):
    return x0 <= x <= x1 and y0 <= y <= y1


def get_cross_section_effective_transform(curve_point, point_setting):
    curve_radius = getattr(curve_point, 'radius', 1.0) if curve_point is not None else 1.0
    curve_tilt = getattr(curve_point, 'tilt', 0.0) if curve_point is not None else 0.0
    scale = max(1e-8, curve_radius * point_setting.scale)
    rotation = math.radians(point_setting.rotation) + curve_tilt
    return scale, rotation


def get_cross_section_effective_scale(curve_point, point_setting):
    scale, _rotation = get_cross_section_effective_transform(curve_point, point_setting)
    return scale



def get_raw_offset(vertex):
    """Return raw offset_x, offset_y without radius/scale/rotation transforms."""
    return vertex.offset_x, vertex.offset_y


def get_effective_offset(vertex, curve_point, point_setting):
    scale, rotation = get_cross_section_effective_transform(curve_point, point_setting)
    x = vertex.offset_x * scale
    y = vertex.offset_y * scale
    cos_r = math.cos(rotation)
    sin_r = math.sin(rotation)
    return x * cos_r - y * sin_r, x * sin_r + y * cos_r





def chaikin_closed(points, iterations=3):
    if len(points) < 3:
        return points
    result = list(points)
    for _ in range(max(1, iterations)):
        refined = []
        count = len(result)
        for i in range(count):
            x0, y0 = result[i]
            x1, y1 = result[(i + 1) % count]
            refined.append((x0 * 0.75 + x1 * 0.25, y0 * 0.75 + y1 * 0.25))
            refined.append((x0 * 0.25 + x1 * 0.75, y0 * 0.25 + y1 * 0.75))
        result = refined
    return result


def make_smooth_preview_lines(points):
    if len(points) < 2:
        return []
    lines = []
    count = len(points)
    for i in range(count):
        lines.append(points[i])
        lines.append(points[(i + 1) % count])
    return lines


def set_vertex_from_effective_offset(vertex, effective_x, effective_y, curve_point, point_setting):
    scale, rotation = get_cross_section_effective_transform(curve_point, point_setting)
    cos_r = math.cos(rotation)
    sin_r = math.sin(rotation)
    local_x = effective_x * cos_r + effective_y * sin_r
    local_y = -effective_x * sin_r + effective_y * cos_r
    vertex.offset_x = local_x / scale
    vertex.offset_y = local_y / scale


def get_widget_target_point_indices(context, settings):
    obj = context.active_object
    if obj is None or obj.type != 'CURVE':
        return []
    selected = get_selected_curve_point_indices(obj) if is_curve_edit_mode(obj) else []
    if settings.active_point_index not in selected:
        selected.append(settings.active_point_index)
    point_range = get_active_spline_point_range(obj, settings)
    return [idx for idx in dict.fromkeys(selected) if point_range[0] <= idx < point_range[1]]


def copy_cross_section_shape(source_ps, target_ps):
    target_verts = target_ps.cross_section_verts
    while len(target_verts) > 0:
        target_verts.remove(len(target_verts) - 1)
    for source_vert in source_ps.cross_section_verts:
        target_vert = target_verts.add()
        target_vert.offset_x = source_vert.offset_x
        target_vert.offset_y = source_vert.offset_y
        target_vert.is_ghost = getattr(source_vert, 'is_ghost', False)
    target_ps.scale = source_ps.scale
    target_ps.rotation = source_ps.rotation
    target_ps.active_vert_index = min(source_ps.active_vert_index, len(target_verts) - 1)
    update_ghost_vertices(target_ps)


def sync_active_cross_section_to_selected_points(context):
    obj = context.active_object
    if obj is None or obj.type != 'CURVE':
        return
    settings = obj.hair_pipe_settings
    active_index = settings.active_point_index
    if not (0 <= active_index < len(settings.point_settings)):
        return
    source_ps = settings.point_settings[active_index]
    for target_index in get_widget_target_point_indices(context, settings):
        if target_index != active_index:
            copy_cross_section_shape(source_ps, settings.point_settings[target_index])
    update_all_ghost_vertices(settings)


def apply_active_vertex_edit_to_selected_points(context, source_ps, vert_idx):
    sync_active_cross_section_to_selected_points(context)


def get_active_curve_point_world_position(context):
    try:
        from .widget_state import get_active_curve_point as _gacp
    except Exception:
        _gacp = None
    obj = context.active_object
    if obj is None or obj.type != 'CURVE':
        return None
    point = _gacp(context) if _gacp is not None else None
    if point is None:
        return None
    if hasattr(point, 'co') and len(point.co) == 4:
        return obj.matrix_world @ Vector(point.co[:3])
    return obj.matrix_world @ point.co


def get_active_curve_tangent(context):
    obj = context.active_object
    if obj is None or obj.type != 'CURVE':
        return Vector((0, 0, 1))

    settings = obj.hair_pipe_settings
    target_index = settings.active_point_index
    global_idx = 0
    for spline in obj.data.splines:
        if spline.type == 'BEZIER':
            points = spline.bezier_points
            for idx, point in enumerate(points):
                if global_idx == target_index:
                    prev_tangent = None
                    next_tangent = None
                    if spline.use_cyclic_u or idx > 0:
                        prev_tangent = point.co - point.handle_left
                    if spline.use_cyclic_u or idx < len(points) - 1:
                        next_tangent = point.handle_right - point.co
                    if prev_tangent is not None and next_tangent is not None:
                        return safe_normalized(obj.matrix_world.to_3x3() @ (prev_tangent + next_tangent), obj.matrix_world.to_3x3() @ next_tangent)
                    if next_tangent is not None:
                        return safe_normalized(obj.matrix_world.to_3x3() @ next_tangent)
                    if prev_tangent is not None:
                        return safe_normalized(obj.matrix_world.to_3x3() @ prev_tangent)
                global_idx += 1
        else:
            points = spline.points
            for idx, point in enumerate(points):
                if global_idx == target_index:
                    co = Vector(point.co[:3])
                    prev_tangent = None
                    next_tangent = None
                    if spline.use_cyclic_u or idx > 0:
                        prev_idx = (idx - 1) % len(points)
                        prev_tangent = co - Vector(points[prev_idx].co[:3])
                    if spline.use_cyclic_u or idx < len(points) - 1:
                        next_idx = (idx + 1) % len(points)
                        next_tangent = Vector(points[next_idx].co[:3]) - co
                    if prev_tangent is not None and next_tangent is not None:
                        return safe_normalized(obj.matrix_world.to_3x3() @ (prev_tangent + next_tangent), obj.matrix_world.to_3x3() @ next_tangent)
                    if next_tangent is not None:
                        return safe_normalized(obj.matrix_world.to_3x3() @ next_tangent)
                    if prev_tangent is not None:
                        return safe_normalized(obj.matrix_world.to_3x3() @ prev_tangent)
                global_idx += 1
    return Vector((0, 0, 1))


def get_view_direction_marker(context, marker_radius):
    direction = get_view_direction_unit(context)
    if direction is None:
        return None
    return direction.x * marker_radius, direction.y * marker_radius


def get_active_curve_minimal_twist_frame(context):
    obj = context.active_object
    if obj is None or obj.type != 'CURVE':
        return None
    settings = obj.hair_pipe_settings
    target_index = settings.active_point_index
    world_3x3 = obj.matrix_world.to_3x3()
    global_idx = 0

    for spline in obj.data.splines:
        if spline.type == 'BEZIER':
            points = spline.bezier_points
            count = len(points)
            if count == 0:
                continue
            tangents = []
            for idx, point in enumerate(points):
                prev_tangent = None
                next_tangent = None
                if spline.use_cyclic_u or idx > 0:
                    prev_tangent = point.co - point.handle_left
                    if prev_tangent.length < 1e-8:
                        prev_tangent = point.co - points[(idx - 1) % count].co
                if spline.use_cyclic_u or idx < count - 1:
                    next_tangent = point.handle_right - point.co
                    if next_tangent.length < 1e-8:
                        next_tangent = points[(idx + 1) % count].co - point.co
                if prev_tangent is not None and next_tangent is not None:
                    tangent = safe_normalized(prev_tangent + next_tangent, next_tangent)
                elif next_tangent is not None:
                    tangent = safe_normalized(next_tangent)
                elif prev_tangent is not None:
                    tangent = safe_normalized(prev_tangent)
                else:
                    tangent = Vector((0, 0, 1))
                tangents.append(safe_normalized(world_3x3 @ tangent))
        else:
            points = spline.points
            count = len(points)
            if count == 0:
                continue
            tangents = []
            for idx, point in enumerate(points):
                co = Vector(point.co[:3])
                prev_tangent = None
                next_tangent = None
                if spline.use_cyclic_u or idx > 0:
                    prev_tangent = co - Vector(points[(idx - 1) % count].co[:3])
                if spline.use_cyclic_u or idx < count - 1:
                    next_tangent = Vector(points[(idx + 1) % count].co[:3]) - co
                if prev_tangent is not None and next_tangent is not None:
                    tangent = safe_normalized(prev_tangent + next_tangent, next_tangent)
                elif next_tangent is not None:
                    tangent = safe_normalized(next_tangent)
                elif prev_tangent is not None:
                    tangent = safe_normalized(prev_tangent)
                else:
                    tangent = Vector((0, 0, 1))
                tangents.append(safe_normalized(world_3x3 @ tangent))

        normal, binormal = get_cross_section_frame(tangents[0])
        for local_idx, tangent in enumerate(tangents):
            if global_idx + local_idx == target_index:
                return normal, binormal
            next_idx = (local_idx + 1) % count
            if next_idx == 0 and not spline.use_cyclic_u:
                continue
            next_tangent = tangents[next_idx]
            try:
                transport = tangents[local_idx].rotation_difference(next_tangent)
                normal = transport @ normal
            except ValueError:
                pass
            normal = normal - next_tangent * normal.dot(next_tangent)
            if normal.length < 1e-8:
                normal, binormal = get_cross_section_frame(next_tangent)
            else:
                normal.normalize()
                binormal = next_tangent.cross(normal).normalized()
        global_idx += count

    return None


def get_active_curve_stable_frame(context):
    return get_active_curve_minimal_twist_frame(context)


def get_view_direction_unit(context):
    region_data = context.region_data
    if region_data is None:
        return None
    center = get_active_curve_point_world_position(context)
    if center is None:
        return None

    view_direction = safe_normalized(region_data.view_rotation @ Vector((0, 0, -1)))
    to_camera_side = -view_direction
    stable_frame = get_active_curve_stable_frame(context)
    if stable_frame is None:
        tangent = get_active_curve_tangent(context)
        stable_frame = get_cross_section_frame(tangent)
    normal, binormal = stable_frame
    projected = Vector((to_camera_side.dot(normal), to_camera_side.dot(binormal)))
    if projected.length < 1e-8:
        return None
    projected.normalize()
    return projected


def get_view_alignment_angle(context):
    direction = get_view_direction_unit(context)
    if direction is None:
        return 0.0
    return -math.pi / 2.0 - math.atan2(direction.y, direction.x)


def get_active_view_cross_section_projection(context, ps):
    region = context.region
    region_data = context.region_data
    obj = context.active_object
    if region is None or region_data is None or obj is None or obj.type != 'CURVE':
        return []
    segments = len(ps.cross_section_verts)
    if segments < 3:
        return []

    try:
        mesh_verts, _faces = get_cached_pipe_mesh(obj)
    except Exception:
        return []
    if not mesh_verts or len(mesh_verts) < segments:
        return []

    active_center = get_active_curve_point_world_position(context)
    if active_center is None:
        return []

    best_start = None
    best_dist = None
    for start in range(0, len(mesh_verts) - segments + 1, segments):
        ring = mesh_verts[start:start + segments]
        ring_center = sum((Vector(v) for v in ring), Vector((0.0, 0.0, 0.0))) / segments
        ring_center_world = obj.matrix_world @ ring_center
        dist = (ring_center_world - active_center).length
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_start = start
    if best_start is None:
        return []

    projected = []
    for idx, vert in enumerate(mesh_verts[best_start:best_start + segments]):
        if idx >= len(ps.cross_section_verts) or getattr(ps.cross_section_verts[idx], 'is_ghost', False):
            continue
        screen_pos = view3d_utils.location_3d_to_region_2d(region, region_data, obj.matrix_world @ Vector(vert))
        if screen_pos is None:
            continue
        projected.append((idx, screen_pos.x, screen_pos.y))
    return projected


def get_active_view_extreme_cross_section_indices(context, ps):
    projected = get_active_view_cross_section_projection(context, ps)
    top_idx = -1
    left_idx = -1
    top_point = None
    left_point = None
    for idx, x, y in projected:
        point = (x, y)
        if top_point is None or y > top_point[1]:
            top_point = point
            top_idx = idx
        if left_point is None or x < left_point[0]:
            left_point = point
            left_idx = idx
    return top_idx, left_idx


def normalize_indexed_points(points):
    if not points:
        return {}, 1.0
    cx = sum(point[1] for point in points) / len(points)
    cy = sum(point[2] for point in points) / len(points)
    centered = [(idx, x - cx, y - cy) for idx, x, y in points]
    scale = max((math.sqrt(x * x + y * y) for _idx, x, y in centered), default=1.0)
    if scale < 1e-8:
        scale = 1.0
    return {idx: (x / scale, y / scale) for idx, x, y in centered}, scale


def get_auto_widget_alignment_from_view(context, ps):
    view_points = get_active_view_cross_section_projection(context, ps)
    verts = ps.cross_section_verts
    real_indices = [idx for idx, vert in enumerate(verts) if not getattr(vert, 'is_ghost', False)]
    view_map, _view_scale = normalize_indexed_points(view_points)
    shared_indices = [idx for idx in real_indices if idx in view_map]
    if len(shared_indices) < 3:
        return get_view_alignment_angle(context), False

    top_idx = max(shared_indices, key=lambda idx: view_map[idx][1])
    left_idx = min(shared_indices, key=lambda idx: view_map[idx][0])

    def widget_map(angle, flip_h):
        points = []
        for idx in shared_indices:
            x, y = get_raw_offset(verts[idx])
            rx, ry = rotate_2d(x, y, angle)
            if flip_h:
                rx = -rx
            points.append((idx, rx, ry))
        normalized, _scale = normalize_indexed_points(points)
        return normalized

    def alignment_score(angle, flip_h):
        candidate = widget_map(angle, flip_h)
        if len(candidate) != len(shared_indices):
            return float('inf')
        shape_error = 0.0
        for idx in shared_indices:
            vx, vy = view_map[idx]
            wx, wy = candidate[idx]
            shape_error += (wx - vx) ** 2 + (wy - vy) ** 2
        shape_error /= max(1, len(shared_indices))

        max_y = max(candidate[idx][1] for idx in shared_indices)
        min_x = min(candidate[idx][0] for idx in shared_indices)
        top_error = (max_y - candidate[top_idx][1]) ** 2
        left_error = (candidate[left_idx][0] - min_x) ** 2
        return shape_error + (top_error + left_error) * 0.35

    best_angle = 0.0
    best_flip = False
    best_score = float('inf')
    for flip_h in (False, True):
        for degree in range(360):
            angle = math.radians(degree)
            score = alignment_score(angle, flip_h)
            if score < best_score:
                best_score = score
                best_angle = angle
                best_flip = flip_h

    step_size = math.radians(0.1)
    search_radius = math.radians(2.0)
    for _ in range(3):
        improved_angle = best_angle
        improved_score = best_score
        steps = max(1, int(search_radius / step_size))
        for step in range(-steps, steps + 1):
            angle = best_angle + step * step_size
            score = alignment_score(angle, best_flip)
            if score < improved_score:
                improved_score = score
                improved_angle = angle
        best_angle = improved_angle
        best_score = improved_score
        search_radius *= 0.25
        step_size *= 0.25

    return best_angle, best_flip


def get_stable_widget_alignment(context, ps, wd):
    region_data = context.region_data
    view_signature = repr(tuple(round(value, 5) for row in region_data.view_matrix for value in row)) if region_data else ""
    signature = f"{context.active_object.hair_pipe_settings.active_point_index}:{view_signature}"
    if getattr(wd, 'auto_alignment_initialized', False) and wd.auto_alignment_signature == signature:
        return wd.auto_alignment_angle, wd.auto_alignment_flip_h

    angle, flip_h = get_auto_widget_alignment_from_view(context, ps)
    wd.auto_alignment_angle = angle
    wd.auto_alignment_flip_h = flip_h
    wd.auto_alignment_signature = signature
    wd.auto_alignment_initialized = True
    return angle, flip_h


def rotate_2d(x, y, angle):
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    return x * cos_a - y * sin_a, x * sin_a + y * cos_a


def effective_to_widget(x, y, cx, cy, sf, alignment_angle, flip_h=False):
    rx, ry = rotate_2d(x, y, alignment_angle)
    if flip_h:
        rx = -rx
    return cx + rx * sf, cy + ry * sf


def widget_to_effective(mx, my, cx, cy, sf, alignment_angle, flip_h=False):
    sx = (mx - cx) / sf
    sy = (my - cy) / sf
    if flip_h:
        sx = -sx
    return rotate_2d(sx, sy, -alignment_angle)


def add_cross_section_vertex(ps, settings):
    verts = ps.cross_section_verts
    n = len(verts)
    active_point_index = settings.active_point_index
    if n < 2:
        context = bpy.context
        point_range = get_active_spline_point_range(context.active_object, settings)
        for idx in range(point_range[0], point_range[1]):
            point_setting = settings.point_settings[idx]
            v = point_setting.cross_section_verts.add()
            v.offset_x = settings.default_radius
            v.offset_y = 0.0
            v.is_ghost = idx != active_point_index
            point_setting.active_vert_index = len(point_setting.cross_section_verts) - 1
        return

    idx = max(0, min(ps.active_vert_index, n - 1))
    point_range = get_active_spline_point_range(context.active_object, settings)
    add_cross_section_vertex_after_all(settings, idx, point_range)


def add_cross_section_vertex_after_all(settings, active_index, idx, point_range=None):
    start, end = point_range or (0, len(settings.point_settings))
    for point_idx in range(start, end):
        point_setting = settings.point_settings[point_idx]
        if len(point_setting.cross_section_verts) >= 2:
            add_cross_section_vertex_after(point_setting, idx, point_idx != active_index)


def insert_cross_section_vertex_on_edge(ps, edge_idx, local_x, local_y, curve_point=None, is_ghost=False):
    verts = ps.cross_section_verts
    n = len(verts)
    edge_idx = max(0, min(edge_idx, n - 1))
    v = verts.add()
    if curve_point is None:
        v.offset_x = local_x
        v.offset_y = local_y
    else:
        set_vertex_from_effective_offset(v, local_x, local_y, curve_point, ps)
    v.is_ghost = is_ghost
    target = edge_idx + 1
    for i in range(len(verts) - 1, target, -1):
        verts.move(i, i - 1)
    ps.active_vert_index = target


def insert_cross_section_vertex_on_edge_at_ratio(ps, edge_idx, edge_t, is_ghost=True):
    verts = ps.cross_section_verts
    n = len(verts)
    edge_idx = max(0, min(edge_idx, n - 1))
    idx_next = (edge_idx + 1) % n
    local_x = verts[edge_idx].offset_x * (1.0 - edge_t) + verts[idx_next].offset_x * edge_t
    local_y = verts[edge_idx].offset_y * (1.0 - edge_t) + verts[idx_next].offset_y * edge_t
    insert_cross_section_vertex_on_edge(ps, edge_idx, local_x, local_y, is_ghost=is_ghost)


def insert_cross_section_vertex_on_edge_all(settings, active_index, edge_idx, local_x, local_y, edge_t, curve_point):
    context = bpy.context
    point_range = get_active_spline_point_range(context.active_object, settings)
    for idx in range(point_range[0], point_range[1]):
        point_setting = settings.point_settings[idx]
        if len(point_setting.cross_section_verts) < 2:
            continue
        if idx == active_index:
            insert_cross_section_vertex_on_edge(point_setting, edge_idx, local_x, local_y, curve_point, is_ghost=False)
        else:
            insert_cross_section_vertex_on_edge_at_ratio(point_setting, edge_idx, edge_t, is_ghost=True)


def distance_point_to_segment(px, py, ax, ay, bx, by):
    abx = bx - ax
    aby = by - ay
    apx = px - ax
    apy = py - ay
    ab_len_sq = abx * abx + aby * aby
    if ab_len_sq < 1e-8:
        return math.sqrt((px - ax) ** 2 + (py - ay) ** 2), ax, ay, 0.0
    t = max(0.0, min(1.0, (apx * abx + apy * aby) / ab_len_sq))
    cx = ax + abx * t
    cy = ay + aby * t
    return math.sqrt((px - cx) ** 2 + (py - cy) ** 2), cx, cy, t



def find_nearest_raw_edge(verts, mx, my, panel_cx, panel_cy, panel_sf, alignment_angle, flip_h=False):
    """Find nearest edge using raw offsets."""
    closest_idx = -1
    closest_dist = 18.0
    closest_local = (0.0, 0.0)
    closest_t = 0.5
    n = len(verts)
    for i in range(n):
        j = (i + 1) % n
        ix, iy = get_raw_offset(verts[i])
        jx, jy = get_raw_offset(verts[j])
        ax, ay = effective_to_widget(ix, iy, panel_cx, panel_cy, panel_sf, alignment_angle, flip_h)
        bx, by = effective_to_widget(jx, jy, panel_cx, panel_cy, panel_sf, alignment_angle, flip_h)
        dist, hit_x, hit_y, edge_t = distance_point_to_segment(mx, my, ax, ay, bx, by)
        if dist < closest_dist:
            closest_dist = dist
            closest_idx = i
            closest_local = widget_to_effective(hit_x, hit_y, panel_cx, panel_cy, panel_sf, alignment_angle, flip_h)
            closest_t = edge_t
    return closest_idx, closest_local, closest_t


def find_nearest_cross_section_edge(verts, mx, my, cx, cy, sf, curve_point, point_setting, alignment_angle, flip_h=False):
    closest_idx = -1
    closest_dist = 18.0
    closest_local = (0.0, 0.0)
    closest_t = 0.5
    n = len(verts)
    for i in range(n):
        j = (i + 1) % n
        ix, iy = get_effective_offset(verts[i], curve_point, point_setting)
        jx, jy = get_effective_offset(verts[j], curve_point, point_setting)
        ax, ay = effective_to_widget(ix, iy, cx, cy, sf, alignment_angle, flip_h)
        bx, by = effective_to_widget(jx, jy, cx, cy, sf, alignment_angle, flip_h)
        dist, hit_x, hit_y, edge_t = distance_point_to_segment(mx, my, ax, ay, bx, by)
        if dist < closest_dist:
            closest_dist = dist
            closest_idx = i
            closest_local = widget_to_effective(hit_x, hit_y, cx, cy, sf, alignment_angle, flip_h)
            closest_t = edge_t
    return closest_idx, closest_local, closest_t



def find_nearest_raw_vertex(verts, mx, my, panel_cx, panel_cy, panel_sf, alignment_angle, flip_h, max_dist=10.0):
    """Find nearest vertex using raw offsets."""
    closest_idx = -1
    closest_dist = max_dist
    for i, v in enumerate(verts):
        ox, oy = get_raw_offset(v)
        px, py = effective_to_widget(ox, oy, panel_cx, panel_cy, panel_sf, alignment_angle, flip_h)
        dist = math.sqrt((mx - px) ** 2 + (my - py) ** 2)
        if dist < closest_dist:
            closest_dist = dist
            closest_idx = i
    return closest_idx


def find_nearest_cross_section_vertex(verts, mx, my, cx, cy, sf, curve_point, point_setting, alignment_angle, max_dist=24.0, flip_h=False):
    closest_idx = -1
    closest_dist = max_dist
    for i, v in enumerate(verts):
        ox, oy = get_effective_offset(v, curve_point, point_setting)
        px, py = effective_to_widget(ox, oy, cx, cy, sf, alignment_angle, flip_h)
        dist = math.sqrt((mx - px) ** 2 + (my - py) ** 2)
        if dist < closest_dist:
            closest_dist = dist
            closest_idx = i
    return closest_idx


def toggle_ghost_between_selected_edge_points(ps, selected_indices):
    verts = ps.cross_section_verts
    n = len(verts)
    if n < 3 or len(selected_indices) != 2:
        return False
    a, b = sorted(selected_indices)
    if a == b:
        return False
    changed = False
    if (a + 1) % n == b and getattr(verts[a], 'is_ghost', False):
        verts[a].is_ghost = False
        changed = True
    if (b + 1) % n == a and getattr(verts[b], 'is_ghost', False):
        verts[b].is_ghost = False
        changed = True
    if (a + 1) % n != b:
        for idx in range(a + 1, b):
            if getattr(verts[idx], 'is_ghost', False):
                verts[idx].is_ghost = False
                changed = True
    if (b + 1) % n != a:
        idx = (b + 1) % n
        while idx != a:
            if getattr(verts[idx], 'is_ghost', False):
                verts[idx].is_ghost = False
                changed = True
            idx = (idx + 1) % n
    return changed


def remove_cross_section_vertex(ps):
    verts = ps.cross_section_verts
    if len(verts) <= 3:
        return False
    idx = max(0, min(ps.active_vert_index, len(verts) - 1))
    verts.remove(idx)
    ps.active_vert_index = min(idx, len(verts) - 1)
    return True


def remove_selected_cross_section_vertices(settings, ps, selected_indices):
    indices = sorted({idx for idx in selected_indices if 0 <= idx < len(ps.cross_section_verts)}, reverse=True)
    if not indices or len(ps.cross_section_verts) - len(indices) < 3:
        return False

    context = bpy.context
    point_range = get_active_spline_point_range(context.active_object, settings)
    for point_idx in range(point_range[0], point_range[1]):
        point_setting = settings.point_settings[point_idx]
        verts = point_setting.cross_section_verts
        for idx in indices:
            if 0 <= idx < len(verts):
                verts.remove(idx)
        point_setting.active_vert_index = min(indices[-1], len(verts) - 1)

    update_all_ghost_vertices(settings)
    return True


