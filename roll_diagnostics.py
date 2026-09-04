import math
import time
from pathlib import Path
import bpy
from mathutils import Matrix, Vector
from .math_utils import get_cross_section_frame as math_get_cross_section_frame, safe_normalized as math_safe_normalized
from .frames import _transport_cross_section_normal, _minimal_twist_frames_from_tangents, _endpoint_driven_frames

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
        if now - _ROLL_DIAGNOSTIC_ACTIVITY.get(key, 0.0) <= 0.75:
            results.extend(values)
    return results


def _frame_roll_angle(tangent, normal):
    reference_normal, reference_binormal = math_get_cross_section_frame(tangent)
    return math.degrees(math.atan2(
        tangent.dot(reference_normal.cross(normal)),
        max(-1.0, min(1.0, reference_normal.dot(normal))),
    ))


def _write_roll_diagnostic(curve_obj, spline_index, ring_specs, frames, is_cyclic):
    if is_cyclic or len(frames) < 2:
        return
    from .edit_utils import get_curve_point_by_global_index
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
