import math
import time
import bpy
from mathutils import Vector
from .curve_data import is_curve_edit_mode as curve_is_curve_edit_mode, get_selected_curve_point_indices as curve_get_selected_curve_point_indices
from .ghost import update_ghost_vertices as ghost_update_ghost_vertices
from .edit_utils import get_curve_point_by_global_index as edit_get_curve_point_by_global_index


def _ghost_vertex_error(point_setting, vertex_idx):
    verts = point_setting.cross_section_verts
    real_count = sum(1 for vertex in verts if not getattr(vertex, 'is_ghost', False))
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
    ghost_update_ghost_vertices(point_setting)
    error = math.hypot(target.offset_x - old_x, target.offset_y - old_y)
    radius = max(1e-6, max(math.hypot(vertex.offset_x, vertex.offset_y) for vertex in verts))
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
        ghost_update_ghost_vertices(point_setting)
    return changed


def _capture_curve_point_snapshot(curve_obj, selected_indices):
    snapshot = {}
    for point_idx in selected_indices:
        point = edit_get_curve_point_by_global_index(curve_obj, point_idx)
        if point is None:
            continue
        snapshot[point_idx] = point.co.copy()
    return snapshot


def _restore_curve_point_snapshot(curve_obj, snapshot):
    for point_idx, co in snapshot.items():
        point = edit_get_curve_point_by_global_index(curve_obj, point_idx)
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
        point = edit_get_curve_point_by_global_index(curve_obj, point_idx)
        prev_point = edit_get_curve_point_by_global_index(curve_obj, prev_idx)
        next_point = edit_get_curve_point_by_global_index(curve_obj, next_idx)
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
        ghost_update_ghost_vertices(ps)
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
        selected_indices = curve_get_selected_curve_point_indices(curve_obj) if curve_is_curve_edit_mode(curve_obj) else []
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
        selected_indices = curve_get_selected_curve_point_indices(curve_obj) if curve_is_curve_edit_mode(curve_obj) else []
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
    changed = apply_auto_ghost_vertices(settings, value, state['selected_indices'], state['snapshot'])
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
        if time.monotonic() - live_state.get('last_change_time', 0.0) < 1.5:
            return 0.08
        finish_auto_ghost_slider(live_curve)
        return None

    bpy.app.timers.register(finish_when_idle, first_interval=0.08)
