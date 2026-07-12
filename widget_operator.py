import bpy
import gpu
import math
import json
import blf
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
from bpy.props import IntProperty, FloatProperty, BoolProperty
from bpy.types import PropertyGroup
from mathutils import Vector
from .operators import (
    generate_pipe_mesh,
    get_curve_points_data,
    get_effective_point_setting,
    interpolate_cross_sections_smooth,
    get_pipe_source_curve,
    get_pipe_object_for_curve,
    is_transition_point,
    is_curve_edit_mode,
    get_selected_curve_point_indices,
    sync_active_point_from_selection,
    sync_point_settings,
    catmull_rom_2d,
    update_ghost_vertices,
    update_all_ghost_vertices,
    safe_normalized,
    get_cross_section_frame,
    add_cross_section_vertex_after,
    remove_cross_section_vertex_all,
)


_draw_handle = None
_addon_keymaps = []
_PIPE_BASEMESH_STATE_KEY = "hair_pipe_widget_basemesh_state"
_CURVE_OVERLAY_STATE_KEY = "hair_pipe_widget_curve_overlay_state"


class HairPipeWidgetSettings(PropertyGroup):
    """Runtime state for the cross-section widget"""
    widget_center_x: FloatProperty(default=0.0)
    widget_center_y: FloatProperty(default=0.0)
    widget_size: FloatProperty(default=320.0)
    widget_scale_factor: FloatProperty(default=1.0)
    is_active: BoolProperty(default=False)
    drag_vert_index: IntProperty(default=-1)
    drag_panel: IntProperty(default=0)
    left_drag_pending: BoolProperty(default=False)
    left_drag_active: BoolProperty(default=False)
    left_drag_start_x: FloatProperty(default=0.0)
    left_drag_start_y: FloatProperty(default=0.0)
    left_drag_vert_index: IntProperty(default=-1)
    lasso_select_active: BoolProperty(default=False)
    lasso_points: bpy.props.StringProperty(default="")
    region_offset_x: IntProperty(default=0)
    region_offset_y: IntProperty(default=0)
    hold_key_mode: BoolProperty(default=False)
    add_button_x0: FloatProperty(default=0.0)
    add_button_y0: FloatProperty(default=0.0)
    add_button_x1: FloatProperty(default=0.0)
    add_button_y1: FloatProperty(default=0.0)
    remove_button_x0: FloatProperty(default=0.0)
    remove_button_y0: FloatProperty(default=0.0)
    remove_button_x1: FloatProperty(default=0.0)
    remove_button_y1: FloatProperty(default=0.0)
    toggle_button_x0: FloatProperty(default=0.0)
    toggle_button_y0: FloatProperty(default=0.0)
    toggle_button_x1: FloatProperty(default=0.0)
    toggle_button_y1: FloatProperty(default=0.0)
    flip_button_x0: FloatProperty(default=0.0)
    flip_button_y0: FloatProperty(default=0.0)
    flip_button_x1: FloatProperty(default=0.0)
    flip_button_y1: FloatProperty(default=0.0)
    idx_button_x0: FloatProperty(default=0.0)
    idx_button_y0: FloatProperty(default=0.0)
    idx_button_x1: FloatProperty(default=0.0)
    idx_button_y1: FloatProperty(default=0.0)
    flip_horizontal: BoolProperty(default=False)
    selected_verts: bpy.props.StringProperty(default="")
    source_curve_name: bpy.props.StringProperty(default="")
    box_select_active: BoolProperty(default=False)
    box_select_3d: BoolProperty(default=False)
    box_x0: FloatProperty(default=0.0)
    box_y0: FloatProperty(default=0.0)
    box_x1: FloatProperty(default=0.0)
    box_y1: FloatProperty(default=0.0)
    rotate_active: BoolProperty(default=False)
    move_active: BoolProperty(default=False)
    scale_active: BoolProperty(default=False)
    display_scale_active: BoolProperty(default=False)
    left_drag_started_inside_widget: BoolProperty(default=False)
    show_vert_indices: BoolProperty(default=False)
    show_full_mesh_grid: BoolProperty(default=False)
    show_smooth_preview: BoolProperty(default=False)
    rotate_start_x: FloatProperty(default=0.0)
    rotate_start_y: FloatProperty(default=0.0)
    move_start_x: FloatProperty(default=0.0)
    move_start_y: FloatProperty(default=0.0)
    scale_start_x: FloatProperty(default=0.0)
    scale_start_y: FloatProperty(default=0.0)
    scale_start_factor: FloatProperty(default=1.0)
    auto_alignment_angle: FloatProperty(default=0.0)
    auto_alignment_flip_h: BoolProperty(default=False)
    auto_alignment_initialized: BoolProperty(default=False)
    rotate_initial_offsets: bpy.props.StringProperty(default="")
    rotate_button_x0: FloatProperty(default=0.0)
    rotate_button_y0: FloatProperty(default=0.0)
    rotate_button_x1: FloatProperty(default=0.0)
    rotate_button_y1: FloatProperty(default=0.0)
    corr_rot_x0: FloatProperty(default=0.0)
    corr_rot_y0: FloatProperty(default=0.0)
    corr_rot_x1: FloatProperty(default=0.0)
    corr_rot_y1: FloatProperty(default=0.0)
    corr_rot_dragging: bpy.props.BoolProperty(default=False)
    corr_rot_drag_start_x: FloatProperty(default=0.0)
    corr_rot_drag_start_angle: FloatProperty(default=0.0)
    corr_rot_drag_start_val: FloatProperty(default=0.0)
    undo_stack: bpy.props.StringProperty(default="[]")



def get_selected_widget_verts(wd):
    raw = wd.selected_verts.strip()
    if not raw:
        return set()
    return set(int(x) for x in raw.split(",") if x.strip().isdigit())


def set_selected_widget_verts(wd, indices):
    wd.selected_verts = ",".join(str(i) for i in sorted(indices))


def get_lasso_points(wd):
    raw = wd.lasso_points.strip()
    if not raw:
        return []
    result = []
    for part in raw.split(";"):
        xy = part.split(":")
        if len(xy) == 2:
            try:
                result.append((float(xy[0]), float(xy[1])))
            except ValueError:
                pass
    return result


def set_lasso_points(wd, points):
    wd.lasso_points = ";".join(f"{x}:{y}" for x, y in points)


def append_lasso_point(wd, x, y):
    points = get_lasso_points(wd)
    if not points or math.sqrt((points[-1][0] - x) ** 2 + (points[-1][1] - y) ** 2) >= 4.0:
        points.append((x, y))
        set_lasso_points(wd, points)


def point_in_polygon(px, py, polygon):
    if len(polygon) < 3:
        return False
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / max(yj - yi, 1e-8) + xi):
            inside = not inside
        j = i
    return inside


def store_rotate_offsets(wd, verts, indices):
    parts = []
    for i in indices:
        if i < len(verts):
            parts.append(str(verts[i].offset_x) + ":" + str(verts[i].offset_y))
        else:
            parts.append("0:0")
    wd.rotate_initial_offsets = ";".join(parts)


def get_rotate_offsets(wd):
    raw = wd.rotate_initial_offsets.strip()
    if not raw:
        return []
    result = []
    for part in raw.split(";"):
        xy = part.split(":")
        if len(xy) == 2:
            result.append((float(xy[0]), float(xy[1])))
    return result



def get_neighbor_point_indices(settings):
    """Return (prev_idx, current_idx, next_idx) for point settings."""
    current = settings.active_point_index
    total = len(settings.point_settings)
    if total <= 1:
        return -1, current, -1
    prev_idx = current - 1 if current > 0 else -1
    next_idx = current + 1 if current < total - 1 else -1
    return prev_idx, current, next_idx


def get_curve_point_by_index(context, idx):
    """Get curve point by global index."""
    obj = context.active_object
    if obj is None or obj.type != 'CURVE':
        return None
    global_idx = 0
    for spline in obj.data.splines:
        points = spline.bezier_points if spline.type == 'BEZIER' else spline.points
        for point in points:
            if global_idx == idx:
                return point
            global_idx += 1
    return None


def draw_circle_points(shader, points, color, radius, segments=20):
    if not points:
        return
    circles = []
    indices = []
    for p in points:
        center_index = len(circles)
        circles.append(p)
        for i in range(segments):
            angle = (i / segments) * math.tau
            circles.append((p[0] + math.cos(angle) * radius, p[1] + math.sin(angle) * radius))
        for i in range(1, segments + 1):
            i1 = center_index + i
            i2 = center_index + (i % segments) + 1
            indices.append((center_index, i1, i2))
    batch = batch_for_shader(shader, 'TRIS', {"pos": circles}, indices=indices)
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def draw_circle_outline(shader, points, color, radius, segments=24, line_width=1.4):
    if not points:
        return
    lines = []
    for p in points:
        ring = []
        for i in range(segments):
            angle = (i / segments) * math.tau
            ring.append((p[0] + math.cos(angle) * radius, p[1] + math.sin(angle) * radius))
        for i in range(segments):
            lines.append(ring[i])
            lines.append(ring[(i + 1) % segments])
    gpu.state.line_width_set(line_width)
    batch = batch_for_shader(shader, 'LINES', {"pos": lines})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def draw_single_cross_section(shader, verts, ps, settings,
                               panel_cx, panel_cy, panel_sf, alignment_angle,
                               flip_h, panel_half, is_active, wd=None):
    """Draw one cross-section panel using raw offsets (uniform size)."""
    n = len(verts)
    if n < 3:
        return

    alpha_mult = 1.0 if is_active else 0.6

    if wd is None or getattr(wd, 'show_smooth_preview', True):
        raw_points = [get_raw_offset(v) for v in verts]
        smooth_raw = chaikin_closed(raw_points, 3)
        smooth_widget_points = [effective_to_widget(x, y, panel_cx, panel_cy, panel_sf, alignment_angle, flip_h) for x, y in smooth_raw]
        smooth_lines = make_smooth_preview_lines(smooth_widget_points)
        if smooth_lines:
            gpu.state.line_width_set(1.5 if is_active else 1.0)
            batch = batch_for_shader(shader, 'LINES', {"pos": smooth_lines})
            shader.bind()
            shader.uniform_float("color", (0.0, 0.95, 1.0, 0.8 * alpha_mult))
            batch.draw(shader)

    outline = []
    ghost_edges = []
    for i in range(n):
        j = (i + 1) % n
        ix, iy = get_raw_offset(verts[i])
        jx, jy = get_raw_offset(verts[j])
        p0 = effective_to_widget(ix, iy, panel_cx, panel_cy, panel_sf, alignment_angle, flip_h)
        p1 = effective_to_widget(jx, jy, panel_cx, panel_cy, panel_sf, alignment_angle, flip_h)
        if getattr(verts[i], 'is_ghost', False) or getattr(verts[j], 'is_ghost', False):
            ghost_edges.extend([p0, p1])
        else:
            outline.extend([p0, p1])
    if outline:
        gpu.state.line_width_set(2.0 if is_active else 1.5)
        batch = batch_for_shader(shader, 'LINES', {"pos": outline})
        shader.bind()
        shader.uniform_float("color", (1.0, 0.8, 0.05, 1.0 * alpha_mult))
        batch.draw(shader)
    if ghost_edges:
        gpu.state.line_width_set(2.0 if is_active else 1.5)
        batch = batch_for_shader(shader, 'LINES', {"pos": ghost_edges})
        shader.bind()
        shader.uniform_float("color", (0.45, 0.65, 1.0, 0.82 * alpha_mult))
        batch.draw(shader)

    normal_pts = []
    for v in verts:
        if getattr(v, 'is_ghost', False):
            continue
        ox, oy = get_raw_offset(v)
        normal_pts.append(effective_to_widget(ox, oy, panel_cx, panel_cy, panel_sf, alignment_angle, flip_h))
    if normal_pts:
        draw_circle_points(shader, normal_pts, (1.0, 1.0, 1.0, 0.9 * alpha_mult), 5.0 if is_active else 4.0)

    if is_active:
        if wd is not None:
            sel_indices = get_selected_widget_verts(wd)
            if sel_indices:
                sel_pts = []
                for si in sel_indices:
                    if 0 <= si < n and not getattr(verts[si], 'is_ghost', False):
                        sx, sy = get_raw_offset(verts[si])
                        sel_pts.append(effective_to_widget(sx, sy, panel_cx, panel_cy, panel_sf, alignment_angle, flip_h))
                if sel_pts:
                    draw_circle_points(shader, sel_pts, (1.0, 0.5, 0.0, 1.0), 5.0)




def select_curve_point_by_index(obj, target_idx):
    """Select a specific curve point by global index, deselecting others."""
    if obj is None or obj.type != 'CURVE':
        return
    global_idx = 0
    for spline in obj.data.splines:
        if spline.type == 'BEZIER':
            for point in spline.bezier_points:
                is_target = (global_idx == target_idx)
                point.select_control_point = is_target
                point.select_left_handle = is_target
                point.select_right_handle = is_target
                global_idx += 1
        else:
            for point in spline.points:
                point.select = (global_idx == target_idx)
                global_idx += 1


def get_curve_start_world_position(obj):
    if obj is None or obj.type != 'CURVE':
        return None
    if len(obj.data.splines) == 0:
        return None
    spline = obj.data.splines[0]
    if spline.type == 'BEZIER':
        if len(spline.bezier_points) == 0:
            return None
        return obj.matrix_world @ spline.bezier_points[0].co
    if len(spline.points) == 0:
        return None
    return obj.matrix_world @ Vector(spline.points[0].co[:3])


def draw_curve_highlight_lines(context, obj):
    if obj is None or obj.type != 'CURVE':
        return
    if is_curve_edit_mode(obj):
        return
    region = context.region
    region_data = context.region_data
    if region is None or region_data is None:
        return

    lines = []
    for spline in obj.data.splines:
        if spline.type == 'BEZIER':
            points = spline.bezier_points
            coords = [obj.matrix_world @ point.co for point in points]
        else:
            points = spline.points
            coords = [obj.matrix_world @ Vector(point.co[:3]) for point in points]
        projected = []
        for co in coords:
            pos = view3d_utils.location_3d_to_region_2d(region, region_data, co)
            if pos is not None:
                projected.append((pos.x, pos.y))
        if not projected:
            continue
        for idx in range(len(projected) - 1):
            lines.append(projected[idx])
            lines.append(projected[idx + 1])
        if spline.use_cyclic_u and len(projected) > 2:
            lines.append(projected[-1])
            lines.append(projected[0])

    if not lines:
        return

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(2.0)
    batch = batch_for_shader(shader, 'LINES', {"pos": lines})
    shader.bind()
    shader.uniform_float("color", (1.0, 0.78, 0.05, 0.55))
    batch.draw(shader)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def draw_selected_curves_highlight(context):
    highlighted = set()
    for selected in context.selected_objects:
        curve_obj = None
        if selected.type == 'CURVE' and hasattr(selected, 'hair_pipe_settings'):
            curve_obj = selected
        elif selected.type == 'MESH':
            curve_obj = get_pipe_source_curve(selected)
        if curve_obj is None or curve_obj.name in highlighted:
            continue
        highlighted.add(curve_obj.name)
        draw_curve_highlight_lines(context, curve_obj)


def draw_curve_start_marker(context, obj):
    region = context.region
    region_data = context.region_data
    if region is None or region_data is None:
        return
    start_world = get_curve_start_world_position(obj)
    if start_world is None:
        return
    pos = view3d_utils.location_3d_to_region_2d(region, region_data, start_world)
    if pos is None:
        return

    x, y = pos.x, pos.y
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.point_size_set(18.0)
    batch = batch_for_shader(shader, 'POINTS', {"pos": [(x, y)]})
    shader.bind()
    shader.uniform_float("color", (0.1, 1.0, 0.15, 1.0))
    batch.draw(shader)

    marker_lines = [
        (x - 10.0, y), (x + 10.0, y),
        (x, y - 10.0), (x, y + 10.0),
    ]
    gpu.state.line_width_set(2.0)
    batch = batch_for_shader(shader, 'LINES', {"pos": marker_lines})
    shader.bind()
    shader.uniform_float("color", (0.1, 1.0, 0.15, 1.0))
    batch.draw(shader)

    font_id = 0
    blf.size(font_id, 14)
    blf.color(font_id, 0.1, 1.0, 0.15, 1.0)
    blf.position(font_id, x + 12.0, y + 8.0, 0)
    blf.draw(font_id, "Start")

    gpu.state.point_size_set(1.0)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def draw_transition_point_markers(context, obj, settings):
    if not is_curve_edit_mode(obj):
        return
    region = context.region
    region_data = context.region_data
    if region is None or region_data is None:
        return

    marker_points = []
    marker_labels = []
    global_idx = 0
    for spline in obj.data.splines:
        points = spline.bezier_points if spline.type == 'BEZIER' else spline.points
        for point in points:
            if global_idx < len(settings.point_settings) and is_transition_point(settings.point_settings[global_idx]):
                co = Vector(point.co[:3]) if hasattr(point, 'co') and len(point.co) == 4 else point.co
                pos = view3d_utils.location_3d_to_region_2d(region, region_data, obj.matrix_world @ co)
                if pos is not None:
                    marker_points.append((pos.x, pos.y))
                    marker_labels.append((global_idx, pos.x, pos.y))
            global_idx += 1

    if not marker_points:
        return

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.point_size_set(22.0)
    batch = batch_for_shader(shader, 'POINTS', {"pos": marker_points})
    shader.bind()
    shader.uniform_float("color", (0.0, 0.85, 1.0, 1.0))
    batch.draw(shader)

    cross_lines = []
    for _idx, x, y in marker_labels:
        cross_lines.extend([(x - 8.0, y - 8.0), (x + 8.0, y + 8.0), (x - 8.0, y + 8.0), (x + 8.0, y - 8.0)])
    gpu.state.line_width_set(2.0)
    batch = batch_for_shader(shader, 'LINES', {"pos": cross_lines})
    shader.bind()
    shader.uniform_float("color", (0.02, 0.12, 0.16, 0.95))
    batch.draw(shader)

    font_id = 0
    blf.size(font_id, 12)
    blf.color(font_id, 0.0, 0.9, 1.0, 1.0)
    for idx, x, y in marker_labels:
        blf.position(font_id, x + 10.0, y + 8.0, 0)
        blf.draw(font_id, f"AUTO {idx}")

    gpu.state.point_size_set(1.0)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def draw_active_pipe_cross_section_ring(context, ps):
    region = context.region
    region_data = context.region_data
    obj = context.active_object
    if region is None or region_data is None or obj is None or obj.type != 'CURVE':
        return
    if len(ps.cross_section_verts) < 3:
        return

    try:
        mesh_verts, _faces = generate_pipe_mesh(obj, obj.hair_pipe_settings)
    except Exception:
        mesh_verts = None
    if not mesh_verts:
        return

    segments = len(ps.cross_section_verts)
    if segments < 3 or len(mesh_verts) < segments:
        return

    selected_curve_indices = get_selected_curve_point_indices(obj) if is_curve_edit_mode(obj) else []
    active_idx = obj.hair_pipe_settings.active_point_index
    if active_idx not in selected_curve_indices:
        selected_curve_indices.append(active_idx)

    control_positions = []
    for spline_data in get_curve_points_data(obj):
        for point_data in spline_data.get('points', []):
            control_positions.append(obj.matrix_world @ point_data['co'])

    ring_candidates = []
    for start in range(0, len(mesh_verts) - segments + 1, segments):
        ring = mesh_verts[start:start + segments]
        ring_center = sum((Vector(v) for v in ring), Vector((0.0, 0.0, 0.0))) / segments
        ring_candidates.append((start, obj.matrix_world @ ring_center))

    selected_ring_starts = []
    used_starts = set()
    for point_idx in selected_curve_indices:
        if not (0 <= point_idx < len(control_positions)):
            continue
        point_setting = obj.hair_pipe_settings.point_settings[point_idx] if point_idx < len(obj.hair_pipe_settings.point_settings) else None
        if point_setting is not None and is_transition_point(point_setting):
            continue
        world_center = control_positions[point_idx]
        best_start = None
        best_dist = None
        for start, ring_center_world in ring_candidates:
            dist = (ring_center_world - world_center).length
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_start = start
        if best_start is not None and best_start not in used_starts:
            selected_ring_starts.append((point_idx, best_start))
            used_starts.add(best_start)

    if not selected_ring_starts:
        return

    wd = context.window_manager.hair_pipe_widget
    show_full_grid = bool(getattr(wd, 'show_full_mesh_grid', False))
    ring_count = len(mesh_verts) // segments
    view_forward = region_data.view_rotation @ Vector((0.0, 0.0, -1.0))
    camera_dir = -safe_normalized(view_forward)
    projected_rings = []
    front_masks = []
    for ring_idx in range(ring_count):
        start = ring_idx * segments
        ring_world = [obj.matrix_world @ Vector(vert) for vert in mesh_verts[start:start + segments]]
        if len(ring_world) != segments:
            projected_rings.append(None)
            front_masks.append(None)
            continue
        ring_center = sum(ring_world, Vector((0.0, 0.0, 0.0))) / segments
        projected = []
        for world_pos in ring_world:
            screen_pos = view3d_utils.location_3d_to_region_2d(region, region_data, world_pos)
            if screen_pos is None:
                projected = []
                break
            projected.append((screen_pos.x, screen_pos.y))
        if len(projected) != segments:
            projected_rings.append(None)
            front_masks.append(None)
            continue
        projected_rings.append(projected)
        front_masks.append([(world_pos - ring_center).dot(camera_dir) >= 0.0 for world_pos in ring_world])

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')

    if show_full_grid:
        grid_lines = []
        valid_projected = [(ring, mask) for ring, mask in zip(projected_rings, front_masks) if ring is not None and mask is not None]
        for ring, front_mask in valid_projected:
            for idx, point in enumerate(ring):
                next_idx = (idx + 1) % len(ring)
                if front_mask[idx] or front_mask[next_idx]:
                    grid_lines.append(point)
                    grid_lines.append(ring[next_idx])
        for ring_idx in range(len(projected_rings) - 1):
            ring = projected_rings[ring_idx]
            next_ring = projected_rings[ring_idx + 1]
            mask = front_masks[ring_idx]
            next_mask = front_masks[ring_idx + 1]
            if ring is None or next_ring is None or mask is None or next_mask is None:
                continue
            for idx in range(min(len(ring), len(next_ring))):
                if mask[idx] or next_mask[idx]:
                    grid_lines.append(ring[idx])
                    grid_lines.append(next_ring[idx])

        if grid_lines:
            gpu.state.line_width_set(1.6)
            batch = batch_for_shader(shader, 'LINES', {"pos": grid_lines})
            shader.bind()
            shader.uniform_float("color", (0.2, 0.85, 1.0, 0.72))
            batch.draw(shader)

    selected_indices = {idx for idx in get_selected_widget_verts(wd) if 0 <= idx < segments}
    if selected_indices and any(ring is not None for ring in projected_rings):
        highlight_lines = []
        for selected_idx in sorted(selected_indices):
            previous_point = None
            for ring in projected_rings:
                if ring is None or selected_idx >= len(ring):
                    continue
                point = ring[selected_idx]
                if previous_point is not None:
                    highlight_lines.append(previous_point)
                    highlight_lines.append(point)
                previous_point = point
        if highlight_lines:
            gpu.state.line_width_set(2.0)
            batch = batch_for_shader(shader, 'LINES', {"pos": highlight_lines})
            shader.bind()
            shader.uniform_float("color", (1.0, 0.55, 0.0, 0.95))
            batch.draw(shader)

    widget_selected_indices = get_selected_widget_verts(wd)
    for point_idx, ring_start in selected_ring_starts:
        ring_idx = ring_start // segments
        if ring_idx >= len(projected_rings):
            continue
        projected = projected_rings[ring_idx]
        if projected is None:
            continue

        lines = []
        for idx, point in enumerate(projected):
            lines.append(point)
            lines.append(projected[(idx + 1) % len(projected)])

        is_active_ring = point_idx == active_idx
        if lines:
            gpu.state.line_width_set(2.4 if is_active_ring else 1.8)
            batch = batch_for_shader(shader, 'LINES', {"pos": lines})
            shader.bind()
            shader.uniform_float("color", (1.0, 0.55, 0.0, 1.0) if is_active_ring else (1.0, 0.78, 0.05, 0.78))
            batch.draw(shader)

        point_setting = obj.hair_pipe_settings.point_settings[point_idx] if point_idx < len(obj.hair_pipe_settings.point_settings) else ps
        normal_points = []
        selected_points = []
        for idx, point in enumerate(projected):
            if idx >= len(point_setting.cross_section_verts) or getattr(point_setting.cross_section_verts[idx], 'is_ghost', False):
                continue
            if is_active_ring and idx in widget_selected_indices:
                selected_points.append(point)
            else:
                normal_points.append(point)
        if normal_points:
            draw_circle_points(shader, normal_points, (1.0, 0.55, 0.0, 0.95) if is_active_ring else (1.0, 0.78, 0.05, 0.72), 3.4 if is_active_ring else 3.0, segments=18)
        if selected_points:
            draw_circle_points(shader, selected_points, (1.0, 1.0, 0.15, 1.0), 4.2, segments=18)

    gpu.state.point_size_set(1.0)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def get_pipe_control_vertices_in_screen_rect(context, x0, y0, x1, y1):
    region = context.region
    region_data = context.region_data
    obj = context.active_object
    if region is None or region_data is None or obj is None or obj.type != 'CURVE':
        return []

    settings = obj.hair_pipe_settings
    if len(settings.point_settings) == 0:
        return []

    try:
        mesh_verts, _faces = generate_pipe_mesh(obj, settings)
    except Exception:
        return []
    if not mesh_verts:
        return []

    segments = len(settings.point_settings[0].cross_section_verts)
    if segments < 3 or len(mesh_verts) < segments:
        return []

    control_positions = []
    for spline_data in get_curve_points_data(obj):
        for point in spline_data.get('points', []):
            control_positions.append(obj.matrix_world @ point['co'])
    if not control_positions:
        return []

    ring_centers = []
    for start in range(0, len(mesh_verts) - segments + 1, segments):
        ring = mesh_verts[start:start + segments]
        ring_center = sum((Vector(v) for v in ring), Vector((0.0, 0.0, 0.0))) / segments
        ring_centers.append((start, obj.matrix_world @ ring_center))

    hits = []
    used_starts = set()
    for point_idx, control_world in enumerate(control_positions[:len(settings.point_settings)]):
        if is_transition_point(settings.point_settings[point_idx]):
            continue
        best_start = None
        best_ring_dist = None
        for start, ring_center_world in ring_centers:
            if start in used_starts:
                continue
            dist = (ring_center_world - control_world).length
            if best_ring_dist is None or dist < best_ring_dist:
                best_ring_dist = dist
                best_start = start
        if best_start is None:
            continue
        used_starts.add(best_start)
        ring_world = [obj.matrix_world @ Vector(v) for v in mesh_verts[best_start:best_start + segments]]
        point_vert_count = len(settings.point_settings[point_idx].cross_section_verts)
        for vert_idx, world_pos in enumerate(ring_world[:point_vert_count]):
            if getattr(settings.point_settings[point_idx].cross_section_verts[vert_idx], 'is_ghost', False):
                continue
            screen_pos = view3d_utils.location_3d_to_region_2d(region, region_data, world_pos)
            if screen_pos is None:
                continue
            if x0 <= screen_pos.x <= x1 and y0 <= screen_pos.y <= y1:
                hits.append((point_idx, vert_idx))
    return hits


def find_nearest_pipe_control_vertex(context, mx, my, max_dist=16.0):
    region = context.region
    region_data = context.region_data
    obj = context.active_object
    if region is None or region_data is None or obj is None or obj.type != 'CURVE':
        return -1, -1

    settings = obj.hair_pipe_settings
    if len(settings.point_settings) == 0:
        return -1, -1

    try:
        mesh_verts, _faces = generate_pipe_mesh(obj, settings)
    except Exception:
        return -1, -1
    if not mesh_verts:
        return -1, -1

    segments = len(settings.point_settings[0].cross_section_verts)
    if segments < 3 or len(mesh_verts) < segments:
        return -1, -1

    control_positions = []
    for spline_data in get_curve_points_data(obj):
        for point in spline_data.get('points', []):
            control_positions.append(obj.matrix_world @ point['co'])
    if not control_positions:
        return -1, -1

    ring_centers = []
    for start in range(0, len(mesh_verts) - segments + 1, segments):
        ring = mesh_verts[start:start + segments]
        ring_center = sum((Vector(v) for v in ring), Vector((0.0, 0.0, 0.0))) / segments
        ring_centers.append((start, obj.matrix_world @ ring_center))

    closest_point_idx = -1
    closest_vert_idx = -1
    closest_dist = max_dist
    used_starts = set()
    for point_idx, control_world in enumerate(control_positions[:len(settings.point_settings)]):
        if is_transition_point(settings.point_settings[point_idx]):
            continue
        best_start = None
        best_ring_dist = None
        for start, ring_center_world in ring_centers:
            if start in used_starts:
                continue
            dist = (ring_center_world - control_world).length
            if best_ring_dist is None or dist < best_ring_dist:
                best_ring_dist = dist
                best_start = start
        if best_start is None:
            continue
        used_starts.add(best_start)
        ring_world = [obj.matrix_world @ Vector(v) for v in mesh_verts[best_start:best_start + segments]]
        point_vert_count = len(settings.point_settings[point_idx].cross_section_verts)
        for vert_idx, world_pos in enumerate(ring_world[:point_vert_count]):
            if getattr(settings.point_settings[point_idx].cross_section_verts[vert_idx], 'is_ghost', False):
                continue
            screen_pos = view3d_utils.location_3d_to_region_2d(region, region_data, world_pos)
            if screen_pos is None:
                continue
            dist = math.sqrt((mx - screen_pos.x) ** 2 + (my - screen_pos.y) ** 2)
            if dist < closest_dist:
                closest_dist = dist
                closest_point_idx = point_idx
                closest_vert_idx = vert_idx
    return closest_point_idx, closest_vert_idx


def rounded_rect_points(x0, y0, x1, y1, radius=8.0, segments=5):
    radius = max(0.0, min(radius, (x1 - x0) * 0.5, (y1 - y0) * 0.5))
    centers = (
        (x1 - radius, y1 - radius, 0.0),
        (x0 + radius, y1 - radius, math.pi * 0.5),
        (x0 + radius, y0 + radius, math.pi),
        (x1 - radius, y0 + radius, math.pi * 1.5),
    )
    points = []
    for cx, cy, start_angle in centers:
        for step in range(segments + 1):
            angle = start_angle + step * (math.pi * 0.5 / segments)
            points.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
    return points


def draw_rounded_rect(shader, x0, y0, x1, y1, radius, fill_color, border_color=None):
    points = rounded_rect_points(x0, y0, x1, y1, radius)
    if fill_color is not None and fill_color[3] > 0.0:
        center = ((x0 + x1) * 0.5, (y0 + y1) * 0.5)
        vertices = [center] + points
        indices = []
        for i in range(1, len(vertices)):
            indices.append((0, i, 1 if i == len(vertices) - 1 else i + 1))
        batch = batch_for_shader(shader, 'TRIS', {"pos": vertices}, indices=indices)
        shader.bind()
        shader.uniform_float("color", fill_color)
        batch.draw(shader)

    if border_color is not None:
        lines = []
        for i, point in enumerate(points):
            lines.append(point)
            lines.append(points[(i + 1) % len(points)])
        gpu.state.line_width_set(1.4)
        batch = batch_for_shader(shader, 'LINES', {"pos": lines})
        shader.bind()
        shader.uniform_float("color", border_color)
        batch.draw(shader)


def draw_widget_button(shader, x0, y0, x1, y1, fill_color=None, enabled=True, active=False):
    if not enabled:
        fill = (0.18, 0.18, 0.18, 1.0)
        border = (0.28, 0.28, 0.28, 1.0)
    elif active:
        fill = (0.36, 0.36, 0.36, 1.0)
        border = (0.58, 0.58, 0.58, 1.0)
    else:
        fill = (0.26, 0.26, 0.26, 1.0)
        border = (0.43, 0.43, 0.43, 1.0)
    radius = min((y1 - y0) * 0.42, 9.0)
    draw_rounded_rect(shader, x0, y0, x1, y1, radius, fill, border)


def draw_centered_label(font_id, text, x0, y0, x1, y1, alpha=1.0):
    blf.size(font_id, 15)
    try:
        width, height = blf.dimensions(font_id, text)
    except Exception:
        width = len(text) * 14.0
        height = 15.0
    blf.color(font_id, 0.86, 0.86, 0.86, alpha)
    blf.position(font_id, x0 + (x1 - x0 - width) * 0.5, y0 + (y1 - y0 - height) * 0.5 + 1.0, 0)
    blf.draw(font_id, text)


def button_width_for_label(font_id, text, min_width=64.0, padding_x=28.0):
    blf.size(font_id, 15)
    try:
        width, _height = blf.dimensions(font_id, text)
    except Exception:
        width = len(text) * 14.0
    return max(min_width, width + padding_x)


def draw_widget_callback(): 
    """Draw the cross-section widget with thumbnail strip at top."""
    try:
        context = bpy.context
    except Exception:
        return

    obj = context.active_object
    if obj is None or obj.type != 'CURVE':
        return
    if not hasattr(obj, 'hair_pipe_settings'):
        return

    settings = obj.hair_pipe_settings
    draw_selected_curves_highlight(context)
    if len(settings.point_settings) == 0:
        return

    draw_transition_point_markers(context, obj, settings)

    wm = context.window_manager
    if not hasattr(wm, 'hair_pipe_widget'):
        return
    wd = wm.hair_pipe_widget
    if not wd.is_active:
        return
    if settings.active_point_index >= len(settings.point_settings):
        return

    ps = settings.point_settings[settings.active_point_index]
    if is_transition_point(ps):
        return
    update_ghost_vertices(ps)
    curve_point = get_active_curve_point(context)
    verts = ps.cross_section_verts
    n = len(verts)
    if n < 3:
        return

    draw_curve_start_marker(context, obj)
    draw_active_pipe_cross_section_ring(context, ps)

    cx = wd.widget_center_x
    cy = wd.widget_center_y
    size = wd.widget_size
    if size < 10:
        return

    padding = 18
    half = size / 2.0 - padding
    alignment_angle, auto_flip_h = get_stable_widget_alignment(context, ps, wd)
    alignment_angle += math.radians(settings.widget_correct_rotation)
    flip_h = auto_flip_h ^ wd.flip_horizontal

    max_extent = 0.0
    for vert in verts:
        max_extent = max(max_extent, abs(vert.offset_x), abs(vert.offset_y))
    base_radius = max(max_extent, settings.default_radius, 0.05)
    if wd.widget_scale_factor <= 1e-8:
        wd.widget_scale_factor = half / (base_radius * 2.4)
    sf = wd.widget_scale_factor

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')

    region = context.region

    # --- Main editor panel (center) ---
    panel_x0 = cx - half
    panel_y0 = cy - half
    panel_x1 = cx + half
    panel_y1 = cy + half
    draw_rounded_rect(
        shader,
        panel_x0,
        panel_y0,
        panel_x1,
        panel_y1,
        14.0,
        (0.18, 0.18, 0.18, 0.88),
        (0.0, 0.0, 0.0, 0.45),
    )
    draw_single_cross_section(shader, verts, ps, settings,
                               cx, cy, sf, alignment_angle, flip_h, half, True, wd)

    cross_size = 9.0
    cross_lines = [
        (cx - cross_size, cy), (cx + cross_size, cy),
        (cx, cy - cross_size), (cx, cy + cross_size),
    ]
    gpu.state.line_width_set(1.4)
    batch = batch_for_shader(shader, 'LINES', {"pos": cross_lines})
    shader.bind()
    shader.uniform_float("color", (0.1, 0.9, 1.0, 0.85))
    batch.draw(shader)
    draw_circle_points(shader, [(cx, cy)], (0.1, 0.9, 1.0, 0.45), 2.0, segments=14)

    # Box select rect
    if wd.box_select_active:
        bx0r = min(wd.box_x0, wd.box_x1)
        by0r = min(wd.box_y0, wd.box_y1)
        bx1r = max(wd.box_x0, wd.box_x1)
        by1r = max(wd.box_y0, wd.box_y1)
        box_lines = [
            (bx0r, by0r), (bx1r, by0r),
            (bx1r, by0r), (bx1r, by1r),
            (bx1r, by1r), (bx0r, by1r),
            (bx0r, by1r), (bx0r, by0r),
        ]
        gpu.state.line_width_set(1.5)
        batch = batch_for_shader(shader, 'LINES', {"pos": box_lines})
        shader.bind()
        shader.uniform_float("color", (1.0, 1.0, 1.0, 0.8))
        batch.draw(shader)

    if wd.lasso_select_active:
        lasso_points = get_lasso_points(wd)
        if len(lasso_points) >= 2:
            lasso_lines = []
            for i in range(len(lasso_points) - 1):
                lasso_lines.append(lasso_points[i])
                lasso_lines.append(lasso_points[i + 1])
            gpu.state.line_width_set(1.5)
            batch = batch_for_shader(shader, 'LINES', {"pos": lasso_lines})
            shader.bind()
            shader.uniform_float("color", (0.3, 0.8, 1.0, 0.9))
            batch.draw(shader)

    wd.add_button_x0 = wd.add_button_y0 = wd.add_button_x1 = wd.add_button_y1 = 0.0
    wd.remove_button_x0 = wd.remove_button_y0 = wd.remove_button_x1 = wd.remove_button_y1 = 0.0
    wd.toggle_button_x0 = wd.toggle_button_y0 = wd.toggle_button_x1 = wd.toggle_button_y1 = 0.0
    wd.rotate_button_x0 = wd.rotate_button_y0 = wd.rotate_button_x1 = wd.rotate_button_y1 = 0.0
    wd.flip_button_x0 = wd.flip_button_y0 = wd.flip_button_x1 = wd.flip_button_y1 = 0.0
    wd.idx_button_x0 = wd.idx_button_y0 = wd.idx_button_x1 = wd.idx_button_y1 = 0.0
    wd.corr_rot_x0 = wd.corr_rot_y0 = wd.corr_rot_x1 = wd.corr_rot_y1 = 0.0

    font_id = 0
    blf.size(font_id, 13)
    blf.color(font_id, 0.7, 0.8, 0.9, 0.7)
    blf.position(font_id, 18.0, 24.0, 0)
    blf.draw(font_id, "滚轮切换截面 | 中键插入点 | 右键拖拽框选 | S 缩放点 | Alt+S 缩放显示区域")

    gpu.state.line_width_set(1.0)
    gpu.state.point_size_set(1.0)
    gpu.state.blend_set('NONE')


def ensure_draw_handler():
    global _draw_handle
    if _draw_handle is None:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            draw_widget_callback, (), 'WINDOW', 'POST_PIXEL'
        )


def remove_draw_handler():
    global _draw_handle
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None


def get_view3d_window_region(context):
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            for region in area.regions:
                if region.type == 'WINDOW':
                    return area, region
    return None, None


def set_curve_overlay_hidden(context, curve_obj, enabled):
    if curve_obj is None or getattr(curve_obj, "type", None) != 'CURVE':
        return

    data = curve_obj.data
    if enabled:
        if not curve_obj.get(_CURVE_OVERLAY_STATE_KEY):
            curve_obj[_CURVE_OVERLAY_STATE_KEY] = json.dumps({
                "show_wire": bool(curve_obj.show_wire),
                "show_in_front": bool(curve_obj.show_in_front),
                "display_type": curve_obj.display_type,
                "hide_viewport": bool(curve_obj.hide_viewport),
                "hide_set": bool(curve_obj.hide_get()),
                "data_show_handles": bool(getattr(data, "show_handles", True)),
                "data_show_normal_face": bool(getattr(data, "show_normal_face", False)),
            })
        curve_obj["hair_pipe_widget_hide_curve_overlay"] = True
        curve_obj.show_wire = False
        curve_obj.show_in_front = False
        curve_obj.hide_viewport = True
        try:
            curve_obj.hide_set(True)
        except Exception:
            pass
        if hasattr(data, "show_handles"):
            data.show_handles = False
        if hasattr(data, "show_normal_face"):
            data.show_normal_face = False
    else:
        raw_state = curve_obj.get(_CURVE_OVERLAY_STATE_KEY)
        if raw_state:
            try:
                state = json.loads(raw_state)
            except Exception:
                state = {}
            curve_obj.display_type = state.get("display_type", curve_obj.display_type)
            curve_obj.show_wire = bool(state.get("show_wire", False))
            curve_obj.show_in_front = bool(state.get("show_in_front", False))
            curve_obj.hide_viewport = bool(state.get("hide_viewport", False))
            try:
                curve_obj.hide_set(bool(state.get("hide_set", False)))
            except Exception:
                pass
            try:
                del curve_obj["hair_pipe_widget_hide_curve_overlay"]
            except Exception:
                pass
            if hasattr(data, "show_handles"):
                data.show_handles = bool(state.get("data_show_handles", getattr(data, "show_handles", True)))
            if hasattr(data, "show_normal_face"):
                data.show_normal_face = bool(state.get("data_show_normal_face", getattr(data, "show_normal_face", False)))
            try:
                del curve_obj[_CURVE_OVERLAY_STATE_KEY]
            except Exception:
                pass

    if context is not None:
        redraw_view3d(context)


def get_widget_source_curve(context):
    wd = getattr(context.window_manager, 'hair_pipe_widget', None) if context is not None else None
    if wd is not None and getattr(wd, 'source_curve_name', ''):
        obj = bpy.data.objects.get(wd.source_curve_name)
        if obj is not None and obj.type == 'CURVE':
            return obj
    obj = context.active_object if context is not None else None
    return obj if obj is not None and getattr(obj, 'type', None) == 'CURVE' else None


def set_pipe_basemesh_preview(context, curve_obj, enabled):
    if curve_obj is None:
        return
    pipe_obj = get_pipe_object_for_curve(curve_obj)
    if pipe_obj is None:
        return

    modifier_states = []
    for modifier in pipe_obj.modifiers:
        modifier_states.append({
            "name": modifier.name,
            "show_viewport": bool(modifier.show_viewport),
        })

    mesh = pipe_obj.data if getattr(pipe_obj, "type", None) == 'MESH' else None
    polygon_smooth_states = []
    if mesh is not None:
        polygon_smooth_states = [bool(poly.use_smooth) for poly in mesh.polygons]

    if enabled:
        if not pipe_obj.get(_PIPE_BASEMESH_STATE_KEY):
            pipe_obj[_PIPE_BASEMESH_STATE_KEY] = json.dumps({
                "display_type": pipe_obj.display_type,
                "show_wire": bool(pipe_obj.show_wire),
                "show_in_front": bool(pipe_obj.show_in_front),
                "modifier_states": modifier_states,
                "polygon_smooth_states": polygon_smooth_states,
                "smooth_shading": bool(getattr(curve_obj.hair_pipe_settings, "smooth_shading", True)),
            })
        curve_obj.hair_pipe_settings.smooth_shading = False
        pipe_obj.display_type = 'TEXTURED'
        pipe_obj.show_wire = True
        pipe_obj.show_in_front = True
        if mesh is not None:
            mesh.polygons.foreach_set("use_smooth", [False] * len(mesh.polygons))
            mesh.update()
        for modifier in pipe_obj.modifiers:
            if modifier.type == 'SUBSURF':
                modifier.show_viewport = False
    else:
        raw_state = pipe_obj.get(_PIPE_BASEMESH_STATE_KEY)
        if raw_state:
            try:
                state = json.loads(raw_state)
            except Exception:
                state = {}
            pipe_obj.display_type = state.get("display_type", 'TEXTURED')
            pipe_obj.show_wire = bool(state.get("show_wire", False))
            pipe_obj.show_in_front = bool(state.get("show_in_front", False))
            if hasattr(curve_obj, "hair_pipe_settings") and "smooth_shading" in state:
                curve_obj.hair_pipe_settings.smooth_shading = bool(state.get("smooth_shading", True))
            if mesh is not None:
                saved_smooth = state.get("polygon_smooth_states", [])
                if len(saved_smooth) == len(mesh.polygons):
                    for poly, use_smooth in zip(mesh.polygons, saved_smooth):
                        poly.use_smooth = bool(use_smooth)
                    mesh.update()
            saved_modifiers = {item.get("name"): item for item in state.get("modifier_states", []) if isinstance(item, dict)}
            for modifier in pipe_obj.modifiers:
                saved = saved_modifiers.get(modifier.name)
                if saved is not None:
                    modifier.show_viewport = bool(saved.get("show_viewport", modifier.show_viewport))
            try:
                del pipe_obj[_PIPE_BASEMESH_STATE_KEY]
            except Exception:
                pass

    if context is not None:
        redraw_view3d(context)


def setup_widget(context):
    obj = context.active_object
    if obj is None or obj.type != 'CURVE' or not is_curve_edit_mode(obj):
        return False

    sync_point_settings(obj)
    if not sync_active_point_from_selection(obj):
        obj.hair_pipe_settings.active_point_index = min(
            obj.hair_pipe_settings.active_point_index,
            max(0, len(obj.hair_pipe_settings.point_settings) - 1),
        )

    wd = context.window_manager.hair_pipe_widget
    area, region = get_view3d_window_region(context)
    if region is None:
        return False

    wd.region_offset_x = region.x
    wd.region_offset_y = region.y
    settings = obj.hair_pipe_settings
    addon_entry = context.preferences.addons.get("hair_curve_pipe")
    widget_layout = addon_entry.preferences if addon_entry is not None else settings
    area_scale = max(0.35, min(1.8, getattr(widget_layout, "widget_area_scale", 1.0)))
    wd.widget_size = min(region.width, region.height) * 0.62 * area_scale
    wd.widget_center_x = region.width / 2.0 + region.width * 0.35 * getattr(widget_layout, "widget_offset_x", 0.0)
    wd.widget_center_y = region.height / 2.0 + region.height * 0.35 * getattr(widget_layout, "widget_offset_y", 0.0)
    wd.widget_scale_factor = 0.0
    wd.source_curve_name = obj.name
    wd.is_active = True
    wd.show_full_mesh_grid = False
    wd.auto_alignment_initialized = False
    wd.drag_vert_index = -1
    set_pipe_basemesh_preview(context, obj, True)
    set_curve_overlay_hidden(context, obj, True)
    ensure_draw_handler()
    redraw_view3d(context)
    return True


def redraw_view3d(context):
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


def serialize_cross_section_undo_state(obj):
    settings = obj.hair_pipe_settings
    state = {
        "active_point_index": settings.active_point_index,
        "widget_correct_rotation": settings.widget_correct_rotation,
        "points": [],
    }
    for ps in settings.point_settings:
        state["points"].append({
            "scale": ps.scale,
            "rotation": ps.rotation,
            "active_vert_index": ps.active_vert_index,
            "use_transition": getattr(ps, "use_transition", False),
            "verts": [
                [v.offset_x, v.offset_y, bool(getattr(v, "is_ghost", False))]
                for v in ps.cross_section_verts
            ],
        })
    return state


def restore_cross_section_undo_state(obj, state):
    settings = obj.hair_pipe_settings
    point_states = state.get("points", [])
    for idx, point_state in enumerate(point_states):
        if idx >= len(settings.point_settings):
            break
        ps = settings.point_settings[idx]
        verts = ps.cross_section_verts
        while len(verts) > 0:
            verts.remove(len(verts) - 1)
        for x, y, is_ghost in point_state.get("verts", []):
            v = verts.add()
            v.offset_x = x
            v.offset_y = y
            v.is_ghost = is_ghost
        ps.scale = point_state.get("scale", ps.scale)
        ps.rotation = point_state.get("rotation", ps.rotation)
        ps.active_vert_index = min(point_state.get("active_vert_index", ps.active_vert_index), max(0, len(verts) - 1))
        ps.use_transition = point_state.get("use_transition", getattr(ps, "use_transition", False))
        update_ghost_vertices(ps)
    settings.active_point_index = min(state.get("active_point_index", settings.active_point_index), max(0, len(settings.point_settings) - 1))
    settings.widget_correct_rotation = state.get("widget_correct_rotation", settings.widget_correct_rotation)
    update_all_ghost_vertices(settings)


def get_widget_undo_stack(wd):
    try:
        stack = json.loads(wd.undo_stack) if wd.undo_stack else []
        return stack if isinstance(stack, list) else []
    except Exception:
        return []


def set_widget_undo_stack(wd, stack):
    wd.undo_stack = json.dumps(stack[-64:])


def push_widget_undo(context, message="编辑横截面"):
    obj = context.active_object
    if obj is None or obj.type != 'CURVE':
        return
    wd = context.window_manager.hair_pipe_widget
    stack = get_widget_undo_stack(wd)
    stack.append(serialize_cross_section_undo_state(obj))
    set_widget_undo_stack(wd, stack)


def pop_widget_undo(context):
    obj = get_widget_source_curve(context)
    if obj is None or obj.type != 'CURVE':
        return False
    wd = context.window_manager.hair_pipe_widget
    stack = get_widget_undo_stack(wd)
    if not stack:
        return False
    state = stack.pop()
    set_widget_undo_stack(wd, stack)
    restore_cross_section_undo_state(obj, state)
    return True


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
    return [idx for idx in dict.fromkeys(selected) if 0 <= idx < len(settings.point_settings)]


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


def get_active_curve_point(context):
    obj = context.active_object
    if obj is None or obj.type != 'CURVE':
        return None
    settings = obj.hair_pipe_settings
    target_index = settings.active_point_index
    global_idx = 0
    for spline in obj.data.splines:
        points = spline.bezier_points if spline.type == 'BEZIER' else spline.points
        for point in points:
            if global_idx == target_index:
                return point
            global_idx += 1
    return None


def get_active_curve_point_world_position(context):
    obj = context.active_object
    if obj is None or obj.type != 'CURVE':
        return None
    point = get_active_curve_point(context)
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
        mesh_verts, _faces = generate_pipe_mesh(obj, obj.hair_pipe_settings)
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
    is_editing = any((
        getattr(wd, 'move_active', False),
        getattr(wd, 'rotate_active', False),
        getattr(wd, 'scale_active', False),
    ))
    if is_editing and getattr(wd, 'auto_alignment_initialized', False):
        return wd.auto_alignment_angle, wd.auto_alignment_flip_h

    angle, flip_h = get_auto_widget_alignment_from_view(context, ps)
    wd.auto_alignment_angle = angle
    wd.auto_alignment_flip_h = flip_h
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
        for idx, point_setting in enumerate(settings.point_settings):
            v = point_setting.cross_section_verts.add()
            v.offset_x = settings.default_radius
            v.offset_y = 0.0
            v.is_ghost = idx != active_point_index
            point_setting.active_vert_index = len(point_setting.cross_section_verts) - 1
        return

    idx = max(0, min(ps.active_vert_index, n - 1))
    add_cross_section_vertex_after_all(settings, active_point_index, idx)


def add_cross_section_vertex_after_all(settings, active_index, idx):
    for point_idx, point_setting in enumerate(settings.point_settings):
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
    for idx, point_setting in enumerate(settings.point_settings):
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


class HAIRPIPE_OT_widget_interact(bpy.types.Operator):
    """Open interactive cross-section editor overlay in the 3D viewport"""
    bl_idname = "hair_pipe.widget_interact"
    bl_label = "编辑横截面"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE' or not is_curve_edit_mode(obj):
            return False
        s = obj.hair_pipe_settings
        if len(s.point_settings) == 0:
            return False
        if s.active_point_index >= len(s.point_settings):
            return False
        ps = s.point_settings[s.active_point_index]
        return not is_transition_point(ps) and len(ps.cross_section_verts) >= 3

    def invoke(self, context, event):
        wd = context.window_manager.hair_pipe_widget
        if wd.is_active:
            source_curve = get_widget_source_curve(context)
            set_curve_overlay_hidden(context, source_curve, False)
            set_pipe_basemesh_preview(context, source_curve, False)
            wd.is_active = False
            wd.drag_vert_index = -1
            redraw_view3d(context)
            return {'FINISHED'}
        if not setup_widget(context):
            self.report({'ERROR'}, "No 3D View")
            return {'CANCELLED'}
        wd.hold_key_mode = False
        self._trigger_key = event.type
        self._trigger_ctrl = event.ctrl
        self._trigger_shift = event.shift
        self._trigger_alt = event.alt
        self._just_opened = True
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _get_local_mouse(self, event, wd):
        return event.mouse_x - wd.region_offset_x, event.mouse_y - wd.region_offset_y

    def modal(self, context, event):
        if hasattr(self, '_just_opened') and self._just_opened:
            if event.type == self._trigger_key and event.value == 'RELEASE':
                self._just_opened = False
            return {'RUNNING_MODAL'}
        if (hasattr(self, '_trigger_key') and event.type == self._trigger_key
                and event.value == 'PRESS'
                and event.ctrl == getattr(self, '_trigger_ctrl', False)
                and event.shift == getattr(self, '_trigger_shift', False)
                and event.alt == getattr(self, '_trigger_alt', False)):
            self._finish(context)
            return {'FINISHED'}
        return handle_widget_modal(self, context, event, close_on_key_release=False)

    def _finish(self, context):
        source_curve = get_widget_source_curve(context)
        set_curve_overlay_hidden(context, source_curve, False)
        set_pipe_basemesh_preview(context, source_curve, False)
        wd = context.window_manager.hair_pipe_widget
        wd.is_active = False
        wd.drag_vert_index = -1
        redraw_view3d(context)


class HAIRPIPE_OT_widget_hold(bpy.types.Operator):
    """Hold shortcut to temporarily show and edit the cross-section widget"""
    bl_idname = "hair_pipe.widget_hold"
    bl_label = "按住编辑横截面"

    @classmethod
    def poll(cls, context):
        return HAIRPIPE_OT_widget_interact.poll(context)

    def invoke(self, context, event):
        if not setup_widget(context):
            self.report({'ERROR'}, "未找到 3D 视图")
            return {'CANCELLED'}
        wd = context.window_manager.hair_pipe_widget
        wd.hold_key_mode = True
        self._hold_key = event.type
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _get_local_mouse(self, event, wd):
        return event.mouse_x - wd.region_offset_x, event.mouse_y - wd.region_offset_y

    def modal(self, context, event):
        return handle_widget_modal(self, context, event, close_on_key_release=True)

    def _finish(self, context):
        set_pipe_basemesh_preview(context, context.active_object, False)
        wd = context.window_manager.hair_pipe_widget
        wd.is_active = False
        wd.drag_vert_index = -1
        wd.move_active = False
        wd.rotate_active = False
        wd.scale_active = False
        wd.display_scale_active = False
        wd.hold_key_mode = False
        redraw_view3d(context)


def handle_widget_modal(operator, context, event, close_on_key_release=False):
    wd = context.window_manager.hair_pipe_widget

    if not wd.is_active:
        operator._finish(context)
        return {'FINISHED'}

    if event.type == 'Z' and event.value == 'PRESS' and event.ctrl:
        pop_widget_undo(context)
        redraw_view3d(context)
        return {'RUNNING_MODAL'}

    if close_on_key_release and event.value == 'RELEASE' and event.type == getattr(operator, '_hold_key', None):
        operator._finish(context)
        return {'FINISHED'}

    obj = context.active_object
    if obj is None or obj.type != 'CURVE' or not is_curve_edit_mode(obj):
        operator._finish(context)
        return {'CANCELLED'}

    settings = obj.hair_pipe_settings
    if settings.active_point_index >= len(settings.point_settings):
        operator._finish(context)
        return {'CANCELLED'}

    ps = settings.point_settings[settings.active_point_index]
    if is_transition_point(ps):
        operator._finish(context)
        return {'CANCELLED'}
    update_ghost_vertices(ps)
    curve_point = get_active_curve_point(context)
    verts = ps.cross_section_verts
    if len(verts) < 3:
        operator._finish(context)
        return {'CANCELLED'}

    cx = wd.widget_center_x
    cy = wd.widget_center_y
    sf = wd.widget_scale_factor
    alignment_angle, auto_flip_h = get_stable_widget_alignment(context, ps, wd)
    alignment_angle += math.radians(settings.widget_correct_rotation)
    flip_h = auto_flip_h ^ wd.flip_horizontal
    view_area, view_region = get_view3d_window_region(context)
    if view_region is None:
        operator._finish(context)
        return {'CANCELLED'}
    if view_area is not None:
        event_region = None
        for candidate_region in view_area.regions:
            if candidate_region.x <= event.mouse_x < candidate_region.x + candidate_region.width and candidate_region.y <= event.mouse_y < candidate_region.y + candidate_region.height:
                event_region = candidate_region
                break
        if event_region is not None and event_region.type != 'WINDOW':
            return {'PASS_THROUGH'}
        if event_region is None and not (view_region.x <= event.mouse_x < view_region.x + view_region.width and view_region.y <= event.mouse_y < view_region.y + view_region.height):
            return {'PASS_THROUGH'}
    wd.region_offset_x = view_region.x
    wd.region_offset_y = view_region.y
    mx, my = operator._get_local_mouse(event, wd)
    if mx < 0 or my < 0 or mx > view_region.width or my > view_region.height:
        return {'PASS_THROUGH'}
    half = wd.widget_size / 2.0
    inside_widget = abs(mx - cx) <= half and abs(my - cy) <= half
    inside_add_button = is_inside_rect(mx, my, wd.add_button_x0, wd.add_button_y0, wd.add_button_x1, wd.add_button_y1)
    inside_remove_button = is_inside_rect(mx, my, wd.remove_button_x0, wd.remove_button_y0, wd.remove_button_x1, wd.remove_button_y1)
    inside_toggle_button = is_inside_rect(mx, my, wd.toggle_button_x0, wd.toggle_button_y0, wd.toggle_button_x1, wd.toggle_button_y1)
    inside_preview_button = is_inside_rect(mx, my, wd.rotate_button_x0, wd.rotate_button_y0, wd.rotate_button_x1, wd.rotate_button_y1)
    inside_flip_button = is_inside_rect(mx, my, wd.flip_button_x0, wd.flip_button_y0, wd.flip_button_x1, wd.flip_button_y1)
    inside_idx_button = is_inside_rect(mx, my, wd.idx_button_x0, wd.idx_button_y0, wd.idx_button_x1, wd.idx_button_y1)
    inside_controls = inside_add_button or inside_remove_button or inside_toggle_button or inside_preview_button or inside_flip_button or inside_idx_button
    inside_corr_rot = is_inside_rect(mx, my, wd.corr_rot_x0, wd.corr_rot_y0, wd.corr_rot_x1, wd.corr_rot_y1)
    drag_threshold = 4.0

    view_cx = view_region.width * 0.5
    view_cy = view_region.height * 0.5

    if event.type == 'T' and event.value == 'PRESS' and event.ctrl:
        push_widget_undo(context, "旋转修正横截面编辑器")
        wd.corr_rot_dragging = True
        wd.corr_rot_drag_start_angle = math.atan2(my - view_cy, mx - view_cx)
        wd.corr_rot_drag_start_val = settings.widget_correct_rotation
        redraw_view3d(context)
        return {'RUNNING_MODAL'}

    if wd.corr_rot_dragging:
        if event.type == 'MOUSEMOVE':
            current_angle = math.atan2(my - view_cy, mx - view_cx)
            delta_angle = math.degrees(current_angle - wd.corr_rot_drag_start_angle)
            settings.widget_correct_rotation = wd.corr_rot_drag_start_val + delta_angle
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            wd.corr_rot_dragging = False
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            settings.widget_correct_rotation = wd.corr_rot_drag_start_val
            wd.corr_rot_dragging = False
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}

    if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.value == 'PRESS':
        if not event.ctrl:
            return {'PASS_THROUGH'}
        total_points = len(settings.point_settings)
        if total_points > 0:
            previous_selection = get_selected_widget_verts(wd)
            step = -1 if event.type == 'WHEELUPMOUSE' else 1
            new_idx = (settings.active_point_index + step) % total_points
            settings.active_point_index = new_idx
            select_curve_point_by_index(obj, new_idx)
            target_ps = settings.point_settings[new_idx]
            target_count = len(target_ps.cross_section_verts)
            preserved_selection = {idx for idx in previous_selection if 0 <= idx < target_count}
            target_ps.active_vert_index = ps.active_vert_index if 0 <= ps.active_vert_index < target_count else -1
            wd.drag_vert_index = -1
            wd.left_drag_pending = False
            wd.left_drag_active = False
            wd.left_drag_vert_index = -1
            set_selected_widget_verts(wd, preserved_selection)
            redraw_view3d(context)
        return {'RUNNING_MODAL'}

    if wd.left_drag_pending:
        moved = math.sqrt((mx - wd.left_drag_start_x) ** 2 + (my - wd.left_drag_start_y) ** 2)
        if event.type == 'MOUSEMOVE' and moved >= drag_threshold:
            if wd.left_drag_vert_index >= 0:
                sel = get_selected_widget_verts(wd)
                if wd.left_drag_vert_index not in sel:
                    sel = {wd.left_drag_vert_index}
                    set_selected_widget_verts(wd, sel)
                movable = {vi for vi in sel if 0 <= vi < len(verts) and not getattr(verts[vi], 'is_ghost', False)}
                if movable:
                    push_widget_undo(context, "移动横截面顶点")
                    set_selected_widget_verts(wd, movable)
                    wd.left_drag_active = True
                    wd.move_active = True
                    wd.move_start_x = wd.left_drag_start_x
                    wd.move_start_y = wd.left_drag_start_y
                    store_rotate_offsets(wd, verts, sorted(movable))
                wd.left_drag_pending = False
                redraw_view3d(context)
                return {'RUNNING_MODAL'}
            wd.left_drag_pending = False
            wd.box_select_active = True
            wd.box_select_3d = not wd.left_drag_started_inside_widget
            wd.box_x0 = wd.left_drag_start_x
            wd.box_y0 = wd.left_drag_start_y
            wd.box_x1 = mx
            wd.box_y1 = my
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if not wd.left_drag_started_inside_widget:
                wd.left_drag_pending = False
                wd.left_drag_vert_index = -1
                redraw_view3d(context)
                return {'RUNNING_MODAL'}
            if wd.left_drag_vert_index >= 0:
                closest_idx = wd.left_drag_vert_index
                ps.active_vert_index = closest_idx
                if event.shift:
                    sel = get_selected_widget_verts(wd)
                    if closest_idx in sel:
                        sel.discard(closest_idx)
                    else:
                        sel.add(closest_idx)
                    set_selected_widget_verts(wd, sel)
                else:
                    set_selected_widget_verts(wd, {closest_idx})
            else:
                set_selected_widget_verts(wd, set())
            wd.left_drag_pending = False
            wd.left_drag_vert_index = -1
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            wd.left_drag_pending = False
            wd.left_drag_vert_index = -1
            redraw_view3d(context)
            return {'RUNNING_MODAL'}

    if wd.move_active:
        sel = sorted(get_selected_widget_verts(wd))
        initial = get_rotate_offsets(wd)
        if event.type == 'MOUSEMOVE':
            dx, dy = widget_to_effective(mx, my, cx, cy, sf, alignment_angle, flip_h)
            sx, sy = widget_to_effective(wd.move_start_x, wd.move_start_y, cx, cy, sf, alignment_angle, flip_h)
            delta_x = dx - sx
            delta_y = dy - sy
            for ip, vi in enumerate(sel):
                if vi < len(verts) and ip < len(initial) and not getattr(verts[vi], 'is_ghost', False):
                    verts[vi].offset_x = initial[ip][0] + delta_x
                    verts[vi].offset_y = initial[ip][1] + delta_y
            update_ghost_vertices(ps)
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and ((wd.left_drag_active and event.value == 'RELEASE') or (not wd.left_drag_active and event.value == 'PRESS')):
            wd.move_active = False
            wd.left_drag_active = False
            wd.left_drag_vert_index = -1
            sync_active_cross_section_to_selected_points(context)
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            for ip, vi in enumerate(sel):
                if vi < len(verts) and ip < len(initial):
                    verts[vi].offset_x = initial[ip][0]
                    verts[vi].offset_y = initial[ip][1]
            wd.move_active = False
            wd.left_drag_active = False
            wd.left_drag_vert_index = -1
            update_ghost_vertices(ps)
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}

    if wd.display_scale_active:
        if event.type == 'MOUSEMOVE':
            start_dist = math.sqrt((wd.scale_start_x - cx) ** 2 + (wd.scale_start_y - cy) ** 2)
            now_dist = math.sqrt((mx - cx) ** 2 + (my - cy) ** 2)
            factor = now_dist / max(start_dist, 1.0)
            wd.widget_scale_factor = max(8.0, min(50000.0, wd.scale_start_factor * factor))
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            wd.display_scale_active = False
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            wd.widget_scale_factor = wd.scale_start_factor
            wd.display_scale_active = False
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}

    if wd.scale_active:
        sel = sorted(get_selected_widget_verts(wd))
        initial = get_rotate_offsets(wd)
        if event.type == 'MOUSEMOVE':
            cnt = max(1, len(initial))
            ctr_x = sum(o[0] for o in initial) / cnt
            ctr_y = sum(o[1] for o in initial) / cnt
            start_dist = math.sqrt((wd.scale_start_x - cx) ** 2 + (wd.scale_start_y - cy) ** 2)
            now_dist = math.sqrt((mx - cx) ** 2 + (my - cy) ** 2)
            factor = now_dist / max(start_dist, 1.0)
            for ip, vi in enumerate(sel):
                if vi < len(verts) and ip < len(initial) and not getattr(verts[vi], 'is_ghost', False):
                    verts[vi].offset_x = ctr_x + (initial[ip][0] - ctr_x) * factor
                    verts[vi].offset_y = ctr_y + (initial[ip][1] - ctr_y) * factor
            update_ghost_vertices(ps)
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            wd.scale_active = False
            sync_active_cross_section_to_selected_points(context)
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            for ip, vi in enumerate(sel):
                if vi < len(verts) and ip < len(initial):
                    verts[vi].offset_x = initial[ip][0]
                    verts[vi].offset_y = initial[ip][1]
            wd.scale_active = False
            update_ghost_vertices(ps)
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}

    # Rotate mode active
    if wd.rotate_active:
        sel = sorted(get_selected_widget_verts(wd))
        initial = get_rotate_offsets(wd)
        if event.type == 'MOUSEMOVE':
            a_start = math.atan2(wd.rotate_start_y - cy, wd.rotate_start_x - cx)
            a_now = math.atan2(my - cy, mx - cx)
            angle = a_now - a_start
            if flip_h:
                angle = -angle
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)
            cnt = max(1, len(initial))
            ctr_x = sum(o[0] for o in initial) / cnt
            ctr_y = sum(o[1] for o in initial) / cnt
            for ip, vi in enumerate(sel):
                if vi < len(verts) and ip < len(initial) and not getattr(verts[vi], 'is_ghost', False):
                    rx = initial[ip][0] - ctr_x
                    ry = initial[ip][1] - ctr_y
                    verts[vi].offset_x = ctr_x + rx * cos_a - ry * sin_a
                    verts[vi].offset_y = ctr_y + rx * sin_a + ry * cos_a
            update_ghost_vertices(ps)
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            wd.rotate_active = False
            for vi in sel:
                if vi < len(verts):
                    apply_active_vertex_edit_to_selected_points(context, ps, vi)
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            for ip, vi in enumerate(sel):
                if vi < len(verts) and ip < len(initial):
                    verts[vi].offset_x = initial[ip][0]
                    verts[vi].offset_y = initial[ip][1]
            wd.rotate_active = False
            update_ghost_vertices(ps)
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}

    # Box select active (right-click drag)
    if wd.box_select_active:
        if event.type == 'MOUSEMOVE':
            wd.box_x1 = mx
            wd.box_y1 = my
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            bx0 = min(wd.box_x0, wd.box_x1)
            by0 = min(wd.box_y0, wd.box_y1)
            bx1 = max(wd.box_x0, wd.box_x1)
            by1 = max(wd.box_y0, wd.box_y1)
            if wd.box_select_3d:
                hits = get_pipe_control_vertices_in_screen_rect(context, bx0, by0, bx1, by1)
                if hits:
                    target_point_idx = settings.active_point_index
                    active_hits = [vert_idx for point_idx, vert_idx in hits if point_idx == target_point_idx]
                    if not active_hits:
                        target_point_idx = hits[0][0]
                        active_hits = [vert_idx for point_idx, vert_idx in hits if point_idx == target_point_idx]
                    settings.active_point_index = target_point_idx
                    select_curve_point_by_index(obj, target_point_idx)
                    target_ps = settings.point_settings[target_point_idx]
                    if active_hits:
                        target_ps.active_vert_index = active_hits[0]
                    selected = set(active_hits)
                else:
                    selected = set()
            else:
                selected = set()
                for i, v in enumerate(verts):
                    ox, oy = get_raw_offset(v)
                    px, py = effective_to_widget(ox, oy, cx, cy, sf, alignment_angle, flip_h)
                    if bx0 <= px <= bx1 and by0 <= py <= by1 and not getattr(v, 'is_ghost', False):
                        selected.add(i)
            if event.shift:
                selected = selected | get_selected_widget_verts(wd)
            set_selected_widget_verts(wd, selected)
            wd.box_select_active = False
            wd.box_select_3d = False
            wd.left_drag_pending = False
            wd.left_drag_vert_index = -1
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type == 'ESC':
            wd.box_select_active = False
            wd.left_drag_pending = False
            wd.left_drag_vert_index = -1
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}

    if wd.lasso_select_active:
        if event.type == 'MOUSEMOVE':
            append_lasso_point(wd, mx, my)
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type == 'RIGHTMOUSE' and event.value == 'RELEASE':
            polygon = get_lasso_points(wd)
            selected = set()
            if len(polygon) >= 3:
                for i, v in enumerate(verts):
                    ox, oy = get_raw_offset(v)
                    px, py = effective_to_widget(ox, oy, cx, cy, sf, alignment_angle, flip_h)
                    if point_in_polygon(px, py, polygon):
                        selected.add(i)
            if event.shift:
                selected = selected | get_selected_widget_verts(wd)
            set_selected_widget_verts(wd, selected)
            wd.lasso_select_active = False
            wd.lasso_points = ""
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type == 'ESC':
            wd.lasso_select_active = False
            wd.lasso_points = ""
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}

    # Middle mouse - insert vertex on edge
    if event.type == 'MIDDLEMOUSE' and event.value == 'PRESS':
        if inside_widget and sf > 0.001:
            edge_idx, local_pos, edge_t = find_nearest_raw_edge(
                verts, mx, my, cx, cy, sf, alignment_angle, flip_h
            )
            if edge_idx >= 0:
                push_widget_undo(context, "插入横截面顶点")
                insert_cross_section_vertex_on_edge_all(
                    settings, settings.active_point_index, edge_idx, local_pos[0], local_pos[1], edge_t, None
                )
                sync_active_cross_section_to_selected_points(context)
                wd.drag_vert_index = -1
                redraw_view3d(context)
                return {'RUNNING_MODAL'}
        if inside_widget or inside_controls:
            return {'RUNNING_MODAL'}

    # Left mouse press
    if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
        if inside_add_button:
            push_widget_undo(context, "添加横截面顶点")
            add_cross_section_vertex(ps, settings)
            sync_active_cross_section_to_selected_points(context)
            wd.drag_vert_index = -1
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if inside_remove_button:
            push_widget_undo(context, "删除横截面顶点")
            remove_cross_section_vertex_all(settings, ps.active_vert_index)
            sync_active_cross_section_to_selected_points(context)
            wd.drag_vert_index = -1
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if inside_toggle_button:
            selected = {idx for idx in get_selected_widget_verts(wd) if 0 <= idx < len(verts)}
            if len(selected) == 2:
                push_widget_undo(context, "解除横截面幽灵线段")
                if toggle_ghost_between_selected_edge_points(ps, selected):
                    update_ghost_vertices(ps)
                    sync_active_cross_section_to_selected_points(context)
            elif 0 <= ps.active_vert_index < len(verts):
                push_widget_undo(context, "切换横截面幽灵点")
                verts[ps.active_vert_index].is_ghost = not getattr(verts[ps.active_vert_index], 'is_ghost', False)
                update_ghost_vertices(ps)
                sync_active_cross_section_to_selected_points(context)
            wd.drag_vert_index = -1
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if inside_preview_button:
            wd.show_smooth_preview = not wd.show_smooth_preview
            wd.drag_vert_index = -1
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if inside_flip_button:
            wd.flip_horizontal = not wd.flip_horizontal
            wd.drag_vert_index = -1
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if inside_idx_button:
            wd.show_full_mesh_grid = not wd.show_full_mesh_grid
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if inside_corr_rot:
            push_widget_undo(context, "旋转修正横截面编辑器")
            wd.corr_rot_dragging = True
            wd.corr_rot_drag_start_x = mx
            wd.corr_rot_drag_start_val = settings.widget_correct_rotation
            redraw_view3d(context)
            return {'RUNNING_MODAL'}

        if not inside_widget:
            point_idx, ring_idx = find_nearest_pipe_control_vertex(context, mx, my)
            wd.left_drag_pending = True
            wd.left_drag_active = False
            wd.left_drag_start_x = mx
            wd.left_drag_start_y = my
            wd.left_drag_started_inside_widget = False
            wd.left_drag_vert_index = -1
            wd.drag_vert_index = -1
            if point_idx >= 0 and ring_idx >= 0:
                settings.active_point_index = point_idx
                select_curve_point_by_index(obj, point_idx)
                target_ps = settings.point_settings[point_idx]
                target_ps.active_vert_index = ring_idx
                if event.shift and point_idx == settings.active_point_index:
                    sel = get_selected_widget_verts(wd)
                    if ring_idx in sel:
                        sel.discard(ring_idx)
                    else:
                        sel.add(ring_idx)
                    set_selected_widget_verts(wd, sel)
                else:
                    set_selected_widget_verts(wd, {ring_idx})
                wd.left_drag_vert_index = ring_idx
                wd.drag_vert_index = ring_idx
                redraw_view3d(context)
                return {'RUNNING_MODAL'}

            return {'RUNNING_MODAL'}

        if not inside_widget:
            redraw_view3d(context)
            return {'RUNNING_MODAL'}

        if inside_widget:
            closest_idx = find_nearest_raw_vertex(verts, mx, my, cx, cy, sf, alignment_angle, flip_h)
            wd.left_drag_pending = True
            wd.left_drag_active = False
            wd.left_drag_start_x = mx
            wd.left_drag_start_y = my
            wd.left_drag_started_inside_widget = True
            wd.left_drag_vert_index = closest_idx
            wd.drag_vert_index = closest_idx
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}

    if event.type == 'MOUSEMOVE':
        return {'RUNNING_MODAL'}

    # Left mouse release
    if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
        wd.drag_vert_index = -1
        wd.left_drag_pending = False
        wd.left_drag_active = False
        wd.left_drag_vert_index = -1
        redraw_view3d(context)
        return {'RUNNING_MODAL'}

    if event.type == 'G' and event.value == 'PRESS':
        sel = get_selected_widget_verts(wd)
        sel = {vi for vi in sel if 0 <= vi < len(verts) and not getattr(verts[vi], 'is_ghost', False)}
        if sel:
            push_widget_undo(context, "移动横截面顶点")
            set_selected_widget_verts(wd, sel)
            wd.move_active = True
            wd.move_start_x = mx
            wd.move_start_y = my
            store_rotate_offsets(wd, verts, sorted(sel))
            redraw_view3d(context)
        return {'RUNNING_MODAL'}

    if event.type == 'R' and event.value == 'PRESS':
        sel = get_selected_widget_verts(wd)
        sel = {vi for vi in sel if 0 <= vi < len(verts) and not getattr(verts[vi], 'is_ghost', False)}
        if sel:
            push_widget_undo(context, "旋转横截面顶点")
            set_selected_widget_verts(wd, sel)
            wd.rotate_active = True
            wd.rotate_start_x = mx
            wd.rotate_start_y = my
            store_rotate_offsets(wd, verts, sorted(sel))
            redraw_view3d(context)
        return {'RUNNING_MODAL'}

    if event.type == 'S' and event.value == 'PRESS' and event.alt:
        wd.display_scale_active = True
        wd.scale_start_x = mx
        wd.scale_start_y = my
        wd.scale_start_factor = wd.widget_scale_factor
        redraw_view3d(context)
        return {'RUNNING_MODAL'}

    if event.type == 'S' and event.value == 'PRESS':
        sel = get_selected_widget_verts(wd)
        sel = {vi for vi in sel if 0 <= vi < len(verts) and not getattr(verts[vi], 'is_ghost', False)}
        if sel:
            push_widget_undo(context, "缩放横截面顶点")
            set_selected_widget_verts(wd, sel)
            wd.scale_active = True
            wd.scale_start_x = mx
            wd.scale_start_y = my
            store_rotate_offsets(wd, verts, sorted(sel))
            redraw_view3d(context)
        return {'RUNNING_MODAL'}

    # A - Select All / Deselect All
    if event.type == 'A' and event.value == 'PRESS':
        sel = get_selected_widget_verts(wd)
        if len(sel) == len(verts):
            set_selected_widget_verts(wd, set())
        else:
            set_selected_widget_verts(wd, set(range(len(verts))))
        redraw_view3d(context)
        return {'RUNNING_MODAL'}

    if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
        return {'PASS_THROUGH'}

    # ESC - close editor
    if event.type == 'ESC':
        wd.move_active = False
        wd.rotate_active = False
        wd.scale_active = False
        wd.left_drag_pending = False
        wd.left_drag_active = False
        wd.left_drag_vert_index = -1
        operator._finish(context)
        return {'FINISHED'}

    inside_corr_rot_box = is_inside_rect(mx, my, wd.corr_rot_x0, wd.corr_rot_y0, wd.corr_rot_x1, wd.corr_rot_y1)
    if (inside_widget or inside_controls or inside_corr_rot_box) and event.type in {'LEFTMOUSE', 'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
        return {'RUNNING_MODAL'}

    return {'PASS_THROUGH'}


def get_widget_edit_context(context):
    obj = get_widget_source_curve(context)
    if obj is None or getattr(obj, 'type', None) != 'CURVE' or not hasattr(obj, 'hair_pipe_settings'):
        return None, None, None, None
    settings = obj.hair_pipe_settings
    if settings.active_point_index >= len(settings.point_settings):
        return obj, settings, None, None
    ps = settings.point_settings[settings.active_point_index]
    wd = getattr(context.window_manager, 'hair_pipe_widget', None)
    return obj, settings, ps, wd


class HAIRPIPE_OT_widget_add_vertex(bpy.types.Operator):
    bl_idname = "hair_pipe.widget_add_vertex"
    bl_label = "添加横截面顶点"

    def execute(self, context):
        obj, settings, ps, wd = get_widget_edit_context(context)
        if ps is None:
            return {'CANCELLED'}
        push_widget_undo(context, "添加横截面顶点")
        add_cross_section_vertex(ps, settings)
        sync_active_cross_section_to_selected_points(context)
        if wd is not None:
            wd.drag_vert_index = -1
        redraw_view3d(context)
        return {'FINISHED'}


class HAIRPIPE_OT_widget_remove_vertex(bpy.types.Operator):
    bl_idname = "hair_pipe.widget_remove_vertex"
    bl_label = "删除横截面顶点"

    def execute(self, context):
        obj, settings, ps, wd = get_widget_edit_context(context)
        if ps is None:
            return {'CANCELLED'}
        push_widget_undo(context, "删除横截面顶点")
        remove_cross_section_vertex_all(settings, ps.active_vert_index)
        sync_active_cross_section_to_selected_points(context)
        if wd is not None:
            wd.drag_vert_index = -1
        redraw_view3d(context)
        return {'FINISHED'}


class HAIRPIPE_OT_widget_toggle_ghost(bpy.types.Operator):
    bl_idname = "hair_pipe.widget_toggle_ghost"
    bl_label = "设置为幽灵点"

    def execute(self, context):
        obj, settings, ps, wd = get_widget_edit_context(context)
        if ps is None:
            return {'CANCELLED'}
        verts = ps.cross_section_verts
        selected = {idx for idx in get_selected_widget_verts(wd) if 0 <= idx < len(verts)} if wd is not None else set()
        if not selected and 0 <= ps.active_vert_index < len(verts):
            selected = {ps.active_vert_index}
        if not selected:
            return {'CANCELLED'}
        push_widget_undo(context, "设置横截面幽灵点")
        changed = False
        for idx in selected:
            if not getattr(verts[idx], 'is_ghost', False):
                verts[idx].is_ghost = True
                changed = True
        if changed:
            update_ghost_vertices(ps)
            sync_active_cross_section_to_selected_points(context)
        if wd is not None:
            set_selected_widget_verts(wd, {idx for idx in selected if 0 <= idx < len(verts) and not getattr(verts[idx], 'is_ghost', False)})
            wd.drag_vert_index = -1
        redraw_view3d(context)
        return {'FINISHED'}


class HAIRPIPE_OT_widget_make_normal(bpy.types.Operator):
    bl_idname = "hair_pipe.widget_make_normal"
    bl_label = "设置为正常点"

    def execute(self, context):
        obj, settings, ps, wd = get_widget_edit_context(context)
        if ps is None:
            return {'CANCELLED'}
        verts = ps.cross_section_verts
        selected = {idx for idx in get_selected_widget_verts(wd) if 0 <= idx < len(verts)} if wd is not None else set()
        if not selected and 0 <= ps.active_vert_index < len(verts):
            selected = {ps.active_vert_index}
        if not selected:
            return {'CANCELLED'}
        push_widget_undo(context, "设置横截面正常点")
        target_indices = get_widget_target_point_indices(context, settings)
        changed = False
        for point_idx in target_indices:
            target_ps = settings.point_settings[point_idx]
            if len(selected) == 2:
                changed = toggle_ghost_between_selected_edge_points(target_ps, selected) or changed
            for idx in selected:
                if 0 <= idx < len(target_ps.cross_section_verts) and getattr(target_ps.cross_section_verts[idx], 'is_ghost', False):
                    target_ps.cross_section_verts[idx].is_ghost = False
                    changed = True
            update_ghost_vertices(target_ps)
        if changed:
            update_all_ghost_vertices(settings)
        if wd is not None:
            set_selected_widget_verts(wd, {idx for idx in selected if 0 <= idx < len(verts) and not getattr(verts[idx], 'is_ghost', False)})
            wd.drag_vert_index = -1
        redraw_view3d(context)
        return {'FINISHED'}


class HAIRPIPE_OT_widget_toggle_smooth_preview(bpy.types.Operator):
    bl_idname = "hair_pipe.widget_toggle_smooth_preview"
    bl_label = "细分预览"

    def execute(self, context):
        wd = getattr(context.window_manager, 'hair_pipe_widget', None)
        if wd is None:
            return {'CANCELLED'}
        wd.show_smooth_preview = not wd.show_smooth_preview
        redraw_view3d(context)
        return {'FINISHED'}


class HAIRPIPE_OT_widget_toggle_flip(bpy.types.Operator):
    bl_idname = "hair_pipe.widget_toggle_flip"
    bl_label = "水平翻转"

    def execute(self, context):
        wd = getattr(context.window_manager, 'hair_pipe_widget', None)
        if wd is None:
            return {'CANCELLED'}
        wd.flip_horizontal = not wd.flip_horizontal
        redraw_view3d(context)
        return {'FINISHED'}


class HAIRPIPE_OT_widget_toggle_grid(bpy.types.Operator):
    bl_idname = "hair_pipe.widget_toggle_grid"
    bl_label = "显示网格"

    def execute(self, context):
        wd = getattr(context.window_manager, 'hair_pipe_widget', None)
        if wd is None:
            return {'CANCELLED'}
        wd.show_full_mesh_grid = not wd.show_full_mesh_grid
        redraw_view3d(context)
        return {'FINISHED'}


class HAIRPIPE_OT_widget_stop(bpy.types.Operator):
    """Close the interactive cross-section editor"""
    bl_idname = "hair_pipe.widget_stop"
    bl_label = "关闭横截面编辑器"

    def execute(self, context):
        set_curve_overlay_hidden(context, context.active_object, False)
        set_pipe_basemesh_preview(context, context.active_object, False)
        wd = context.window_manager.hair_pipe_widget
        wd.is_active = False
        wd.drag_vert_index = -1
        wd.hold_key_mode = False
        redraw_view3d(context)
        return {'FINISHED'}


classes = (
    HairPipeWidgetSettings,
    HAIRPIPE_OT_widget_interact,
    HAIRPIPE_OT_widget_hold,
    HAIRPIPE_OT_widget_add_vertex,
    HAIRPIPE_OT_widget_remove_vertex,
    HAIRPIPE_OT_widget_toggle_ghost,
    HAIRPIPE_OT_widget_make_normal,
    HAIRPIPE_OT_widget_toggle_smooth_preview,
    HAIRPIPE_OT_widget_toggle_flip,
    HAIRPIPE_OT_widget_toggle_grid,
    HAIRPIPE_OT_widget_stop,
)


def register_keymaps():
    pass


def unregister_keymaps():
    pass


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.hair_pipe_widget = bpy.props.PointerProperty(
        type=HairPipeWidgetSettings
    )
    ensure_draw_handler()
    register_keymaps()


def unregister():
    unregister_keymaps()
    remove_draw_handler()
    del bpy.types.WindowManager.hair_pipe_widget
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
