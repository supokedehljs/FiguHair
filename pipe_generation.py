import math
from mathutils import Vector
from .curve_data import get_curve_points_data, is_curve_edit_mode
from .frames import build_minimal_twist_rings, smooth_ring_offsets
from .ghost import update_all_ghost_vertices
from .math_utils import catmull_rom_vector, catmull_rom_tangent_vector, safe_normalized
from .sampling import evaluate_bezier_segment, evaluate_bezier_tangent, distribute_steps_by_lengths, invert_bezier_arc_length
from .transition import get_effective_point_setting, get_point_setting, interpolate_cross_sections_smooth, update_transition_point_values


def _get_start_roll_normal(curve_obj, start_tangent):
    from .frames import _get_start_roll_normal as _fn
    try:
        return _fn(curve_obj, start_tangent)
    except Exception:
        from .math_utils import get_cross_section_frame
        n, _ = get_cross_section_frame(start_tangent)
        return n


def _estimate_avg_radius(point_setting, point_dict, default_radius):
    try:
        verts = point_setting.cross_section_verts
        if verts and len(verts) > 0:
            scale = float(getattr(point_setting, 'scale', 1.0))
            curve_radius = float(point_dict.get('radius', 1.0)) if isinstance(point_dict, dict) else 1.0
            total = 0.0
            for v in verts:
                total += math.hypot(float(v.offset_x), float(v.offset_y))
            avg = total / max(1, len(verts))
            if avg > 1e-6:
                return max(1e-4, avg * scale * curve_radius)
    except Exception:
        pass
    try:
        return max(1e-4, float(default_radius) * float(getattr(point_setting, 'scale', 1.0)))
    except Exception:
        return max(1e-4, float(default_radius) if default_radius else 0.05)


def _adaptive_steps_for_segment(seg_length, r0, r1, segments, max_steps):
    avg_radius = max(1e-4, (r0 + r1) * 0.5)
    seg_circum = max(1e-4, 2.0 * math.pi * avg_radius)
    circum_edge = seg_circum / max(3, segments)
    # 仅在用户显式开启自适应时调用：目标纵向边长 ≈ 周向边长 * 1.15
    target_longitudinal = max(circum_edge * 1.15, avg_radius * 1.8, 1e-4)
    steps = int(math.ceil(seg_length / target_longitudinal))
    steps = max(1, min(int(max_steps), steps))
    return steps


def generate_pipe_mesh(curve_obj, settings):
    update_transition_point_values(curve_obj, settings)
    update_all_ghost_vertices(settings)
    splines_data = get_curve_points_data(curve_obj)
    if not splines_data:
        return None, None

    all_verts = []
    all_faces = []
    vert_offset = 0
    point_settings = settings.point_settings
    global_point_idx = 0

    # 已简化：固定 1点=1环，忽略旧的 pipe_resolution/adaptive 属性（保留兼容但不再生效）
    adaptive_enabled = False
    adaptive_max = 4
    resolution = 0

    for spline_index, spline_data in enumerate(splines_data):
        points = spline_data['points']
        resolution = 0  # 固定 1点=1环，已隐藏面板选项
        is_cyclic = spline_data['cyclic']
        num_points = len(points)
        if num_points < 2:
            global_point_idx += num_points
            continue

        ring_specs = []
        if spline_data['type'] == 'BEZIER':
            seg_count = num_points if is_cyclic else num_points - 1
            ARC_SUBDIV = 8
            seg_lengths = []
            for seg_idx in range(seg_count):
                idx0 = seg_idx
                idx1 = (seg_idx + 1) % num_points
                p0_ = points[idx0]['co']
                h0r_ = points[idx0]['handle_right']
                h1l_ = points[idx1]['handle_left']
                p1_ = points[idx1]['co']
                length = 0.0
                prev = evaluate_bezier_segment(p0_, h0r_, h1l_, p1_, 0.0)
                for k in range(1, ARC_SUBDIV + 1):
                    cur = evaluate_bezier_segment(p0_, h0r_, h1l_, p1_, k / ARC_SUBDIV)
                    length += (cur - prev).length
                    prev = cur
                seg_lengths.append(max(length, 1e-8))

            if resolution == 0 and adaptive_enabled:
                seg_steps = []
                for seg_idx in range(seg_count):
                    idx0 = seg_idx
                    idx1 = (seg_idx + 1) % num_points
                    ps0 = get_effective_point_setting(point_settings, global_point_idx + idx0, settings)
                    ps1 = get_effective_point_setting(point_settings, global_point_idx + idx1, settings)
                    segments = max(len(ps0.cross_section_verts), len(ps1.cross_section_verts), int(getattr(settings, 'default_segments', 8)))
                    segments = max(3, segments)
                    r0 = _estimate_avg_radius(ps0, points[idx0], settings.default_radius)
                    r1 = _estimate_avg_radius(ps1, points[idx1], settings.default_radius)
                    steps = _adaptive_steps_for_segment(seg_lengths[seg_idx], r0, r1, segments, adaptive_max)
                    seg_steps.append(steps)
            elif resolution == 0:
                # 严格 1点=1环：每段恰好1个步进，末段由后处理补终点，总环数 == 控制点数
                seg_steps = [1] * seg_count
            else:
                total_steps = seg_count * max(1, resolution + 1)
                seg_steps = distribute_steps_by_lengths(seg_lengths, total_steps)

            for seg_idx in range(seg_count):
                idx0 = seg_idx
                idx1 = (seg_idx + 1) % num_points
                p0 = points[idx0]['co']
                h0r = points[idx0]['handle_right']
                h1l = points[idx1]['handle_left']
                p1 = points[idx1]['co']
                global_idx0 = global_point_idx + idx0
                global_idx1 = global_point_idx + idx1
                ps0 = get_effective_point_setting(point_settings, global_idx0, settings)
                ps1 = get_effective_point_setting(point_settings, global_idx1, settings)
                idx_prev = (idx0 - 1) % num_points if is_cyclic or idx0 > 0 else idx0
                idx_next = (idx1 + 1) % num_points if is_cyclic or idx1 < num_points - 1 else idx1
                ps_prev = get_effective_point_setting(point_settings, global_point_idx + idx_prev, settings)
                ps_next = get_effective_point_setting(point_settings, global_point_idx + idx_next, settings)
                steps = seg_steps[seg_idx]
                step_count = steps if (is_cyclic or seg_idx < seg_count - 1) else steps + 1
                segment_length = seg_lengths[seg_idx]
                for step in range(step_count):
                    if not is_cyclic and seg_idx == seg_count - 1 and step == step_count - 1:
                        distance_t = 1.0
                        shape_t = 1.0
                    else:
                        distance_t = step / steps
                        shape_t = invert_bezier_arc_length(p0, h0r, h1l, p1, segment_length * distance_t, segment_length)
                    pos = evaluate_bezier_segment(p0, h0r, h1l, p1, shape_t)
                    tan = evaluate_bezier_tangent(p0, h0r, h1l, p1, shape_t)
                    interp = interpolate_cross_sections_smooth(
                        ps_prev, ps0, ps1, ps_next, distance_t,
                        points[idx_prev], points[idx0], points[idx1], points[idx_next],
                        settings.transition_mode, settings.transition_strength
                    )
                    ring_specs.append((pos, tan, interp))

        elif spline_data['type'] == 'NURBS':
            seg_count = num_points if is_cyclic else num_points - 1
            seg_lengths = []
            for seg_idx in range(seg_count):
                idx0 = seg_idx
                idx1 = (seg_idx + 1) % num_points
                seg_lengths.append(max((points[idx1]['co'] - points[idx0]['co']).length, 1e-8))

            if resolution == 0 and adaptive_enabled:
                seg_steps = []
                for seg_idx in range(seg_count):
                    idx0 = seg_idx
                    idx1 = (seg_idx + 1) % num_points
                    ps0 = get_effective_point_setting(point_settings, global_point_idx + idx0, settings)
                    ps1 = get_effective_point_setting(point_settings, global_point_idx + idx1, settings)
                    segments = max(len(ps0.cross_section_verts), len(ps1.cross_section_verts), int(getattr(settings, 'default_segments', 8)))
                    segments = max(3, segments)
                    r0 = _estimate_avg_radius(ps0, points[idx0], settings.default_radius)
                    r1 = _estimate_avg_radius(ps1, points[idx1], settings.default_radius)
                    seg_steps.append(_adaptive_steps_for_segment(seg_lengths[seg_idx], r0, r1, segments, adaptive_max))
            elif resolution == 0:
                seg_steps = [1] * seg_count
            else:
                total_steps = seg_count * max(1, resolution + 1)
                seg_steps = distribute_steps_by_lengths(seg_lengths, total_steps)

            for seg_idx in range(seg_count):
                idx0 = seg_idx
                idx1 = (seg_idx + 1) % num_points
                idx_prev = (idx0 - 1) % num_points if is_cyclic or idx0 > 0 else idx0
                idx_next = (idx1 + 1) % num_points if is_cyclic or idx1 < num_points - 1 else idx1
                p_prev = points[idx_prev]['co']
                p0 = points[idx0]['co']
                p1 = points[idx1]['co']
                p_next = points[idx_next]['co']
                ps_prev = get_effective_point_setting(point_settings, global_point_idx + idx_prev, settings)
                ps0 = get_effective_point_setting(point_settings, global_point_idx + idx0, settings)
                ps1 = get_effective_point_setting(point_settings, global_point_idx + idx1, settings)
                ps_next = get_effective_point_setting(point_settings, global_point_idx + idx_next, settings)
                steps = seg_steps[seg_idx]
                step_count = steps if (is_cyclic or seg_idx < seg_count - 1) else steps + 1
                for step in range(step_count):
                    t = 1.0 if (not is_cyclic and seg_idx == seg_count - 1 and step == step_count - 1) else step / steps
                    pos = catmull_rom_vector(p_prev, p0, p1, p_next, t)
                    tan = safe_normalized(catmull_rom_tangent_vector(p_prev, p0, p1, p_next, t), p1 - p0)
                    interp = interpolate_cross_sections_smooth(
                        ps_prev, ps0, ps1, ps_next, t,
                        points[idx_prev], points[idx0], points[idx1], points[idx_next],
                        settings.transition_mode, settings.transition_strength,
                    )
                    ring_specs.append((pos, tan, interp))

        elif spline_data['type'] == 'POLY':
            seg_count = num_points if is_cyclic else num_points - 1
            seg_lengths = []
            for seg_idx in range(seg_count):
                idx0 = seg_idx
                idx1 = (seg_idx + 1) % num_points
                seg_lengths.append(max((points[idx1]['co'] - points[idx0]['co']).length, 1e-8))

            if resolution == 0 and adaptive_enabled:
                seg_steps = []
                for seg_idx in range(seg_count):
                    idx0 = seg_idx
                    idx1 = (seg_idx + 1) % num_points
                    ps0 = get_point_setting(point_settings, global_point_idx + idx0, settings)
                    ps1 = get_point_setting(point_settings, global_point_idx + idx1, settings)
                    segments = max(len(ps0.cross_section_verts), len(ps1.cross_section_verts), int(getattr(settings, 'default_segments', 8)))
                    segments = max(3, segments)
                    r0 = _estimate_avg_radius(ps0, points[idx0], settings.default_radius)
                    r1 = _estimate_avg_radius(ps1, points[idx1], settings.default_radius)
                    seg_steps.append(_adaptive_steps_for_segment(seg_lengths[seg_idx], r0, r1, segments, adaptive_max))
            elif resolution == 0:
                seg_steps = [1] * seg_count
            else:
                total_steps = seg_count * max(1, resolution + 1)
                seg_steps = distribute_steps_by_lengths(seg_lengths, total_steps)

            for seg_idx in range(seg_count):
                idx0 = seg_idx
                idx1 = (seg_idx + 1) % num_points
                p0 = points[idx0]['co']
                p1 = points[idx1]['co']
                ps0 = get_point_setting(point_settings, global_point_idx + idx0, settings)
                ps1 = get_point_setting(point_settings, global_point_idx + idx1, settings)
                idx_prev = (idx0 - 1) % num_points if is_cyclic or idx0 > 0 else idx0
                idx_next = (idx1 + 1) % num_points if is_cyclic or idx1 < num_points - 1 else idx1
                ps_prev = get_point_setting(point_settings, global_point_idx + idx_prev, settings)
                ps_next = get_point_setting(point_settings, global_point_idx + idx_next, settings)
                steps = seg_steps[seg_idx]
                step_count = steps if (is_cyclic or seg_idx < seg_count - 1) else steps + 1
                for step in range(step_count):
                    t = 1.0 if (not is_cyclic and seg_idx == seg_count - 1 and step == step_count - 1) else step / steps
                    pos = p0.lerp(p1, t)
                    tan = safe_normalized(p1 - p0)
                    interp = interpolate_cross_sections_smooth(
                        ps_prev, ps0, ps1, ps_next, t,
                        points[idx_prev], points[idx0], points[idx1], points[idx_next],
                        settings.transition_mode, settings.transition_strength
                    )
                    ring_specs.append((pos, tan, interp))

        if settings.strong_smoothing:
            ring_specs = smooth_ring_offsets(
                ring_specs,
                settings.strong_smoothing_iterations,
                0.45,
                is_cyclic,
            )

        start_normal = None
        if not is_cyclic and ring_specs:
            start_normal = _get_start_roll_normal(curve_obj, safe_normalized(ring_specs[0][1]))
        rings = build_minimal_twist_rings(
            ring_specs, is_cyclic, start_normal, curve_obj, spline_index,
            'START_FIXED',
        )
        global_point_idx += num_points
        if not rings:
            continue

        segments = len(rings[0])
        for ring in rings:
            all_verts.extend(ring)
        num_rings = len(rings)
        ring_count = num_rings if is_cyclic else num_rings - 1
        for i in range(ring_count):
            i_next = (i + 1) % num_rings
            bridge_offset = 0
            target_idx = global_point_idx - num_points + min(i + 1, num_points - 1)
            if 0 <= target_idx < len(point_settings):
                bridge_offset = int(getattr(point_settings[target_idx], 'bridge_offset', 0))
            for j in range(segments):
                j_next = (j + 1) % segments
                v0 = vert_offset + i * segments + j
                v1 = vert_offset + i * segments + j_next
                v2 = vert_offset + i_next * segments + ((j_next + bridge_offset) % segments)
                v3 = vert_offset + i_next * segments + ((j + bridge_offset) % segments)
                all_faces.append((v0, v1, v2, v3))
        if settings.cap_ends and not is_cyclic and num_rings > 0:
            cap_s = list(range(vert_offset, vert_offset + segments))
            all_faces.append(tuple(reversed(cap_s)))
        vert_offset += num_rings * segments

    return all_verts, all_faces
