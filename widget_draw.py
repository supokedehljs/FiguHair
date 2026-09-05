import bpy
import gpu
import math
import blf
import time
import json
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
from mathutils import Vector
from .curve_data import get_curve_points_data, is_curve_edit_mode, get_selected_curve_point_indices
from .hair_lifecycle import get_pipe_object_for_curve, get_pipe_source_curve
from .ghost import update_all_ghost_vertices, update_ghost_vertices
from .math_utils import catmull_rom_2d, get_cross_section_frame, safe_normalized
from .widget_geometry import get_raw_offset, effective_to_widget, chaikin_closed, make_smooth_preview_lines, get_stable_widget_alignment, fit_widget_scale_to_cross_section
from .widget_state import get_selected_widget_verts, get_widget_source_curve, get_active_curve_point, redraw_view3d, get_curve_point_by_index, select_curve_point_by_index, proportional_edit_enabled, get_lasso_points, context_matches_widget_view
from .widget_cache import get_cached_pipe_mesh
from .pipe_generation import generate_pipe_mesh
from .transition import is_transition_point
from .roll_diagnostics import get_uncontrolled_roll_diagnostics

_draw_handle = None


def draw_cross_section_delete_menu(self, context):
    layout = self.layout
    layout.separator()
    layout.operator(
        HAIRPIPE_OT_widget_delete_selected_vertices.bl_idname,
        text="删除横截面顶点",
        icon='REMOVE',
    )


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


def get_longitudinal_circle_screen_data(context, obj, settings, radius):
    region = context.region
    region_data = context.region_data
    active_idx = settings.active_point_index
    if region is None or region_data is None or active_idx < 0:
        return None, 0.0

    world_positions = []
    for spline_data in get_curve_points_data(obj):
        for point_data in spline_data.get('points', []):
            world_positions.append(obj.matrix_world @ point_data['co'])
    if active_idx >= len(world_positions):
        return None, 0.0

    center = view3d_utils.location_3d_to_region_2d(region, region_data, world_positions[active_idx])
    if center is None:
        return None, 0.0

    adjacent_distances = []
    for target_idx in (active_idx - 1, active_idx + 1):
        if 0 <= target_idx < len(world_positions):
            projected = view3d_utils.location_3d_to_region_2d(region, region_data, world_positions[target_idx])
            if projected is not None:
                adjacent_distances.append(math.hypot(projected.x - center.x, projected.y - center.y))
    pixels_per_section = sum(adjacent_distances) / len(adjacent_distances) if adjacent_distances else 24.0
    pixels_per_section = max(8.0, min(80.0, pixels_per_section))
    return (center.x, center.y), max(18.0, radius * pixels_per_section)


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
                selected_ghost_pts = []
                for si in sel_indices:
                    if 0 <= si < n:
                        sx, sy = get_raw_offset(verts[si])
                        point = effective_to_widget(sx, sy, panel_cx, panel_cy, panel_sf, alignment_angle, flip_h)
                        if getattr(verts[si], 'is_ghost', False):
                            selected_ghost_pts.append(point)
                        else:
                            sel_pts.append(point)
                if sel_pts:
                    draw_circle_points(shader, sel_pts, (1.0, 0.5, 0.0, 1.0), 5.0)
                if selected_ghost_pts:
                    draw_circle_points(shader, selected_ghost_pts, (1.0, 0.38, 0.02, 0.9), 2.35, segments=12)




def get_curve_start_world_positions(obj):
    if obj is None or obj.type != 'CURVE':
        return []
    starts = []
    for spline in obj.data.splines:
        if spline.type == 'BEZIER':
            if len(spline.bezier_points) > 0:
                starts.append(obj.matrix_world @ spline.bezier_points[0].co)
        elif len(spline.points) > 0:
            starts.append(obj.matrix_world @ Vector(spline.points[0].co[:3]))
    return starts


def get_curve_start_world_position(obj):
    starts = get_curve_start_world_positions(obj)
    return starts[0] if starts else None


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
    start_positions = get_curve_start_world_positions(obj)
    if not start_positions:
        return
    projected = []
    for start_world in start_positions:
        pos = view3d_utils.location_3d_to_region_2d(region, region_data, start_world)
        if pos is not None:
            projected.append((pos.x, pos.y))
    if not projected:
        return

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.point_size_set(9.0)
    batch = batch_for_shader(shader, 'POINTS', {"pos": projected})
    shader.bind()
    shader.uniform_float("color", (0.1, 1.0, 0.15, 1.0))
    batch.draw(shader)

    gpu.state.point_size_set(1.0)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def draw_uncontrolled_roll_markers(context, obj):
    if obj is None or obj.type != 'CURVE' or not is_curve_edit_mode(obj):
        return
    diagnostics = get_uncontrolled_roll_diagnostics(obj)
    if not diagnostics:
        return
    region = context.region
    region_data = context.region_data
    if region is None or region_data is None:
        return

    font_id = 0
    blf.size(font_id, 13)
    blf.color(font_id, 1.0, 0.08, 0.04, 1.0)
    for point_idx, local_position, angle in diagnostics:
        screen = view3d_utils.location_3d_to_region_2d(region, region_data, obj.matrix_world @ local_position)
        if screen is None:
            continue
        blf.position(font_id, screen.x + 9.0, screen.y + 9.0, 0)
        blf.draw(font_id, f"{angle:+.1f}°")


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


def get_curve_highlight_point_index(obj):
    settings = getattr(obj, 'hair_pipe_settings', None)
    if settings is None or not settings.point_settings:
        return -1
    selected = get_selected_curve_point_indices(obj) if is_curve_edit_mode(obj) else []
    if len(selected) == 1 and 0 <= selected[0] < len(settings.point_settings):
        obj['hair_pipe_last_highlight_point'] = int(selected[0])
        return selected[0]
    stored = int(obj.get('hair_pipe_last_highlight_point', settings.active_point_index))
    return max(0, min(stored, len(settings.point_settings) - 1))


def get_selected_curve_highlight_targets(context, active_obj):
    targets = []
    for selected_obj in context.selected_objects:
        if selected_obj.type != 'CURVE' or not hasattr(selected_obj, 'hair_pipe_settings'):
            continue
        settings = selected_obj.hair_pipe_settings
        if not settings.plugin_enabled or not is_curve_edit_mode(selected_obj):
            continue
        point_idx = get_curve_highlight_point_index(selected_obj)
        if point_idx >= 0:
            targets.append((selected_obj, point_idx))
    if active_obj is not None and active_obj.type == 'CURVE' and all(
        target[0] != active_obj for target in targets
    ):
        point_idx = get_curve_highlight_point_index(active_obj)
        if point_idx >= 0:
            targets.insert(0, (active_obj, point_idx))
    return targets


def draw_active_pipe_cross_section_ring(context, ps, curve_obj=None, point_idx=None):
    region = context.region
    region_data = context.region_data
    obj = curve_obj or context.active_object
    if region is None or region_data is None or obj is None or obj.type != 'CURVE':
        return
    if len(ps.cross_section_verts) < 3:
        return

    try:
        mesh_verts, _faces = get_cached_pipe_mesh(obj)
    except Exception:
        mesh_verts = None
    if not mesh_verts:
        return

    segments = len(ps.cross_section_verts)
    if segments < 3 or len(mesh_verts) < segments:
        return

    active_idx = point_idx if point_idx is not None else get_curve_highlight_point_index(obj)
    selected_curve_indices = [active_idx] if active_idx >= 0 else []

    control_positions = []
    spline_ranges = []
    point_offset = 0
    for spline_data in get_curve_points_data(obj):
        spline_points = spline_data.get('points', [])
        control_positions.extend(obj.matrix_world @ point_data['co'] for point_data in spline_points)
        spline_ranges.append((point_offset, point_offset + len(spline_points)))
        point_offset += len(spline_points)

    active_spline_range = next(
        (item for item in spline_ranges if item[0] <= active_idx < item[1]),
        None,
    )
    all_spline_ring_ranges = []
    for idx, spline_data in enumerate(get_curve_points_data(obj)):
        point_count = len(spline_data.get('points', []))
        if point_count < 2:
            all_spline_ring_ranges.append(((0, 0), segments))
        else:
            # sampled ring count per spline; segments for display ring may differ
            segment_count = point_count if spline_data.get('cyclic', False) else point_count - 1
            sample_steps = segment_count * max(1, int(getattr(obj.hair_pipe_settings, 'pipe_resolution', 0)) + 1)
            ring_count_for_spline = sample_steps if spline_data.get('cyclic', False) else sample_steps + 1
            start_ring = all_spline_ring_ranges[-1][0][1] if all_spline_ring_ranges else 0
            end_ring = start_ring + ring_count_for_spline
            ps_seg = len(obj.hair_pipe_settings.point_settings[spline_ranges[idx][0]].cross_section_verts) if idx < len(spline_ranges) and spline_ranges[idx][0] < len(obj.hair_pipe_settings.point_settings) and len(obj.hair_pipe_settings.point_settings[spline_ranges[idx][0]].cross_section_verts) >= 3 else segments
            all_spline_ring_ranges.append(((start_ring, end_ring), ps_seg))
        start_ring = all_spline_ring_ranges[-1][0][1] if all_spline_ring_ranges else 0
        end_ring = start_ring + (all_spline_ring_ranges[-1][0][1] - all_spline_ring_ranges[-1][0][0]) if all_spline_ring_ranges else 0
    ring_counts_for_segments = {}
    for idx, (s_start, s_end) in enumerate(spline_ranges):
        ring_range = all_spline_ring_ranges[idx][0] if idx < len(all_spline_ring_ranges) else (0, 0)
        if ring_range[1] > ring_range[0]:
            ring_counts_for_segments[(s_start, s_end)] = ring_range
    active_spline_ring_range = None
    for idx, spline_range in enumerate(spline_ranges):
        if spline_range[0] <= active_idx < spline_range[1]:
            active_spline_ring_range = all_spline_ring_ranges[idx][0] if idx < len(all_spline_ring_ranges) else None
            break
    ring_candidates = []
    for start in range(0, len(mesh_verts) - segments + 1, segments):
        ring = mesh_verts[start:start + segments]
        ring_center = sum((Vector(v) for v in ring), Vector((0.0, 0.0, 0.0))) / segments
        ring_candidates.append((start, obj.matrix_world @ ring_center))

    selected_ring_starts = []
    used_starts = set()
    candidate_slice = ring_candidates
    if active_spline_ring_range is not None:
        r0, r1 = active_spline_ring_range
        candidate_slice = [item for item in ring_candidates if r0 * segments <= item[0] < r1 * segments]
    for point_idx in selected_curve_indices:
        if not (0 <= point_idx < len(control_positions)):
            continue
        point_setting = obj.hair_pipe_settings.point_settings[point_idx] if point_idx < len(obj.hair_pipe_settings.point_settings) else None
        if point_setting is not None and is_transition_point(point_setting):
            continue
        world_center = control_positions[point_idx]
        best_start = None
        best_dist = None
        for start, ring_center_world in candidate_slice:
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
    preview_mode = getattr(wd, 'preview_mode', 'SUBDIV')
    show_roll_grid = False
    show_section_grid = False
    ring_count = len(mesh_verts) // segments
    spline_ring_ranges = []
    for spline_data in get_curve_points_data(obj):
        point_count = len(spline_data.get('points', []))
        if point_count < 2:
            spline_ring_ranges.append((0, 0))
            continue
        segment_count = point_count if spline_data.get('cyclic', False) else point_count - 1
        sample_steps = segment_count * max(1, int(getattr(obj.hair_pipe_settings, 'pipe_resolution', 0)) + 1)
        ring_count_for_spline = sample_steps if spline_data.get('cyclic', False) else sample_steps + 1
        start_ring = spline_ring_ranges[-1][1] if spline_ring_ranges else 0
        end_ring = min(ring_count, start_ring + ring_count_for_spline)
        spline_ring_ranges.append((start_ring, end_ring))
    if not spline_ring_ranges and ring_count:
        spline_ring_ranges.append((0, ring_count))
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

    bridge_offsets = [None] * max(0, ring_count - 1)
    ring_to_point = {}
    if active_spline_range is not None and active_spline_ring_range is not None:
        s_start, s_end = active_spline_range
        r_start, r_end = active_spline_ring_range
        local_ring_count = max(1, r_end - r_start)
        for ring_idx in range(ring_count):
            if r_start <= ring_idx < r_end:
                t = (ring_idx - r_start) / max(1, local_ring_count - 1)
                mapped = int(round(s_start + t * (s_end - s_start - 1)))
                mapped = max(s_start, min(s_end - 1, mapped))
                ring_to_point[ring_idx] = mapped
    for ring_idx in range(len(bridge_offsets)):
        if ring_idx in ring_to_point and ring_idx + 1 in ring_to_point:
            src = ring_to_point[ring_idx]
            dst = ring_to_point[ring_idx + 1]
            src_spline = active_spline_range is not None and active_spline_range[0] <= src < active_spline_range[1]
            dst_spline = active_spline_range is not None and active_spline_range[0] <= dst < active_spline_range[1]
            if src_spline and dst_spline:
                bridge_offsets[ring_idx] = int(
                    getattr(obj.hair_pipe_settings.point_settings[dst], 'bridge_offset', 0)
                ) if dst < len(obj.hair_pipe_settings.point_settings) else 0
            else:
                bridge_offsets[ring_idx] = None
            continue
        next_start = (ring_idx + 1) * segments
        next_ring = mesh_verts[next_start:next_start + segments]
        if len(next_ring) != segments or not control_positions:
            bridge_offsets[ring_idx] = None
            continue
        next_center = sum((Vector(vertex) for vertex in next_ring), Vector((0.0, 0.0, 0.0))) / segments
        next_center_world = obj.matrix_world @ next_center
        target_idx = min(
            range(len(control_positions)),
            key=lambda idx: (control_positions[idx] - next_center_world).length_squared,
        )
        same_spline = active_spline_range is not None and active_spline_range[0] <= target_idx < active_spline_range[1]
        if same_spline and target_idx < len(obj.hair_pipe_settings.point_settings):
            bridge_offsets[ring_idx] = int(
                getattr(obj.hair_pipe_settings.point_settings[target_idx], 'bridge_offset', 0)
            )
        else:
            bridge_offsets[ring_idx] = None

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')

    if show_full_grid or show_roll_grid or show_section_grid:
        grid_lines = []
        valid_projected = [(ring, mask) for ring, mask in zip(projected_rings, front_masks) if ring is not None and mask is not None]
        if show_full_grid or show_section_grid:
            for ring, front_mask in valid_projected:
                for idx, point in enumerate(ring):
                    next_idx = (idx + 1) % len(ring)
                    if front_mask[idx] or front_mask[next_idx]:
                        grid_lines.append(point)
                        grid_lines.append(ring[next_idx])
        ring_connection_range = range(len(projected_rings) - 1) if (show_full_grid or show_roll_grid) else ()
        for ring_idx in ring_connection_range:
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
        active_ring_idx = selected_ring_starts[0][1] // segments if selected_ring_starts else ring_count // 2
        fade_distance = max(3, min(12, int(math.ceil(ring_count * 0.18))))
        gpu.state.line_width_set(1.65)
        for selected_idx in sorted(selected_indices):
            ring_indices = {active_ring_idx: selected_idx}
            for ring_idx in range(active_ring_idx, len(projected_rings) - 1):
                current_idx = ring_indices[ring_idx]
                offset = bridge_offsets[ring_idx]
                if offset is None:
                    break
                ring_indices[ring_idx + 1] = (current_idx + offset) % segments
            for ring_idx in range(active_ring_idx - 1, -1, -1):
                next_idx = ring_indices[ring_idx + 1]
                offset = bridge_offsets[ring_idx]
                if offset is None:
                    break
                ring_indices[ring_idx] = (next_idx - offset) % segments

            for ring_idx in range(len(projected_rings) - 1):
                ring = projected_rings[ring_idx]
                next_ring = projected_rings[ring_idx + 1]
                current_idx = ring_indices.get(ring_idx)
                next_idx = ring_indices.get(ring_idx + 1)
                if ring is None or next_ring is None or current_idx is None or next_idx is None:
                    continue
                distance = abs(ring_idx + 0.5 - active_ring_idx)
                if distance >= fade_distance:
                    continue
                alpha = 0.95 * (1.0 - distance / fade_distance)
                segment_lines = (ring[current_idx], next_ring[next_idx])
                batch = batch_for_shader(shader, 'LINES', {"pos": segment_lines})
                shader.bind()
                shader.uniform_float("color", (1.0, 0.55, 0.0, alpha))
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
            gpu.state.line_width_set(1.65 if is_active_ring else 1.3)
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
            normal_color = (1.0, 1.0, 1.0, 0.92) if is_active_ring else (1.0, 0.78, 0.05, 0.72)
            draw_circle_points(shader, normal_points, normal_color, 3.4 if is_active_ring else 3.0, segments=18)
        if selected_points:
            draw_circle_points(shader, selected_points, (1.0, 0.5, 0.0, 1.0), 4.2, segments=18)

    gpu.state.point_size_set(1.0)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def get_pipe_control_vertices_in_screen_rect(context, x0, y0, x1, y1, spline_filter=None):
    region = context.region
    region_data = context.region_data
    obj = context.active_object
    if region is None or region_data is None or obj is None or obj.type != 'CURVE':
        return []

    settings = obj.hair_pipe_settings
    if len(settings.point_settings) == 0:
        return []

    try:
        mesh_verts, _faces = get_cached_pipe_mesh(obj)
    except Exception:
        return []
    if not mesh_verts:
        return []

    segments = len(settings.point_settings[0].cross_section_verts)
    if segments < 3 or len(mesh_verts) < segments:
        return []

    spline_ranges = get_curve_spline_point_ranges_bypass(obj) if 'get_curve_spline_point_ranges_bypass' in globals() else []
    if not spline_ranges:
        offset = 0
        for spline in obj.data.splines:
            count = len(spline.bezier_points) if spline.type == 'BEZIER' else len(spline.points)
            spline_ranges.append((offset, offset + count))
            offset += count
    allowed = set()
    if spline_filter is not None:
        allowed.add(spline_filter)
    else:
        active_idx = settings.active_point_index
        for start, end in spline_ranges:
            if start <= active_idx < end:
                allowed.add((start, end))
                break

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
        point_in_allowed = any(start <= point_idx < end for start, end in allowed) if allowed else True
        if not point_in_allowed:
            continue
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
        mesh_verts, _faces = get_cached_pipe_mesh(obj)
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

    wm = context.window_manager
    if not hasattr(wm, 'hair_pipe_widget'):
        return
    wd = wm.hair_pipe_widget
    if not wd.is_active or not context_matches_widget_view(context, wd):
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
    draw_uncontrolled_roll_markers(context, obj)

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
    for section_obj, highlight_idx in get_selected_curve_highlight_targets(context, obj):
        section_settings = section_obj.hair_pipe_settings
        if 0 <= highlight_idx < len(section_settings.point_settings):
            draw_active_pipe_cross_section_ring(
                context,
                section_settings.point_settings[highlight_idx],
                section_obj,
                highlight_idx,
            )

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

    if wd.widget_scale_factor <= 1e-8 or wd.fitted_point_index != settings.active_point_index:
        fit_widget_scale_to_cross_section(wd, verts, half, alignment_angle, flip_h)
        wd.fitted_point_index = settings.active_point_index
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

    if proportional_edit_enabled(context) and wd.move_active:
        circle_center, circle_radius = get_longitudinal_circle_screen_data(
            context, obj, settings, wd.longitudinal_radius
        )
        if circle_center is not None:
            draw_circle_outline(
                shader,
                [circle_center],
                (1.0, 1.0, 1.0, 0.92),
                circle_radius,
                segments=64,
                line_width=1.5,
            )

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


