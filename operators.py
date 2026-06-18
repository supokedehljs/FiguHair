import bpy
import math
from mathutils import Vector, Matrix
from bpy.props import IntProperty, FloatProperty


def get_curve_points_data(curve_obj):
    """Extract control points from a curve object"""
    splines = curve_obj.data.splines
    all_splines_data = []

    for spline in splines:
        points_data = []
        if spline.type == 'BEZIER':
            for bp in spline.bezier_points:
                points_data.append({
                    'co': curve_obj.matrix_world @ bp.co,
                    'handle_left': curve_obj.matrix_world @ bp.handle_left,
                    'handle_right': curve_obj.matrix_world @ bp.handle_right,
                    'radius': bp.radius,
                    'tilt': bp.tilt,
                })
        elif spline.type in ('POLY', 'NURBS'):
            for p in spline.points:
                co = Vector(p.co[:3])
                points_data.append({
                    'co': curve_obj.matrix_world @ co,
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
    u = 1.0 - t
    return (u**3)*p0 + 3*(u**2)*t*h0_right + 3*u*(t**2)*h1_left + (t**3)*p1


def evaluate_bezier_tangent(p0, h0_right, h1_left, p1, t):
    u = 1.0 - t
    tangent = 3*(u**2)*(h0_right-p0) + 6*u*t*(h1_left-h0_right) + 3*(t**2)*(p1-h1_left)
    if tangent.length < 1e-8:
        tangent = p1 - p0
    return tangent.normalized()


def make_nurbs_knot_vector(num_points, degree, is_cyclic, use_endpoint):
    if is_cyclic:
        return [float(i) for i in range(num_points + 2 * degree + 1)]

    knot_count = num_points + degree + 1
    if use_endpoint:
        interior_count = knot_count - 2 * (degree + 1)
        knots = [0.0] * (degree + 1)
        if interior_count > 0:
            for i in range(1, interior_count + 1):
                knots.append(float(i) / float(interior_count + 1))
        knots.extend([1.0] * (degree + 1))
        return knots

    return [float(i) for i in range(knot_count)]


def find_nurbs_span(num_eval_points, degree, u, knots):
    last_span = num_eval_points - 1
    if u >= knots[last_span + 1]:
        return last_span
    if u <= knots[degree]:
        return degree

    low = degree
    high = last_span + 1
    mid = (low + high) // 2
    while u < knots[mid] or u >= knots[mid + 1]:
        if u < knots[mid]:
            high = mid
        else:
            low = mid
        mid = (low + high) // 2
    return mid


def nurbs_basis_values(span, degree, u, knots):
    values = [0.0] * (degree + 1)
    left = [0.0] * (degree + 1)
    right = [0.0] * (degree + 1)
    values[0] = 1.0

    for j in range(1, degree + 1):
        left[j] = u - knots[span + 1 - j]
        right[j] = knots[span + j] - u
        saved = 0.0
        for r in range(j):
            denominator = right[r + 1] + left[j - r]
            temp = values[r] / denominator if abs(denominator) > 1e-8 else 0.0
            values[r] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        values[j] = saved

    return values


def get_nurbs_weighted_controls(points, degree, u, knots, is_cyclic):
    eval_points = points + points[:degree] if is_cyclic else points
    span = find_nurbs_span(len(eval_points), degree, u, knots)
    basis_values = nurbs_basis_values(span, degree, u, knots)

    weighted = []
    total = 0.0
    point_count = len(points)
    for local_idx, basis in enumerate(basis_values):
        eval_idx = span - degree + local_idx
        if eval_idx < 0 or eval_idx >= len(eval_points):
            continue
        control_idx = eval_idx % point_count
        point = eval_points[eval_idx]
        weight = basis * point.get('weight', 1.0)
        if weight > 1e-8:
            weighted.append((control_idx, weight))
            total += weight

    return weighted, total


def evaluate_nurbs_from_weighted(points, weighted, total):
    if total < 1e-8 or not weighted:
        return points[0]['co'].copy()

    numerator = Vector((0, 0, 0))
    for idx, weight in weighted:
        numerator += points[idx]['co'] * weight
    return numerator / total


def get_nurbs_domain(num_points, degree, knots, is_cyclic):
    if is_cyclic:
        return knots[degree], knots[num_points]
    return knots[degree], knots[num_points]


def interpolate_nurbs_cross_sections(point_settings, points, weighted, total, settings, global_point_idx):
    if total < 1e-8 or not weighted:
        return []

    max_count = 0
    cached_offsets = []
    for idx, weight in weighted:
        ps = get_point_setting(point_settings, global_point_idx + idx, settings)
        local_offsets = interpolate_cross_sections(ps, ps, 0.0, points[idx], points[idx])
        if local_offsets:
            cached_offsets.append((local_offsets, weight))
            max_count = max(max_count, len(local_offsets))
    if max_count == 0:
        return []

    accum = [(0.0, 0.0) for _ in range(max_count)]
    for local_offsets, weight in cached_offsets:
        normalized_weight = weight / total
        for i in range(max_count):
            ox, oy = local_offsets[i % len(local_offsets)]
            ax, ay = accum[i]
            accum[i] = (ax + ox * normalized_weight, ay + oy * normalized_weight)

    return accum


def safe_normalized(vector, fallback=None):
    if vector.length >= 1e-8:
        return vector.normalized()
    if fallback is not None and fallback.length >= 1e-8:
        return fallback.normalized()
    return Vector((0, 0, 1))


def average_tangents(prev_tangent, next_tangent):
    prev_dir = safe_normalized(prev_tangent)
    next_dir = safe_normalized(next_tangent, prev_dir)
    averaged = prev_dir + next_dir
    if averaged.length < 1e-8:
        return next_dir
    return averaged.normalized()


def get_bezier_control_tangent(points, idx, is_cyclic):
    num_points = len(points)
    point = points[idx]
    prev_tangent = None
    next_tangent = None

    if is_cyclic or idx > 0:
        prev_tangent = point['co'] - point['handle_left']
        if prev_tangent.length < 1e-8:
            prev_idx = (idx - 1) % num_points
            prev_tangent = point['co'] - points[prev_idx]['co']
    if is_cyclic or idx < num_points - 1:
        next_tangent = point['handle_right'] - point['co']
        if next_tangent.length < 1e-8:
            next_idx = (idx + 1) % num_points
            next_tangent = points[next_idx]['co'] - point['co']

    if prev_tangent is not None and next_tangent is not None:
        return average_tangents(prev_tangent, next_tangent)
    if next_tangent is not None:
        return safe_normalized(next_tangent)
    if prev_tangent is not None:
        return safe_normalized(prev_tangent)
    return Vector((0, 0, 1))


def get_poly_control_tangent(points, idx, is_cyclic):
    num_points = len(points)
    point = points[idx]['co']
    prev_tangent = None
    next_tangent = None

    if is_cyclic or idx > 0:
        prev_idx = (idx - 1) % num_points
        prev_tangent = point - points[prev_idx]['co']
    if is_cyclic or idx < num_points - 1:
        next_idx = (idx + 1) % num_points
        next_tangent = points[next_idx]['co'] - point

    if prev_tangent is not None and next_tangent is not None:
        return average_tangents(prev_tangent, next_tangent)
    if next_tangent is not None:
        return safe_normalized(next_tangent)
    if prev_tangent is not None:
        return safe_normalized(prev_tangent)
    return Vector((0, 0, 1))


def get_cross_section_frame(tangent):
    tangent = safe_normalized(tangent)
    up = Vector((0, 0, 1))
    if abs(tangent.dot(up)) > 0.999:
        up = Vector((1, 0, 0))
    normal = tangent.cross(up).normalized()
    binormal = tangent.cross(normal).normalized()
    return normal, binormal


def interpolate_cross_sections(ps0, ps1, t, point0=None, point1=None):
    """Interpolate cross-section vertex positions between two point settings"""
    verts0 = ps0.cross_section_verts
    verts1 = ps1.cross_section_verts
    n0 = len(verts0)
    n1 = len(verts1)
    if n0 == 0 or n1 == 0:
        return []

    num_verts = min(n0, n1)
    curve_radius0 = point0.get('radius', 1.0) if point0 else 1.0
    curve_radius1 = point1.get('radius', 1.0) if point1 else 1.0
    curve_tilt0 = point0.get('tilt', 0.0) if point0 else 0.0
    curve_tilt1 = point1.get('tilt', 0.0) if point1 else 0.0
    scale0 = ps0.scale * curve_radius0
    scale1 = ps1.scale * curve_radius1
    rot0 = math.radians(ps0.rotation) + curve_tilt0
    rot1 = math.radians(ps1.rotation) + curve_tilt1

    interp_rot = rot0 * (1.0 - t) + rot1 * t
    cos_r = math.cos(interp_rot)
    sin_r = math.sin(interp_rot)

    result = []
    for i in range(num_verts):
        x0 = verts0[i % n0].offset_x * scale0
        y0 = verts0[i % n0].offset_y * scale0
        x1 = verts1[i % n1].offset_x * scale1
        y1 = verts1[i % n1].offset_y * scale1
        lx = x0 * (1.0 - t) + x1 * t
        ly = y0 * (1.0 - t) + y1 * t
        rx = lx * cos_r - ly * sin_r
        ry = lx * sin_r + ly * cos_r
        result.append((rx, ry))
    return result


def make_ring_from_interpolated(center, tangent, interp_offsets):
    normal, binormal = get_cross_section_frame(tangent)
    verts = []
    for rx, ry in interp_offsets:
        point = center + normal * rx + binormal * ry
        verts.append(point)
    return verts


def get_point_setting(point_settings, idx, settings):
    if idx < len(point_settings):
        return point_settings[idx]

    class DefaultPointSetting:
        def __init__(self, s):
            self.rotation = 0.0
            self.scale = 1.0
            self.cross_section_verts = self._make_circle(s.default_radius, s.default_segments)
        def _make_circle(self, radius, segments):
            class FakeVert:
                def __init__(self, x, y):
                    self.offset_x = x
                    self.offset_y = y
            verts = []
            for i in range(segments):
                angle = 2.0 * math.pi * i / segments
                verts.append(FakeVert(math.cos(angle)*radius, math.sin(angle)*radius))
            return verts
    return DefaultPointSetting(settings)


def init_cross_section_circle(point_setting, radius, segments):
    point_setting.cross_section_verts.clear()
    for i in range(segments):
        angle = 2.0 * math.pi * i / segments
        v = point_setting.cross_section_verts.add()
        v.offset_x = math.cos(angle) * radius
        v.offset_y = math.sin(angle) * radius


def generate_pipe_mesh(curve_obj, settings):
    splines_data = get_curve_points_data(curve_obj)
    if not splines_data:
        return None, None

    all_verts = []
    all_faces = []
    vert_offset = 0
    point_settings = settings.point_settings
    global_point_idx = 0

    for spline_data in splines_data:
        points = spline_data['points']
        resolution = spline_data['resolution']
        is_cyclic = spline_data['cyclic']
        num_points = len(points)
        if num_points < 2:
            global_point_idx += num_points
            continue

        rings = []
        if spline_data['type'] == 'BEZIER':
            seg_count = num_points if is_cyclic else num_points - 1
            for seg_idx in range(seg_count):
                idx0 = seg_idx
                idx1 = (seg_idx + 1) % num_points
                p0 = points[idx0]['co']
                h0r = points[idx0]['handle_right']
                h1l = points[idx1]['handle_left']
                p1 = points[idx1]['co']
                ps0 = get_point_setting(point_settings, global_point_idx + idx0, settings)
                ps1 = get_point_setting(point_settings, global_point_idx + idx1, settings)
                steps = max(1, resolution)
                end_inc = 1 if (seg_idx == seg_count - 1 and not is_cyclic) else 0
                for step in range(steps + end_inc):
                    t = step / steps
                    pos = evaluate_bezier_segment(p0, h0r, h1l, p1, t)
                    tan0 = get_bezier_control_tangent(points, idx0, is_cyclic)
                    tan1 = get_bezier_control_tangent(points, idx1, is_cyclic)
                    tan = safe_normalized(tan0.lerp(tan1, t), evaluate_bezier_tangent(p0, h0r, h1l, p1, t))
                    interp = interpolate_cross_sections(ps0, ps1, t, points[idx0], points[idx1])
                    if interp:
                        ring = make_ring_from_interpolated(pos, tan, interp)
                    else:
                        ring = [pos]
                    rings.append(ring)
        elif spline_data['type'] == 'NURBS':
            order = max(2, min(spline_data.get('order_u', 4), num_points))
            degree = order - 1
            use_endpoint = spline_data.get('use_endpoint_u', False)
            knots = make_nurbs_knot_vector(num_points, degree, is_cyclic, use_endpoint)
            u_start, u_end = get_nurbs_domain(num_points, degree, knots, is_cyclic)
            sample_count = max(2, (num_points if is_cyclic else num_points - 1) * max(4, resolution * 2))
            ring_count = sample_count if is_cyclic else sample_count + 1
            u_range = u_end - u_start
            centers = []
            interp_offsets = []

            for sample_idx in range(ring_count):
                if is_cyclic:
                    t = sample_idx / ring_count
                else:
                    t = sample_idx / (ring_count - 1)
                u = u_start + u_range * t
                if is_cyclic and sample_idx == ring_count - 1:
                    u = u_end - 1e-8

                weighted, total = get_nurbs_weighted_controls(points, degree, u, knots, is_cyclic)
                centers.append(evaluate_nurbs_from_weighted(points, weighted, total))
                interp_offsets.append(interpolate_nurbs_cross_sections(
                    point_settings, points, weighted, total, settings, global_point_idx
                ))

            for sample_idx, pos in enumerate(centers):
                if is_cyclic:
                    prev_pos = centers[(sample_idx - 1) % ring_count]
                    next_pos = centers[(sample_idx + 1) % ring_count]
                else:
                    prev_pos = centers[max(0, sample_idx - 1)]
                    next_pos = centers[min(ring_count - 1, sample_idx + 1)]
                tan = safe_normalized(next_pos - prev_pos)
                interp = interp_offsets[sample_idx]
                if interp:
                    ring = make_ring_from_interpolated(pos, tan, interp)
                else:
                    ring = [pos]
                rings.append(ring)
        elif spline_data['type'] == 'POLY':
            seg_count = num_points if is_cyclic else num_points - 1
            for seg_idx in range(seg_count):
                idx0 = seg_idx
                idx1 = (seg_idx + 1) % num_points
                p0 = points[idx0]['co']
                p1 = points[idx1]['co']
                ps0 = get_point_setting(point_settings, global_point_idx + idx0, settings)
                ps1 = get_point_setting(point_settings, global_point_idx + idx1, settings)
                steps = max(1, resolution)
                end_inc = 1 if (seg_idx == seg_count - 1 and not is_cyclic) else 0
                for step in range(steps + end_inc):
                    t = step / steps
                    pos = p0.lerp(p1, t)
                    tan0 = get_poly_control_tangent(points, idx0, is_cyclic)
                    tan1 = get_poly_control_tangent(points, idx1, is_cyclic)
                    tan = safe_normalized(tan0.lerp(tan1, t), p1 - p0)
                    interp = interpolate_cross_sections(ps0, ps1, t, points[idx0], points[idx1])
                    if interp:
                        ring = make_ring_from_interpolated(pos, tan, interp)
                    else:
                        ring = [pos]
                    rings.append(ring)

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
            for j in range(segments):
                j_next = (j + 1) % segments
                v0 = vert_offset + i * segments + j
                v1 = vert_offset + i * segments + j_next
                v2 = vert_offset + i_next * segments + j_next
                v3 = vert_offset + i_next * segments + j
                all_faces.append((v0, v1, v2, v3))
        if settings.cap_ends and not is_cyclic and num_rings > 0:
            cap_s = list(range(vert_offset, vert_offset + segments))
            cap_e = list(range(vert_offset + (num_rings-1)*segments, vert_offset + num_rings*segments))
            all_faces.append(tuple(reversed(cap_s)))
            all_faces.append(tuple(cap_e))
        vert_offset += num_rings * segments

    return all_verts, all_faces


def sync_point_settings(curve_obj):
    settings = curve_obj.hair_pipe_settings
    total_points = 0
    for spline in curve_obj.data.splines:
        if spline.type == 'BEZIER':
            total_points += len(spline.bezier_points)
        else:
            total_points += len(spline.points)
    current = len(settings.point_settings)
    if current < total_points:
        for _ in range(total_points - current):
            ps = settings.point_settings.add()
            ps.scale = 1.0
            ps.rotation = 0.0
            init_cross_section_circle(ps, settings.default_radius, settings.default_segments)
    elif current > total_points:
        for _ in range(current - total_points):
            settings.point_settings.remove(len(settings.point_settings) - 1)

    if total_points > 0 and settings.active_point_index >= total_points:
        settings.active_point_index = total_points - 1


def is_curve_edit_mode(curve_obj):
    return getattr(curve_obj, 'mode', '') in {'EDIT', 'EDIT_CURVE'}


def get_selected_curve_point_index(curve_obj):
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


def sync_active_point_from_selection(curve_obj):
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


def get_curve_point_by_global_index(curve_obj, target_index):
    if curve_obj is None or curve_obj.type != 'CURVE':
        return None

    global_point_idx = 0
    for spline in curve_obj.data.splines:
        points = spline.bezier_points if spline.type == 'BEZIER' else spline.points
        for point in points:
            if global_point_idx == target_index:
                return point
            global_point_idx += 1
    return None


class HAIRPIPE_OT_generate_pipe(bpy.types.Operator):
    """Generate pipe mesh from curve with per-point custom cross-sections"""
    bl_idname = "hair_pipe.generate_pipe"
    bl_label = "Generate Hair Pipe"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'CURVE'

    def execute(self, context):
        curve_obj = context.active_object
        settings = curve_obj.hair_pipe_settings
        sync_point_settings(curve_obj)
        verts, faces = generate_pipe_mesh(curve_obj, settings)
        if verts is None:
            self.report({'ERROR'}, "Could not generate pipe from curve")
            return {'CANCELLED'}
        mesh_name = curve_obj.name + "_FiguHair"
        mesh = bpy.data.meshes.new(mesh_name)
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        existing_obj = bpy.data.objects.get(mesh_name)
        if existing_obj:
            old_mesh = existing_obj.data
            existing_obj.data = mesh
            mesh.name = mesh_name
            if old_mesh and old_mesh.users == 0:
                bpy.data.meshes.remove(old_mesh)
            pipe_obj = existing_obj
        else:
            pipe_obj = bpy.data.objects.new(mesh_name, mesh)
            context.collection.objects.link(pipe_obj)
        if settings.smooth_shading:
            for poly in mesh.polygons:
                poly.use_smooth = True
        pipe_obj.matrix_world = Matrix.Identity(4)
        self.report({'INFO'}, f"Generated pipe with {len(verts)} vertices")
        return {'FINISHED'}


class HAIRPIPE_OT_sync_points(bpy.types.Operator):
    """Sync point settings with curve control points"""
    bl_idname = "hair_pipe.sync_points"
    bl_label = "Sync Point Settings"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'CURVE'

    def execute(self, context):
        sync_point_settings(context.active_object)
        self.report({'INFO'}, "Point settings synced")
        return {'FINISHED'}


class HAIRPIPE_OT_reset_cross_section(bpy.types.Operator):
    """Reset active point's cross-section to a circle"""
    bl_idname = "hair_pipe.reset_cross_section"
    bl_label = "Reset to Circle"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE':
            return False
        s = obj.hair_pipe_settings
        return s.active_point_index < len(s.point_settings)

    def execute(self, context):
        settings = context.active_object.hair_pipe_settings
        ps = settings.point_settings[settings.active_point_index]
        init_cross_section_circle(ps, settings.default_radius, settings.default_segments)
        ps.scale = 1.0
        ps.rotation = 0.0
        return {'FINISHED'}


class HAIRPIPE_OT_reset_all_cross_sections(bpy.types.Operator):
    """Reset ALL points' cross-sections to circles"""
    bl_idname = "hair_pipe.reset_all_cross_sections"
    bl_label = "Reset All to Circle"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'CURVE'

    def execute(self, context):
        settings = context.active_object.hair_pipe_settings
        for ps in settings.point_settings:
            init_cross_section_circle(ps, settings.default_radius, settings.default_segments)
            ps.scale = 1.0
            ps.rotation = 0.0
        return {'FINISHED'}


class HAIRPIPE_OT_taper_linear(bpy.types.Operator):
    """Apply linear taper from root to tip"""
    bl_idname = "hair_pipe.taper_linear"
    bl_label = "Linear Taper"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'CURVE'

    def execute(self, context):
        curve_obj = context.active_object
        settings = curve_obj.hair_pipe_settings
        sync_point_settings(curve_obj)
        num = len(settings.point_settings)
        if num < 2:
            return {'CANCELLED'}
        for i, ps in enumerate(settings.point_settings):
            ps.scale = 1.0 - (i / (num - 1)) * 0.95
        self.report({'INFO'}, "Applied linear taper")
        return {'FINISHED'}


class HAIRPIPE_OT_add_cs_vert(bpy.types.Operator):
    """Add a vertex to the active point's cross-section"""
    bl_idname = "hair_pipe.add_cs_vert"
    bl_label = "Add Vertex"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE':
            return False
        s = obj.hair_pipe_settings
        return s.active_point_index < len(s.point_settings)

    def execute(self, context):
        settings = context.active_object.hair_pipe_settings
        ps = settings.point_settings[settings.active_point_index]
        csv = ps.cross_section_verts
        n = len(csv)
        if n < 2:
            v = csv.add()
            v.offset_x = settings.default_radius
            v.offset_y = 0.0
        else:
            idx = ps.active_vert_index
            idx_next = (idx + 1) % n
            v = csv.add()
            v.offset_x = (csv[idx].offset_x + csv[idx_next].offset_x) * 0.5
            v.offset_y = (csv[idx].offset_y + csv[idx_next].offset_y) * 0.5
            target = idx + 1
            for i in range(len(csv) - 1, target, -1):
                csv.move(i, i - 1)
            ps.active_vert_index = target
        return {'FINISHED'}


class HAIRPIPE_OT_remove_cs_vert(bpy.types.Operator):
    """Remove the active vertex from the cross-section"""
    bl_idname = "hair_pipe.remove_cs_vert"
    bl_label = "Remove Vertex"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE':
            return False
        s = obj.hair_pipe_settings
        if s.active_point_index >= len(s.point_settings):
            return False
        ps = s.point_settings[s.active_point_index]
        return len(ps.cross_section_verts) > 3

    def execute(self, context):
        settings = context.active_object.hair_pipe_settings
        ps = settings.point_settings[settings.active_point_index]
        ps.cross_section_verts.remove(ps.active_vert_index)
        if ps.active_vert_index >= len(ps.cross_section_verts):
            ps.active_vert_index = len(ps.cross_section_verts) - 1
        return {'FINISHED'}


class HAIRPIPE_OT_select_point(bpy.types.Operator):
    """Select a control point for editing"""
    bl_idname = "hair_pipe.select_point"
    bl_label = "Select Point"
    point_index: IntProperty()

    def execute(self, context):
        context.active_object.hair_pipe_settings.active_point_index = self.point_index
        return {'FINISHED'}


class HAIRPIPE_OT_copy_cs_to_all(bpy.types.Operator):
    """Copy active point's cross-section to all other points"""
    bl_idname = "hair_pipe.copy_cs_to_all"
    bl_label = "Copy to All Points"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE':
            return False
        s = obj.hair_pipe_settings
        return s.active_point_index < len(s.point_settings)

    def execute(self, context):
        settings = context.active_object.hair_pipe_settings
        src = settings.point_settings[settings.active_point_index]
        for i, ps in enumerate(settings.point_settings):
            if i == settings.active_point_index:
                continue
            ps.cross_section_verts.clear()
            for sv in src.cross_section_verts:
                v = ps.cross_section_verts.add()
                v.offset_x = sv.offset_x
                v.offset_y = sv.offset_y
        self.report({'INFO'}, "Cross-section copied to all points")
        return {'FINISHED'}


classes = (
    HAIRPIPE_OT_generate_pipe,
    HAIRPIPE_OT_sync_points,
    HAIRPIPE_OT_reset_cross_section,
    HAIRPIPE_OT_reset_all_cross_sections,
    HAIRPIPE_OT_taper_linear,
    HAIRPIPE_OT_add_cs_vert,
    HAIRPIPE_OT_remove_cs_vert,
    HAIRPIPE_OT_select_point,
    HAIRPIPE_OT_copy_cs_to_all,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
