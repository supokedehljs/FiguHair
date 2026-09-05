import bpy
import gpu
import math
import time
import json
import blf
from mathutils import Vector
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
from bpy.props import IntProperty, FloatProperty, BoolProperty
from bpy.types import PropertyGroup
from .cross_section import add_cross_section_vertex_after, remove_cross_section_vertex_all, get_curve_spline_point_ranges, get_active_spline_point_range
from .curve_data import get_curve_points_data, is_curve_edit_mode, get_selected_curve_point_indices
from .hair_lifecycle import get_pipe_object_for_curve, get_pipe_source_curve
from .ghost import update_all_ghost_vertices, update_ghost_vertices
from .math_utils import catmull_rom_2d, get_cross_section_frame, safe_normalized
from .widget_geometry import effective_to_widget, get_raw_offset, rotate_2d, get_active_curve_point_world_position
from .widget_cache import get_cached_pipe_mesh
from .point_data import sync_point_settings, sync_active_point_from_selection

_draw_handle = None
_addon_keymaps = []
_PIPE_BASEMESH_STATE_KEY = "hair_pipe_widget_basemesh_state"
_CURVE_OVERLAY_STATE_KEY = "hair_pipe_widget_curve_overlay_state"
_last_widget_pipe_refresh = 0.0

def refresh_widget_preview_from_property(self, context):
    curve_obj = get_widget_source_curve(context)
    if self.is_active and curve_obj is not None:
        set_pipe_basemesh_preview(context, curve_obj, False)
        set_pipe_basemesh_preview(context, curve_obj, True)
    redraw_view3d(context)


def get_base_preview_enabled(self):
    return self.preview_mode == 'BASE'


def set_base_preview_enabled(self, enabled):
    if enabled:
        self.preview_mode = 'BASE'
    elif self.preview_mode == 'BASE':
        self.preview_mode = 'SUBDIV'


def get_subdiv_preview_enabled(self):
    return self.preview_mode == 'SUBDIV'


def set_subdiv_preview_enabled(self, enabled):
    if enabled:
        self.preview_mode = 'SUBDIV'
    elif self.preview_mode == 'SUBDIV':
        self.preview_mode = 'BASE'


def get_solo_display_enabled(self):
    return self.solo_hold_active


def set_solo_display_enabled(self, enabled):
    set_widget_solo_state(bpy.context, self, bool(enabled))


_WIDGET_MESH_THROTTLE = 0.035
_last_widget_mesh_time = 0.0


class HairPipeWidgetSettings(PropertyGroup):
    """Runtime state for the cross-section widget"""
    widget_center_x: FloatProperty(default=0.0)
    widget_center_y: FloatProperty(default=0.0)
    widget_size: FloatProperty(default=320.0)
    widget_scale_factor: FloatProperty(default=1.0)
    fitted_point_index: IntProperty(default=-1)
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
    bound_area_pointer: bpy.props.StringProperty(default="")
    bound_region_pointer: bpy.props.StringProperty(default="")
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
    # Non-empty while the read-only overlay of a bound slave is being edited.
    bound_edit_curve_name: bpy.props.StringProperty(default="")
    bound_edit_point_index: IntProperty(default=-1)
    source_curve_name: bpy.props.StringProperty(default="")
    context_menu_point_index: IntProperty(default=-1)
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
    preview_mode: bpy.props.EnumProperty(
        name="横截面预览模式",
        items=(
            ('BASE', "去细分显示", "去除细分并使用平直着色"),
            ('SUBDIV', "细分显示", "保留细分并使用平滑着色"),
        ),
        default='SUBDIV',
    )
    preview_in_front: BoolProperty(
        name="显示在最前",
        description="让当前头发预览始终显示在其他物体前方",
        default=False,
        update=refresh_widget_preview_from_property,
    )
    base_preview_enabled: BoolProperty(
        name="去细分显示",
        description="显示无细分、平直着色的基础网格；与细分显示互斥",
        get=get_base_preview_enabled,
        set=set_base_preview_enabled,
        update=refresh_widget_preview_from_property,
    )
    subdiv_preview_enabled: BoolProperty(
        name="细分显示",
        description="显示带细分和平滑着色的网格；与去细分显示互斥",
        get=get_subdiv_preview_enabled,
        set=set_subdiv_preview_enabled,
        update=refresh_widget_preview_from_property,
    )
    solo_hold_active: BoolProperty(default=False)
    solo_display_enabled: BoolProperty(
        name="单独显示",
        description="只显示当前选中的 FiguHair 头发及其关联对象",
        get=get_solo_display_enabled,
        set=set_solo_display_enabled,
    )
    solo_hold_states: bpy.props.StringProperty(default="{}")
    show_unsubdivided_mesh: BoolProperty(default=True)
    show_mesh_in_front: BoolProperty(default=True)
    rotate_start_x: FloatProperty(default=0.0)
    rotate_start_y: FloatProperty(default=0.0)
    move_start_x: FloatProperty(default=0.0)
    move_start_y: FloatProperty(default=0.0)
    scale_start_x: FloatProperty(default=0.0)
    scale_start_y: FloatProperty(default=0.0)
    scale_start_factor: FloatProperty(default=1.0)
    proportional_radius: FloatProperty(default=120.0, min=8.0, max=5000.0)
    proportional_center_x: FloatProperty(default=0.0)
    proportional_center_y: FloatProperty(default=0.0)
    transform_pivot_x: FloatProperty(default=0.0)
    transform_pivot_y: FloatProperty(default=0.0)
    transform_mouse_pivot_x: FloatProperty(default=0.0)
    transform_mouse_pivot_y: FloatProperty(default=0.0)
    transform_mouse_pivot_valid: BoolProperty(default=False)
    auto_alignment_angle: FloatProperty(default=0.0)
    auto_alignment_flip_h: BoolProperty(default=False)
    auto_alignment_initialized: BoolProperty(default=False)
    auto_alignment_signature: bpy.props.StringProperty(default="")
    rotate_initial_offsets: bpy.props.StringProperty(default="")
    proportional_weights: bpy.props.StringProperty(default="{}")
    longitudinal_radius: FloatProperty(default=3.0, min=1.0, max=1000.0)
    longitudinal_initial_state: bpy.props.StringProperty(default="{}")
    mouse_x: FloatProperty(default=0.0)
    mouse_y: FloatProperty(default=0.0)
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



def proportional_edit_enabled(context):
    tool_settings = getattr(getattr(context, 'scene', None), 'tool_settings', None)
    return bool(getattr(tool_settings, 'use_proportional_edit', False))


def proportional_weight(context, distance, radius):
    if not proportional_edit_enabled(context):
        return 1.0 if distance <= 1e-8 else 0.0
    if distance >= radius:
        return 0.0
    ratio = max(0.0, min(1.0, distance / max(radius, 1e-8)))
    falloff = getattr(getattr(context.scene, 'tool_settings', None), 'proportional_edit_falloff', 'SMOOTH')
    if falloff == 'CONSTANT':
        return 1.0
    if falloff == 'LINEAR':
        return 1.0 - ratio
    if falloff == 'SHARP':
        return (1.0 - ratio) ** 2
    if falloff == 'ROOT':
        return math.sqrt(1.0 - ratio)
    if falloff == 'SPHERE':
        return math.sqrt(max(0.0, 1.0 - ratio * ratio))
    return (1.0 - ratio) * (1.0 - ratio) * (3.0 - 2.0 * (1.0 - ratio))


def get_proportional_vertex_weights(context, verts, selected, cx, cy, sf, alignment_angle, flip_h, radius, baseline=None):
    if not proportional_edit_enabled(context):
        return {idx: 1.0 for idx in selected}
    selected_points = []
    for idx in selected:
        if 0 <= idx < len(verts) and not getattr(verts[idx], 'is_ghost', False):
            ox, oy = baseline.get(idx, get_raw_offset(verts[idx])) if baseline is not None else get_raw_offset(verts[idx])
            selected_points.append(effective_to_widget(ox, oy, cx, cy, sf, alignment_angle, flip_h))
    weights = {}
    for idx, vertex in enumerate(verts):
        if getattr(vertex, 'is_ghost', False):
            continue
        ox, oy = baseline.get(idx, get_raw_offset(vertex)) if baseline is not None else get_raw_offset(vertex)
        px, py = effective_to_widget(ox, oy, cx, cy, sf, alignment_angle, flip_h)
        distance = min((math.hypot(px - sx, py - sy) for sx, sy in selected_points), default=float('inf'))
        weight = proportional_weight(context, distance, radius)
        if weight > 0.0:
            weights[idx] = weight
    return weights


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
            parts.append(f"{i}:{verts[i].offset_x}:{verts[i].offset_y}")
    wd.rotate_initial_offsets = ";".join(parts)


def set_proportional_weights(wd, weights):
    wd.proportional_weights = json.dumps(weights)


def get_proportional_weights(wd):
    try:
        return {int(idx): float(weight) for idx, weight in json.loads(wd.proportional_weights).items()}
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        return {}


def get_longitudinal_weights(context, settings, active_idx, radius):
    weights = {}
    for point_idx in range(len(settings.point_settings)):
        distance = abs(point_idx - active_idx)
        weight = proportional_weight(context, distance, radius)
        if weight > 0.0:
            weights[point_idx] = weight
    return weights


LONGITUDINAL_MOVE_MODE_LABELS = (
    "0 各横截面局部方向",
    "1 完整世界空间投影",
    "2 视图平面直接投影",
    "3 视图平面切线约束",
    "4 活动横截面世界轴",
    "5 网格顶点屏幕方向",
)
def get_curve_point_by_global_index(obj, point_idx):
    current_idx = 0
    for spline in obj.data.splines:
        points = spline.bezier_points if spline.type == 'BEZIER' else spline.points
        for point in points:
            if current_idx == point_idx:
                return point
            current_idx += 1
    return None


def get_all_control_point_frames(context):
    obj = context.active_object
    frames = {}
    global_idx = 0
    world_3x3 = obj.matrix_world.to_3x3()
    for spline in obj.data.splines:
        points = spline.bezier_points if spline.type == 'BEZIER' else spline.points
        count = len(points)
        if count == 0:
            continue
        tangents = []
        for idx, point in enumerate(points):
            if spline.type == 'BEZIER':
                previous = point.co - point.handle_left if spline.use_cyclic_u or idx > 0 else None
                following = point.handle_right - point.co if spline.use_cyclic_u or idx < count - 1 else None
            else:
                co = Vector(point.co[:3])
                previous = co - Vector(points[(idx - 1) % count].co[:3]) if spline.use_cyclic_u or idx > 0 else None
                following = Vector(points[(idx + 1) % count].co[:3]) - co if spline.use_cyclic_u or idx < count - 1 else None
            if previous is not None and following is not None:
                tangent = safe_normalized(previous + following, following)
            else:
                tangent = safe_normalized(following if following is not None else previous, Vector((0, 0, 1)))
            tangents.append(safe_normalized(world_3x3 @ tangent))

        normal, binormal = get_cross_section_frame(tangents[0])
        for local_idx, tangent in enumerate(tangents):
            if local_idx > 0:
                previous_tangent = tangents[local_idx - 1]
                try:
                    normal = previous_tangent.rotation_difference(tangent) @ normal
                except ValueError:
                    pass
                normal = normal - tangent * normal.dot(tangent)
                if normal.length < 1e-8:
                    normal, binormal = get_cross_section_frame(tangent)
                else:
                    normal.normalize()
                    binormal = tangent.cross(normal).normalized()
            frames[global_idx + local_idx] = (normal.copy(), binormal.copy())
        global_idx += count
    return frames


def get_longitudinal_delta(context, settings, point_idx, delta_x, delta_y, mode, initial_offset, frames=None):
    if mode == 0:
        return delta_x, delta_y

    active_idx = settings.active_point_index
    frames = frames or get_all_control_point_frames(context)
    active_frame = frames.get(active_idx)
    target_frame = frames.get(point_idx)
    if active_frame is None or target_frame is None:
        return delta_x, delta_y

    obj = context.active_object
    active_point = get_curve_point_by_global_index(obj, active_idx)
    target_point = get_curve_point_by_global_index(obj, point_idx)
    active_tilt = getattr(active_point, 'tilt', 0.0) if active_point is not None else 0.0
    target_tilt = getattr(target_point, 'tilt', 0.0) if target_point is not None else 0.0
    active_scale = max(1e-8, settings.point_settings[active_idx].scale * getattr(active_point, 'radius', 1.0))
    target_scale = max(1e-8, settings.point_settings[point_idx].scale * getattr(target_point, 'radius', 1.0))

    active_normal, active_binormal = active_frame
    target_normal, target_binormal = target_frame
    active_rotation = math.radians(settings.point_settings[active_idx].rotation) + active_tilt
    target_rotation = math.radians(settings.point_settings[point_idx].rotation) + target_tilt
    active_cos = math.cos(active_rotation)
    active_sin = math.sin(active_rotation)
    target_cos = math.cos(target_rotation)
    target_sin = math.sin(target_rotation)

    active_x_axis = active_normal * active_cos + active_binormal * active_sin
    active_y_axis = -active_normal * active_sin + active_binormal * active_cos
    target_x_axis = target_normal * target_cos + target_binormal * target_sin
    target_y_axis = -target_normal * target_sin + target_binormal * target_cos

    region_data = context.region_data
    view_right = region_data.view_rotation @ Vector((1.0, 0.0, 0.0)) if region_data else active_x_axis
    view_up = region_data.view_rotation @ Vector((0.0, 1.0, 0.0)) if region_data else active_y_axis
    view_forward = region_data.view_rotation @ Vector((0.0, 0.0, -1.0)) if region_data else active_x_axis.cross(active_y_axis)

    if mode == 1:
        world_delta = (active_x_axis * delta_x + active_y_axis * delta_y) * active_scale
    elif mode == 2:
        world_delta = (view_right * delta_x + view_up * delta_y) * active_scale
    elif mode == 3:
        screen_delta = view_right * delta_x + view_up * delta_y
        target_tangent = target_x_axis.cross(target_y_axis).normalized()
        world_delta = (screen_delta - target_tangent * screen_delta.dot(target_tangent)) * active_scale
    elif mode == 4:
        active_tangent = active_x_axis.cross(active_y_axis).normalized()
        screen_delta = view_right * delta_x + view_up * delta_y
        world_delta = (screen_delta - active_tangent * screen_delta.dot(active_tangent)) * active_scale
    else:
        screen_x = target_x_axis - view_forward * target_x_axis.dot(view_forward)
        screen_y = target_y_axis - view_forward * target_y_axis.dot(view_forward)
        matrix_det = screen_x.dot(view_right) * screen_y.dot(view_up) - screen_x.dot(view_up) * screen_y.dot(view_right)
        if abs(matrix_det) < 1e-8:
            world_delta = (view_right * delta_x + view_up * delta_y) * active_scale
        else:
            desired_x = delta_x * active_scale
            desired_y = delta_y * active_scale
            local_x = (desired_x * screen_y.dot(view_up) - desired_y * screen_y.dot(view_right)) / matrix_det
            local_y = (screen_x.dot(view_right) * desired_y - screen_x.dot(view_up) * desired_x) / matrix_det
            return local_x / target_scale, local_y / target_scale

    return world_delta.dot(target_x_axis) / target_scale, world_delta.dot(target_y_axis) / target_scale


def apply_longitudinal_move(context, settings, wd, selected, delta_x, delta_y):
    state = get_longitudinal_initial_state(wd)
    restore_longitudinal_initial_state(settings, state)
    weights = get_longitudinal_weights(context, settings, settings.active_point_index, wd.longitudinal_radius)
    frames = None
    for point_idx, weight in weights.items():
        point_state = state.get(point_idx, {})
        if point_idx >= len(settings.point_settings):
            continue
        verts = settings.point_settings[point_idx].cross_section_verts
        for vert_idx in selected:
            initial_offset = point_state.get(vert_idx)
            if initial_offset is not None and vert_idx < len(verts):
                local_dx, local_dy = get_longitudinal_delta(
                    context,
                    settings,
                    point_idx,
                    delta_x,
                    delta_y,
                    0,
                    initial_offset,
                    frames,
                )
                verts[vert_idx].offset_x = initial_offset[0] + local_dx * weight
                verts[vert_idx].offset_y = initial_offset[1] + local_dy * weight
    update_all_ghost_vertices(settings)


def get_selected_3d_mesh_screen_center(context, selected):
    """Project the active ring's selected generated-mesh vertices to screen space."""
    obj = context.active_object
    region = context.region
    region_data = context.region_data
    if obj is None or obj.type != 'CURVE' or region is None or region_data is None or not selected:
        return None
    settings = obj.hair_pipe_settings
    active_idx = settings.active_point_index
    if not (0 <= active_idx < len(settings.point_settings)):
        return None
    segments = len(settings.point_settings[active_idx].cross_section_verts)
    if segments < 3:
        return None
    try:
        mesh_verts, _faces = get_cached_pipe_mesh(obj)
    except Exception:
        return None
    if not mesh_verts or len(mesh_verts) < segments:
        return None

    active_world = get_active_curve_point_world_position(context)
    if active_world is None:
        return None
    best_ring = None
    best_distance = None
    for start in range(0, len(mesh_verts) - segments + 1, segments):
        ring = mesh_verts[start:start + segments]
        center = sum((Vector(vertex) for vertex in ring), Vector((0.0, 0.0, 0.0))) / segments
        distance = ((obj.matrix_world @ center) - active_world).length_squared
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_ring = ring
    if best_ring is None:
        return None

    projected = []
    for idx in selected:
        if 0 <= idx < len(best_ring):
            screen = view3d_utils.location_3d_to_region_2d(
                region, region_data, obj.matrix_world @ Vector(best_ring[idx])
            )
            if screen is not None:
                projected.append((screen.x, screen.y))
    if not projected:
        return None
    return (
        sum(point[0] for point in projected) / len(projected),
        sum(point[1] for point in projected) / len(projected),
    )


def prepare_proportional_transform(context, wd, verts, selected, cx, cy, sf, alignment_angle, flip_h, mouse_inside_widget=True):
    weights = get_proportional_vertex_weights(
        context, verts, selected, cx, cy, sf, alignment_angle, flip_h, wd.proportional_radius
    )
    selected_points = []
    for idx in selected:
        if 0 <= idx < len(verts):
            ox, oy = get_raw_offset(verts[idx])
            selected_points.append(effective_to_widget(ox, oy, cx, cy, sf, alignment_angle, flip_h))
    if selected_points:
        wd.proportional_center_x = sum(point[0] for point in selected_points) / len(selected_points)
        wd.proportional_center_y = sum(point[1] for point in selected_points) / len(selected_points)
    selected_offsets = [get_raw_offset(verts[idx]) for idx in selected if 0 <= idx < len(verts)]
    if selected_offsets:
        wd.transform_pivot_x = sum(offset[0] for offset in selected_offsets) / len(selected_offsets)
        wd.transform_pivot_y = sum(offset[1] for offset in selected_offsets) / len(selected_offsets)

    # The geometric pivot stays in profile coordinates, while the mouse pivot
    # is the screen-space center of the selected points. Keep it fixed during
    # the gesture so the mouse can make a full turn around the selection.
    selected_widget_points = [
        effective_to_widget(*get_raw_offset(verts[idx]), cx, cy, sf, alignment_angle, flip_h)
        for idx in selected if 0 <= idx < len(verts)
    ]
    if mouse_inside_widget:
        selected_mouse_points = selected_widget_points
    else:
        mesh_center = get_selected_3d_mesh_screen_center(context, selected)
        selected_mouse_points = [mesh_center] if mesh_center is not None else selected_widget_points
    if selected_mouse_points:
        wd.transform_mouse_pivot_x = sum(point[0] for point in selected_mouse_points) / len(selected_mouse_points)
        wd.transform_mouse_pivot_y = sum(point[1] for point in selected_mouse_points) / len(selected_mouse_points)
        wd.transform_mouse_pivot_valid = True
    else:
        wd.transform_mouse_pivot_valid = False
    set_proportional_weights(wd, weights)
    if proportional_edit_enabled(context):
        store_rotate_offsets(
            wd,
            verts,
            [idx for idx, vertex in enumerate(verts) if not getattr(vertex, 'is_ghost', False)],
        )
    else:
        store_rotate_offsets(wd, verts, sorted(weights))


def store_longitudinal_initial_state(wd, settings, selected):
    state = {}
    for point_idx, point_setting in enumerate(settings.point_settings):
        point_state = {}
        for vert_idx in selected:
            if 0 <= vert_idx < len(point_setting.cross_section_verts):
                vertex = point_setting.cross_section_verts[vert_idx]
                if not getattr(vertex, 'is_ghost', False):
                    point_state[str(vert_idx)] = [vertex.offset_x, vertex.offset_y]
        if point_state:
            state[str(point_idx)] = point_state
    wd.longitudinal_initial_state = json.dumps(state)


def get_longitudinal_initial_state(wd):
    try:
        raw = json.loads(wd.longitudinal_initial_state)
        return {
            int(point_idx): {int(vert_idx): tuple(offset) for vert_idx, offset in point_state.items()}
            for point_idx, point_state in raw.items()
        }
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        return {}


def restore_longitudinal_initial_state(settings, state):
    for point_idx, point_state in state.items():
        if point_idx >= len(settings.point_settings):
            continue
        verts = settings.point_settings[point_idx].cross_section_verts
        for vert_idx, offset in point_state.items():
            if vert_idx < len(verts):
                verts[vert_idx].offset_x = offset[0]
                verts[vert_idx].offset_y = offset[1]


def get_rotate_offsets(wd):
    raw = wd.rotate_initial_offsets.strip()
    if not raw:
        return {}
    result = {}
    for part in raw.split(";"):
        values = part.split(":")
        if len(values) == 3:
            try:
                result[int(values[0])] = (float(values[1]), float(values[2]))
            except ValueError:
                continue
    return result



def map_vertex_index_between_sections(settings, source_idx, target_idx, vertex_idx):
    if source_idx == target_idx:
        return vertex_idx
    total = len(settings.point_settings)
    if not (0 <= source_idx < total and 0 <= target_idx < total):
        return vertex_idx

    mapped_idx = int(vertex_idx)
    if abs(target_idx - source_idx) != 1:
        target_count = len(settings.point_settings[target_idx].cross_section_verts)
        return mapped_idx % target_count if target_count > 0 else mapped_idx
    if target_idx > source_idx:
        for section_idx in range(source_idx + 1, target_idx + 1):
            target_count = len(settings.point_settings[section_idx].cross_section_verts)
            if target_count <= 0:
                return mapped_idx
            offset = int(getattr(settings.point_settings[section_idx], 'bridge_offset', 0))
            mapped_idx = (mapped_idx + offset) % target_count
    else:
        for section_idx in range(source_idx, target_idx, -1):
            target_count = len(settings.point_settings[section_idx - 1].cross_section_verts)
            if target_count <= 0:
                return mapped_idx
            offset = int(getattr(settings.point_settings[section_idx], 'bridge_offset', 0))
            mapped_idx = (mapped_idx - offset) % target_count
    return mapped_idx


def get_neighbor_point_indices(settings):
    """Return neighbors within the active spline, never across separate hairs."""
    current = settings.active_point_index
    total = len(settings.point_settings)
    if total <= 1:
        return -1, current, -1
    obj = bpy.context.active_object
    if obj is None or obj.type != 'CURVE':
        return -1, current, -1
    start = 0
    end = total
    offset = 0
    for spline in obj.data.splines:
        count = len(spline.bezier_points) if spline.type == 'BEZIER' else len(spline.points)
        if offset <= current < offset + count:
            start, end = offset, offset + count
            break
        offset += count
    prev_idx = current - 1 if current > start else -1
    next_idx = current + 1 if current + 1 < end else -1
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


def context_matches_widget_view(context, wd):
    area = getattr(context, 'area', None)
    region = getattr(context, 'region', None)
    if area is None or region is None or area.type != 'VIEW_3D' or region.type != 'WINDOW':
        return False
    try:
        return (
            wd.bound_area_pointer == str(area.as_pointer())
            and wd.bound_region_pointer == str(region.as_pointer())
        )
    except ReferenceError:
        return False


def get_view3d_window_region(context):
    current_area = getattr(context, 'area', None)
    current_region = getattr(context, 'region', None)
    if current_area is not None and current_area.type == 'VIEW_3D':
        if current_region is not None and current_region.type == 'WINDOW':
            return current_area, current_region
        for region in current_area.regions:
            if region.type == 'WINDOW':
                return current_area, region
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
        wd = getattr(context.window_manager, 'hair_pipe_widget', None) if context is not None else None
        preview_mode = getattr(wd, 'preview_mode', 'BASE')
        curve_obj.hair_pipe_settings.smooth_shading = preview_mode == 'SUBDIV'
        disable_subdiv = preview_mode == 'BASE'
        show_in_front = bool(getattr(wd, 'preview_in_front', False))
        pipe_obj.display_type = 'TEXTURED'
        pipe_obj.show_wire = preview_mode == 'BASE'
        pipe_obj.show_in_front = show_in_front
        if mesh is not None:
            use_smooth = preview_mode == 'SUBDIV'
            mesh.polygons.foreach_set("use_smooth", [use_smooth] * len(mesh.polygons))
            mesh.update()
        for modifier in pipe_obj.modifiers:
            if modifier.type == 'SUBSURF':
                modifier.show_viewport = bool(preview_mode == 'SUBDIV')
        # Explicitly tag the object so Blender 5.0 invalidates the evaluated
        # modifier stack immediately when switching BASE/SUBDIV preview.
        try:
            pipe_obj.update_tag(refresh={'DATA'})
            if mesh is not None:
                mesh.update_tag()
        except (AttributeError, RuntimeError, TypeError):
            try:
                pipe_obj.update_tag()
            except (AttributeError, RuntimeError):
                pass
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
    wd.bound_area_pointer = str(area.as_pointer())
    wd.bound_region_pointer = str(region.as_pointer())
    settings = obj.hair_pipe_settings
    addon_entry = context.preferences.addons.get("hair_curve_pipe")
    widget_layout = addon_entry.preferences if addon_entry is not None else settings
    area_scale = max(0.35, min(1.8, getattr(widget_layout, "widget_area_scale", 1.0)))
    wd.widget_size = min(region.width, region.height) * 0.62 * area_scale
    wd.widget_center_x = region.width / 2.0 + region.width * 0.35 * getattr(widget_layout, "widget_offset_x", 0.0)
    wd.widget_center_y = region.height / 2.0 + region.height * 0.35 * getattr(widget_layout, "widget_offset_y", 0.0)
    wd.widget_scale_factor = 0.0
    wd.fitted_point_index = -1
    wd.source_curve_name = obj.name
    wd.bound_edit_curve_name = ''
    wd.bound_edit_point_index = -1
    wd.is_active = True
    wd.show_full_mesh_grid = False
    wd.auto_alignment_initialized = False
    wd.drag_vert_index = -1
    set_pipe_basemesh_preview(context, obj, True)
    set_curve_overlay_hidden(context, obj, True)
    try:
        from .widget_draw import ensure_draw_handler as _ensure
        _ensure()
    except Exception:
        pass
    redraw_view3d(context)
    return True


def restore_widget_solo_hold(context, wd):
    if not wd.solo_hold_active:
        return
    try:
        states = json.loads(wd.solo_hold_states)
    except (TypeError, ValueError, json.JSONDecodeError):
        states = {}
    for scene_obj in context.view_layer.objects:
        if scene_obj.name in states:
            scene_obj.hide_set(bool(states[scene_obj.name]))
    wd.solo_hold_states = "{}"
    wd.solo_hold_active = False


def set_widget_solo_state(context, wd, enabled):
    if context is None or getattr(context, 'view_layer', None) is None:
        return
    if not enabled:
        restore_widget_solo_hold(context, wd)
        redraw_view3d(context)
        return
    if wd.solo_hold_active:
        return

    source_curve = get_widget_source_curve(context)
    family_names = set()
    selected_curves = []
    for selected_obj in context.selected_objects:
        curve = None
        if selected_obj.type == 'CURVE' and hasattr(selected_obj, 'hair_pipe_settings'):
            curve = selected_obj
        elif selected_obj.type == 'MESH':
            curve = get_pipe_source_curve(selected_obj)
        elif selected_obj.type == 'EMPTY':
            curve = next(
                (child for child in selected_obj.children
                 if child.type == 'CURVE' and hasattr(child, 'hair_pipe_settings')),
                None,
            )
        if curve is not None and curve not in selected_curves:
            selected_curves.append(curve)
    if source_curve is not None and source_curve not in selected_curves:
        selected_curves.append(source_curve)

    for curve in selected_curves:
        family_names.add(curve.name)
        pipe_obj = get_pipe_object_for_curve(curve)
        if pipe_obj is not None:
            family_names.add(pipe_obj.name)
        root_obj = curve.parent
        if root_obj is not None:
            family_names.add(root_obj.name)
            family_names.update(child.name for child in root_obj.children)

    states = {}
    for scene_obj in context.view_layer.objects:
        hidden_before_solo = bool(scene_obj.hide_get())
        if scene_obj.type == 'CURVE' and scene_obj.get("hair_pipe_widget_hide_curve_overlay", False):
            raw_overlay_state = scene_obj.get(_CURVE_OVERLAY_STATE_KEY)
            if raw_overlay_state:
                try:
                    hidden_before_solo = bool(json.loads(raw_overlay_state).get("hide_set", hidden_before_solo))
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass
        states[scene_obj.name] = hidden_before_solo
        scene_obj.hide_set(scene_obj.name not in family_names)
    wd.solo_hold_states = json.dumps(states)
    wd.solo_hold_active = True
    redraw_view3d(context)


def cleanup_widget_display_state(context, wd):
    source_curve = get_widget_source_curve(context)
    set_curve_overlay_hidden(context, source_curve, False)
    set_pipe_basemesh_preview(context, source_curve, False)


def refresh_pipe_during_widget_edit(context, min_interval=1.0 / 30.0):
    global _last_widget_pipe_refresh
    now = time.perf_counter()
    if now - _last_widget_pipe_refresh < min_interval:
        return
    obj = context.active_object
    if obj is None or obj.type != 'CURVE':
        return
    try:
        from .handler import rebuild_existing_pipe
        rebuild_existing_pipe(obj, fast=True)
        _last_widget_pipe_refresh = now
    except (AttributeError, RuntimeError, ValueError):
        pass


def redraw_view3d(context, refresh_pipe=True):
    if refresh_pipe and getattr(getattr(context.window_manager, 'hair_pipe_widget', None), 'is_active', False):
        refresh_pipe_during_widget_edit(context)
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
            "bridge_offset": getattr(ps, "bridge_offset", 0),
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
        ps.bridge_offset = point_state.get("bridge_offset", getattr(ps, "bridge_offset", 0))
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


def get_transform_mouse_pivot(context, fallback_x, fallback_y):
    wd = getattr(context.window_manager, 'hair_pipe_widget', None)
    if wd is not None and getattr(wd, 'transform_mouse_pivot_valid', False):
        return wd.transform_mouse_pivot_x, wd.transform_mouse_pivot_y
    return fallback_x, fallback_y


