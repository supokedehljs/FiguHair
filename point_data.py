import json
import math
import bpy
from .curve_data import get_curve_points_data as curve_get_curve_points_data, is_curve_edit_mode as curve_is_curve_edit_mode
from .cross_section import normalize_cross_section_topology as cross_section_normalize_cross_section_topology
from .ghost import update_all_ghost_vertices as ghost_update_all_ghost_vertices
from .math_utils import lerp_angle


def _curve_point_position_signatures(curve_obj):
    if curve_obj is None or curve_obj.type != 'CURVE':
        return []
    if curve_is_curve_edit_mode(curve_obj):
        try:
            curve_obj.update_from_editmode()
        except Exception:
            pass
    signatures = []
    for spline in curve_obj.data.splines:
        if spline.type == 'BEZIER':
            points = spline.bezier_points
            for point in points:
                co = point.co
                signatures.append((round(co.x, 6), round(co.y, 6), round(co.z, 6)))
        else:
            points = spline.points
            for point in points:
                co = point.co
                signatures.append((round(co.x, 6), round(co.y, 6), round(co.z, 6)))
    return signatures


def _load_curve_point_signatures(curve_obj):
    raw = curve_obj.get("hair_pipe_point_signatures", "") if curve_obj else ""
    if not raw:
        return []
    try:
        return [tuple(item) for item in json.loads(raw)]
    except Exception:
        return []


def _store_curve_point_signatures(curve_obj, signatures):
    try:
        curve_obj["hair_pipe_point_signatures"] = json.dumps(signatures)
    except Exception:
        pass


def _point_setting_to_data(point_setting):
    return {
        "scale": point_setting.scale,
        "rotation": point_setting.rotation,
        "use_transition": bool(getattr(point_setting, "use_transition", False)),
        "active_vert_index": point_setting.active_vert_index,
        "verts": [
            {"offset_x": vert.offset_x, "offset_y": vert.offset_y, "is_ghost": bool(getattr(vert, "is_ghost", False))}
            for vert in point_setting.cross_section_verts
        ],
    }


def _default_point_setting_data(settings):
    verts = []
    for idx in range(settings.default_segments):
        angle = 2.0 * math.pi * idx / settings.default_segments
        verts.append({"offset_x": math.cos(angle) * settings.default_radius, "offset_y": math.sin(angle) * settings.default_radius, "is_ghost": False})
    return {"scale": 1.0, "rotation": 0.0, "use_transition": False, "active_vert_index": 0, "verts": verts}


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
        verts.append({"offset_x": lv["offset_x"] * (1.0 - t) + rv["offset_x"] * t, "offset_y": lv["offset_y"] * (1.0 - t) + rv["offset_y"] * t, "is_ghost": bool(lv.get("is_ghost", False) and rv.get("is_ghost", False))})
    return {"scale": left_data.get("scale", 1.0) * (1.0 - t) + right_data.get("scale", 1.0) * t, "rotation": lerp_angle(left_data.get("rotation", 0.0), right_data.get("rotation", 0.0), t), "use_transition": False, "active_vert_index": 0, "verts": verts}


def _clone_point_setting_data(data):
    if data is None:
        return None
    return {"scale": data.get("scale", 1.0), "rotation": data.get("rotation", 0.0), "use_transition": bool(data.get("use_transition", False)), "active_vert_index": data.get("active_vert_index", 0), "verts": [dict(vert) for vert in data.get("verts", [])]}


def _apply_point_setting_data(point_setting, data, settings):
    if data is None:
        data = _default_point_setting_data(settings)
    verts = data.get("verts", [])
    point_setting.cross_section_verts.clear()
    point_setting.scale = data.get("scale", 1.0)
    point_setting.rotation = data.get("rotation", 0.0)
    point_setting.use_transition = bool(data.get("use_transition", False))
    for vert_data in verts:
        vert = point_setting.cross_section_verts.add()
        vert.offset_x = vert_data.get("offset_x", 0.0)
        vert.offset_y = vert_data.get("offset_y", 0.0)
        vert.is_ghost = bool(vert_data.get("is_ghost", False))
    if len(point_setting.cross_section_verts) == 0:
        # fallback circle
        for idx in range(settings.default_segments):
            angle = 2.0 * math.pi * idx / settings.default_segments
            v = point_setting.cross_section_verts.add()
            v.offset_x = math.cos(angle) * settings.default_radius
            v.offset_y = math.sin(angle) * settings.default_radius
            v.is_ghost = False
    point_setting.active_vert_index = min(max(0, int(data.get("active_vert_index", 0))), max(0, len(point_setting.cross_section_verts) - 1))


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
    while suffix < old_count - prefix and suffix < new_count - prefix and old_signatures[old_count - 1 - suffix] == new_signatures[new_count - 1 - suffix]:
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


def init_cross_section_circle(point_setting, radius, segments):
    point_setting.cross_section_verts.clear()
    for i in range(segments):
        angle = 2.0 * math.pi * i / segments
        v = point_setting.cross_section_verts.add()
        v.offset_x = math.cos(angle) * radius
        v.offset_y = math.sin(angle) * radius
        v.is_ghost = False


def sync_point_settings(curve_obj):
    settings = curve_obj.hair_pipe_settings
    new_signatures = _curve_point_position_signatures(curve_obj)
    total_points = len(new_signatures)
    current = len(settings.point_settings)
    old_signatures = _load_curve_point_signatures(curve_obj)
    if old_signatures and new_signatures and old_signatures[0] != new_signatures[0]:
        curve_obj["hair_pipe_start_point_changed"] = True
    old_data = [_point_setting_to_data(ps) for ps in settings.point_settings]
    if current < total_points:
        inserted = False
        if len(old_signatures) == current and current > 0:
            prefix, suffix = _matching_prefix_suffix(old_signatures, new_signatures)
            insert_count = total_points - current
            if prefix + suffix == current:
                _replace_point_settings_from_data(settings, _rebuild_point_data_for_insert(old_data, prefix, insert_count, settings))
                if settings.active_point_index >= prefix:
                    settings.active_point_index += insert_count
                inserted = True
        if not inserted:
            template_data = old_data[settings.active_point_index] if current > 0 else _default_point_setting_data(settings)
            for _ in range(total_points - current):
                ps = settings.point_settings.add()
                _apply_point_setting_data(ps, template_data, settings)
    elif current > total_points:
        removed = False
        if len(old_signatures) == current and total_points > 0:
            prefix, suffix = _matching_prefix_suffix(old_signatures, new_signatures)
            remove_count = current - total_points
            if prefix + suffix == total_points:
                rebuilt = []
                rebuilt.extend(_clone_point_setting_data(data) for data in old_data[:prefix])
                rebuilt.extend(_clone_point_setting_data(data) for data in old_data[prefix + remove_count:])
                _replace_point_settings_from_data(settings, rebuilt)
                if settings.active_point_index >= prefix + remove_count:
                    settings.active_point_index -= remove_count
                elif settings.active_point_index >= prefix:
                    settings.active_point_index = max(0, prefix - 1)
                removed = True
        if not removed:
            for _ in range(current - total_points):
                settings.point_settings.remove(len(settings.point_settings) - 1)
    if total_points > 0 and settings.active_point_index >= total_points:
        settings.active_point_index = total_points - 1
    if total_points == 0:
        settings.active_point_index = 0
    cross_section_normalize_cross_section_topology(settings, curve_obj)
    ghost_update_all_ghost_vertices(settings)
    _store_curve_point_signatures(curve_obj, new_signatures)


def sync_active_point_from_selection(curve_obj):
    from .curve_data import get_selected_curve_point_index
    settings = curve_obj.hair_pipe_settings
    selected_index = get_selected_curve_point_index(curve_obj)
    if selected_index is None:
        return False
    sync_point_settings(curve_obj)
    if selected_index >= len(settings.point_settings):
        return False
    if settings.active_point_index != selected_index:
        settings.active_point_index = selected_index
    return True
