"""
Thin facade — 兼容旧 from .operators import X 的唯一入口。
所有真实实现已搬到 30+ 个小模块，这里只做 re-export + Blender 注册。
"""
import bpy

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
    _transport_cross_section_normal as frames_transport_normal,
    _minimal_twist_frames_from_tangents as frames_minimal_twist,
    _endpoint_driven_frames as frames_endpoint_driven,
    _get_start_roll_normal as frames_get_start_roll_normal,
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
from .pipe_generation import generate_pipe_mesh as pipe_generate_pipe_mesh
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
from .binding import (
    HAIRPIPE_OT_bind_cross_curve as binding_bind_cross_curve,
    HAIRPIPE_OT_unbind_cross_curve as binding_unbind_cross_curve,
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
from .slider_ops import (
    update_one_shot_slider_value as slider_update_one_shot_slider_value,
    finish_one_shot_slider as slider_finish_one_shot_slider,
    ensure_one_shot_slider_gesture as slider_ensure_one_shot_slider_gesture,
    update_auto_ghost_slider as slider_update_auto_ghost_slider,
    finish_auto_ghost_slider as slider_finish_auto_ghost_slider,
    ensure_auto_ghost_slider_gesture as slider_ensure_auto_ghost_slider_gesture,
    apply_auto_ghost_vertices as slider_apply_auto_ghost_vertices,
)
from .roll_diagnostics import (
    get_uncontrolled_roll_diagnostics as roll_get_uncontrolled_roll_diagnostics,
    _write_roll_diagnostic as roll_write_roll_diagnostic,
    _frame_roll_angle as roll_frame_roll_angle,
)
from .plugin_state import is_plugin_enabled as plugin_is_plugin_enabled, apply_plugin_enabled_state as plugin_apply_plugin_enabled_state

# ---- thin aliases (keep old import path working) ----
ensure_curve_defaults = curve_ensure_curve_defaults
get_curve_points_data = curve_get_curve_points_data
evaluate_bezier_segment = sampling_evaluate_bezier_segment
evaluate_bezier_tangent = sampling_evaluate_bezier_tangent
make_nurbs_knot_vector = sampling_make_nurbs_knot_vector
find_nurbs_span = sampling_find_nurbs_span
nurbs_basis_values = sampling_nurbs_basis_values
get_nurbs_weighted_controls = sampling_get_nurbs_weighted_controls
evaluate_nurbs_from_weighted = sampling_evaluate_nurbs_from_weighted
get_nurbs_domain = sampling_get_nurbs_domain
interpolate_nurbs_cross_sections = transition_interpolate_nurbs_cross_sections
interpolate_nurbs_cross_sections_by_control_range = transition_interpolate_nurbs_cross_sections_by_control_range
make_cumulative_lengths = sampling_make_cumulative_lengths
find_nearest_center_distance = sampling_find_nearest_center_distance
interpolate_cross_sections_by_anchor_distance = transition_interpolate_cross_sections_by_anchor_distance
distribute_steps_by_lengths = sampling_distribute_steps_by_lengths
bezier_arc_length_at_t = sampling_bezier_arc_length_at_t
invert_bezier_arc_length = sampling_invert_bezier_arc_length
catmull_rom_vector = math_catmull_rom_vector
catmull_rom_tangent_vector = math_catmull_rom_tangent_vector
safe_normalized = math_safe_normalized
average_tangents = sampling_average_tangents
get_bezier_control_tangent = sampling_get_bezier_control_tangent
get_poly_control_tangent = sampling_get_poly_control_tangent
get_cross_section_frame = math_get_cross_section_frame
catmull_rom_value = math_catmull_rom_value
catmull_rom_2d = math_catmull_rom_2d
ease_value = interp_ease_value
lerp_value = interp_lerp_value
mix_value = interp_mix_value
monotone_tangent = interp_monotone_tangent
hermite_value = interp_hermite_value
interpolate_section_value = interp_interpolate_section_value
is_transition_point = transition_is_transition_point
find_previous_editable_point_index = transition_find_previous_editable_point_index
find_next_editable_point_index = transition_find_next_editable_point_index
get_transition_source_indices = transition_get_transition_source_indices
get_effective_point_setting = transition_get_effective_point_setting
get_cross_section_sample = transition_get_cross_section_sample
interpolate_cross_sections = transition_interpolate_cross_sections
interpolate_cross_sections_smooth = transition_interpolate_cross_sections_smooth
interpolate_transition_cross_section = transition_interpolate_transition_cross_section
update_transition_point_values = transition_update_transition_point_values
smooth_ring_offsets = frames_smooth_ring_offsets
make_ring_from_frame = frames_make_ring_from_frame
get_uncontrolled_roll_diagnostics = roll_get_uncontrolled_roll_diagnostics
_frame_roll_angle = roll_frame_roll_angle
_write_roll_diagnostic = roll_write_roll_diagnostic
_transport_cross_section_normal = frames_transport_normal
_minimal_twist_frames_from_tangents = frames_minimal_twist
_endpoint_driven_frames = frames_endpoint_driven
_get_start_roll_normal = frames_get_start_roll_normal
build_minimal_twist_rings = frames_build_minimal_twist_rings
get_point_setting = transition_get_point_setting
init_cross_section_circle = point_init_cross_section_circle
update_ghost_vertices = ghost_update_ghost_vertices
update_all_ghost_vertices = ghost_update_all_ghost_vertices
apply_auto_ghost_vertices = slider_apply_auto_ghost_vertices
update_one_shot_slider_value = slider_update_one_shot_slider_value
finish_one_shot_slider = slider_finish_one_shot_slider
ensure_one_shot_slider_gesture = slider_ensure_one_shot_slider_gesture
update_auto_ghost_slider = slider_update_auto_ghost_slider
finish_auto_ghost_slider = slider_finish_auto_ghost_slider
ensure_auto_ghost_slider_gesture = slider_ensure_auto_ghost_slider_gesture
add_cross_section_vertex_after = cross_section_add_cross_section_vertex_after
get_curve_spline_point_ranges = cross_section_get_curve_spline_point_ranges
get_active_spline_point_range = cross_section_get_active_spline_point_range
add_cross_section_vertex_after_all = cross_section_add_cross_section_vertex_after_all
remove_cross_section_vertex_all = cross_section_remove_cross_section_vertex_all
normalize_cross_section_topology = cross_section_normalize_cross_section_topology
generate_pipe_mesh = pipe_generate_pipe_mesh
_curve_point_position_signatures = point__curve_point_position_signatures
_load_curve_point_signatures = point__load_curve_point_signatures
_store_curve_point_signatures = point__store_curve_point_signatures
_point_setting_to_data = point__point_setting_to_data
_default_point_setting_data = point__default_point_setting_data
_apply_point_setting_data = point__apply_point_setting_data
sync_point_settings = point_sync_point_settings
is_curve_edit_mode = curve_is_curve_edit_mode
get_selected_curve_point_index = curve_get_selected_curve_point_index
get_selected_curve_point_indices = curve_get_selected_curve_point_indices
sync_active_point_from_selection = point_sync_active_point_from_selection
get_next_figuhair_base_name = lifecycle_get_next_figuhair_base_name
get_curve_from_figuhair_root = lifecycle_get_curve_from_figuhair_root
get_figuhair_root = lifecycle_get_figuhair_root
ensure_figuhair_root = lifecycle_ensure_figuhair_root
get_pipe_mesh_name = lifecycle_get_pipe_mesh_name
get_tail_mesh_name = lifecycle_get_tail_mesh_name
get_pipe_object_for_curve = lifecycle_get_pipe_object_for_curve
get_tail_object_for_curve = lifecycle_get_tail_object_for_curve
verts_to_world_space = mesh_verts_to_world_space
generated_pipe_vertices = lifecycle_generated_pipe_vertices
set_generated_object_transform = lifecycle_set_generated_object_transform
get_pipe_source_curve = lifecycle_get_pipe_source_curve
get_tail_source_curve = lifecycle_get_tail_source_curve
get_context_curve_object = lifecycle_get_context_curve_object
ensure_pipe_subdivision_modifier = pipe_ensure_pipe_subdivision_modifier
estimate_tail_direction_from_vertices = tail_estimate_tail_direction_from_vertices
create_tail_mesh_geometry = tail_create_tail_mesh_geometry
flatten_ring_points = mesh_flatten_ring_points
get_stored_tail_connection_ring = tail_get_stored_tail_connection_ring
store_tail_connection_state = tail_store_tail_connection_state
build_tail_connection_basis = tail_build_tail_connection_basis
transform_tail_vertices_by_connection = tail_transform_tail_vertices_by_connection
resample_ring_points = mesh_resample_ring_points
rebuild_tail_grid = tail_rebuild_tail_grid
get_tail_pose_rotation = tail_get_tail_pose_rotation
sanitize_faces = mesh_sanitize_faces
rebuild_mesh_safely = mesh_rebuild_mesh_safely
shade_mesh_smooth = mesh_shade_mesh_smooth
infer_inserted_ring_index = tail_infer_inserted_ring_index
infer_removed_ring_index = tail_infer_removed_ring_index
make_tail_bridge_faces = tail_make_tail_bridge_faces
remap_tail_face_after_connection_change = tail_remap_tail_face_after_connection_change
infer_tail_lower_ring_count = tail_infer_tail_lower_ring_count
retopologize_tail_connection = tail_retopologize_tail_connection
update_tail_mesh_connection = tail_update_tail_mesh_connection
update_tail_mesh_for_curve = tail_update_tail_mesh_for_curve
configure_pipe_object = pipe_configure_pipe_object
ensure_selected_curve_visible = selection_ensure_selected_curve_visible
sync_selected_curve_visibility = selection_sync_selected_curve_visibility
redirect_pipe_selection = selection_redirect_pipe_selection
get_curve_point_by_global_index = edit_get_curve_point_by_global_index
edge_flow_t = edit_edge_flow_t
lerp_angle = math_lerp_angle
lerp_radians = math_lerp_radians
find_previous_edge_flow_source_index = edit_find_previous_edge_flow_source_index
find_next_edge_flow_source_index = edit_find_next_edge_flow_source_index
apply_edge_flow_to_target_indices = edit_apply_edge_flow_to_target_indices
extract_tube_rings_from_mesh = pipe_extract_tube_rings_from_mesh
make_hair_curve_from_tube_mesh = pipe_make_hair_curve_from_tube_mesh
is_plugin_enabled = plugin_is_plugin_enabled
apply_plugin_enabled_state = plugin_apply_plugin_enabled_state

# keep a few helpers that were thin wrappers but now delegated
def make_ring_from_interpolated(center, tangent, interp_offsets):
    normal, binormal = get_cross_section_frame(tangent)
    return make_ring_from_frame(center, normal, binormal, interp_offsets)

# re-export operator classes (unchanged idnames)
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
    binding_bind_cross_curve,
    binding_unbind_cross_curve,
)

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
