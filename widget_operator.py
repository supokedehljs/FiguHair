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
    box_select_active: BoolProperty(default=False)
    box_x0: FloatProperty(default=0.0)
    box_y0: FloatProperty(default=0.0)
    box_x1: FloatProperty(default=0.0)
    box_y1: FloatProperty(default=0.0)
    rotate_active: BoolProperty(default=False)
    move_active: BoolProperty(default=False)
    scale_active: BoolProperty(default=False)
    show_vert_indices: BoolProperty(default=False)
    show_full_mesh_grid: BoolProperty(default=False)
    rotate_start_x: FloatProperty(default=0.0)
    rotate_start_y: FloatProperty(default=0.0)
    move_start_x: FloatProperty(default=0.0)
    move_start_y: FloatProperty(default=0.0)
    scale_start_x: FloatProperty(default=0.0)
    scale_start_y: FloatProperty(default=0.0)
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

    outline = []
    for i in range(n):
        j = (i + 1) % n
        ix, iy = get_raw_offset(verts[i])
        jx, jy = get_raw_offset(verts[j])
        outline.append(effective_to_widget(ix, iy, panel_cx, panel_cy, panel_sf, alignment_angle, flip_h))
        outline.append(effective_to_widget(jx, jy, panel_cx, panel_cy, panel_sf, alignment_angle, flip_h))
    gpu.state.line_width_set(2.0 if is_active else 1.5)
    batch = batch_for_shader(shader, 'LINES', {"pos": outline})
    shader.bind()
    shader.uniform_float("color", (1.0, 0.8, 0.05, 1.0 * alpha_mult))
    batch.draw(shader)

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

    normal_pts = []
    ghost_pts = []
    for v in verts:
        ox, oy = get_raw_offset(v)
        point = effective_to_widget(ox, oy, panel_cx, panel_cy, panel_sf, alignment_angle, flip_h)
        if getattr(v, 'is_ghost', False):
            ghost_pts.append(point)
        else:
            normal_pts.append(point)
    if ghost_pts:
        draw_circle_points(shader, ghost_pts, (0.45, 0.65, 1.0, 0.45 * alpha_mult), 4.5 if is_active else 3.5)
    if normal_pts:
        draw_circle_points(shader, normal_pts, (1.0, 1.0, 1.0, 0.9 * alpha_mult), 5.0 if is_active else 4.0)

    if is_active:
        aidx = ps.active_vert_index
        if 0 <= aidx < n:
            ax, ay = get_raw_offset(verts[aidx])
            ap = [effective_to_widget(ax, ay, panel_cx, panel_cy, panel_sf, alignment_angle, flip_h)]
            active_color = (1.0, 0.5, 0.0, 1.0) if wd is not None and aidx in get_selected_widget_verts(wd) else ((0.0, 0.95, 1.0, 1.0) if not getattr(verts[aidx], 'is_ghost', False) else (0.55, 0.75, 1.0, 0.95))
            draw_circle_points(shader, ap, active_color, 5.0 if is_active else 4.0)

        if wd is not None:
            sel_indices = get_selected_widget_verts(wd)
            if sel_indices:
                sel_pts = []
                for si in sel_indices:
                    if 0 <= si < n:
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
    center = get_active_curve_point_world_position(context)
    if center is None:
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

    world_center = center
    best_start = None
    best_dist = None
    for start in range(0, len(mesh_verts) - segments + 1, segments):
        ring = mesh_verts[start:start + segments]
        ring_center = sum((Vector(v) for v in ring), Vector((0.0, 0.0, 0.0))) / segments
        ring_center_world = obj.matrix_world @ ring_center
        dist = (ring_center_world - world_center).length
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_start = start

    if best_start is None:
        return

    show_full_grid = bool(getattr(context.window_manager.hair_pipe_widget, 'show_full_mesh_grid', False))
    if show_full_grid:
        ring_count = len(mesh_verts) // segments
        view_forward = region_data.view_rotation @ Vector((0.0, 0.0, -1.0))
        camera_dir = -safe_normalized(view_forward)
        world_rings = []
        projected_rings = []
        front_masks = []
        for ring_idx in range(ring_count):
            start = ring_idx * segments
            ring_world = [obj.matrix_world @ Vector(vert) for vert in mesh_verts[start:start + segments]]
            if len(ring_world) != segments:
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
                continue
            world_rings.append(ring_world)
            projected_rings.append(projected)
            front_masks.append([(world_pos - ring_center).dot(camera_dir) >= 0.0 for world_pos in ring_world])

        grid_lines = []
        for ring, front_mask in zip(projected_rings, front_masks):
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
            for idx in range(min(len(ring), len(next_ring))):
                if mask[idx] or next_mask[idx]:
                    grid_lines.append(ring[idx])
                    grid_lines.append(next_ring[idx])

        if grid_lines:
            shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            gpu.state.blend_set('ALPHA')
            gpu.state.line_width_set(1.6)
            batch = batch_for_shader(shader, 'LINES', {"pos": grid_lines})
            shader.bind()
            shader.uniform_float("color", (0.2, 0.85, 1.0, 0.72))
            batch.draw(shader)

    ring_world = [obj.matrix_world @ Vector(v) for v in mesh_verts[best_start:best_start + segments]]
    projected = []
    for world_pos in ring_world:
        screen_pos = view3d_utils.location_3d_to_region_2d(region, region_data, world_pos)
        if screen_pos is None:
            return
        projected.append((screen_pos.x, screen_pos.y))

    lines = []
    for idx, point in enumerate(projected):
        lines.append(point)
        lines.append(projected[(idx + 1) % len(projected)])

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(4.0)
    batch = batch_for_shader(shader, 'LINES', {"pos": lines})
    shader.bind()
    shader.uniform_float("color", (1.0, 0.55, 0.0, 1.0))
    batch.draw(shader)

    gpu.state.point_size_set(7.0)
    batch = batch_for_shader(shader, 'POINTS', {"pos": projected})
    shader.bind()
    shader.uniform_float("color", (1.0, 1.0, 0.15, 0.95))
    batch.draw(shader)

    gpu.state.point_size_set(1.0)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


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
    alignment_angle = get_view_alignment_angle(context) + math.radians(settings.widget_correct_rotation)
    flip_h = wd.flip_horizontal

    base_radius = settings.default_radius
    if base_radius < 1e-6:
        base_radius = 0.05
    if wd.widget_scale_factor <= 1e-8:
        wd.widget_scale_factor = half / (base_radius * 2.4)
    sf = wd.widget_scale_factor

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')

    region = context.region
    dim_w = region.width if region is not None else size * 2.0
    dim_h = region.height if region is not None else size * 2.0
    dim_bg = [(0.0, 0.0), (dim_w, 0.0), (dim_w, dim_h), (0.0, dim_h)]
    batch = batch_for_shader(shader, 'TRIS', {"pos": dim_bg}, indices=[(0, 1, 2), (0, 2, 3)])
    shader.bind()
    shader.uniform_float("color", (0.0, 0.0, 0.0, 0.42))
    batch.draw(shader)

    # --- Thumbnail strip at top ---
    total_points = len(settings.point_settings)
    thumb_size = 140.0
    thumb_gap = 24.0
    thumb_total_w = total_points * thumb_size + (total_points - 1) * thumb_gap
    thumb_start_x = cx - thumb_total_w * 0.5
    thumb_y = cy + half + padding + 30.0
    thumb_sf = thumb_size * 0.28 / max(base_radius, 0.01)

    for pt_idx in range(total_points):
        tx = thumb_start_x + pt_idx * (thumb_size + thumb_gap) + thumb_size * 0.5
        ty = thumb_y
        is_current = (pt_idx == settings.active_point_index)

        th = thumb_size * 0.5

        pt_ps = settings.point_settings[pt_idx]
        if is_transition_point(pt_ps):
            font_id = 0
            blf.size(font_id, 13)
            blf.color(font_id, 0.25, 0.85, 1.0, 0.85 if is_current else 0.5)
            blf.position(font_id, tx - 22, ty - 6, 0)
            blf.draw(font_id, "AUTO")
            pt_verts = []
        else:
            pt_verts = pt_ps.cross_section_verts
        ptn = len(pt_verts)
        if ptn >= 3:
            thumb_outline = []
            for i in range(ptn):
                j = (i + 1) % ptn
                ix, iy = get_raw_offset(pt_verts[i])
                jx, jy = get_raw_offset(pt_verts[j])
                thumb_outline.append(effective_to_widget(ix, iy, tx, ty, thumb_sf, alignment_angle, flip_h))
                thumb_outline.append(effective_to_widget(jx, jy, tx, ty, thumb_sf, alignment_angle, flip_h))
            gpu.state.line_width_set(1.5 if is_current else 1.0)
            batch = batch_for_shader(shader, 'LINES', {"pos": thumb_outline})
            shader.bind()
            line_color = (1.0, 0.9, 0.2, 1.0) if is_current else (0.8, 0.7, 0.3, 0.7)
            shader.uniform_float("color", line_color)
            batch.draw(shader)

        font_id = 0
        blf.size(font_id, 15)
        if is_current:
            blf.color(font_id, 1.0, 0.4, 0.2, 1.0)
        else:
            blf.color(font_id, 0.7, 0.7, 0.7, 0.6)
        blf.position(font_id, tx - 6, ty - th - 20, 0)
        blf.draw(font_id, str(pt_idx))
        if is_current:
            gpu.state.line_width_set(2.0)
            underline = [(tx - 10, ty - th - 22), (tx + 10, ty - th - 22)]
            batch = batch_for_shader(shader, 'LINES', {"pos": underline})
            shader.bind()
            shader.uniform_float("color", (1.0, 0.4, 0.2, 1.0))
            batch.draw(shader)

    # Store thumbnail bounds for click detection
    wd.region_offset_x = wd.region_offset_x  # keep existing
    # We'll store strip info via computed values in modal

    # --- Main editor panel (center) ---
    draw_single_cross_section(shader, verts, ps, settings,
                               cx, cy, sf, alignment_angle, flip_h, half, True, wd)

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

    # --- Buttons ---
    x0, y0 = cx - half - padding, cy - half - padding
    button_h = 36.0
    gap = 8.0
    by0 = y0 - button_h - 12.0
    by1 = by0 + button_h
    font_id = 0
    button_defs = [
        ('add', "添加"),
        ('remove', "删除"),
        ('toggle', "幽灵点"),
        ('flip', "水平翻转"),
        ('idx', "显示网格"),
    ]
    button_widths = [button_width_for_label(font_id, label) for _key, label in button_defs]
    total_w = sum(button_widths) + gap * (len(button_widths) - 1)
    cur_x = cx - total_w * 0.5
    bounds = {}
    for (key, _label), width in zip(button_defs, button_widths):
        bounds[key] = (cur_x, by0, cur_x + width, by1)
        cur_x += width + gap

    add_x0, _, add_x1, _ = bounds['add']
    rem_x0, _, rem_x1, _ = bounds['remove']
    tog_x0, _, tog_x1, _ = bounds['toggle']
    flip_x0, _, flip_x1, _ = bounds['flip']
    idx_x0, _, idx_x1, _ = bounds['idx']
    wd.add_button_x0, wd.add_button_y0, wd.add_button_x1, wd.add_button_y1 = bounds['add']
    wd.remove_button_x0, wd.remove_button_y0, wd.remove_button_x1, wd.remove_button_y1 = bounds['remove']
    wd.toggle_button_x0, wd.toggle_button_y0, wd.toggle_button_x1, wd.toggle_button_y1 = bounds['toggle']
    wd.flip_button_x0, wd.flip_button_y0, wd.flip_button_x1, wd.flip_button_y1 = bounds['flip']
    wd.idx_button_x0, wd.idx_button_y0, wd.idx_button_x1, wd.idx_button_y1 = bounds['idx']
    wd.rotate_button_x0 = wd.rotate_button_y0 = wd.rotate_button_x1 = wd.rotate_button_y1 = 0.0

    can_remove = all(len(pset.cross_section_verts) > 3 for pset in settings.point_settings)
    active_is_ghost = 0 <= ps.active_vert_index < n and getattr(verts[ps.active_vert_index], 'is_ghost', False)
    draw_widget_button(shader, add_x0, by0, add_x1, by1)
    draw_widget_button(shader, rem_x0, by0, rem_x1, by1, enabled=can_remove)
    draw_widget_button(shader, tog_x0, by0, tog_x1, by1, active=active_is_ghost)
    draw_widget_button(shader, flip_x0, by0, flip_x1, by1, active=flip_h)
    draw_widget_button(shader, idx_x0, by0, idx_x1, by1, active=wd.show_full_mesh_grid)

    draw_centered_label(font_id, "添加", add_x0, by0, add_x1, by1)
    draw_centered_label(font_id, "删除", rem_x0, by0, rem_x1, by1, 1.0 if can_remove else 0.38)
    draw_centered_label(font_id, "幽灵点", tog_x0, by0, tog_x1, by1)
    draw_centered_label(font_id, "水平翻转", flip_x0, by0, flip_x1, by1)
    draw_centered_label(font_id, "显示网格", idx_x0, by0, idx_x1, by1)

    # Rotation correction field
    corr_w = 160.0
    corr_h = 32.0
    corr_x0 = cx - corr_w * 0.5
    corr_x1 = corr_x0 + corr_w
    corr_y0 = by0 - corr_h - 14.0
    corr_y1 = corr_y0 + corr_h
    wd.corr_rot_x0 = corr_x0
    wd.corr_rot_y0 = corr_y0
    wd.corr_rot_x1 = corr_x1
    wd.corr_rot_y1 = corr_y1
    draw_widget_button(shader, corr_x0, corr_y0, corr_x1, corr_y1, enabled=True,
                       active=abs(settings.widget_correct_rotation) > 0.01)
    font_id = 0
    blf.size(font_id, 14)
    blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
    corr_label = f"\u65cb\u8f6c\u4fee\u6b63: {settings.widget_correct_rotation:.1f}\u00b0"
    blf.position(font_id, corr_x0 + 8.0, corr_y0 + 9.0, 0)
    blf.draw(font_id, corr_label)

    blf.size(font_id, 13)
    blf.color(font_id, 0.7, 0.8, 0.9, 0.7)
    blf.position(font_id, 18.0, 24.0, 0)
    blf.draw(font_id, "\u70b9\u51fb\u4e0a\u65b9\u7f29\u7565\u56fe\u5207\u6362\u622a\u9762 | \u4e2d\u952e\u63d2\u5165\u70b9 | \u53f3\u952e\u62d6\u62fd\u6846\u9009")

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


def setup_widget(context):
    obj = context.active_object
    if obj is not None and obj.type == 'CURVE':
        sync_point_settings(obj)
        if is_curve_edit_mode(obj):
            sync_active_point_from_selection(obj)

    wd = context.window_manager.hair_pipe_widget
    area, region = get_view3d_window_region(context)
    if region is None:
        return False

    wd.region_offset_x = region.x
    wd.region_offset_y = region.y
    wd.widget_size = min(region.width, region.height) * 0.62
    wd.widget_center_x = region.width / 2.0
    wd.widget_center_y = region.height / 2.0
    wd.widget_scale_factor = 0.0
    wd.is_active = True
    wd.drag_vert_index = -1
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
    obj = context.active_object
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



def find_nearest_raw_vertex(verts, mx, my, panel_cx, panel_cy, panel_sf, alignment_angle, flip_h, max_dist=24.0):
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
        if obj is None or obj.type != 'CURVE':
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
        wd = context.window_manager.hair_pipe_widget
        wd.is_active = False
        wd.drag_vert_index = -1
        wd.move_active = False
        wd.rotate_active = False
        wd.scale_active = False
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

    if close_on_key_release and event.value == 'RELEASE' and event.type not in {'LEFTMOUSE', 'RIGHTMOUSE', 'MIDDLEMOUSE', 'MOUSEMOVE'}:
        operator._finish(context)
        return {'FINISHED'}

    obj = context.active_object
    if obj is None or obj.type != 'CURVE':
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
    alignment_angle = get_view_alignment_angle(context) + math.radians(settings.widget_correct_rotation)
    flip_h = wd.flip_horizontal
    mx, my = operator._get_local_mouse(event, wd)
    half = wd.widget_size / 2.0
    inside_widget = abs(mx - cx) <= half and abs(my - cy) <= half
    inside_add_button = is_inside_rect(mx, my, wd.add_button_x0, wd.add_button_y0, wd.add_button_x1, wd.add_button_y1)
    inside_remove_button = is_inside_rect(mx, my, wd.remove_button_x0, wd.remove_button_y0, wd.remove_button_x1, wd.remove_button_y1)
    inside_toggle_button = is_inside_rect(mx, my, wd.toggle_button_x0, wd.toggle_button_y0, wd.toggle_button_x1, wd.toggle_button_y1)
    inside_flip_button = is_inside_rect(mx, my, wd.flip_button_x0, wd.flip_button_y0, wd.flip_button_x1, wd.flip_button_y1)
    inside_idx_button = is_inside_rect(mx, my, wd.idx_button_x0, wd.idx_button_y0, wd.idx_button_x1, wd.idx_button_y1)
    inside_controls = inside_add_button or inside_remove_button or inside_toggle_button or inside_flip_button or inside_idx_button
    drag_threshold = 4.0

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
            wd.box_x0 = wd.left_drag_start_x
            wd.box_y0 = wd.left_drag_start_y
            wd.box_x1 = mx
            wd.box_y1 = my
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
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
            selected = set()
            for i, v in enumerate(verts):
                ox, oy = get_raw_offset(v)
                px, py = effective_to_widget(ox, oy, cx, cy, sf, alignment_angle, flip_h)
                if bx0 <= px <= bx1 and by0 <= py <= by1:
                    selected.add(i)
            if event.shift:
                selected = selected | get_selected_widget_verts(wd)
            set_selected_widget_verts(wd, selected)
            wd.box_select_active = False
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
            if 0 <= ps.active_vert_index < len(verts):
                push_widget_undo(context, "切换横截面幽灵点")
                verts[ps.active_vert_index].is_ghost = not getattr(verts[ps.active_vert_index], 'is_ghost', False)
                update_ghost_vertices(ps)
                sync_active_cross_section_to_selected_points(context)
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
        inside_corr_rot = is_inside_rect(mx, my, wd.corr_rot_x0, wd.corr_rot_y0, wd.corr_rot_x1, wd.corr_rot_y1)
        if inside_corr_rot:
            push_widget_undo(context, "旋转修正横截面编辑器")
            wd.corr_rot_dragging = True
            wd.corr_rot_drag_start_x = mx
            wd.corr_rot_drag_start_val = settings.widget_correct_rotation
            redraw_view3d(context)
            return {'RUNNING_MODAL'}

        total_points = len(settings.point_settings)
        thumb_size = 140.0
        thumb_gap = 24.0
        thumb_total_w = total_points * thumb_size + (total_points - 1) * thumb_gap
        thumb_start_x = cx - thumb_total_w * 0.5
        thumb_y = cy + half + 18 + 30.0
        thumb_th = thumb_size * 0.5
        for pt_idx in range(total_points):
            tx = thumb_start_x + pt_idx * (thumb_size + thumb_gap) + thumb_size * 0.5
            if abs(mx - tx) <= thumb_th and abs(my - thumb_y) <= thumb_th:
                settings.active_point_index = pt_idx
                select_curve_point_by_index(obj, pt_idx)
                wd.drag_vert_index = -1
                set_selected_widget_verts(wd, set())
                redraw_view3d(context)
                return {'RUNNING_MODAL'}

        closest_idx = find_nearest_raw_vertex(verts, mx, my, cx, cy, sf, alignment_angle, flip_h)
        wd.left_drag_pending = True
        wd.left_drag_active = False
        wd.left_drag_start_x = mx
        wd.left_drag_start_y = my
        wd.left_drag_vert_index = closest_idx
        wd.drag_vert_index = closest_idx
        redraw_view3d(context)
        return {'RUNNING_MODAL'}

    # Rotation correction drag
    if event.type == 'MOUSEMOVE' and wd.corr_rot_dragging:
        delta_x = mx - wd.corr_rot_drag_start_x
        settings.widget_correct_rotation = wd.corr_rot_drag_start_val + delta_x * 0.5
        redraw_view3d(context)
        return {'RUNNING_MODAL'}

    if event.type == 'LEFTMOUSE' and event.value == 'RELEASE' and wd.corr_rot_dragging:
        wd.corr_rot_dragging = False
        redraw_view3d(context)
        return {'RUNNING_MODAL'}

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
        if not sel and 0 <= ps.active_vert_index < len(verts):
            sel = {ps.active_vert_index}
            set_selected_widget_verts(wd, sel)
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
        if not sel and 0 <= ps.active_vert_index < len(verts):
            sel = {ps.active_vert_index}
            set_selected_widget_verts(wd, sel)
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

    if event.type == 'S' and event.value == 'PRESS':
        sel = get_selected_widget_verts(wd)
        if not sel and 0 <= ps.active_vert_index < len(verts):
            sel = {ps.active_vert_index}
            set_selected_widget_verts(wd, sel)
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
        wd.move_active = False
        wd.rotate_active = False
        wd.scale_active = False
        wd.box_select_active = False
        wd.left_drag_pending = False
        wd.left_drag_active = False
        wd.left_drag_vert_index = -1
        wd.lasso_select_active = False
        operator._finish(context)
        return {'FINISHED'}

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


class HAIRPIPE_OT_widget_stop(bpy.types.Operator):
    """Close the interactive cross-section editor"""
    bl_idname = "hair_pipe.widget_stop"
    bl_label = "关闭横截面编辑器"

    def execute(self, context):
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
