import math
from mathutils import Matrix, Vector
from .math_utils import get_cross_section_frame, safe_normalized


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


def _frame_roll_angle(tangent, normal):
    reference_normal, reference_binormal = get_cross_section_frame(tangent)
    return math.degrees(math.atan2(
        tangent.dot(reference_normal.cross(normal)),
        max(-1.0, min(1.0, reference_normal.dot(normal))),
    ))


def make_ring_from_frame(center, normal, binormal, interp_offsets):
    verts = []
    for rx, ry in interp_offsets:
        point = center + normal * rx + binormal * ry
        verts.append(point)
    return verts


def build_minimal_twist_rings(ring_specs, is_cyclic=False, start_normal=None, curve_obj=None, spline_index=0, roll_mode='START_FIXED'):
    if not ring_specs:
        return []
    rings = []
    frames = _endpoint_driven_frames(
        [center for center, _raw_tangent, _offsets in ring_specs],
        [raw_tangent for _center, raw_tangent, _offsets in ring_specs],
        is_cyclic, start_normal, 'START_FIXED',
    )
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


def smooth_ring_offsets(ring_specs, iterations=2, factor=0.5, is_cyclic=False):
    if len(ring_specs) < 3:
        return ring_specs
    smoothed = list(ring_specs)
    for _ in range(max(1, iterations)):
        next_specs = list(smoothed)
        start = 0 if is_cyclic else 1
        end = len(smoothed) if is_cyclic else len(smoothed) - 1
        for i in range(start, end):
            prev_spec = smoothed[(i - 1) % len(smoothed)]
            center, tangent, offsets = smoothed[i]
            next_spec = smoothed[(i + 1) % len(smoothed)]
            prev_offsets = prev_spec[2]
            next_offsets = next_spec[2]
            if not offsets or not prev_offsets or not next_offsets:
                continue
            count = min(len(offsets), len(prev_offsets), len(next_offsets))
            new_offsets = []
            for j in range(count):
                ox, oy = offsets[j]
                px, py = prev_offsets[j]
                nx, ny = next_offsets[j]
                avg_x = (px + nx) * 0.5
                avg_y = (py + ny) * 0.5
                new_offsets.append((ox * (1.0 - factor) + avg_x * factor, oy * (1.0 - factor) + avg_y * factor))
            next_specs[i] = (center, tangent, new_offsets)
        smoothed = next_specs
    return smoothed
