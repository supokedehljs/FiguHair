import bpy
import gpu
import math
import blf
import time
import json
from mathutils import Vector
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
from bpy.props import IntProperty, FloatProperty, BoolProperty
from .widget_geometry import *
from .widget_state import *
from .widget_draw import *
from .widget_cache import *
from .pipe_generation import generate_pipe_mesh
from .transition import is_transition_point, get_effective_point_setting
from .point_data import sync_point_settings, sync_active_point_from_selection
from .cross_section import get_active_spline_point_range
from .binding import (
    is_bound_slave_point, get_bound_edit_target, get_bound_sections_for_target,
    get_bound_section_display_offsets, set_binding_vertex_snap,
    find_nearest_source_vertex_world, get_bound_vertex_world, set_bound_vertex_world,
)

class HAIRPIPE_OT_widget_interact(bpy.types.Operator):
    """Open interactive cross-section editor overlay in the 3D viewport"""
    bl_idname = "hair_pipe.widget_interact"
    bl_label = "编辑横截面"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE' or not hasattr(obj, 'hair_pipe_settings'):
            return False
        if context.mode not in {'OBJECT', 'EDIT_CURVE'}:
            return False
        s = obj.hair_pipe_settings
        if len(s.point_settings) == 0:
            return False
        if s.active_point_index >= len(s.point_settings):
            return False
        ps = s.point_settings[s.active_point_index]
        if is_bound_slave_point(obj, s.active_point_index):
            return False
        return not is_transition_point(ps) and len(ps.cross_section_verts) >= 3

    def invoke(self, context, event):
        obj = context.active_object
        if obj is not None and obj.type == 'CURVE' and context.mode == 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='EDIT')
            except RuntimeError:
                self.report({'ERROR'}, "无法进入曲线编辑模式")
                return {'CANCELLED'}
            sync_point_settings(obj)
            if not sync_active_point_from_selection(obj):
                select_curve_point_by_index(obj, obj.hair_pipe_settings.active_point_index)

        wd = context.window_manager.hair_pipe_widget
        if wd.is_active:
            cleanup_widget_display_state(context, wd)
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
        cleanup_widget_display_state(context, wd)
        wd.is_active = False
        wd.drag_vert_index = -1
        wd.bound_edit_curve_name = ''
        wd.bound_edit_point_index = -1
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
        cleanup_widget_display_state(context, wd)
        wd.is_active = False
        wd.drag_vert_index = -1
        wd.move_active = False
        wd.rotate_active = False
        wd.scale_active = False
        wd.transform_mouse_pivot_valid = False
        wd.display_scale_active = False
        wd.bound_edit_curve_name = ''
        wd.bound_edit_point_index = -1
        wd.hold_key_mode = False
        redraw_view3d(context)


def handle_widget_modal(operator, context, event, close_on_key_release=False):
    wd = context.window_manager.hair_pipe_widget

    if not wd.is_active:
        operator._finish(context)
        return {'FINISHED'}

    if event.type == 'Z' and event.value == 'PRESS' and event.ctrl:
        if pop_widget_undo(context):
            clear_pipe_mesh_cache()
            refresh_pipe_during_widget_edit(context, min_interval=0.0)
        redraw_view3d(context, refresh_pipe=False)
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
    bound_name = getattr(wd, 'bound_edit_curve_name', '')
    bound_point = int(getattr(wd, 'bound_edit_point_index', -1))
    if bound_name:
        bound_obj = bpy.data.objects.get(bound_name)
        if bound_obj is not None and bound_obj.type == 'CURVE':
            bound_sections = get_bound_sections_for_target(obj, settings.active_point_index)
            for candidate_obj, candidate_idx, candidate_ps in bound_sections:
                if candidate_obj == bound_obj and candidate_idx == bound_point:
                    ps = candidate_ps
                    break
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
        if event_region is not None and event_region.type != 'WINDOW' and not wd.box_select_active:
            return {'PASS_THROUGH'}
        if event_region is None and not wd.box_select_active and not (view_region.x <= event.mouse_x < view_region.x + view_region.width and view_region.y <= event.mouse_y < view_region.y + view_region.height):
            return {'PASS_THROUGH'}
    wd.region_offset_x = view_region.x
    wd.region_offset_y = view_region.y
    mx, my = operator._get_local_mouse(event, wd)
    wd.mouse_x = mx
    wd.mouse_y = my
    if (mx < 0 or my < 0 or mx > view_region.width or my > view_region.height) and not wd.box_select_active:
        return {'PASS_THROUGH'}
    if wd.box_select_active:
        mx = max(0.0, min(float(view_region.width), mx))
        my = max(0.0, min(float(view_region.height), my))
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
    base_key = 'Q'
    in_front_key = 'W'
    solo_key = 'E'

    if event.type == base_key and event.value == 'PRESS' and not event.ctrl and not event.shift and not event.alt:
        wd.preview_mode = 'BASE' if wd.preview_mode == 'SUBDIV' else 'SUBDIV'
        source_curve = get_widget_source_curve(context)
        if source_curve is not None:
            set_pipe_basemesh_preview(context, source_curve, False)
            set_pipe_basemesh_preview(context, source_curve, True)
        redraw_view3d(context)
        return {'RUNNING_MODAL'}

    if event.type == in_front_key and event.value == 'PRESS' and not event.ctrl and not event.shift and not event.alt:
        wd.preview_in_front = not wd.preview_in_front
        return {'RUNNING_MODAL'}

    if event.type == solo_key and event.value == 'PRESS' and not event.ctrl and not event.shift and not event.alt:
        set_widget_solo_state(context, wd, not wd.solo_hold_active)
        return {'RUNNING_MODAL'}

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

    active_section = resolve_active_section(context)
    if active_section is None:
        return {'RUNNING_MODAL'}

    if not wd.move_active and event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.value == 'PRESS':
        if event.shift and not event.ctrl:
            sections = [(None, settings.active_point_index)]
            sections.extend(
                (child_obj, child_idx)
                for child_obj, child_idx, _child_ps in get_bound_sections_for_target(
                    obj, settings.active_point_index
                )
            )
            if sections:
                current = (bpy.data.objects.get(wd.bound_edit_curve_name),
                           int(wd.bound_edit_point_index)) if wd.bound_edit_curve_name else (None, settings.active_point_index)
                try:
                    current_index = next(i for i, item in enumerate(sections) if item == current)
                except StopIteration:
                    current_index = 0
                step = 1 if event.type == 'WHEELDOWNMOUSE' else -1
                next_obj, next_point = sections[(current_index + step) % len(sections)]
                if next_obj is None:
                    clear_bound_edit_selection(wd)
                    wd.active_section_curve_name = ''
                    wd.active_section_point_index = int(next_point)
                    settings.active_point_index = next_point
                else:
                    wd.bound_edit_curve_name = next_obj.name
                    wd.bound_edit_point_index = int(next_point)
                    wd.active_section_curve_name = next_obj.name
                    wd.active_section_point_index = int(next_point)
                wd.box_select_active = False
                wd.left_drag_pending = False
                wd.drag_vert_index = -1
                redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if not event.ctrl:
            return {'PASS_THROUGH'}
        total_points = len(settings.point_settings)
        if total_points > 0:
            previous_selection = get_current_selected_widget_verts(wd)
            previous_point_idx = settings.active_point_index
            step = -1 if event.type == 'WHEELUPMOUSE' else 1
            new_idx = (previous_point_idx + step) % total_points
            settings.active_point_index = new_idx
            wd.auto_alignment_initialized = False
            wd.fitted_point_index = -1
            select_curve_point_by_index(obj, new_idx)
            target_ps = settings.point_settings[new_idx]
            target_count = len(target_ps.cross_section_verts)
            preserved_selection = {
                map_vertex_index_between_sections(settings, previous_point_idx, new_idx, idx)
                for idx in previous_selection
            }
            preserved_selection = {idx for idx in preserved_selection if 0 <= idx < target_count}
            target_ps.active_vert_index = map_vertex_index_between_sections(
                settings,
                previous_point_idx,
                new_idx,
                ps.active_vert_index,
            ) if ps.active_vert_index >= 0 and target_count > 0 else -1
            wd.drag_vert_index = -1
            wd.left_drag_pending = False
            wd.left_drag_active = False
            wd.left_drag_vert_index = -1
            set_current_selected_widget_verts(wd, preserved_selection)
            redraw_view3d(context)
        return {'RUNNING_MODAL'}

    if wd.left_drag_pending:
        moved = math.sqrt((mx - wd.left_drag_start_x) ** 2 + (my - wd.left_drag_start_y) ** 2)
        if event.type == 'MOUSEMOVE' and moved >= drag_threshold:
            wd.left_drag_pending = False
            wd.left_drag_vert_index = -1
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
                # A click in the 3D area is resolved on release. A drag has
                # already switched to box_select_active above, so this path
                # is only the non-moving point-selection case.
                if getattr(wd, 'bound_edit_curve_name', ''):
                    active_bound = bpy.data.objects.get(wd.bound_edit_curve_name)
                    point_idx, ring_idx = get_active_section_nearest_vertex(
                        context, obj, settings.active_point_index, active_bound,
                        int(wd.bound_edit_point_index), mx, my,
                    )
                else:
                    point_idx, ring_idx = get_active_section_nearest_vertex(
                        context, obj, settings.active_point_index,
                        mouse_x=mx, mouse_y=my,
                    )
                if point_idx >= 0 and ring_idx >= 0:
                    if getattr(wd, 'bound_edit_curve_name', ''):
                        active_bound = bpy.data.objects.get(wd.bound_edit_curve_name)
                        bound_idx = int(wd.bound_edit_point_index)
                        if active_bound is not None:
                            active_bound.hair_pipe_settings.point_settings[bound_idx].active_vert_index = ring_idx
                        set_bound_selected_widget_verts(wd, {ring_idx}, active_bound, bound_idx)
                    else:
                        settings.active_point_index = point_idx
                        select_curve_point_by_index(obj, point_idx)
                        settings.point_settings[point_idx].active_vert_index = ring_idx
                        set_selected_widget_verts(wd, {ring_idx})
                elif not event.shift:
                    set_current_selected_widget_verts(wd, set())
                wd.left_drag_pending = False
                wd.left_drag_vert_index = -1
                redraw_view3d(context)
                return {'RUNNING_MODAL'}
            if wd.left_drag_vert_index >= 0:
                closest_idx = wd.left_drag_vert_index
                ps.active_vert_index = closest_idx
                if event.shift:
                    sel = get_current_selected_widget_verts(wd)
                    if closest_idx in sel:
                        sel.discard(closest_idx)
                    else:
                        sel.add(closest_idx)
                    set_current_selected_widget_verts(wd, sel)
                else:
                    set_current_selected_widget_verts(wd, {closest_idx})
            else:
                set_current_selected_widget_verts(wd, set())
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
        sel = sorted(get_current_selected_widget_verts(wd))
        initial = get_rotate_offsets(wd)
        if proportional_edit_enabled(context) and event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.value == 'PRESS':
            step = -0.5 if event.type == 'WHEELUPMOUSE' else 0.5
            wd.longitudinal_radius = max(1.0, min(1000.0, wd.longitudinal_radius + step))
            dx, dy = widget_to_effective(mx, my, cx, cy, sf, alignment_angle, flip_h)
            sx, sy = widget_to_effective(wd.move_start_x, wd.move_start_y, cx, cy, sf, alignment_angle, flip_h)
            apply_longitudinal_move(context, settings, wd, set(sel), dx - sx, dy - sy)
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
            wd.proportional_radius = max(8.0, min(5000.0, wd.proportional_radius * factor))
            weights = get_proportional_vertex_weights(
                context,
                verts,
                set(sel),
                cx,
                cy,
                sf,
                alignment_angle,
                flip_h,
                wd.proportional_radius,
                baseline=initial,
            )
            dx, dy = widget_to_effective(mx, my, cx, cy, sf, alignment_angle, flip_h)
            sx, sy = widget_to_effective(wd.move_start_x, wd.move_start_y, cx, cy, sf, alignment_angle, flip_h)
            delta_x = dx - sx
            delta_y = dy - sy
            for vi, initial_offset in initial.items():
                if vi >= len(verts):
                    continue
                weight = weights.get(vi, 0.0)
                verts[vi].offset_x = initial_offset[0] + delta_x * weight
                verts[vi].offset_y = initial_offset[1] + delta_y * weight
            set_proportional_weights(wd, weights)
            update_ghost_vertices(ps)
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE':
            if getattr(wd, 'snap_bound_points', False) and getattr(wd, 'bound_edit_curve_name', ''):
                active_bound = bpy.data.objects.get(wd.bound_edit_curve_name)
                bound_idx = int(getattr(wd, 'bound_edit_point_index', -1))
                if active_bound is not None and sel:
                    source_ps = settings.point_settings[settings.active_point_index]
                    slave_ps = active_bound.hair_pipe_settings.point_settings[bound_idx]
                    # Use the actual source mesh ring through the binding helper.
                    for slave_vertex in sel:
                        world = get_bound_vertex_world(active_bound, bound_idx, slave_vertex)
                        if world is None:
                            continue
                        source_vertex, target_world = find_nearest_source_vertex_world(
                            obj, settings.active_point_index, world,
                        )
                        if source_vertex >= 0 and target_world is not None and (target_world - world).length <= wd.snap_distance:
                            set_binding_vertex_snap(active_bound, bound_idx, slave_vertex, source_vertex, enabled=True)
                            set_bound_vertex_world(active_bound, bound_idx, slave_vertex, target_world)
            dx, dy = widget_to_effective(mx, my, cx, cy, sf, alignment_angle, flip_h)
            sx, sy = widget_to_effective(wd.move_start_x, wd.move_start_y, cx, cy, sf, alignment_angle, flip_h)
            delta_x = dx - sx
            delta_y = dy - sy
            if proportional_edit_enabled(context):
                apply_longitudinal_move(context, settings, wd, set(sel), delta_x, delta_y)
            else:
                weights = get_proportional_weights(wd)
                for vi, weight in weights.items():
                    initial_offset = initial.get(vi)
                    if initial_offset is not None and vi < len(verts) and not getattr(verts[vi], 'is_ghost', False):
                        verts[vi].offset_x = initial_offset[0] + delta_x * weight
                        verts[vi].offset_y = initial_offset[1] + delta_y * weight
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
            for vi, initial_offset in initial.items():
                if vi < len(verts):
                    verts[vi].offset_x = initial_offset[0]
                    verts[vi].offset_y = initial_offset[1]
            restore_longitudinal_initial_state(settings, get_longitudinal_initial_state(wd))
            update_all_ghost_vertices(settings)
            wd.move_active = False
            wd.left_drag_active = False
            wd.left_drag_vert_index = -1
            update_ghost_vertices(ps)
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}

    if wd.display_scale_active:
        if event.type == 'MOUSEMOVE':
            mouse_pivot_x, mouse_pivot_y = get_transform_mouse_pivot(context, cx, cy)
            start_dist = math.hypot(wd.scale_start_x - mouse_pivot_x, wd.scale_start_y - mouse_pivot_y)
            now_dist = math.hypot(mx - mouse_pivot_x, my - mouse_pivot_y)
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
        sel = sorted(get_current_selected_widget_verts(wd))
        initial = get_rotate_offsets(wd)
        if event.type == 'MOUSEMOVE':
            ctr_x = wd.transform_pivot_x
            ctr_y = wd.transform_pivot_y
            mouse_pivot_x, mouse_pivot_y = get_transform_mouse_pivot(context, cx, cy)
            start_dist = math.hypot(wd.scale_start_x - mouse_pivot_x, wd.scale_start_y - mouse_pivot_y)
            now_dist = math.hypot(mx - mouse_pivot_x, my - mouse_pivot_y)
            factor = now_dist / max(start_dist, 1.0)
            weights = get_proportional_weights(wd)
            for vi, weight in weights.items():
                initial_offset = initial.get(vi)
                if initial_offset is not None and vi < len(verts) and not getattr(verts[vi], 'is_ghost', False):
                    initial_x, initial_y = initial_offset
                    target_x = ctr_x + (initial_x - ctr_x) * factor
                    target_y = ctr_y + (initial_y - ctr_y) * factor
                    verts[vi].offset_x = initial_x + (target_x - initial_x) * weight
                    verts[vi].offset_y = initial_y + (target_y - initial_y) * weight
            update_ghost_vertices(ps)
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            wd.scale_active = False
            wd.transform_mouse_pivot_valid = False
            sync_active_cross_section_to_selected_points(context)
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            for vi, initial_offset in initial.items():
                if vi < len(verts):
                    verts[vi].offset_x = initial_offset[0]
                    verts[vi].offset_y = initial_offset[1]
            wd.scale_active = False
            wd.transform_mouse_pivot_valid = False
            update_ghost_vertices(ps)
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}

    # Rotate mode active
    if wd.rotate_active:
        sel = sorted(get_current_selected_widget_verts(wd))
        initial = get_rotate_offsets(wd)
        if event.type == 'MOUSEMOVE':
            mouse_pivot_x, mouse_pivot_y = get_transform_mouse_pivot(context, cx, cy)
            a_start = math.atan2(wd.rotate_start_y - mouse_pivot_y, wd.rotate_start_x - mouse_pivot_x)
            a_now = math.atan2(my - mouse_pivot_y, mx - mouse_pivot_x)
            angle = a_now - a_start
            if flip_h:
                angle = -angle
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)
            ctr_x = wd.transform_pivot_x
            ctr_y = wd.transform_pivot_y
            weights = get_proportional_weights(wd)
            for vi, weight in weights.items():
                initial_offset = initial.get(vi)
                if initial_offset is not None and vi < len(verts) and not getattr(verts[vi], 'is_ghost', False):
                    weighted_angle = angle * weight
                    weighted_cos = math.cos(weighted_angle)
                    weighted_sin = math.sin(weighted_angle)
                    rx = initial_offset[0] - ctr_x
                    ry = initial_offset[1] - ctr_y
                    target_x = ctr_x + rx * weighted_cos - ry * weighted_sin
                    target_y = ctr_y + rx * weighted_sin + ry * weighted_cos
                    verts[vi].offset_x = initial_offset[0] + (target_x - initial_offset[0]) * weight
                    verts[vi].offset_y = initial_offset[1] + (target_y - initial_offset[1]) * weight
            update_ghost_vertices(ps)
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            wd.rotate_active = False
            wd.transform_mouse_pivot_valid = False
            for vi in sel:
                if vi < len(verts):
                    apply_active_vertex_edit_to_selected_points(context, ps, vi)
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            for vi, initial_offset in initial.items():
                if vi < len(verts):
                    verts[vi].offset_x = initial_offset[0]
                    verts[vi].offset_y = initial_offset[1]
            wd.rotate_active = False
            wd.transform_mouse_pivot_valid = False
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
                if getattr(wd, 'bound_edit_curve_name', ''):
                    active_bound = bpy.data.objects.get(wd.bound_edit_curve_name)
                    bound_hits = get_bound_section_vertices_in_screen_rect(
                        context, obj, settings.active_point_index,
                        active_bound, int(wd.bound_edit_point_index),
                        bx0, by0, bx1, by1,
                    ) if active_bound is not None else []
                    hits = [(int(wd.bound_edit_point_index), idx) for idx in bound_hits]
                else:
                    hits = get_active_section_vertices_in_screen_rect(
                        context, bx0, by0, bx1, by1,
                    )
                if hits:
                    hits_by_point = {}
                    for point_idx, vert_idx in hits:
                        hits_by_point.setdefault(point_idx, set()).add(vert_idx)
                    if getattr(wd, 'bound_edit_curve_name', ''):
                        # Bound 3D hits are indices in the bound profile, not
                        # source-curve point indices. Never switch the source
                        # active point when editing a bound section.
                        active_bound = bpy.data.objects.get(wd.bound_edit_curve_name)
                        bound_idx = int(wd.bound_edit_point_index)
                        if active_bound is not None and 0 <= bound_idx < len(active_bound.hair_pipe_settings.point_settings):
                            active_bound.hair_pipe_settings.point_settings[bound_idx].active_vert_index = min(hits_by_point.get(bound_idx, set()) or {0})
                        selected = set(hits_by_point.get(bound_idx, set()))
                        set_bound_selected_widget_verts(wd, selected, active_bound, bound_idx)
                    else:
                        target_point_idx = settings.active_point_index
                        if target_point_idx not in hits_by_point:
                            target_point_idx = next(iter(hits_by_point))
                        settings.active_point_index = target_point_idx
                        select_curve_point_by_index(obj, target_point_idx)
                        target_ps = settings.point_settings[target_point_idx]
                        active_hits = hits_by_point[target_point_idx]
                        target_ps.active_vert_index = min(active_hits)
                        selected = set(active_hits)
                        set_selected_widget_verts(wd, selected)
                else:
                    selected = set()
            else:
                selected = set()
                if getattr(wd, 'bound_edit_curve_name', ''):
                    active_bound_obj = bpy.data.objects.get(wd.bound_edit_curve_name)
                    offsets = get_bound_section_display_offsets(
                        obj, settings.active_point_index, active_bound_obj,
                        int(getattr(wd, 'bound_edit_point_index', -1)),
                    ) if active_bound_obj is not None else []
                    for i, (ox, oy) in enumerate(offsets):
                        px, py = effective_to_widget(ox, oy, cx, cy, sf, alignment_angle, flip_h)
                        if bx0 <= px <= bx1 and by0 <= py <= by1:
                            selected.add(i)
                else:
                    for i, vertex in enumerate(verts):
                        ox, oy = get_raw_offset(vertex)
                        px, py = effective_to_widget(ox, oy, cx, cy, sf, alignment_angle, flip_h)
                        if bx0 <= px <= bx1 and by0 <= py <= by1:
                            selected.add(i)
                if event.shift:
                    selected |= get_current_selected_widget_verts(wd)
                set_current_selected_widget_verts(wd, selected)
            if wd.box_select_3d and not getattr(wd, 'bound_edit_curve_name', '') and hits:
                for point_idx, point_hits in hits_by_point.items():
                    if point_idx < len(settings.point_settings) and point_hits:
                        settings.point_settings[point_idx].active_vert_index = min(point_hits)
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
            display_offsets = None
            if getattr(wd, 'bound_edit_curve_name', ''):
                bound_obj = bpy.data.objects.get(wd.bound_edit_curve_name)
                if bound_obj is not None:
                    display_offsets = get_bound_section_display_offsets(
                        obj, settings.active_point_index, bound_obj,
                        int(getattr(wd, 'bound_edit_point_index', -1)),
                    )
            if len(polygon) >= 3:
                for i, v in enumerate(verts):
                    if display_offsets is not None and i < len(display_offsets):
                        ox, oy = display_offsets[i]
                    else:
                        ox, oy = get_raw_offset(v)
                    px, py = effective_to_widget(ox, oy, cx, cy, sf, alignment_angle, flip_h)
                    if point_in_polygon(px, py, polygon):
                        selected.add(i)
            if event.shift:
                selected = selected | get_current_selected_widget_verts(wd)
            set_current_selected_widget_verts(wd, selected)
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
            point_range = get_active_spline_point_range(context.active_object, settings)
            remove_cross_section_vertex_all(settings, ps.active_vert_index, point_range)
            sync_active_cross_section_to_selected_points(context)
            wd.drag_vert_index = -1
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if inside_toggle_button:
            selected = {idx for idx in get_current_selected_widget_verts(wd) if 0 <= idx < len(verts)}
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
            # Do not resolve a 3D point on press. Keeping the press pending
            # guarantees that the same gesture can become a box selection.
            # A click is resolved on release in the pending branch above.
            return {'RUNNING_MODAL'}

        if not inside_widget:
            redraw_view3d(context)
            return {'RUNNING_MODAL'}

        if inside_widget:
            # Only the explicitly active layer is interactive. Other bound
            # sections are visual references and must never steal a click.
            if getattr(wd, 'bound_edit_curve_name', ''):
                bound_obj = bpy.data.objects.get(wd.bound_edit_curve_name)
                display_offsets = get_bound_section_display_offsets(
                    obj, settings.active_point_index, bound_obj,
                    int(getattr(wd, 'bound_edit_point_index', -1)),
                ) if bound_obj is not None else []
                candidates = []
                for index, (ox, oy) in enumerate(display_offsets):
                    px, py = effective_to_widget(ox, oy, cx, cy, sf, alignment_angle, flip_h)
                    distance = (px - mx) ** 2 + (py - my) ** 2
                    candidates.append((distance, index))
                closest_idx = min(candidates)[1] if candidates and min(candidates)[0] <= 100.0 else -1
            else:
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
        sel = get_current_selected_widget_verts(wd)
        sel = {vi for vi in sel if 0 <= vi < len(verts) and not getattr(verts[vi], 'is_ghost', False)}
        if sel:
            push_widget_undo(context, "移动横截面顶点")
            set_current_selected_widget_verts(wd, sel)
            wd.move_active = True
            wd.move_start_x = mx
            wd.move_start_y = my
            prepare_proportional_transform(context, wd, verts, sel, cx, cy, sf, alignment_angle, flip_h, inside_widget)
            store_longitudinal_initial_state(wd, settings, sel)
            redraw_view3d(context)
        return {'RUNNING_MODAL'}

    if event.type == 'R' and event.value == 'PRESS':
        sel = get_current_selected_widget_verts(wd)
        sel = {vi for vi in sel if 0 <= vi < len(verts) and not getattr(verts[vi], 'is_ghost', False)}
        if sel:
            push_widget_undo(context, "旋转横截面顶点")
            set_current_selected_widget_verts(wd, sel)
            wd.rotate_active = True
            wd.rotate_start_x = mx
            wd.rotate_start_y = my
            prepare_proportional_transform(context, wd, verts, sel, cx, cy, sf, alignment_angle, flip_h, inside_widget)
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
        if getattr(wd, 'bound_edit_curve_name', ''):
            return {'RUNNING_MODAL'}
        sel = get_current_selected_widget_verts(wd)
        sel = {vi for vi in sel if 0 <= vi < len(verts) and not getattr(verts[vi], 'is_ghost', False)}
        if sel:
            push_widget_undo(context, "缩放横截面顶点")
            set_current_selected_widget_verts(wd, sel)
            wd.scale_active = True
            wd.scale_start_x = mx
            wd.scale_start_y = my
            prepare_proportional_transform(context, wd, verts, sel, cx, cy, sf, alignment_angle, flip_h, inside_widget)
            redraw_view3d(context)
        return {'RUNNING_MODAL'}

    # A - Select All / Deselect All
    if event.type == 'A' and event.value == 'PRESS':
        sel = get_current_selected_widget_verts(wd)
        if len(sel) == len(verts):
            set_current_selected_widget_verts(wd, set())
        else:
            set_current_selected_widget_verts(wd, set(range(len(verts))))
        redraw_view3d(context)
        return {'RUNNING_MODAL'}

    if event.type == 'X' and event.value == 'PRESS':
        return {'PASS_THROUGH'}

    if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
        if event.alt or event.ctrl or event.shift or event.oskey:
            return {'PASS_THROUGH'}
        target_point_index = settings.active_point_index
        wd.context_menu_point_index = target_point_index
        if inside_widget:
            bound_hit = get_bound_edit_target(
                obj, settings.active_point_index, mx, my, cx, cy,
                sf, alignment_angle, flip_h,
            )
            if bound_hit is not None:
                bound_obj, bound_point, closest_idx, bound_ps = bound_hit
                wd.bound_edit_curve_name = bound_obj.name
                wd.bound_edit_point_index = bound_point
                set_bound_selected_widget_verts(wd, {closest_idx}, bound_obj, bound_point)
                if getattr(wd, 'snap_bound_points', False):
                    source_ps = settings.point_settings[settings.active_point_index]
                    source_vertex = min(closest_idx, len(source_ps.cross_section_verts) - 1)
                    set_binding_vertex_snap(
                        bound_obj, bound_point, closest_idx, source_vertex, enabled=True,
                    )
                ps = bound_ps
                verts = ps.cross_section_verts
            else:
                clear_bound_edit_selection(wd)
                closest_idx = find_nearest_raw_vertex(verts, mx, my, cx, cy, sf, alignment_angle, flip_h)
            if closest_idx >= 0:
                ps.active_vert_index = closest_idx
                set_bound_selected_widget_verts(wd, {closest_idx}, bound_obj, bound_point)
                redraw_view3d(context)
        bpy.ops.wm.call_menu(name="HAIRPIPE_MT_widget_context_menu")
        settings.active_point_index = target_point_index
        wd.context_menu_point_index = target_point_index
        return {'RUNNING_MODAL'}

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
        point_range = get_active_spline_point_range(obj, settings)
        remove_cross_section_vertex_all(settings, ps.active_vert_index, point_range)
        sync_active_cross_section_to_selected_points(context)
        if wd is not None:
            wd.drag_vert_index = -1
        redraw_view3d(context)
        return {'FINISHED'}


class HAIRPIPE_MT_widget_context_menu(bpy.types.Menu):
    bl_idname = "HAIRPIPE_MT_widget_context_menu"
    bl_label = "横截面编辑"

    def draw(self, context):
        layout = self.layout
        layout.operator_context = 'INVOKE_DEFAULT'
        wd = getattr(context.window_manager, 'hair_pipe_widget', None)
        bridge_op = layout.operator(
            "hair_pipe.widget_bridge_offset",
            text="上下桥接错位",
            icon='ARROW_LEFTRIGHT',
        )
        bridge_op.point_index = int(getattr(wd, 'context_menu_point_index', -1))
        layout.separator()
        layout.operator("hair_pipe.widget_toggle_ghost", text="设置为幽灵点", icon='GHOST_ENABLED')
        layout.operator("hair_pipe.widget_make_normal", text="转换为正常点", icon='GHOST_DISABLED')
        layout.separator()
        layout.operator("hair_pipe.cross_section_spread", text="横截面传递", icon='DUPLICATE')


class HAIRPIPE_OT_widget_smooth_selected_vertices(bpy.types.Operator):
    bl_idname = "hair_pipe.widget_smooth_selected_vertices"
    bl_label = "平滑横截面顶点"
    bl_description = "将选中的横截面顶点向相邻顶点平均位置平滑"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(
        name="平滑模式",
        items=(
            ('NEIGHBOR', "普通平滑", "向相邻顶点的平均位置平滑"),
            ('CIRCULAR', "圆形平滑", "向以横截面中心为圆心的均匀圆形平滑"),
        ),
        default='NEIGHBOR',
    )
    strength: FloatProperty(name="强度", default=0.5, min=0.0, max=1.0)
    iterations: IntProperty(name="次数", default=1, min=1, max=20)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        wd = getattr(context.window_manager, "hair_pipe_widget", None)
        return obj is not None and obj.type == 'CURVE' and wd is not None and wd.is_active

    def execute(self, context):
        obj = context.active_object
        settings = obj.hair_pipe_settings
        if not settings.point_settings:
            return {'CANCELLED'}
        point_idx = max(0, min(settings.active_point_index, len(settings.point_settings) - 1))
        ps = settings.point_settings[point_idx]
        verts = ps.cross_section_verts
        wd = context.window_manager.hair_pipe_widget
        selected = {
            idx for idx in get_current_selected_widget_verts(wd)
            if 0 <= idx < len(verts) and not getattr(verts[idx], 'is_ghost', False)
        }
        if not selected:
            self.report({'WARNING'}, "请先选择需要平滑的横截面顶点")
            return {'CANCELLED'}

        push_widget_undo(context, "平滑横截面顶点")
        for _iteration in range(self.iterations):
            original = [(vertex.offset_x, vertex.offset_y) for vertex in verts]
            updates = {}
            count = len(verts)
            center_x = sum(point[0] for point in original) / count
            center_y = sum(point[1] for point in original) / count
            mean_radius = sum(math.hypot(point[0] - center_x, point[1] - center_y) for point in original) / count
            for idx in selected:
                if self.mode == 'CIRCULAR':
                    radial_x = original[idx][0] - center_x
                    radial_y = original[idx][1] - center_y
                    radial_length = math.hypot(radial_x, radial_y)
                    if radial_length > 1e-8:
                        target_x = center_x + radial_x / radial_length * mean_radius
                        target_y = center_y + radial_y / radial_length * mean_radius
                    else:
                        angle = math.tau * idx / count
                        target_x = center_x + math.cos(angle) * mean_radius
                        target_y = center_y + math.sin(angle) * mean_radius
                else:
                    previous_idx = (idx - 1) % count
                    next_idx = (idx + 1) % count
                    target_x = (original[previous_idx][0] + original[next_idx][0]) * 0.5
                    target_y = (original[previous_idx][1] + original[next_idx][1]) * 0.5
                updates[idx] = (
                    original[idx][0] + (target_x - original[idx][0]) * self.strength,
                    original[idx][1] + (target_y - original[idx][1]) * self.strength,
                )
            for idx, (offset_x, offset_y) in updates.items():
                verts[idx].offset_x = offset_x
                verts[idx].offset_y = offset_y

        update_ghost_vertices(ps)
        sync_active_cross_section_to_selected_points(context)
        clear_pipe_mesh_cache()
        redraw_view3d(context)
        return {'FINISHED'}


class HAIRPIPE_OT_widget_delete_selected_vertices(bpy.types.Operator):
    bl_idname = "hair_pipe.widget_delete_selected_vertices"
    bl_label = "删除横截面顶点"

    @classmethod
    def poll(cls, context):
        obj, settings, ps, wd = get_widget_edit_context(context)
        return (
            obj is not None
            and ps is not None
            and wd is not None
            and wd.is_active
            and bool(get_current_selected_widget_verts(wd))
        )

    def execute(self, context):
        obj, settings, ps, wd = get_widget_edit_context(context)
        selected = get_current_selected_widget_verts(wd)
        if ps is None or len(ps.cross_section_verts) - len(selected) < 3:
            self.report({'WARNING'}, "横截面至少需要保留三个顶点")
            return {'CANCELLED'}
        push_widget_undo(context, "删除横截面顶点")
        if not remove_selected_cross_section_vertices(settings, ps, selected):
            return {'CANCELLED'}
        set_current_selected_widget_verts(wd, set())
        wd.drag_vert_index = -1
        redraw_view3d(context)
        return {'FINISHED'}


class HAIRPIPE_OT_widget_bridge_offset(bpy.types.Operator):
    bl_idname = "hair_pipe.widget_bridge_offset"
    bl_label = "上下桥接错位"
    bl_description = "调整当前横截面与上一个横截面的顶点连接偏移"
    bl_options = {'REGISTER', 'UNDO'}

    offset: IntProperty(
        name="偏移数量",
        description="当前横截面与上一个横截面之间的顶点偏移数量",
        default=0,
        min=-64,
        max=64,
    )
    point_index: IntProperty(default=-1, options={'HIDDEN'})
    _start_mouse_x = 0
    _initial_offset = 0
    _undo_pushed = False
    _confirmed = False

    @classmethod
    def poll(cls, context):
        obj, settings, ps, wd = get_widget_edit_context(context)
        return obj is not None and ps is not None and wd is not None and wd.is_active

    def invoke(self, context, event):
        obj, settings, ps, wd = get_widget_edit_context(context)
        if settings is None:
            return {'CANCELLED'}
        target_index = int(getattr(wd, 'context_menu_point_index', -1)) if wd is not None else -1
        if not (0 <= target_index < len(settings.point_settings)):
            target_index = settings.active_point_index
        self.point_index = target_index
        settings.active_point_index = target_index
        select_curve_point_by_index(obj, target_index)
        self._initial_offset = int(getattr(settings.point_settings[target_index], 'bridge_offset', 0))
        self.offset = self._initial_offset
        self._start_mouse_x = int(getattr(event, 'mouse_region_x', 0))
        push_widget_undo(context, "上下桥接错位")
        self._undo_pushed = True
        self._confirmed = False
        context.window_manager.modal_handler_add(self)
        context.area.header_text_set(
            f"上下桥接错位：左右移动调整 {self.offset:+d} | 左键确认 | 右键取消"
        )
        return {'RUNNING_MODAL'}

    def update_modal_offset(self, context, mouse_x):
        delta = int(round((mouse_x - self._start_mouse_x) / 12.0))
        self.offset = max(-64, min(64, self._initial_offset + delta))
        obj, settings, _ps, _wd = get_widget_edit_context(context)
        if settings is None or not (0 <= self.point_index < len(settings.point_settings)):
            return
        settings.point_settings[self.point_index].bridge_offset = self.offset
        clear_pipe_mesh_cache()
        refresh_pipe_during_widget_edit(context, min_interval=0.0)
        redraw_view3d(context, refresh_pipe=False)

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            self.update_modal_offset(context, int(getattr(event, 'mouse_region_x', self._start_mouse_x)))
            context.area.header_text_set(
                f"上下桥接错位：{self.offset:+d} | 左键确认 | 右键取消"
            )
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self._confirmed = True
            context.area.header_text_set(None)
            redraw_view3d(context, refresh_pipe=False)
            return {'FINISHED'}
        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            obj, settings, _ps, _wd = get_widget_edit_context(context)
            if settings is not None and 0 <= self.point_index < len(settings.point_settings):
                settings.point_settings[self.point_index].bridge_offset = self._initial_offset
                clear_pipe_mesh_cache()
                refresh_pipe_during_widget_edit(context, min_interval=0.0)
            if self._undo_pushed:
                pop_widget_undo(context)
            context.area.header_text_set(None)
            redraw_view3d(context, refresh_pipe=False)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def execute(self, context):
        obj, settings, ps, wd = get_widget_edit_context(context)
        if settings is None:
            return {'CANCELLED'}
        target_index = self.point_index
        if not (0 <= target_index < len(settings.point_settings)):
            return {'CANCELLED'}
        settings.active_point_index = target_index
        select_curve_point_by_index(obj, target_index)
        settings.point_settings[target_index].bridge_offset = int(self.offset)
        clear_pipe_mesh_cache()
        refresh_pipe_during_widget_edit(context, min_interval=0.0)
        settings.active_point_index = target_index
        select_curve_point_by_index(obj, target_index)
        if wd is not None:
            wd.context_menu_point_index = target_index
        redraw_view3d(context, refresh_pipe=False)
        return {'FINISHED'}


class HAIRPIPE_OT_widget_toggle_ghost(bpy.types.Operator):
    bl_idname = "hair_pipe.widget_toggle_ghost"
    bl_label = "设置为幽灵点"

    def execute(self, context):
        obj, settings, ps, wd = get_widget_edit_context(context)
        if ps is None:
            return {'CANCELLED'}
        verts = ps.cross_section_verts
        selected = {idx for idx in get_current_selected_widget_verts(wd) if 0 <= idx < len(verts)} if wd is not None else set()
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
            set_current_selected_widget_verts(wd, selected)
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
        selected = {idx for idx in get_current_selected_widget_verts(wd) if 0 <= idx < len(verts)} if wd is not None else set()
        selected_ghosts = {idx for idx in selected if getattr(verts[idx], 'is_ghost', False)}
        if not selected_ghosts:
            return {'CANCELLED'}
        push_widget_undo(context, "设置横截面正常点")
        target_indices = get_widget_target_point_indices(context, settings)
        changed = False
        for point_idx in target_indices:
            target_ps = settings.point_settings[point_idx]
            for idx in selected_ghosts:
                if 0 <= idx < len(target_ps.cross_section_verts) and getattr(target_ps.cross_section_verts[idx], 'is_ghost', False):
                    target_ps.cross_section_verts[idx].is_ghost = False
                    changed = True
            update_ghost_vertices(target_ps)
        if changed:
            update_all_ghost_vertices(settings)
        if wd is not None:
            set_current_selected_widget_verts(wd, {idx for idx in selected_ghosts if 0 <= idx < len(verts)})
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
        wd = context.window_manager.hair_pipe_widget
        cleanup_widget_display_state(context, wd)
        wd.is_active = False
        wd.drag_vert_index = -1
        wd.hold_key_mode = False
        redraw_view3d(context)
        return {'FINISHED'}


classes = (
    HAIRPIPE_MT_widget_context_menu,
    HairPipeWidgetSettings,
    HAIRPIPE_OT_widget_interact,
    HAIRPIPE_OT_widget_hold,
    HAIRPIPE_OT_widget_add_vertex,
    HAIRPIPE_OT_widget_remove_vertex,
    HAIRPIPE_OT_widget_smooth_selected_vertices,
    HAIRPIPE_OT_widget_delete_selected_vertices,
    HAIRPIPE_OT_widget_bridge_offset,
    HAIRPIPE_OT_widget_toggle_ghost,
    HAIRPIPE_OT_widget_make_normal,
    HAIRPIPE_OT_widget_toggle_smooth_preview,
    HAIRPIPE_OT_widget_toggle_flip,
    HAIRPIPE_OT_widget_toggle_grid,
    HAIRPIPE_OT_widget_stop,
)
def draw_widget_context_menu(self, context):
    wd = getattr(context.window_manager, "hair_pipe_widget", None)
    obj = context.active_object
    if obj is None or obj.type != 'CURVE' or wd is None or not wd.is_active or not is_curve_edit_mode(obj):
        return
    self.layout.separator()
    self.layout.operator("wm.call_menu", text="横截面编辑", icon='MOD_CURVE').name = "HAIRPIPE_MT_widget_context_menu"


def register_keymaps():
    bpy.types.VIEW3D_MT_edit_curve_delete.append(draw_cross_section_delete_menu)
    bpy.types.VIEW3D_MT_edit_curve_context_menu.append(draw_widget_context_menu)


def unregister_keymaps():
    for menu, callback in (
        (bpy.types.VIEW3D_MT_edit_curve_delete, draw_cross_section_delete_menu),
        (bpy.types.VIEW3D_MT_edit_curve_context_menu, draw_widget_context_menu),
    ):
        try:
            menu.remove(callback)
        except (AttributeError, ValueError):
            pass


def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError as e:
            if "already registered" not in str(e):
                raise
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
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError):
            pass
