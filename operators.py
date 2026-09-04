import bpy
import gpu
import math
import json
import time
import random
import colorsys
from gpu_extras.batch import batch_for_shader
from pathlib import Path
from mathutils import Matrix, Vector
from bpy.props import IntProperty, FloatProperty, EnumProperty, BoolProperty, StringProperty
from bpy_extras import view3d_utils
from .cross_section import (
    add_cross_section_vertex_after as cross_section_add_cross_section_vertex_after,
    get_curve_spline_point_ranges as cross_section_get_curve_spline_point_ranges,
    get_active_spline_point_range as cross_section_get_active_spline_point_range,
    add_cross_section_vertex_after_all as cross_section_add_cross_section_vertex_after_all,
    remove_cross_section_vertex_all as cross_section_remove_cross_section_vertex_all,
    normalize_cross_section_topology as cross_section_normalize_cross_section_topology,
)
from .curve_data import (
    ensure_curve_defaults as curve_ensure_curve_defaults,
    get_curve_points_data as curve_get_curve_points_data,
    is_curve_edit_mode as curve_is_curve_edit_mode,
    get_selected_curve_point_index as curve_get_selected_curve_point_index,
    get_selected_curve_point_indices as curve_get_selected_curve_point_indices,
)
from .frames import (
    build_minimal_twist_rings as frames_build_minimal_twist_rings,
    smooth_ring_offsets as frames_smooth_ring_offsets,
    make_ring_from_frame as frames_make_ring_from_frame,
)
from .ghost import (
    update_ghost_vertices as ghost_update_ghost_vertices,
    update_all_ghost_vertices as ghost_update_all_ghost_vertices,
)
from .interp import (
    ease_value as interp_ease_value,
    lerp_value as interp_lerp_value,
    mix_value as interp_mix_value,
    monotone_tangent as interp_monotone_tangent,
    hermite_value as interp_hermite_value,
    interpolate_section_value as interp_interpolate_section_value,
)
from .sampling import (
    evaluate_bezier_segment as sampling_evaluate_bezier_segment,
    evaluate_bezier_tangent as sampling_evaluate_bezier_tangent,
    make_nurbs_knot_vector as sampling_make_nurbs_knot_vector,
    find_nurbs_span as sampling_find_nurbs_span,
    nurbs_basis_values as sampling_nurbs_basis_values,
    get_nurbs_weighted_controls as sampling_get_nurbs_weighted_controls,
    evaluate_nurbs_from_weighted as sampling_evaluate_nurbs_from_weighted,
    get_nurbs_domain as sampling_get_nurbs_domain,
    distribute_steps_by_lengths as sampling_distribute_steps_by_lengths,
    bezier_arc_length_at_t as sampling_bezier_arc_length_at_t,
    invert_bezier_arc_length as sampling_invert_bezier_arc_length,
    make_cumulative_lengths as sampling_make_cumulative_lengths,
    find_nearest_center_distance as sampling_find_nearest_center_distance,
    average_tangents as sampling_average_tangents,
    get_bezier_control_tangent as sampling_get_bezier_control_tangent,
    get_poly_control_tangent as sampling_get_poly_control_tangent,
)
from .math_utils import (
    catmull_rom_vector as math_catmull_rom_vector,
    catmull_rom_tangent_vector as math_catmull_rom_tangent_vector,
    safe_normalized as math_safe_normalized,
    get_cross_section_frame as math_get_cross_section_frame,
    catmull_rom_2d as math_catmull_rom_2d,
    catmull_rom_value as math_catmull_rom_value,
    lerp_angle as math_lerp_angle,
    lerp_radians as math_lerp_radians,
)
from .transition import (
    is_transition_point as transition_is_transition_point,
    find_previous_editable_point_index as transition_find_previous_editable_point_index,
    find_next_editable_point_index as transition_find_next_editable_point_index,
    get_transition_source_indices as transition_get_transition_source_indices,
    get_point_setting as transition_get_point_setting,
    get_effective_point_setting as transition_get_effective_point_setting,
    get_cross_section_sample as transition_get_cross_section_sample,
    interpolate_cross_sections as transition_interpolate_cross_sections,
    interpolate_cross_sections_smooth as transition_interpolate_cross_sections_smooth,
    interpolate_transition_cross_section as transition_interpolate_transition_cross_section,
    update_transition_point_values as transition_update_transition_point_values,
    interpolate_nurbs_cross_sections as transition_interpolate_nurbs_cross_sections,
    interpolate_nurbs_cross_sections_by_control_range as transition_interpolate_nurbs_cross_sections_by_control_range,
    interpolate_cross_sections_by_anchor_distance as transition_interpolate_cross_sections_by_anchor_distance,
)
from .edit_utils import (
    get_curve_point_by_global_index as edit_get_curve_point_by_global_index,
    edge_flow_t as edit_edge_flow_t,
    find_previous_edge_flow_source_index as edit_find_previous_edge_flow_source_index,
    find_next_edge_flow_source_index as edit_find_next_edge_flow_source_index,
    apply_edge_flow_to_target_indices as edit_apply_edge_flow_to_target_indices,
)
from .point_data import (
    sync_point_settings as point_sync_point_settings,
    sync_active_point_from_selection as point_sync_active_point_from_selection,
    init_cross_section_circle as point_init_cross_section_circle,
    _curve_point_position_signatures as point__curve_point_position_signatures,
    _load_curve_point_signatures as point__load_curve_point_signatures,
    _store_curve_point_signatures as point__store_curve_point_signatures,
    _point_setting_to_data as point__point_setting_to_data,
    _default_point_setting_data as point__default_point_setting_data,
    _apply_point_setting_data as point__apply_point_setting_data,
)
from .pipe_generation import (
    generate_pipe_mesh as pipe_generate_pipe_mesh,
)
from .selection import (
    ensure_selected_curve_visible as selection_ensure_selected_curve_visible,
    sync_selected_curve_visibility as selection_sync_selected_curve_visibility,
    redirect_pipe_selection as selection_redirect_pipe_selection,
)
from .hair_lifecycle import (
    get_next_figuhair_base_name as lifecycle_get_next_figuhair_base_name,
    get_curve_from_figuhair_root as lifecycle_get_curve_from_figuhair_root,
    get_figuhair_root as lifecycle_get_figuhair_root,
    ensure_figuhair_root as lifecycle_ensure_figuhair_root,
    get_pipe_mesh_name as lifecycle_get_pipe_mesh_name,
    get_tail_mesh_name as lifecycle_get_tail_mesh_name,
    get_pipe_object_for_curve as lifecycle_get_pipe_object_for_curve,
    get_tail_object_for_curve as lifecycle_get_tail_object_for_curve,
    get_pipe_source_curve as lifecycle_get_pipe_source_curve,
    get_tail_source_curve as lifecycle_get_tail_source_curve,
    get_context_curve_object as lifecycle_get_context_curve_object,
    get_hair_family_objects as lifecycle_get_hair_family_objects,
    generated_pipe_vertices as lifecycle_generated_pipe_vertices,
    set_generated_object_transform as lifecycle_set_generated_object_transform,
)
from .hair_ops import (
    HAIRPIPE_OT_toggle_plugin_enabled as hair_ops_toggle_plugin_enabled,
    HAIRPIPE_OT_hide_hair as hair_ops_hide_hair,
    HAIRPIPE_OT_show_all_hair as hair_ops_show_all_hair,
    HAIRPIPE_OT_family_local_view as hair_ops_family_local_view,
    HAIRPIPE_OT_delete_hair as hair_ops_delete_hair,
    HAIRPIPE_OT_duplicate_hair as hair_ops_duplicate_hair,
    HAIRPIPE_OT_merge_hair_for_export as hair_ops_merge_hair_for_export,
    _is_pipe_mesh_obj as hair_ops_is_pipe_mesh_obj,
    _is_tail_mesh_only_obj as hair_ops_is_tail_mesh_only_obj,
    _is_figuhair_family_obj as hair_ops_is_figuhair_family_obj,
    _copy_spline_to_curve as hair_ops_copy_spline_to_curve,
)
from .cross_section_ops import (
    HAIRPIPE_OT_toggle_cross_section_transition as cs_toggle_cross_section_transition,
    HAIRPIPE_OT_reset_cross_section as cs_reset_cross_section,
    HAIRPIPE_OT_reset_all_cross_sections as cs_reset_all_cross_sections,
    HAIRPIPE_OT_taper_linear as cs_taper_linear,
    HAIRPIPE_OT_add_cs_vert as cs_add_cs_vert,
    HAIRPIPE_OT_remove_cs_vert as cs_remove_cs_vert,
    HAIRPIPE_OT_select_point as cs_select_point,
    HAIRPIPE_OT_copy_cross_section as cs_copy_cross_section,
    HAIRPIPE_OT_paste_cross_section as cs_paste_cross_section,
    HAIRPIPE_OT_copy_cs_to_all as cs_copy_cs_to_all,
    copy_point_cross_section as cs_copy_point_cross_section,
    _HAIRPIPE_CROSS_SECTION_CLIPBOARD as cs_clipboard,
)
from .pipe_ops import (
    HAIRPIPE_OT_mesh_to_hair_curve as pipe_mesh_to_hair_curve,
    HAIRPIPE_OT_generate_pipe as pipe_generate_pipe,
    HAIRPIPE_OT_sync_points as pipe_sync_points,
    make_hair_curve_from_tube_mesh as pipe_make_hair_curve_from_tube_mesh,
    extract_tube_rings_from_mesh as pipe_extract_tube_rings_from_mesh,
    configure_pipe_object as pipe_configure_pipe_object,
    ensure_pipe_subdivision_modifier as pipe_ensure_pipe_subdivision_modifier,
)
from .edit_ops import (
    HAIRPIPE_OT_apply_edge_flow as edit_apply_edge_flow,
    HAIRPIPE_OT_reverse_curve_direction as edit_reverse_curve_direction,
    HAIRPIPE_OT_equalize_point_distance as edit_equalize_point_distance,
)
from .view_ops import (
    HAIRPIPE_OT_apply_global_mesh_selectability as view_apply_global_mesh_selectability,
    HAIRPIPE_OT_toggle_redirect_selection as view_toggle_redirect_selection,
    HAIRPIPE_OT_toggle_solo_display as view_toggle_solo_display,
    HAIRPIPE_OT_create_tail_mesh as view_create_tail_mesh,
    HAIRPIPE_OT_remove_tail_mesh as view_remove_tail_mesh,
    HAIRPIPE_OT_toggle_tail_visibility as view_toggle_tail_visibility,
    HAIRPIPE_OT_hide_all_tail_meshes as view_hide_all_tail_meshes,
    HAIRPIPE_OT_edit_tail_mesh as view_edit_tail_mesh,
)
from .interactive_ops import (
    HAIRPIPE_OT_cross_section_spread as interactive_cross_section_spread,
    HAIRPIPE_OT_draw_hair_curve as interactive_draw_hair_curve,
)
from .mesh_utils import (
    sanitize_faces as mesh_sanitize_faces,
    rebuild_mesh_safely as mesh_rebuild_mesh_safely,
    shade_mesh_smooth as mesh_shade_mesh_smooth,
    verts_to_world_space as mesh_verts_to_world_space,
    flatten_ring_points as mesh_flatten_ring_points,
    resample_ring_points as mesh_resample_ring_points,
)
from .tail_utils import (
    estimate_tail_direction_from_vertices as tail_estimate_tail_direction_from_vertices,
    create_tail_mesh_geometry as tail_create_tail_mesh_geometry,
    get_stored_tail_connection_ring as tail_get_stored_tail_connection_ring,
    store_tail_connection_state as tail_store_tail_connection_state,
    build_tail_connection_basis as tail_build_tail_connection_basis,
    transform_tail_vertices_by_connection as tail_transform_tail_vertices_by_connection,
    rebuild_tail_grid as tail_rebuild_tail_grid,
    get_tail_pose_rotation as tail_get_tail_pose_rotation,
    infer_inserted_ring_index as tail_infer_inserted_ring_index,
    infer_removed_ring_index as tail_infer_removed_ring_index,
    make_tail_bridge_faces as tail_make_tail_bridge_faces,
    remap_tail_face_after_connection_change as tail_remap_tail_face_after_connection_change,
    infer_tail_lower_ring_count as tail_infer_tail_lower_ring_count,
    retopologize_tail_connection as tail_retopologize_tail_connection,
    update_tail_mesh_connection as tail_update_tail_mesh_connection,
    update_tail_mesh_for_curve as tail_update_tail_mesh_for_curve,
)



def ensure_curve_defaults(curve_obj):
    return curve_ensure_curve_defaults(curve_obj)
def get_curve_points_data(curve_obj):
    return curve_get_curve_points_data(curve_obj)
def _legacy_get_curve_points_data(curve_obj):
    """Retained internally until all geometry consumers use curve_data."""
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
    return sampling_evaluate_bezier_segment(p0, h0_right, h1_left, p1, t)
def evaluate_bezier_tangent(p0, h0_right, h1_left, p1, t):
    return sampling_evaluate_bezier_tangent(p0, h0_right, h1_left, p1, t)
def make_nurbs_knot_vector(num_points, degree, is_cyclic, use_endpoint):
    return sampling_make_nurbs_knot_vector(num_points, degree, is_cyclic, use_endpoint)
def find_nurbs_span(num_eval_points, degree, u, knots):
    return sampling_find_nurbs_span(num_eval_points, degree, u, knots)
def nurbs_basis_values(span, degree, u, knots):
    return sampling_nurbs_basis_values(span, degree, u, knots)
def get_nurbs_weighted_controls(points, degree, u, knots, is_cyclic):
    return sampling_get_nurbs_weighted_controls(points, degree, u, knots, is_cyclic)
def evaluate_nurbs_from_weighted(points, weighted, total):
    return sampling_evaluate_nurbs_from_weighted(points, weighted, total)
def get_nurbs_domain(num_points, degree, knots, is_cyclic):
    return sampling_get_nurbs_domain(num_points, degree, knots, is_cyclic)
def interpolate_nurbs_cross_sections(point_settings, points, weighted, total, settings, global_point_idx):
    return transition_interpolate_nurbs_cross_sections(point_settings, points, weighted, total, settings, global_point_idx)
def interpolate_nurbs_cross_sections_by_control_range(point_settings, points, settings, global_point_idx, sample_t, is_cyclic):
    return transition_interpolate_nurbs_cross_sections_by_control_range(point_settings, points, settings, global_point_idx, sample_t, is_cyclic)
def make_cumulative_lengths(centers, is_cyclic=False):
    return sampling_make_cumulative_lengths(centers, is_cyclic)
def find_nearest_center_distance(centers, distances, co):
    return sampling_find_nearest_center_distance(centers, distances, co)
def interpolate_cross_sections_by_anchor_distance(point_settings, points, settings, global_point_idx, anchors, distance):
    return transition_interpolate_cross_sections_by_anchor_distance(point_settings, points, settings, global_point_idx, anchors, distance)
def distribute_steps_by_lengths(lengths, total_steps):
    return sampling_distribute_steps_by_lengths(lengths, total_steps)
def bezier_arc_length_at_t(p0, h0_right, h1_left, p1, t, subdivisions=12):
    return sampling_bezier_arc_length_at_t(p0, h0_right, h1_left, p1, t, subdivisions)
def invert_bezier_arc_length(p0, h0_right, h1_left, p1, target_length, total_length):
    return sampling_invert_bezier_arc_length(p0, h0_right, h1_left, p1, target_length, total_length)
def catmull_rom_vector(p0, p1, p2, p3, t):
    return math_catmull_rom_vector(p0, p1, p2, p3, t)
def catmull_rom_tangent_vector(p0, p1, p2, p3, t):
    return math_catmull_rom_tangent_vector(p0, p1, p2, p3, t)
def safe_normalized(vector, fallback=None):
    return math_safe_normalized(vector, fallback)
def average_tangents(prev_tangent, next_tangent):
    return sampling_average_tangents(prev_tangent, next_tangent)
def get_bezier_control_tangent(points, idx, is_cyclic):
    return sampling_get_bezier_control_tangent(points, idx, is_cyclic)
def get_poly_control_tangent(points, idx, is_cyclic):
    return sampling_get_poly_control_tangent(points, idx, is_cyclic)
def get_cross_section_frame(tangent):
    return math_get_cross_section_frame(tangent)
def catmull_rom_value(v0, v1, v2, v3, t):
    return math_catmull_rom_value(v0, v1, v2, v3, t)
def catmull_rom_2d(p0, p1, p2, p3, t):
    return math_catmull_rom_2d(p0, p1, p2, p3, t)
def ease_value(v0, v1, t):
    return interp_ease_value(v0, v1, t)
def lerp_value(v0, v1, t):
    return interp_lerp_value(v0, v1, t)
def mix_value(a, b, factor):
    return interp_mix_value(a, b, factor)
def monotone_tangent(prev_value, value, next_value):
    return interp_monotone_tangent(prev_value, value, next_value)
def hermite_value(v0, v1, m0, m1, t):
    return interp_hermite_value(v0, v1, m0, m1, t)
def interpolate_section_value(prev_value, value0, value1, next_value, t, mode, strength):
    return interp_interpolate_section_value(prev_value, value0, value1, next_value, t, mode, strength)
def is_transition_point(point_setting):
    return transition_is_transition_point(point_setting)
def find_previous_editable_point_index(point_settings, idx):
    return transition_find_previous_editable_point_index(point_settings, idx)
def find_next_editable_point_index(point_settings, idx):
    return transition_find_next_editable_point_index(point_settings, idx)
def get_transition_source_indices(point_settings, idx):
    return transition_get_transition_source_indices(point_settings, idx)
def get_effective_point_setting(point_settings, idx, settings):
    return transition_get_effective_point_setting(point_settings, idx, settings)
def get_cross_section_sample(point_setting, point=None, vert_idx=0):
    return transition_get_cross_section_sample(point_setting, point, vert_idx)
def interpolate_cross_sections(ps0, ps1, t, point0=None, point1=None):
    return transition_interpolate_cross_sections(ps0, ps1, t, point0, point1)
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
    return transition_interpolate_transition_cross_section(point_settings, idx, settings, point)
def update_transition_point_values(curve_obj, settings):
    return transition_update_transition_point_values(curve_obj, settings)
def smooth_ring_offsets(ring_specs, iterations=2, factor=0.5, is_cyclic=False):
    return frames_smooth_ring_offsets(ring_specs, iterations, factor, is_cyclic)
def make_ring_from_frame(center, normal, binormal, interp_offsets):
    return frames_make_ring_from_frame(center, normal, binormal, interp_offsets)
def make_ring_from_interpolated(center, tangent, interp_offsets):
    normal, binormal = get_cross_section_frame(tangent)
    return make_ring_from_frame(center, normal, binormal, interp_offsets)


_ROLL_DIAGNOSTIC_LOG_PATH = Path(bpy.app.tempdir) / "figuhair_roll_diagnostics.log"
_ROLL_DIAGNOSTIC_STATE = {}
_ROLL_DIAGNOSTIC_RESULTS = {}
_ROLL_DIAGNOSTIC_ACTIVITY = {}


def get_uncontrolled_roll_diagnostics(curve_obj):
    if curve_obj is None:
        return []
    results = []
    pointer = curve_obj.as_pointer()
    now = time.monotonic()
    for key, values in _ROLL_DIAGNOSTIC_RESULTS.items():
        curve_pointer, _spline_index = key
        if curve_pointer != pointer:
            continue
        # A changing geometry signature is a more reliable indication of an
        # active G transform than WindowManager.operators, which does not expose
        # Blender's currently running transform consistently.
        if now - _ROLL_DIAGNOSTIC_ACTIVITY.get(key, 0.0) <= 0.75:
            results.extend(values)
    return results


def _frame_roll_angle(tangent, normal):
    reference_normal, reference_binormal = get_cross_section_frame(tangent)
    return math.degrees(math.atan2(
        tangent.dot(reference_normal.cross(normal)),
        max(-1.0, min(1.0, reference_normal.dot(normal))),
    ))


def _write_roll_diagnostic(curve_obj, spline_index, ring_specs, frames, is_cyclic):
    if is_cyclic or len(frames) < 2:
        return

    signature = tuple(round(value, 5) for spec in ring_specs for value in spec[0])
    key = (curve_obj.as_pointer(), spline_index)
    previous = _ROLL_DIAGNOSTIC_STATE.get(key)
    current = [(tangent.copy(), normal.copy()) for tangent, normal, _binormal in frames]
    control_signature = tuple(
        (round(ps.rotation, 5), round(getattr(get_curve_point_by_global_index(curve_obj, idx), 'tilt', 0.0), 5))
        for idx, ps in enumerate(curve_obj.hair_pipe_settings.point_settings)
    )
    _ROLL_DIAGNOSTIC_STATE[key] = (signature, current, control_signature)
    if previous is None:
        return
    if previous[0] == signature:
        return
    _ROLL_DIAGNOSTIC_ACTIVITY[key] = time.monotonic()
    if curve_obj.hair_pipe_settings.roll_mode != 'START_FIXED':
        _ROLL_DIAGNOSTIC_RESULTS.pop(key, None)
        return

    old_frames = previous[1]
    old_control_signature = previous[2] if len(previous) > 2 else control_signature
    if old_control_signature != control_signature:
        _ROLL_DIAGNOSTIC_RESULTS.pop(key, None)
        return

    samples = list(range(len(frames)))
    messages = []
    detected = []
    for idx in samples:
        old_idx = round(idx * (len(old_frames) - 1) / max(1, len(frames) - 1))
        old_tangent, old_normal = old_frames[old_idx]
        tangent, normal, _binormal = frames[idx]
        transported_old_normal = _transport_cross_section_normal(old_tangent, tangent, old_normal)
        roll_delta = math.degrees(math.atan2(
            tangent.dot(transported_old_normal.cross(normal)),
            max(-1.0, min(1.0, transported_old_normal.dot(normal))),
        ))
        tangent_delta = math.degrees(math.acos(max(-1.0, min(1.0, old_tangent.dot(tangent)))))
        messages.append(
            f"ring={idx}/{len(frames) - 1} tangent_change={tangent_delta:.3f}deg "
            f"frame_roll_change={roll_delta:.3f}deg current_roll={_frame_roll_angle(tangent, normal):.3f}deg"
        )
        if idx > 0 and abs(roll_delta) >= 0.1:
            detected.append((ring_specs[idx][0].copy(), roll_delta))

    # Collapse dense sampled-ring warnings to the strongest value near each
    # curve control point, so the viewport remains readable.
    point_positions = [
        Vector(point.co[:3])
        for spline in curve_obj.data.splines
        for point in (spline.bezier_points if spline.type == 'BEZIER' else spline.points)
    ]
    point_results = {}
    for center, roll_delta in detected:
        if not point_positions:
            continue
        point_idx = min(range(len(point_positions)), key=lambda idx: (point_positions[idx] - center).length_squared)
        old_result = point_results.get(point_idx)
        if old_result is None or abs(roll_delta) > abs(old_result[1]):
            point_results[point_idx] = (point_positions[point_idx].copy(), roll_delta)
    new_results = [
        (point_idx, position, angle)
        for point_idx, (position, angle) in sorted(point_results.items())
    ]
    if new_results:
        _ROLL_DIAGNOSTIC_RESULTS[key] = new_results

    start_tangent, start_normal, _binormal = frames[0]
    with _ROLL_DIAGNOSTIC_LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(
            f"\ncurve={curve_obj.name!r} spline={spline_index} type=NURBS_OR_OPEN "
            f"start_tangent=({start_tangent.x:.5f},{start_tangent.y:.5f},{start_tangent.z:.5f}) "
            f"start_roll={_frame_roll_angle(start_tangent, start_normal):.3f}deg\n"
        )
        log_file.write("\n".join(messages) + "\n")


def _transport_cross_section_normal(prev_tangent, tangent, prev_normal):
    prev_tangent = safe_normalized(prev_tangent)
    tangent = safe_normalized(tangent, prev_tangent)
    tangent_dot = max(-1.0, min(1.0, prev_tangent.dot(tangent)))

    if tangent_dot < -0.999999:
        normal = prev_normal - tangent * prev_normal.dot(tangent)
    else:
        try:
            normal = prev_tangent.rotation_difference(tangent) @ prev_normal
        except ValueError:
            normal = prev_normal.copy()
        normal = normal - tangent * normal.dot(tangent)

    if normal.length < 1e-8:
        normal, _binormal = get_cross_section_frame(tangent)
    else:
        normal.normalize()
    return normal


def _minimal_twist_frames_from_tangents(raw_tangents, is_cyclic=False, start_normal=None):
    if not raw_tangents:
        return []

    first_tangent = safe_normalized(raw_tangents[0])
    if start_normal is None:
        normal, binormal = get_cross_section_frame(first_tangent)
    else:
        normal = start_normal - first_tangent * start_normal.dot(first_tangent)
        if normal.length < 1e-8:
            normal, binormal = get_cross_section_frame(first_tangent)
        else:
            normal.normalize()
            binormal = first_tangent.cross(normal).normalized()
    frames = [(first_tangent, normal.copy(), binormal.copy())]
    prev_tangent = first_tangent

    for raw_tangent in raw_tangents[1:]:
        tangent = safe_normalized(raw_tangent, prev_tangent)
        normal = _transport_cross_section_normal(prev_tangent, tangent, normal)
        binormal = tangent.cross(normal).normalized()
        frames.append((tangent, normal.copy(), binormal.copy()))
        prev_tangent = tangent

    if is_cyclic and len(frames) > 2:
        seam_normal = _transport_cross_section_normal(frames[-1][0], frames[0][0], frames[-1][1])
        first_tangent = frames[0][0]
        first_normal = frames[0][1]
        seam_angle = math.atan2(
            first_tangent.dot(seam_normal.cross(first_normal)),
            max(-1.0, min(1.0, seam_normal.dot(first_normal))),
        )
        frame_count = len(frames)
        corrected = []
        for idx, (tangent, frame_normal, _frame_binormal) in enumerate(frames):
            correction = seam_angle * idx / frame_count
            if abs(correction) > 1e-12:
                frame_normal = Matrix.Rotation(correction, 3, tangent) @ frame_normal
            frame_normal = frame_normal - tangent * frame_normal.dot(tangent)
            frame_normal.normalize()
            corrected.append((tangent, frame_normal, tangent.cross(frame_normal).normalized()))
        frames = corrected

    return frames


def _removed_forward_independent_tangents(centers, fallback_tangents):
    count = len(centers)
    if count < 2:
        return [safe_normalized(tangent) for tangent in fallback_tangents]
    tangents = []
    for idx in range(count):
        # A ring must not use the previous center in its direction. Moving point
        # i therefore cannot rotate the frame at i+1. The final ring reuses the
        # last forward segment because it has no following point.
        if idx < count - 1:
            direction = centers[idx + 1] - centers[idx]
        else:
            direction = centers[idx] - centers[idx - 1]
        fallback = fallback_tangents[min(idx, len(fallback_tangents) - 1)]
        tangents.append(safe_normalized(direction, fallback))
    return tangents


def _removed_hybrid_stable_frames(raw_tangents, start_normal):
    if not raw_tangents:
        return []

    # The first two curve points define one global roll anchor. Every later
    # frame is solved directly from this anchor, never from the preceding ring.
    # Therefore moving an intermediate point cannot propagate accumulated roll
    # into the following cross-sections.
    anchor_tangent = safe_normalized(raw_tangents[0])
    anchor_normal = start_normal - anchor_tangent * start_normal.dot(anchor_tangent)
    if anchor_normal.length < 1e-8:
        anchor_normal, _anchor_binormal = get_cross_section_frame(anchor_tangent)
    else:
        anchor_normal.normalize()
    anchor_binormal = anchor_tangent.cross(anchor_normal).normalized()

    frames = []
    for raw_tangent in raw_tangents:
        tangent = safe_normalized(raw_tangent, anchor_tangent)
        tangent_dot = max(-1.0, min(1.0, anchor_tangent.dot(tangent)))

        if tangent_dot > -0.9999:
            # Shortest-arc rotation contains no roll around the destination
            # tangent and depends only on START plus this ring's own tangent.
            try:
                normal = anchor_tangent.rotation_difference(tangent) @ anchor_normal
            except ValueError:
                normal = anchor_normal.copy()
        else:
            # At the exact opposite direction the shortest arc is ambiguous.
            # Use the START normal as a deterministic 180-degree rotation axis,
            # rather than borrowing a direction from the previous ring.
            normal = anchor_normal.copy()

        normal = normal - tangent * normal.dot(tangent)
        if normal.length < 1e-8:
            normal = anchor_binormal - tangent * anchor_binormal.dot(tangent)
        if normal.length < 1e-8:
            normal, binormal = get_cross_section_frame(tangent)
        else:
            normal.normalize()
            binormal = tangent.cross(normal).normalized()
        frames.append((tangent, normal.copy(), binormal.copy()))
    return frames


def _endpoint_driven_frames(centers, raw_tangents, is_cyclic=False, start_normal=None, roll_mode='START_FIXED'):
    if not raw_tangents:
        return []
    if is_cyclic or start_normal is None:
        return _minimal_twist_frames_from_tangents(raw_tangents, is_cyclic)

    first_tangent = safe_normalized(raw_tangents[0])
    anchor_normal = start_normal.copy()
    anchor_binormal = first_tangent.cross(anchor_normal)
    if anchor_binormal.length < 1e-8:
        _unused_normal, anchor_binormal = get_cross_section_frame(first_tangent)
    else:
        anchor_binormal.normalize()

    frames = []
    for raw_tangent in raw_tangents:
        tangent = safe_normalized(raw_tangent, first_tangent)
        normal = anchor_normal - tangent * anchor_normal.dot(tangent)
        if normal.length < 1e-8:
            normal = anchor_binormal - tangent * anchor_binormal.dot(tangent)
        if normal.length < 1e-8:
            normal, binormal = get_cross_section_frame(tangent)
        else:
            normal.normalize()
            binormal = tangent.cross(normal).normalized()
        frames.append((tangent, normal, binormal))
    return frames


def _get_start_roll_normal(curve_obj, start_tangent):
    """Return a START-anchored frame normal without changing it for other points."""
    anchor_normal = curve_obj.get("hair_pipe_start_roll_anchor_normal")
    anchor_tangent = curve_obj.get("hair_pipe_start_roll_anchor_tangent")
    start_changed = bool(curve_obj.get("hair_pipe_start_point_changed", False))

    if not anchor_normal or not anchor_tangent:
        anchor_normal, _binormal = get_cross_section_frame(start_tangent)
        anchor_tangent = start_tangent.copy()
    else:
        anchor_normal = Vector(anchor_normal)
        anchor_tangent = safe_normalized(Vector(anchor_tangent), start_tangent)
        if start_changed:
            anchor_normal = _transport_cross_section_normal(anchor_tangent, start_tangent, anchor_normal)
            anchor_tangent = start_tangent.copy()

    normal = anchor_normal - start_tangent * anchor_normal.dot(start_tangent)
    if normal.length < 1e-8:
        normal, _binormal = get_cross_section_frame(start_tangent)
    else:
        normal.normalize()

    curve_obj["hair_pipe_start_roll_anchor_normal"] = tuple(anchor_normal)
    curve_obj["hair_pipe_start_roll_anchor_tangent"] = tuple(anchor_tangent)
    curve_obj["hair_pipe_start_point_changed"] = False
    return normal


def build_minimal_twist_rings(
    ring_specs, is_cyclic=False, start_normal=None, curve_obj=None, spline_index=0,
    roll_mode='START_FIXED',
):
    if not ring_specs:
        return []

    rings = []
    frames = _endpoint_driven_frames(
        [center for center, _raw_tangent, _offsets in ring_specs],
        [raw_tangent for _center, raw_tangent, _offsets in ring_specs],
        is_cyclic,
        start_normal,
        'START_FIXED',
    )
    if curve_obj is not None:
        _write_roll_diagnostic(curve_obj, spline_index, ring_specs, frames, is_cyclic)

    for (center, _raw_tangent, offsets), (_tangent, normal, binormal) in zip(ring_specs, frames):
        tangent = _tangent


        if normal.length < 1e-8:
            normal, binormal = get_cross_section_frame(tangent)
        else:
            normal.normalize()
            binormal = tangent.cross(normal).normalized()
        if offsets:
            rings.append(make_ring_from_frame(center, normal, binormal, offsets))
        else:
            rings.append([center])

    return rings


def get_point_setting(point_settings, idx, settings):
    return transition_get_point_setting(point_settings, idx, settings)
def init_cross_section_circle(point_setting, radius, segments):
    return point_init_cross_section_circle(point_setting, radius, segments)
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


from .ghost import (
    update_ghost_vertices as ghost_update_ghost_vertices,
    update_all_ghost_vertices as ghost_update_all_ghost_vertices,
)


def update_ghost_vertices(point_setting):
    return ghost_update_ghost_vertices(point_setting)
def update_all_ghost_vertices(settings):
    return ghost_update_all_ghost_vertices(settings)
def _ghost_vertex_error(point_setting, vertex_idx):
    verts = point_setting.cross_section_verts
    real_count = sum(1 for vertex in verts if not getattr(vertex, 'is_ghost', False))
    # A valid closed cross-section must always retain at least three editable
    # vertices; two vertices collapse the profile into a line.
    if real_count <= 3 or vertex_idx < 0 or vertex_idx >= len(verts):
        return float('inf')
    target = verts[vertex_idx]
    if getattr(target, 'is_ghost', False):
        return float('inf')

    original = [
        (vertex.offset_x, vertex.offset_y, bool(getattr(vertex, 'is_ghost', False)))
        for vertex in verts
    ]
    old_x, old_y, _is_ghost = original[vertex_idx]
    target.is_ghost = True
    update_ghost_vertices(point_setting)
    error = math.hypot(target.offset_x - old_x, target.offset_y - old_y)
    radius = max(
        1e-6,
        max(math.hypot(vertex.offset_x, vertex.offset_y) for vertex in verts),
    )

    for vertex, (x, y, is_ghost) in zip(verts, original):
        vertex.offset_x = x
        vertex.offset_y = y
        vertex.is_ghost = is_ghost
    return error / radius


_AUTO_GHOST_SLIDER_STATE = {}
_AUTO_GHOST_SLIDER_RESETTING = set()
_ONE_SHOT_SLIDER_STATE = {}
_ONE_SHOT_SLIDER_RESETTING = set()


def _restore_auto_ghost_snapshot(settings, snapshot):
    for point_idx, vertex_data in snapshot.items():
        if point_idx >= len(settings.point_settings):
            continue
        verts = settings.point_settings[point_idx].cross_section_verts
        for vertex, (x, y, is_ghost) in zip(verts, vertex_data):
            vertex.offset_x = x
            vertex.offset_y = y
            vertex.is_ghost = is_ghost


def _capture_auto_ghost_snapshot(settings, selected_indices):
    return {
        point_idx: [
            (vertex.offset_x, vertex.offset_y, bool(getattr(vertex, 'is_ghost', False)))
            for vertex in settings.point_settings[point_idx].cross_section_verts
        ]
        for point_idx in selected_indices
        if 0 <= point_idx < len(settings.point_settings)
    }


def apply_auto_ghost_vertices(settings, tolerance, selected_indices, snapshot):
    tolerance = max(0.0, min(1.0, float(tolerance)))
    _restore_auto_ghost_snapshot(settings, snapshot)
    changed = 0

    for point_idx in selected_indices:
        if point_idx < 0 or point_idx >= len(settings.point_settings):
            continue
        point_setting = settings.point_settings[point_idx]
        verts = point_setting.cross_section_verts
        if len(verts) <= 2:
            continue

        candidates = []
        for vertex_idx, vertex in enumerate(verts):
            if getattr(vertex, 'is_ghost', False):
                continue
            error = _ghost_vertex_error(point_setting, vertex_idx)
            if math.isfinite(error):
                candidates.append((error, vertex_idx))

        normal_count = sum(1 for vertex in verts if not getattr(vertex, 'is_ghost', False))
        removable_count = max(0, normal_count - 3)
        target_count = min(removable_count, int(round(tolerance * removable_count)))
        candidates.sort(key=lambda item: (item[0], item[1]))
        for _error, vertex_idx in candidates[:target_count]:
            verts[vertex_idx].is_ghost = True
            changed += 1
        update_ghost_vertices(point_setting)

    return changed


def _capture_curve_point_snapshot(curve_obj, selected_indices):
    snapshot = {}
    for point_idx in selected_indices:
        point = get_curve_point_by_global_index(curve_obj, point_idx)
        if point is None:
            continue
        snapshot[point_idx] = point.co.copy()
    return snapshot


def _restore_curve_point_snapshot(curve_obj, snapshot):
    for point_idx, co in snapshot.items():
        point = get_curve_point_by_global_index(curve_obj, point_idx)
        if point is None:
            continue
        if hasattr(point.co, 'w'):
            point.co = co
        else:
            delta = Vector(co[:3]) - point.co
            point.co = Vector(co[:3])
            if hasattr(point, 'handle_left'):
                point.handle_left += delta
                point.handle_right += delta


def _apply_curve_smooth_slider(curve_obj, value, state):
    _restore_curve_point_snapshot(curve_obj, state['snapshot'])
    selected = state['selected_indices']
    selected_set = set(selected)
    for point_idx in selected:
        prev_idx = point_idx - 1
        next_idx = point_idx + 1
        if prev_idx in selected_set or next_idx in selected_set:
            continue
        point = get_curve_point_by_global_index(curve_obj, point_idx)
        prev_point = get_curve_point_by_global_index(curve_obj, prev_idx)
        next_point = get_curve_point_by_global_index(curve_obj, next_idx)
        if point is None or prev_point is None or next_point is None:
            continue
        old_co = Vector(state['snapshot'][point_idx][:3])
        target = (Vector(prev_point.co[:3]) + Vector(next_point.co[:3])) * 0.5
        new_co = old_co.lerp(target, value)
        if hasattr(point, 'handle_left'):
            delta = new_co - point.co
            point.co = new_co
            point.handle_left += delta
            point.handle_right += delta
        else:
            point.co.x, point.co.y, point.co.z = new_co


def _apply_section_smooth_slider(curve_obj, value, state, circular=False):
    settings = curve_obj.hair_pipe_settings
    _restore_auto_ghost_snapshot(settings, state['snapshot'])
    wd = getattr(bpy.context.window_manager, 'hair_pipe_widget', None)
    selected_vertices = state['selected_vertices']
    for point_idx in state['selected_indices']:
        if point_idx < 0 or point_idx >= len(settings.point_settings):
            continue
        ps = settings.point_settings[point_idx]
        verts = ps.cross_section_verts
        original = [(v.offset_x, v.offset_y) for v in verts]
        if not original:
            continue
        center_x = sum(x for x, _y in original) / len(original)
        center_y = sum(y for _x, y in original) / len(original)
        mean_radius = sum(math.hypot(x - center_x, y - center_y) for x, y in original) / len(original)
        for idx in selected_vertices:
            if idx >= len(verts) or getattr(verts[idx], 'is_ghost', False):
                continue
            if circular:
                radial_x = original[idx][0] - center_x
                radial_y = original[idx][1] - center_y
                length = math.hypot(radial_x, radial_y)
                if length <= 1e-8:
                    continue
                target_x = center_x + radial_x / length * mean_radius
                target_y = center_y + radial_y / length * mean_radius
            else:
                prev_idx = (idx - 1) % len(verts)
                next_idx = (idx + 1) % len(verts)
                target_x = (original[prev_idx][0] + original[next_idx][0]) * 0.5
                target_y = (original[prev_idx][1] + original[next_idx][1]) * 0.5
            verts[idx].offset_x = original[idx][0] + (target_x - original[idx][0]) * value
            verts[idx].offset_y = original[idx][1] + (target_y - original[idx][1]) * value
        update_ghost_vertices(ps)
    if wd is not None:
        try:
            from .widget_operator import clear_pipe_mesh_cache, redraw_view3d
            clear_pipe_mesh_cache()
            redraw_view3d(bpy.context)
        except (ImportError, AttributeError, RuntimeError):
            pass


def update_one_shot_slider_value(curve_obj, settings, slider_name):
    if slider_name == 'auto_ghost_tolerance':
        return update_auto_ghost_slider(curve_obj, settings)
    key = (curve_obj.as_pointer(), slider_name)
    if key in _ONE_SHOT_SLIDER_RESETTING:
        return 0
    value = max(0.0, min(1.0, float(getattr(settings, slider_name))))
    state = _ONE_SHOT_SLIDER_STATE.get(key)
    if state is None:
        selected_indices = get_selected_curve_point_indices(curve_obj) if is_curve_edit_mode(curve_obj) else []
        if not selected_indices:
            return 0
        state = {'selected_indices': selected_indices, 'last_change_time': time.monotonic()}
        if slider_name == 'curve_smooth_slider':
            state['snapshot'] = _capture_curve_point_snapshot(curve_obj, selected_indices)
            try:
                bpy.ops.ed.undo_push(message="曲线平滑")
            except RuntimeError:
                pass
        else:
            wd = getattr(bpy.context.window_manager, 'hair_pipe_widget', None)
            if wd is None or not wd.is_active:
                return 0
            from .widget_operator import get_selected_widget_verts, push_widget_undo
            state['selected_vertices'] = get_selected_widget_verts(wd)
            if not state['selected_vertices']:
                return 0
            state['snapshot'] = _capture_auto_ghost_snapshot(settings, selected_indices)
            push_widget_undo(bpy.context, "平滑横截面顶点")
        _ONE_SHOT_SLIDER_STATE[key] = state
    else:
        state['last_change_time'] = time.monotonic()

    if slider_name == 'curve_smooth_slider':
        _apply_curve_smooth_slider(curve_obj, value, state)
    else:
        _apply_section_smooth_slider(curve_obj, value, state, slider_name == 'circular_smooth_slider')
    curve_obj.data.update_tag()
    curve_obj.update_tag()
    return 1


def finish_one_shot_slider(curve_obj, slider_name):
    key = (curve_obj.as_pointer(), slider_name)
    _ONE_SHOT_SLIDER_STATE.pop(key, None)
    _ONE_SHOT_SLIDER_RESETTING.add(key)
    try:
        setattr(curve_obj.hair_pipe_settings, slider_name, 0.0)
    finally:
        _ONE_SHOT_SLIDER_RESETTING.discard(key)


def ensure_one_shot_slider_gesture(curve_obj, slider_name):
    if slider_name == 'auto_ghost_tolerance':
        ensure_auto_ghost_slider_gesture(bpy.context, curve_obj)
        return
    key = (curve_obj.as_pointer(), slider_name)
    state = _ONE_SHOT_SLIDER_STATE.get(key)
    if state is None or state.get('timer_registered', False):
        return
    state['timer_registered'] = True
    curve_name = curve_obj.name

    def finish_when_idle():
        live_curve = bpy.data.objects.get(curve_name)
        if live_curve is None:
            return None
        live_state = _ONE_SHOT_SLIDER_STATE.get((live_curve.as_pointer(), slider_name))
        if live_state is None:
            return None
        if time.monotonic() - live_state.get('last_change_time', 0.0) < 1.5:
            return 0.08
        finish_one_shot_slider(live_curve, slider_name)
        return None

    bpy.app.timers.register(finish_when_idle, first_interval=0.08)


def update_auto_ghost_slider(curve_obj, settings):
    value = max(0.0, min(1.0, float(settings.auto_ghost_tolerance)))
    state_key = curve_obj.as_pointer()
    if state_key in _AUTO_GHOST_SLIDER_RESETTING:
        return 0
    state = _AUTO_GHOST_SLIDER_STATE.get(state_key)

    if state is None:
        selected_indices = get_selected_curve_point_indices(curve_obj) if is_curve_edit_mode(curve_obj) else []
        if not selected_indices:
            return 0
        state = {
            'selected_indices': selected_indices,
            'snapshot': _capture_auto_ghost_snapshot(settings, selected_indices),
            'last_change_time': time.monotonic(),
            'undo_pushed': False,
        }
        try:
            from .widget_operator import push_widget_undo
            push_widget_undo(bpy.context, "自动简化横截面")
            state['undo_pushed'] = True
        except (ImportError, AttributeError, RuntimeError):
            pass
        _AUTO_GHOST_SLIDER_STATE[state_key] = state
    else:
        state['last_change_time'] = time.monotonic()

    changed = apply_auto_ghost_vertices(
        settings,
        value,
        state['selected_indices'],
        state['snapshot'],
    )
    curve_obj.data.update_tag()
    curve_obj.update_tag()
    return changed


def finish_auto_ghost_slider(curve_obj):
    if curve_obj is None or getattr(curve_obj, 'type', None) != 'CURVE':
        return
    settings = curve_obj.hair_pipe_settings
    state_key = curve_obj.as_pointer()
    _AUTO_GHOST_SLIDER_STATE.pop(state_key, None)
    _AUTO_GHOST_SLIDER_RESETTING.add(state_key)
    try:
        settings.auto_ghost_tolerance = 0.0
    finally:
        _AUTO_GHOST_SLIDER_RESETTING.discard(state_key)


def ensure_auto_ghost_slider_gesture(context, curve_obj):
    if curve_obj is None:
        return
    state = _AUTO_GHOST_SLIDER_STATE.get(curve_obj.as_pointer())
    if state is None or state.get('timer_registered', False):
        return
    state['timer_registered'] = True
    curve_name = curve_obj.name

    def finish_when_idle():
        live_curve = bpy.data.objects.get(curve_name)
        if live_curve is None:
            return None
        live_state = _AUTO_GHOST_SLIDER_STATE.get(live_curve.as_pointer())
        if live_state is None:
            return None
        # Keep one immutable snapshot throughout a deliberate drag, including
        # pauses at 0 or 1 before the user reverses direction.  This timer does
        # not own mouse events, so use a generous idle window rather than
        # prematurely committing and losing reversibility.
        if time.monotonic() - live_state.get('last_change_time', 0.0) < 1.5:
            return 0.08
        finish_auto_ghost_slider(live_curve)
        return None

    bpy.app.timers.register(finish_when_idle, first_interval=0.08)


def add_cross_section_vertex_after(point_setting, idx, is_ghost=False):
    return cross_section_add_cross_section_vertex_after(point_setting, idx, is_ghost)
def get_curve_spline_point_ranges(curve_obj):
    return cross_section_get_curve_spline_point_ranges(curve_obj)
def get_active_spline_point_range(curve_obj, settings):
    return cross_section_get_active_spline_point_range(curve_obj, settings)
def add_cross_section_vertex_after_all(settings, idx, point_range=None):
    return cross_section_add_cross_section_vertex_after_all(settings, idx, point_range)
def remove_cross_section_vertex_all(settings, idx, point_range=None):
    return cross_section_remove_cross_section_vertex_all(settings, idx, point_range)
def normalize_cross_section_topology(settings, curve_obj=None):
    return cross_section_normalize_cross_section_topology(settings, curve_obj)
def generate_pipe_mesh(curve_obj, settings):
    return pipe_generate_pipe_mesh(curve_obj, settings)
def _curve_point_position_signatures(curve_obj):
    return point__curve_point_position_signatures(curve_obj)
def _load_curve_point_signatures(curve_obj):
    return point__load_curve_point_signatures(curve_obj)
def _store_curve_point_signatures(curve_obj, signatures):
    return point__store_curve_point_signatures(curve_obj, signatures)
def _point_setting_to_data(point_setting):
    return point__point_setting_to_data(point_setting)
def _default_point_setting_data(settings):
    return point__default_point_setting_data(settings)
def _interpolate_point_setting_data(left_data, right_data, t):
    if left_data is None and right_data is None:
        return None
    if left_data is None:
        return _clone_point_setting_data(right_data)
    if right_data is None:
        return _clone_point_setting_data(left_data)

    left_verts = left_data.get("verts", [])
    right_verts = right_data.get("verts", [])
    count = min(len(left_verts), len(right_verts))
    if count < 3:
        return _clone_point_setting_data(left_data if len(left_verts) >= len(right_verts) else right_data)

    verts = []
    for idx in range(count):
        lv = left_verts[idx]
        rv = right_verts[idx]
        verts.append({
            "offset_x": lv["offset_x"] * (1.0 - t) + rv["offset_x"] * t,
            "offset_y": lv["offset_y"] * (1.0 - t) + rv["offset_y"] * t,
            "is_ghost": bool(lv.get("is_ghost", False) and rv.get("is_ghost", False)),
        })
    return {
        "scale": left_data.get("scale", 1.0) * (1.0 - t) + right_data.get("scale", 1.0) * t,
        "rotation": lerp_angle(left_data.get("rotation", 0.0), right_data.get("rotation", 0.0), t),
        "use_transition": False,
        "active_vert_index": 0,
        "verts": verts,
    }


def _clone_point_setting_data(data):
    if data is None:
        return None
    return {
        "scale": data.get("scale", 1.0),
        "rotation": data.get("rotation", 0.0),
        "use_transition": bool(data.get("use_transition", False)),
        "active_vert_index": data.get("active_vert_index", 0),
        "verts": [dict(vert) for vert in data.get("verts", [])],
    }


def _apply_point_setting_data(point_setting, data, settings):
    return point__apply_point_setting_data(point_setting, data, settings)
def _replace_point_settings_from_data(settings, point_data):
    settings.point_settings.clear()
    for data in point_data:
        point_setting = settings.point_settings.add()
        _apply_point_setting_data(point_setting, data, settings)


def _matching_prefix_suffix(old_signatures, new_signatures):
    prefix = 0
    old_count = len(old_signatures)
    new_count = len(new_signatures)
    while prefix < old_count and prefix < new_count and old_signatures[prefix] == new_signatures[prefix]:
        prefix += 1

    suffix = 0
    while (
        suffix < old_count - prefix
        and suffix < new_count - prefix
        and old_signatures[old_count - 1 - suffix] == new_signatures[new_count - 1 - suffix]
    ):
        suffix += 1
    return prefix, suffix


def _rebuild_point_data_for_insert(old_data, insert_index, insert_count, settings):
    rebuilt = []
    rebuilt.extend(_clone_point_setting_data(data) for data in old_data[:insert_index])
    left_data = old_data[insert_index - 1] if insert_index > 0 else None
    right_data = old_data[insert_index] if insert_index < len(old_data) else None
    fallback = right_data or left_data or _default_point_setting_data(settings)
    for idx in range(insert_count):
        if left_data is not None and right_data is not None:
            rebuilt.append(_interpolate_point_setting_data(left_data, right_data, (idx + 1) / (insert_count + 1)))
        else:
            rebuilt.append(_clone_point_setting_data(fallback))
    rebuilt.extend(_clone_point_setting_data(data) for data in old_data[insert_index:])
    return rebuilt


def sync_point_settings(curve_obj):
    return point_sync_point_settings(curve_obj)
def is_curve_edit_mode(curve_obj):
    return curve_is_curve_edit_mode(curve_obj)
def get_selected_curve_point_index(curve_obj):
    return curve_get_selected_curve_point_index(curve_obj)
def _legacy_get_selected_curve_point_index(curve_obj):
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
    return curve_get_selected_curve_point_indices(curve_obj)
def _legacy_get_selected_curve_point_indices(curve_obj):
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
    return point_sync_active_point_from_selection(curve_obj)
def get_next_figuhair_base_name():
    return lifecycle_get_next_figuhair_base_name()
def get_curve_from_figuhair_root(root_obj):
    return lifecycle_get_curve_from_figuhair_root(root_obj)
def get_figuhair_root(curve_obj):
    return lifecycle_get_figuhair_root(curve_obj)
def ensure_figuhair_root(curve_obj):
    return lifecycle_ensure_figuhair_root(curve_obj)
def get_pipe_mesh_name(curve_obj):
    return lifecycle_get_pipe_mesh_name(curve_obj)
def get_tail_mesh_name(curve_obj):
    return lifecycle_get_tail_mesh_name(curve_obj)
def get_pipe_object_for_curve(curve_obj):
    return lifecycle_get_pipe_object_for_curve(curve_obj)
def _legacy_get_pipe_object_for_curve(curve_obj):
    root_obj = get_figuhair_root(curve_obj)
    if root_obj is not None:
        for child in root_obj.children:
            if child.type == 'MESH' and get_pipe_source_curve(child) == curve_obj:
                return child
            if child.type == 'MESH' and child.name.endswith(" Mesh"):
                return child
    for child in curve_obj.children:
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
    return lifecycle_get_tail_object_for_curve(curve_obj)
def _legacy_get_tail_object_for_curve(curve_obj):
    root_obj = get_figuhair_root(curve_obj)
    if root_obj is not None:
        for child in root_obj.children:
            if child.type == 'MESH' and child.get("hair_pipe_tail_source_curve") == curve_obj.name:
                return child
            if child.type == 'MESH' and child.name.endswith(" Tail"):
                return child
    for child in curve_obj.children:
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


def verts_to_world_space(*args, **kwargs):
    return mesh_verts_to_world_space(*args, **kwargs)
def generated_pipe_vertices(verts, curve_obj):
    return lifecycle_generated_pipe_vertices(verts, curve_obj)
def set_generated_object_transform(obj, curve_obj):
    return lifecycle_set_generated_object_transform(obj, curve_obj)
def get_pipe_source_curve(pipe_obj):
    return lifecycle_get_pipe_source_curve(pipe_obj)
def get_tail_source_curve(tail_obj):
    return lifecycle_get_tail_source_curve(tail_obj)
def get_context_curve_object(context):
    return lifecycle_get_context_curve_object(context)
def parent_keep_world(obj, parent_obj):
    world_matrix = obj.matrix_world.copy()
    obj.parent = parent_obj
    obj.matrix_world = world_matrix


def detach_keep_world(obj):
    if obj is None or obj.parent is None:
        return
    world_matrix = obj.matrix_world.copy()
    obj.parent = None
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
    return pipe_ensure_pipe_subdivision_modifier(pipe_obj, show_viewport, levels)
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


def estimate_tail_direction_from_vertices(*args, **kwargs):
    return tail_estimate_tail_direction_from_vertices(*args, **kwargs)
def create_tail_mesh_geometry(*args, **kwargs):
    return tail_create_tail_mesh_geometry(*args, **kwargs)
def flatten_ring_points(*args, **kwargs):
    return mesh_flatten_ring_points(*args, **kwargs)
def get_stored_tail_connection_ring(*args, **kwargs):
    return tail_get_stored_tail_connection_ring(*args, **kwargs)
def store_tail_connection_state(*args, **kwargs):
    return tail_store_tail_connection_state(*args, **kwargs)
def build_tail_connection_basis(*args, **kwargs):
    return tail_build_tail_connection_basis(*args, **kwargs)
def transform_tail_vertices_by_connection(*args, **kwargs):
    return tail_transform_tail_vertices_by_connection(*args, **kwargs)
def resample_ring_points(*args, **kwargs):
    return mesh_resample_ring_points(*args, **kwargs)
def rebuild_tail_grid(*args, **kwargs):
    return tail_rebuild_tail_grid(*args, **kwargs)
def get_tail_pose_rotation(*args, **kwargs):
    return tail_get_tail_pose_rotation(*args, **kwargs)
def sanitize_faces(*args, **kwargs):
    return mesh_sanitize_faces(*args, **kwargs)
def rebuild_mesh_safely(*args, **kwargs):
    return mesh_rebuild_mesh_safely(*args, **kwargs)
def shade_mesh_smooth(*args, **kwargs):
    return mesh_shade_mesh_smooth(*args, **kwargs)
def infer_inserted_ring_index(*args, **kwargs):
    return tail_infer_inserted_ring_index(*args, **kwargs)
def infer_removed_ring_index(*args, **kwargs):
    return tail_infer_removed_ring_index(*args, **kwargs)
def make_tail_bridge_faces(*args, **kwargs):
    return tail_make_tail_bridge_faces(*args, **kwargs)
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


def remap_tail_face_after_connection_change(*args, **kwargs):
    return tail_remap_tail_face_after_connection_change(*args, **kwargs)
def infer_tail_lower_ring_count(*args, **kwargs):
    return tail_infer_tail_lower_ring_count(*args, **kwargs)
def retopologize_tail_connection(*args, **kwargs):
    return tail_retopologize_tail_connection(*args, **kwargs)
def update_tail_mesh_connection(*args, **kwargs):
    return tail_update_tail_mesh_connection(*args, **kwargs)
def update_tail_mesh_for_curve(*args, **kwargs):
    return tail_update_tail_mesh_for_curve(*args, **kwargs)
def configure_pipe_object(pipe_obj, curve_obj):
    return pipe_configure_pipe_object(pipe_obj, curve_obj)
def ensure_selected_curve_visible(curve_obj):
    return selection_ensure_selected_curve_visible(curve_obj)
def sync_selected_curve_visibility(context):
    return selection_sync_selected_curve_visibility(context)
def redirect_pipe_selection(context, pipe_obj=None):
    return selection_redirect_pipe_selection(context, pipe_obj)
def get_curve_point_by_global_index(curve_obj, target_index):
    return edit_get_curve_point_by_global_index(curve_obj, target_index)
def edge_flow_t(mode, t, power):
    return edit_edge_flow_t(mode, t, power)
def lerp_angle(a, b, t):
    return math_lerp_angle(a, b, t)
def lerp_radians(a, b, t):
    return math_lerp_radians(a, b, t)
def find_previous_edge_flow_source_index(point_settings, idx, target_indices):
    return edit_find_previous_edge_flow_source_index(point_settings, idx, target_indices)
def find_next_edge_flow_source_index(point_settings, idx, target_indices):
    return edit_find_next_edge_flow_source_index(point_settings, idx, target_indices)
def apply_edge_flow_to_target_indices(curve_obj, settings, target_indices, mode, power, blend):
    return edit_apply_edge_flow_to_target_indices(curve_obj, settings, target_indices, mode, power, blend)
def _edge_key(a, b):
    return (a, b) if a < b else (b, a)


def _ordered_boundary_loops(mesh):
    edge_faces = {}
    for poly in mesh.polygons:
        verts = list(poly.vertices)
        for idx, v0 in enumerate(verts):
            v1 = verts[(idx + 1) % len(verts)]
            edge_faces.setdefault(_edge_key(v0, v1), []).append(poly.index)

    boundary_adj = {}
    for edge, faces in edge_faces.items():
        if len(faces) == 1:
            a, b = edge
            boundary_adj.setdefault(a, []).append(b)
            boundary_adj.setdefault(b, []).append(a)

    loops = []
    visited_edges = set()
    for start, neighbors in boundary_adj.items():
        for first_next in neighbors:
            edge = _edge_key(start, first_next)
            if edge in visited_edges:
                continue
            loop = [start]
            prev = start
            cur = first_next
            visited_edges.add(edge)
            while True:
                loop.append(cur)
                next_candidates = [v for v in boundary_adj.get(cur, []) if v != prev]
                if not next_candidates:
                    break
                nxt = next_candidates[0]
                next_edge = _edge_key(cur, nxt)
                if nxt == start:
                    visited_edges.add(next_edge)
                    break
                if next_edge in visited_edges:
                    break
                visited_edges.add(next_edge)
                prev, cur = cur, nxt
            if len(loop) >= 3:
                loops.append(loop)
    return loops


def _mesh_edge_maps(mesh):
    edge_to_faces = {}
    vertex_to_edges = {}
    for poly in mesh.polygons:
        verts = list(poly.vertices)
        for idx, v0 in enumerate(verts):
            v1 = verts[(idx + 1) % len(verts)]
            key = _edge_key(v0, v1)
            edge_to_faces.setdefault(key, []).append(poly.index)
            vertex_to_edges.setdefault(v0, set()).add(key)
            vertex_to_edges.setdefault(v1, set()).add(key)
    return edge_to_faces, vertex_to_edges


def _connected_unvisited_edges(seed_edge, available_edges):
    component = set()
    stack = [seed_edge]
    while stack:
        edge = stack.pop()
        if edge in component or edge not in available_edges:
            continue
        component.add(edge)
        a, b = edge
        for other in available_edges:
            if other in component:
                continue
            if a in other or b in other:
                stack.append(other)
    return component


def _order_cycle_edges(edges):
    if not edges:
        return None
    adj = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    if any(len(neighbors) != 2 for neighbors in adj.values()):
        return None
    start = next(iter(adj))
    loop = [start]
    prev = None
    cur = start
    for _ in range(len(adj)):
        neighbors = adj[cur]
        nxt = neighbors[0] if neighbors[0] != prev else neighbors[1]
        if nxt == start:
            return loop if len(loop) == len(adj) else None
        if nxt in loop:
            return None
        loop.append(nxt)
        prev, cur = cur, nxt
    return None


def _ring_from_cap_faces(mesh):
    candidates = []
    for poly in mesh.polygons:
        if len(poly.vertices) >= 3:
            candidates.append((poly.index, list(poly.vertices)))
    return max(candidates, key=lambda item: len(item[1])) if candidates else (None, None)


def _extract_rings_by_ordered_quads(mesh, start_ring, edge_to_faces, initially_used_faces=None):
    rings = [start_ring]
    used_faces = set(initially_used_faces or [])
    max_steps = max(1, len(mesh.polygons) + 1)
    for _ in range(max_steps):
        next_ring, step_faces = _step_ring_by_ordered_quads(mesh, rings[-1], used_faces, edge_to_faces)
        if next_ring is None:
            break
        if set(next_ring) == set(rings[-1]):
            break
        rings.append(next_ring)
        used_faces.update(step_faces)
    return rings if len(rings) >= 2 else None


def extract_tube_rings_from_mesh(*args, **kwargs):
    return pipe_extract_tube_rings_from_mesh(*args, **kwargs)
def _extract_open_tube_rings_by_faces(mesh, loops, edge_to_faces):
    if not loops:
        return None
    start_ring = max(loops, key=len)
    rings = [start_ring]
    used_faces = set()
    max_steps = max(1, len(mesh.polygons) + 1)
    for _ in range(max_steps):
        next_ring, step_faces = _step_ring_by_ordered_quads(mesh, rings[-1], used_faces, edge_to_faces)
        if next_ring is None:
            break
        rings.append(next_ring)
        used_faces.update(step_faces)
        next_set = set(next_ring)
        if any(next_set == set(loop) for loop in loops if set(loop) != set(start_ring)):
            break
    if len(rings) < 2:
        return None
    return rings


def _step_ring_by_ordered_quads(mesh, ring, used_faces, edge_to_faces):
    count = len(ring)
    step_faces = []
    ring_set = set(ring)
    next_by_current = {}

    for idx in range(count):
        a = ring[idx]
        b = ring[(idx + 1) % count]
        face_index = None
        for candidate in edge_to_faces.get(_edge_key(a, b), []):
            if candidate not in used_faces and len(mesh.polygons[candidate].vertices) == 4:
                face_index = candidate
                break
        if face_index is None:
            return None, []

        verts = list(mesh.polygons[face_index].vertices)
        if sum(1 for v in verts if v in ring_set) != 2:
            return None, []

        try:
            a_pos = verts.index(a)
            b_pos = verts.index(b)
        except ValueError:
            return None, []

        if verts[(a_pos + 1) % 4] == b:
            next_a = verts[(a_pos - 1) % 4]
            next_b = verts[(b_pos + 1) % 4]
        elif verts[(b_pos + 1) % 4] == a:
            next_a = verts[(a_pos + 1) % 4]
            next_b = verts[(b_pos - 1) % 4]
        else:
            return None, []

        if next_a in ring_set or next_b in ring_set or next_a == next_b:
            return None, []
        if next_by_current.get(a, next_a) != next_a or next_by_current.get(b, next_b) != next_b:
            return None, []
        next_by_current[a] = next_a
        next_by_current[b] = next_b
        step_faces.append(face_index)

    if len(next_by_current) != count:
        return None, []
    next_ring = [next_by_current[vert_idx] for vert_idx in ring]
    if len(set(next_ring)) != count:
        return None, []
    return next_ring, step_faces


def _ring_center_from_indices(ring, positions):
    center = Vector((0.0, 0.0, 0.0))
    for vert_idx in ring:
        center += positions[vert_idx]
    return center / max(1, len(ring))


def _best_aligned_ring_order(previous_ring, current_ring, positions, previous_center, current_center):
    count = len(current_ring)
    if count <= 2 or len(previous_ring) != count:
        return current_ring
    previous_offsets = [positions[v] - previous_center for v in previous_ring]
    best_score = None
    best_ring = current_ring
    for flip in (False, True):
        candidate = list(reversed(current_ring)) if flip else list(current_ring)
        for shift in range(count):
            ordered = candidate[shift:] + candidate[:shift]
            score = 0.0
            for idx, vert_idx in enumerate(ordered):
                offset = positions[vert_idx] - current_center
                score += (offset - previous_offsets[idx]).length_squared
            if best_score is None or score < best_score:
                best_score = score
                best_ring = ordered
    return best_ring


def _align_ring_orders(rings, positions, centers):
    if not rings:
        return rings
    aligned = [list(rings[0])]
    for idx in range(1, len(rings)):
        aligned.append(_best_aligned_ring_order(
            aligned[-1],
            list(rings[idx]),
            positions,
            centers[idx - 1],
            centers[idx],
        ))
    return aligned


def _curve_tangent_at_center(centers, idx):
    if len(centers) <= 1:
        return Vector((0.0, 0.0, 1.0))
    if idx == 0:
        return centers[1] - centers[0]
    if idx == len(centers) - 1:
        return centers[-1] - centers[-2]
    return centers[idx + 1] - centers[idx - 1]


def _minimal_twist_frames_for_centers_legacy_unused(centers):
    if not centers:
        return []
    first_tangent = safe_normalized(_curve_tangent_at_center(centers, 0))
    normal, binormal = get_cross_section_frame(first_tangent)
    frames = [(first_tangent, normal.copy(), binormal.copy())]
    prev_tangent = first_tangent
    for idx in range(1, len(centers)):
        tangent = safe_normalized(_curve_tangent_at_center(centers, idx), prev_tangent)
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
        frames.append((tangent, normal.copy(), binormal.copy()))
        prev_tangent = tangent
    return frames


def _conversion_frames_for_start_fixed(centers):
    """Use the exact START-fixed frame convention used after conversion."""
    if not centers:
        return [], None, None
    tangents = [_curve_tangent_at_center(centers, idx) for idx in range(len(centers))]
    first_tangent = safe_normalized(tangents[0])
    anchor_normal, _anchor_binormal = get_cross_section_frame(first_tangent)
    frames = _endpoint_driven_frames(
        centers, tangents, False, anchor_normal, 'START_FIXED',
    )
    return frames, anchor_normal, first_tangent


def _signed_polygon_area_2d(points):
    area = 0.0
    count = len(points)
    for idx in range(count):
        x0, y0 = points[idx]
        x1, y1 = points[(idx + 1) % count]
        area += x0 * y1 - x1 * y0
    return area * 0.5


def make_hair_curve_from_tube_mesh(context, mesh_obj):
    return pipe_make_hair_curve_from_tube_mesh(context, mesh_obj)

HAIRPIPE_OT_mesh_to_hair_curve = pipe_mesh_to_hair_curve
HAIRPIPE_OT_generate_pipe = pipe_generate_pipe
HAIRPIPE_OT_sync_points = pipe_sync_points
HAIRPIPE_OT_toggle_cross_section_transition = cs_toggle_cross_section_transition
HAIRPIPE_OT_apply_edge_flow = edit_apply_edge_flow

HAIRPIPE_OT_reset_cross_section = cs_reset_cross_section
HAIRPIPE_OT_reset_all_cross_sections = cs_reset_all_cross_sections
HAIRPIPE_OT_taper_linear = cs_taper_linear
HAIRPIPE_OT_add_cs_vert = cs_add_cs_vert
HAIRPIPE_OT_remove_cs_vert = cs_remove_cs_vert
HAIRPIPE_OT_select_point = cs_select_point
HAIRPIPE_OT_copy_cross_section = cs_copy_cross_section
HAIRPIPE_OT_paste_cross_section = cs_paste_cross_section
HAIRPIPE_OT_copy_cs_to_all = cs_copy_cs_to_all
HAIRPIPE_OT_apply_global_mesh_selectability = view_apply_global_mesh_selectability

HAIRPIPE_OT_toggle_redirect_selection = view_toggle_redirect_selection

HAIRPIPE_OT_reverse_curve_direction = edit_reverse_curve_direction

HAIRPIPE_OT_equalize_point_distance = edit_equalize_point_distance

HAIRPIPE_OT_create_tail_mesh = view_create_tail_mesh

HAIRPIPE_OT_remove_tail_mesh = view_remove_tail_mesh

HAIRPIPE_OT_toggle_tail_visibility = view_toggle_tail_visibility

HAIRPIPE_OT_hide_all_tail_meshes = view_hide_all_tail_meshes

HAIRPIPE_OT_toggle_solo_display = view_toggle_solo_display

HAIRPIPE_OT_edit_tail_mesh = view_edit_tail_mesh

HAIRPIPE_OT_hide_hair = hair_ops_hide_hair
HAIRPIPE_OT_show_all_hair = hair_ops_show_all_hair
HAIRPIPE_OT_family_local_view = hair_ops_family_local_view
HAIRPIPE_OT_delete_hair = hair_ops_delete_hair
HAIRPIPE_OT_toggle_plugin_enabled = hair_ops_toggle_plugin_enabled
HAIRPIPE_OT_duplicate_hair = hair_ops_duplicate_hair
HAIRPIPE_OT_merge_hair_for_export = hair_ops_merge_hair_for_export

def _is_pipe_mesh_obj(*args, **kwargs):
    return hair_ops_is_pipe_mesh_obj(*args, **kwargs)
def _is_hair_pipe_mesh_obj(obj):
    return hair_ops_is_pipe_mesh_obj(obj) or hair_ops_is_tail_mesh_only_obj(obj)
def _is_tail_mesh_only_obj(*args, **kwargs):
    return hair_ops_is_tail_mesh_only_obj(*args, **kwargs)
def _is_figuhair_family_obj(*args, **kwargs):
    return hair_ops_is_figuhair_family_obj(*args, **kwargs)

HAIRPIPE_OT_cross_section_spread = interactive_cross_section_spread

HAIRPIPE_OT_draw_hair_curve = interactive_draw_hair_curve

classes = (
    HAIRPIPE_OT_cross_section_spread,
    HAIRPIPE_OT_draw_hair_curve,
    HAIRPIPE_OT_mesh_to_hair_curve,
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
    HAIRPIPE_OT_reverse_curve_direction,
    HAIRPIPE_OT_equalize_point_distance,
    HAIRPIPE_OT_hide_hair,
    HAIRPIPE_OT_show_all_hair,
    HAIRPIPE_OT_family_local_view,
    HAIRPIPE_OT_delete_hair,
    HAIRPIPE_OT_duplicate_hair,
    HAIRPIPE_OT_merge_hair_for_export,
    HAIRPIPE_OT_toggle_plugin_enabled,
)



_PLUGIN_ENABLED_GUARD = False

def is_plugin_enabled():
    """Return whether FiguHair global plugin switch is on (any curve's setting)."""
    for obj in bpy.data.objects:
        if obj.type == 'CURVE' and hasattr(obj, 'hair_pipe_settings'):
            try:
                return bool(obj.hair_pipe_settings.plugin_enabled)
            except Exception:
                pass
    return True

def apply_plugin_enabled_state(enabled):
    """Sync global redirect/selection state when plugin_enabled toggles."""
    global _PLUGIN_ENABLED_GUARD
    if _PLUGIN_ENABLED_GUARD:
        return
    _PLUGIN_ENABLED_GUARD = True
    try:
        enabled = bool(enabled)
        # push to every hair curve
        for obj in bpy.data.objects:
            if obj.type == 'CURVE' and hasattr(obj, 'hair_pipe_settings'):
                try:
                    if obj.hair_pipe_settings.plugin_enabled != enabled:
                        obj.hair_pipe_settings.plugin_enabled = enabled
                except Exception:
                    pass
            # also show/hide generated meshes accordingly via selection module
            # keep pipe meshes selectable state in sync
            if obj.type == 'MESH' and obj.get("hair_pipe_source_curve"):
                try:
                    obj.hide_select = enabled
                except Exception:
                    pass
        # also notify view_ops global redirect sync if available
        try:
            from .view_ops import sync_global_redirect_selection
            for obj in bpy.data.objects:
                if obj.type == 'CURVE' and hasattr(obj, 'hair_pipe_settings') and obj.hair_pipe_settings.plugin_enabled == enabled:
                    try:
                        sync_global_redirect_selection(obj)
                    except Exception:
                        pass
                    break
        except Exception:
            pass
    finally:
        _PLUGIN_ENABLED_GUARD = False

def draw_hair_add_menu(self, context):
    layout = self.layout
    layout.operator("hair_pipe.draw_hair_curve", text="添加头发", icon='CURVE_DATA')
    layout.separator()


_addon_keymaps = []


def register_keymaps():
    wm = bpy.context.window_manager
    keyconfig = wm.keyconfigs.addon if wm is not None else None
    if keyconfig is None:
        return
    keymap = keyconfig.keymaps.get('Object Mode')
    if keymap is None:
        keymap = keyconfig.keymaps.new(name='Object Mode', space_type='EMPTY')
    bindings = (
        ('hair_pipe.hide_hair', 'H', 'PRESS', {}),
        ('hair_pipe.show_all_hair', 'H', 'PRESS', {'alt': True}),
        ('hair_pipe.duplicate_hair', 'D', 'PRESS', {'shift': True}),
        ('hair_pipe.delete_hair', 'X', 'PRESS', {}),
        ('hair_pipe.delete_hair', 'DEL', 'PRESS', {}),
        ('hair_pipe.family_local_view', 'NUMPAD_SLASH', 'PRESS', {}),
    )
    existing = {(item.idname, item.type, item.value, item.ctrl, item.shift, item.alt) for item in keymap.keymap_items}
    for operator, key_type, value, modifiers in bindings:
        if any(item.idname == operator and item.type == key_type and item.value == value for item in keymap.keymap_items):
            continue
        item = keymap.keymap_items.new(operator, key_type, value, **modifiers)
        _addon_keymaps.append((keymap, item))


def unregister_keymaps():
    for keymap, item in reversed(_addon_keymaps):
        try:
            keymap.keymap_items.remove(item)
        except (ReferenceError, RuntimeError):
            pass
    _addon_keymaps.clear()


def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError as e:
            if "already registered" not in str(e):
                raise
    bpy.types.VIEW3D_MT_add.prepend(draw_hair_add_menu)
    register_keymaps()


def unregister():
    unregister_keymaps()
    try:
        bpy.types.VIEW3D_MT_add.remove(draw_hair_add_menu)
    except (AttributeError, ValueError):
        pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError):
            pass