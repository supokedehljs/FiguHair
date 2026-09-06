"""Cross-curve control-point bindings for FiguHair."""
import json
import math
import bpy
from mathutils import Vector
from .math_utils import get_cross_section_frame, safe_normalized
from .hair_lifecycle import get_pipe_object_for_curve

_BINDING_KEY = "hair_pipe_cross_curve_binding"


def _curve_points(curve_obj):
    points = []
    for spline in curve_obj.data.splines:
        source = spline.bezier_points if spline.type == 'BEZIER' else spline.points
        points.extend(source)
    return points


def _point_local_co(point):
    co = point.co
    return Vector((co.x, co.y, co.z))


def _set_point_local_co(point, value):
    if hasattr(point.co, 'w'):
        point.co = (value.x, value.y, value.z, point.co.w)
    else:
        point.co = value


def _point_setting(curve_obj, index):
    settings = getattr(curve_obj, 'hair_pipe_settings', None)
    if settings is None or not (0 <= index < len(settings.point_settings)):
        return None
    return settings.point_settings[index]


def _get_bindings(slave_obj):
    """Load all bindings; transparently upgrade the old single-binding format."""
    raw = slave_obj.get(_BINDING_KEY, "") if slave_obj else ""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if isinstance(data, dict) and isinstance(data.get('bindings'), list):
        return [item for item in data['bindings'] if isinstance(item, dict)]
    # Version 1 stored one binding directly as a dict.
    return [data] if isinstance(data, dict) else []


def get_bound_vertex_world(slave_obj, slave_point_index, slave_vertex_index):
    ps = _point_setting(slave_obj, int(slave_point_index))
    data = _get_binding(slave_obj)
    if ps is None or data is None:
        return None
    source = bpy.data.objects.get(data.get('source_curve', ''))
    if source is None:
        return None
    source_center = _world_point(source, int(data.get('source_point', -1)))
    basis = _stored_binding_plane(data)
    if source_center is None or basis is None or not (0 <= int(slave_vertex_index) < len(ps.cross_section_verts)):
        return None
    _, u, v, _ = basis
    scale = float(ps.scale)
    rotation = math.radians(float(ps.rotation))
    raw_x = float(ps.cross_section_verts[int(slave_vertex_index)].offset_x) * scale
    raw_y = float(ps.cross_section_verts[int(slave_vertex_index)].offset_y) * scale
    cos_r = math.cos(rotation)
    sin_r = math.sin(rotation)
    x = raw_x * cos_r - raw_y * sin_r
    y = raw_x * sin_r + raw_y * cos_r
    return source_center + u * x + v * y


def set_bound_vertex_world(slave_obj, slave_point_index, slave_vertex_index, world_position):
    ps = _point_setting(slave_obj, int(slave_point_index))
    data = _get_binding(slave_obj)
    if ps is None or data is None:
        return False
    source = bpy.data.objects.get(data.get('source_curve', ''))
    center = _world_point(source, int(data.get('source_point', -1))) if source is not None else None
    basis = _stored_binding_plane(data)
    if center is None or basis is None or not (0 <= int(slave_vertex_index) < len(ps.cross_section_verts)):
        return False
    _, u, v, _ = basis
    scale = max(1.0e-8, float(ps.scale))
    rotation = math.radians(float(ps.rotation))
    radial = Vector(world_position) - center
    x = radial.dot(u)
    y = radial.dot(v)
    cos_r = math.cos(rotation)
    sin_r = math.sin(rotation)
    vertex = ps.cross_section_verts[int(slave_vertex_index)]
    vertex.offset_x = (x * cos_r + y * sin_r) / scale
    vertex.offset_y = (-x * sin_r + y * cos_r) / scale
    return True


def find_nearest_source_vertex_world(source_obj, source_point_index, world_position):
    source_ps = _point_setting(source_obj, int(source_point_index))
    if source_ps is None:
        return -1, None
    ring = _nearest_pipe_ring(
        get_pipe_object_for_curve(source_obj), source_obj, int(source_point_index),
        len(source_ps.cross_section_verts),
    )
    if not ring:
        return -1, None
    index = min(range(len(ring)), key=lambda i: (ring[i] - world_position).length_squared)
    return index, ring[index]


def set_binding_vertex_snap(slave_obj, slave_point_index, slave_vertex_index, source_vertex_index, enabled=True):
    """Persist a vertex-to-vertex snap relationship on a binding record."""
    bindings = _get_bindings(slave_obj)
    changed = False
    for record in bindings:
        if int(record.get('slave_point', -1)) == int(slave_point_index):
            snaps = record.get('vertex_snaps', {})
            if not isinstance(snaps, dict):
                snaps = {}
            if enabled:
                snaps[str(int(slave_vertex_index))] = int(source_vertex_index)
            else:
                snaps.pop(str(int(slave_vertex_index)), None)
            record['vertex_snaps'] = snaps
            changed = True
    if changed:
        _set_bindings(slave_obj, bindings)
    return changed


def _set_bindings(slave_obj, bindings):
    if bindings:
        slave_obj[_BINDING_KEY] = json.dumps(
            {'version': 2, 'bindings': list(bindings)}, separators=(',', ':')
        )
    elif _BINDING_KEY in slave_obj:
        del slave_obj[_BINDING_KEY]


def _get_binding(slave_obj):
    bindings = _get_bindings(slave_obj)
    return bindings[0] if bindings else None


def get_curve_binding(curve_obj):
    return _get_binding(curve_obj)


def get_binding_source_curve(curve_obj):
    data = _get_binding(curve_obj)
    if not data:
        return None
    source = bpy.data.objects.get(data.get('source_curve', ''))
    return source if source is not None and source.type == 'CURVE' else None


def _selected_point_index(curve_obj):
    from .curve_data import get_selected_curve_point_indices
    selected = get_selected_curve_point_indices(curve_obj)
    return selected[-1] if selected else None


def _selected_curves(context):
    return [
        obj for obj in getattr(context, 'selected_objects', ())
        if obj is not None and obj.type == 'CURVE' and hasattr(obj, 'hair_pipe_settings')
    ]


def _point_tilt(curve_obj, index):
    points = _curve_points(curve_obj)
    if not (0 <= int(index) < len(points)):
        return 0.0
    return float(getattr(points[int(index)], 'tilt', 0.0))


def _world_point(curve_obj, index):
    points = _curve_points(curve_obj)
    if not (0 <= index < len(points)):
        return None
    return curve_obj.matrix_world @ _point_local_co(points[index])


def _point_tangent_world(curve_obj, index):
    """Approximate the generated pipe tangent at a control point."""
    points = _curve_points(curve_obj)
    if not (0 <= index < len(points)):
        return None
    point = points[index]
    spline = None
    count = 0
    for candidate in curve_obj.data.splines:
        candidate_points = candidate.bezier_points if candidate.type == 'BEZIER' else candidate.points
        if count <= index < count + len(candidate_points):
            spline = candidate
            local_index = index - count
            break
        count += len(candidate_points)
    if spline is None:
        return None
    source = spline.bezier_points if spline.type == 'BEZIER' else spline.points
    if spline.type == 'BEZIER':
        tangent = point.handle_right - point.handle_left
        if tangent.length < 1.0e-8:
            tangent = point.handle_right - point.co
    else:
        if len(source) < 2:
            tangent = Vector((0.0, 0.0, 1.0))
        elif local_index == 0:
            tangent = Vector(source[1].co[:3]) - Vector(source[0].co[:3])
        elif local_index == len(source) - 1:
            tangent = Vector(source[-1].co[:3]) - Vector(source[-2].co[:3])
        else:
            tangent = Vector(source[local_index + 1].co[:3]) - Vector(source[local_index - 1].co[:3])
    return safe_normalized(curve_obj.matrix_world.to_3x3() @ tangent)


def _rotation_from_real_pipe_rings(source_obj, source_idx, slave_obj, slave_idx, fallback):
    """Calibrate slave rotation from the actual generated mesh ring directions.

    The curve-local frame is only an approximation: the pipe generator applies
    endpoint-driven minimal-twist frames. Reading the real rings keeps the 2D
    widget and the rendered 3D pipe in the same coordinate system.
    """
    try:
        from .hair_lifecycle import get_pipe_object_for_curve
        source_pipe = get_pipe_object_for_curve(source_obj)
        slave_pipe = get_pipe_object_for_curve(slave_obj)
        if source_pipe is None or slave_pipe is None:
            return float(fallback)
        source_ps = _point_setting(source_obj, source_idx)
        slave_ps = _point_setting(slave_obj, slave_idx)
        source_count = len(source_ps.cross_section_verts) if source_ps else 0
        slave_count = len(slave_ps.cross_section_verts) if slave_ps else 0
        if source_count < 3 or slave_count < 3:
            return float(fallback)

        def ring_vertices(pipe, curve, point_index, count):
            points_before = 0
            for spline in curve.data.splines:
                spline_points = spline.bezier_points if spline.type == 'BEZIER' else spline.points
                if points_before <= point_index < points_before + len(spline_points):
                    local = point_index - points_before
                    start = (points_before + local) * count
                    verts = list(pipe.data.vertices)[start:start + count]
                    if len(verts) == count:
                        return [pipe.matrix_world @ v.co for v in verts]
                    return None
                points_before += len(spline_points)
            return None

        source_ring = ring_vertices(source_pipe, source_obj, source_idx, source_count)
        slave_ring = ring_vertices(slave_pipe, slave_obj, slave_idx, slave_count)
        if not source_ring or not slave_ring:
            return float(fallback)
        source_center = sum(source_ring, Vector()) / len(source_ring)
        slave_center = sum(slave_ring, Vector()) / len(slave_ring)
        source_tangent = _point_tangent_world(source_obj, source_idx)
        slave_tangent = _point_tangent_world(slave_obj, slave_idx)
        if source_tangent is None or slave_tangent is None:
            return float(fallback)
        desired = source_ring[0] - source_center
        desired = desired - slave_tangent * desired.dot(slave_tangent)
        current = slave_ring[0] - slave_center
        current = current - slave_tangent * current.dot(slave_tangent)
        if desired.length < 1.0e-8 or current.length < 1.0e-8:
            return float(fallback)
        desired.normalize()
        current.normalize()
        cross = current.cross(desired)
        angle = math.atan2(cross.dot(slave_tangent), current.dot(desired))
        return float(fallback) + math.degrees(angle)
    except (AttributeError, IndexError, RuntimeError, ValueError, TypeError):
        return float(fallback)


def _binding_plane_data(source_obj, source_idx):
    """Capture one immutable world-space basis from the source mesh ring."""
    source_ps = _point_setting(source_obj, source_idx)
    if source_ps is None:
        return {}
    ring = _nearest_pipe_ring(
        get_pipe_object_for_curve(source_obj), source_obj, source_idx,
        len(source_ps.cross_section_verts),
    )
    basis = _orthogonal_ring_basis(ring)
    if basis is None:
        return {}
    center, u, v, normal = basis
    return {
        'plane_center': list(center),
        'plane_u': list(u),
        'plane_v': list(v),
        'plane_normal': list(normal),
    }


def _stored_binding_plane(data):
    try:
        center = Vector(data['plane_center'])
        u = safe_normalized(Vector(data['plane_u']))
        v = safe_normalized(Vector(data['plane_v']))
        normal = safe_normalized(Vector(data['plane_normal']))
        if u.length < 1.0e-8 or v.length < 1.0e-8 or normal.length < 1.0e-8:
            return None
        return center, u, v, normal
    except (KeyError, TypeError, ValueError):
        return None


def _apply_binding_record(slave_obj, data):
    """Apply one binding record without joining meshes or changing topology."""
    if not data or slave_obj is None or slave_obj.type != 'CURVE':
        return False
    source = bpy.data.objects.get(data.get('source_curve', ''))
    if source is None or source.type != 'CURVE':
        return False
    # In multi-object Edit Mode the latest coordinates can still live in the
    # edit mesh. Flush them before sampling the target world position.
    for curve in (source, slave_obj):
        try:
            if getattr(curve, 'mode', '') in {'EDIT', 'EDIT_CURVE'}:
                curve.update_from_editmode()
        except (AttributeError, RuntimeError):
            pass
    source_index = int(data.get('source_point', -1))
    slave_index = int(data.get('slave_point', -1))
    target_world = _world_point(source, source_index)
    points = _curve_points(slave_obj)
    if target_world is None or not (0 <= slave_index < len(points)):
        return False

    local_target = slave_obj.matrix_world.inverted_safe() @ target_world
    point = points[slave_index]
    old_local = _point_local_co(point)
    local_delta = local_target - old_local
    position_changed = local_delta.length_squared > 1.0e-14
    _set_point_local_co(point, local_target)
    # Preserve the slave Bezier tangent while snapping its control point. This
    # avoids introducing a sharp kink that can become a subdivision "boulder".
    if position_changed and hasattr(point, 'handle_left'):
        point.handle_left = point.handle_left + local_delta
        point.handle_right = point.handle_right + local_delta

    source_ps = _point_setting(source, source_index)
    slave_ps = _point_setting(slave_obj, slave_index)
    # Binding controls the slave control-point position only. The slave
    # profile remains independently editable: never overwrite its scale or
    # rotation during depsgraph/timer updates.
    settings_changed = False
    if not (position_changed or settings_changed):
        return False
    if position_changed or settings_changed:
        try:
            slave_obj.update_tag()
            slave_obj.data.update_tag()
        except (AttributeError, RuntimeError):
            pass
    return position_changed or settings_changed


def apply_binding(slave_obj):
    changed = False
    for data in _get_bindings(slave_obj):
        changed = _apply_binding_record(slave_obj, data) or changed
    return changed


def _nearest_pipe_ring(pipe_obj, curve_obj, point_index, count):
    """Find the generated base-mesh ring corresponding to a control point."""
    if pipe_obj is None or getattr(pipe_obj, 'type', None) != 'MESH' or count < 3:
        return None
    target = _world_point(curve_obj, point_index)
    if target is None:
        return None
    vertices = list(pipe_obj.data.vertices)
    if len(vertices) < count:
        return None
    best = None
    best_dist = None
    ring_count = len(vertices) // count
    for ring_idx in range(ring_count):
        start = ring_idx * count
        ring = vertices[start:start + count]
        center = sum((pipe_obj.matrix_world @ vertex.co for vertex in ring), Vector()) / count
        distance = (center - target).length_squared
        if best_dist is None or distance < best_dist:
            best_dist = distance
            best = [pipe_obj.matrix_world @ vertex.co for vertex in ring]
    return best


def _ring_plane_normal(ring, fallback=None):
    """Stable normal from every edge; independent of one edited vertex."""
    if not ring or len(ring) < 3:
        return fallback.copy() if fallback is not None else None
    center = sum(ring, Vector()) / len(ring)
    normal = Vector()
    for index, point in enumerate(ring):
        a = point - center
        b = ring[(index + 1) % len(ring)] - center
        normal += a.cross(b)
    if normal.length < 1.0e-10:
        return fallback.copy() if fallback is not None else None
    normal.normalize()
    if fallback is not None and normal.dot(fallback) < 0.0:
        normal.negate()
    return normal


def _basis_on_current_source_plane(source_ring, stored_basis):
    """Use the live source plane normal with stable stored in-plane roll."""
    if not source_ring:
        return stored_basis
    old_center, old_u, old_v, old_normal = stored_basis if stored_basis else (None, None, None, None)
    normal = _ring_plane_normal(source_ring, old_normal)
    if normal is None:
        return stored_basis
    center = sum(source_ring, Vector()) / len(source_ring)
    u = old_u - normal * old_u.dot(normal) if old_u is not None else None
    if u is None or u.length < 1.0e-8:
        u = source_ring[0] - center
        u = u - normal * u.dot(normal)
    if u.length < 1.0e-8:
        u, _ = get_cross_section_frame(normal)
    else:
        u.normalize()
    v = normal.cross(u).normalized()
    if old_v is not None and v.dot(old_v) < 0.0:
        u.negate()
        v.negate()
    return center, u, v, normal


def _orthogonal_ring_basis(ring):
    if not ring or len(ring) < 3:
        return None
    center = sum(ring, Vector()) / len(ring)
    u = ring[0] - center
    if u.length < 1.0e-8:
        return None
    u.normalize()
    v = ring[1] - center
    v = v - u * v.dot(u)
    if v.length < 1.0e-8:
        return None
    v.normalize()
    normal = u.cross(v)
    if normal.length < 1.0e-8:
        return None
    normal.normalize()
    v = normal.cross(u).normalized()
    return center, u, v, normal


def apply_bound_frames_to_generated_vertices(curve_obj, verts):
    """Apply bound section frames before a mesh is written.

    This is the single binding write path used by mesh generation. It keeps
    the slave profile/scale/rotation independent while taking only the bound
    section center and plane from its source curve.
    """
    if curve_obj is None or curve_obj.type != 'CURVE' or not verts:
        return verts
    pipe_obj = get_pipe_object_for_curve(curve_obj)
    if pipe_obj is None:
        return verts
    inverse_pipe = pipe_obj.matrix_world.inverted_safe()
    for data in _get_bindings(curve_obj):
        source = bpy.data.objects.get(data.get('source_curve', ''))
        if source is None:
            continue
        source_index = int(data.get('source_point', -1))
        slave_index = int(data.get('slave_point', -1))
        source_ps = _point_setting(source, source_index)
        slave_ps = _point_setting(curve_obj, slave_index)
        if source_ps is None or slave_ps is None:
            continue
        source_pipe = get_pipe_object_for_curve(source)
        source_ring = _nearest_pipe_ring(source_pipe, source, source_index, len(source_ps.cross_section_verts))
        basis = _stored_binding_plane(data)
        if source_ring:
            basis = _basis_on_current_source_plane(source_ring, basis)
        if basis is None:
            continue
        _center, source_u, source_v, _normal = basis
        source_center = _world_point(source, source_index)
        if source_center is None:
            source_center = basis[0]
        count = len(slave_ps.cross_section_verts)
        start = slave_index * count
        if start < 0 or start + count > len(verts):
            continue
        scale = float(slave_ps.scale)
        rotation = math.radians(float(slave_ps.rotation))
        cos_r = math.cos(rotation)
        sin_r = math.sin(rotation)
        snap_map = data.get('vertex_snaps', {})
        for offset, profile_vert in enumerate(slave_ps.cross_section_verts):
            raw_x = float(profile_vert.offset_x) * scale
            raw_y = float(profile_vert.offset_y) * scale
            x = raw_x * cos_r - raw_y * sin_r
            y = raw_x * sin_r + raw_y * cos_r
            desired = source_center + source_u * x + source_v * y
            target_vertex = snap_map.get(str(offset)) if isinstance(snap_map, dict) else None
            try:
                target_vertex = int(target_vertex)
            except (TypeError, ValueError):
                target_vertex = -1
            if source_ring and 0 <= target_vertex < len(source_ring):
                desired = source_ring[target_vertex]
            verts[start + offset] = inverse_pipe @ desired
    return verts


def align_binding_ring_planes(slave_obj):
    """Place every bound slave base ring in its target's actual 3D plane.

    This is deliberately a final vertex-space correction. The generator may
    use the slave curve's own minimal-twist frame, but the bound ring must use
    the target ring's real plane and center. No curve-neighbour tangent can
    override this result.
    """
    from .hair_lifecycle import get_pipe_object_for_curve
    slave_pipe = get_pipe_object_for_curve(slave_obj)
    if slave_pipe is None:
        return False
    changed = False
    bindings = _get_bindings(slave_obj)
    binding_data_changed = False
    for data in bindings:
        source = bpy.data.objects.get(data.get('source_curve', ''))
        if source is None or source.type != 'CURVE':
            continue
        source_ps = _point_setting(source, int(data.get('source_point', -1)))
        slave_ps = _point_setting(slave_obj, int(data.get('slave_point', -1)))
        if source_ps is None or slave_ps is None:
            continue
        source_count = len(source_ps.cross_section_verts)
        slave_count = len(slave_ps.cross_section_verts)
        if source_count < 3 or slave_count < 3:
            continue
        source_pipe = get_pipe_object_for_curve(source)
        source_ring = _nearest_pipe_ring(source_pipe, source, int(data.get('source_point', -1)), source_count)
        slave_ring = _nearest_pipe_ring(slave_pipe, slave_obj, int(data.get('slave_point', -1)), slave_count)
        # Profile editing must not redefine the plane. Only a change to the
        # source curve point's tilt (the Alt+T operation) is allowed to update
        # the stored 3D basis. This cleanly separates shape edits from roll.
        current_tilt = _point_tilt(source, int(data.get('source_point', -1)))
        stored_tilt = data.get('source_tilt')
        stored_basis = _stored_binding_plane(data)
        source_basis = _basis_on_current_source_plane(source_ring, stored_basis)
        if source_basis is None:
            continue
        _ring_center, source_u, source_v, source_normal = source_basis
        # The ring centroid changes when a single profile vertex is edited.
        # It is valid for estimating the plane, but never as the binding
        # anchor. The anchor is the source curve control point itself.
        source_center = _world_point(source, int(data.get('source_point', -1)))
        if source_center is None:
            source_center = _ring_center
        # Persist the live plane axes, while storing the stable curve-point
        # anchor separately from the shape-dependent ring centroid.
        data.update({
            'plane_center': list(source_center),
            'plane_u': list(source_u),
            'plane_v': list(source_v),
            'plane_normal': list(source_normal),
            'source_tilt': current_tilt,
        })
        binding_data_changed = binding_data_changed or (
            data.get('plane_center') != list(source_center)
            or data.get('plane_u') != list(source_u)
            or data.get('plane_v') != list(source_v)
            or data.get('plane_normal') != list(source_normal)
        )
        # The final ring is generated directly from the slave profile's 2D
        # coordinates in the frozen source axes. Never derive axes from the
        # current slave ring: moving one profile vertex would rotate that basis.
        scale = float(slave_ps.scale)
        rotation = math.radians(float(slave_ps.rotation))
        cos_r = math.cos(rotation)
        sin_r = math.sin(rotation)
        # Do not recenter or redistribute the profile here. Re-centering would
        # move every untouched vertex in the opposite direction whenever one
        # vertex is edited. The target control point already owns the ring
        # center; profile coordinates must be passed through independently.
        # Locate the corresponding ring again by comparing its world center.
        # The slave ring only identifies which ring to rewrite; it never
        # supplies orientation axes.
        slave_center = sum(slave_ring, Vector()) / len(slave_ring)
        vertices = list(slave_pipe.data.vertices)
        target_start = None
        target_distance = None
        for ring_idx in range(len(vertices) // slave_count):
            start = ring_idx * slave_count
            ring = vertices[start:start + slave_count]
            center = sum((slave_pipe.matrix_world @ item.co for item in ring), Vector()) / slave_count
            distance = (center - slave_center).length_squared
            if target_distance is None or distance < target_distance:
                target_distance = distance
                target_start = start
        if target_start is None:
            continue
        inv_matrix = slave_pipe.matrix_world.inverted_safe()
        local_vertices = []
        snap_map = data.get('vertex_snaps', {})
        for offset, vertex in enumerate(vertices[target_start:target_start + slave_count]):
            profile_vert = slave_ps.cross_section_verts[offset]
            raw_x = float(profile_vert.offset_x) * scale
            raw_y = float(profile_vert.offset_y) * scale
            x = raw_x * cos_r - raw_y * sin_r
            y = raw_x * sin_r + raw_y * cos_r
            desired = source_center + source_u * x + source_v * y
            target_vertex = snap_map.get(str(offset)) if isinstance(snap_map, dict) else None
            if target_vertex is not None:
                try:
                    target_vertex = int(target_vertex)
                    if source_ring and 0 <= target_vertex < len(source_ring):
                        desired = source_ring[target_vertex]
                except (TypeError, ValueError):
                    pass
            local_vertices.append(inv_matrix @ desired)
        # Do not write/update the mesh when alignment is already exact. The
        # old unconditional write caused a depsgraph feedback loop and made
        # the viewport flicker during every G/R/S mouse move.
        ring_changed = any(
            (vertex.co - local_co).length_squared > 1.0e-14
            for vertex, local_co in zip(vertices[target_start:target_start + slave_count], local_vertices)
        )
        if ring_changed:
            for vertex, local_co in zip(vertices[target_start:target_start + slave_count], local_vertices):
                vertex.co = local_co
            changed = True
    if binding_data_changed:
        _set_bindings(slave_obj, bindings)
    if changed:
        slave_pipe.data.update()
        slave_obj['hair_pipe_mesh_revision'] = int(slave_obj.get('hair_pipe_mesh_revision', 0)) + 1
    return changed


def align_bound_dependents(source_obj):
    """Re-apply source ring planes after the source pipe is rebuilt."""
    changed = False
    if source_obj is None:
        return changed
    for obj in list(bpy.data.objects):
        if obj.type != 'CURVE' or not _get_bindings(obj):
            continue
        if any(item.get('source_curve') == source_obj.name for item in _get_bindings(obj)):
            changed = align_binding_ring_planes(obj) or changed
    return changed


def repair_all_binding_planes():
    """Repair loaded scenes whose binding rings were not finalized on load."""
    changed = []
    for obj in list(bpy.data.objects):
        if obj.type != 'CURVE' or not _get_bindings(obj):
            continue
        if align_binding_ring_planes(obj):
            changed.append(obj)
    return changed


def apply_bindings_for_curves(curve_names):
    """Apply only bindings touched by the changed source/slave curves."""
    names = {str(name) for name in curve_names if name}
    if not names:
        return []
    changed = []
    for obj in bpy.data.objects:
        if obj.type != 'CURVE':
            continue
        records = _get_bindings(obj)
        if not records:
            continue
        if not any(
            obj.name in names or str(item.get('source_curve', '')) in names
            for item in records
        ):
            continue
        if apply_binding(obj):
            changed.append(obj)
    return changed


def apply_all_bindings():
    changed = []
    for obj in list(bpy.data.objects):
        if obj.type != 'CURVE' or not _get_bindings(obj):
            continue
        if apply_binding(obj):
            changed.append(obj)
    return changed


def create_binding(context):
    curves = _selected_curves(context)
    if len(curves) != 2:
        return None, "需要选中两条 FiguHair 曲线"
    target = context.active_object
    if target not in curves:
        target = curves[0]
    slave = curves[0] if curves[1] == target else curves[1]
    target_index = _selected_point_index(target)
    slave_index = _selected_point_index(slave)
    if target_index is None or slave_index is None:
        return None, "请在两条曲线上各选择一个控制点"
    if target_index >= len(target.hair_pipe_settings.point_settings):
        return None, "目标点没有有效横截面"
    if slave_index >= len(slave.hair_pipe_settings.point_settings):
        return None, "从属点没有有效横截面"
    target_ps = target.hair_pipe_settings.point_settings[target_index]
    slave_ps = slave.hair_pipe_settings.point_settings[slave_index]
    initial_rotation = _rotation_from_real_pipe_rings(
        target, target_index, slave, slave_index, slave_ps.rotation,
    )
    plane_data = _binding_plane_data(target, target_index)
    plane = _stored_binding_plane(plane_data)
    display_world_per_unit = _world_per_profile_unit(
        target, target_index, target_ps, plane,
    )
    data = {
        'source_curve': target.name,
        'source_point': int(target_index),
        'source_tilt': _point_tilt(target, target_index),
        'display_world_per_unit': float(display_world_per_unit),
        'slave_point': int(slave_index),
        'scale_ratio': float(slave_ps.scale) / max(1.0e-6, float(target_ps.scale)),
        # Calibrate orientation once at bind time. Recomputing this from the
        # first ring vertex while editing the profile makes rotation depend on
        # which shape vertex was moved.
        'slave_rotation': float(initial_rotation),
        'profile_rotation': 0.0,
        'rotation_offset': 0.0,
        **plane_data,
    }
    bindings = [item for item in _get_bindings(slave)
                if not (item.get('source_curve') == target.name and
                        int(item.get('slave_point', -1)) == int(slave_index))]
    bindings.append(data)
    _set_bindings(slave, bindings)
    apply_binding(slave)
    return slave, None


def remove_binding(context):
    curves = _selected_curves(context)
    removed = 0
    for curve in curves:
        bindings = _get_bindings(curve)
        if bindings:
            removed += len(bindings)
            _set_bindings(curve, [])
    return removed


def is_bound_slave(curve_obj, point_index=None):
    bindings = _get_bindings(curve_obj)
    if point_index is None:
        return bool(bindings)
    return any(int(item.get('slave_point', -1)) == int(point_index) for item in bindings)


def is_bound_slave_point(curve_obj, point_index):
    return is_bound_slave(curve_obj, point_index)


def get_bound_sections_for_target(target_obj, target_point_index):
    """Return slave curve/point pairs controlled by a target section."""
    result = []
    if target_obj is None:
        return result
    for obj in bpy.data.objects:
        if obj.type != 'CURVE':
            continue
        for data in _get_bindings(obj):
            if data.get('source_curve') != target_obj.name:
                continue
            if int(data.get('source_point', -1)) != int(target_point_index):
                continue
            slave_index = int(data.get('slave_point', -1))
            ps = _point_setting(obj, slave_index)
            if ps is not None:
                result.append((obj, slave_index, ps))
    return result


def _find_binding_record(target_obj, target_point_index, slave_obj, slave_point_index):
    for data in _get_bindings(slave_obj):
        if (data.get('source_curve') == target_obj.name and
                int(data.get('source_point', -1)) == int(target_point_index) and
                int(data.get('slave_point', -1)) == int(slave_point_index)):
            return data
    return None


def _world_per_profile_unit(curve_obj, point_index, point_setting, plane):
    pipe = get_pipe_object_for_curve(curve_obj)
    ring = _nearest_pipe_ring(
        pipe, curve_obj, int(point_index), len(point_setting.cross_section_verts),
    )
    if not ring or plane is None:
        return 1.0
    center, u, v, _normal = plane
    numerator = 0.0
    denominator = 0.0
    for index, vertex in enumerate(point_setting.cross_section_verts):
        if index >= len(ring):
            break
        raw_x = float(vertex.offset_x)
        raw_y = float(vertex.offset_y)
        radial = ring[index] - center
        actual_x = radial.dot(u)
        actual_y = radial.dot(v)
        numerator += raw_x * actual_x + raw_y * actual_y
        denominator += raw_x * raw_x + raw_y * raw_y
    if denominator <= 1.0e-10:
        return 1.0
    value = numerator / denominator
    return abs(value) if abs(value) > 1.0e-8 else 1.0


def get_bound_section_display_offsets(target_obj, target_point_index, slave_obj, slave_point_index):
    """Project the real slave 3D ring into the source section's 2D space."""
    source_ps = _point_setting(target_obj, int(target_point_index))
    slave_ps = _point_setting(slave_obj, int(slave_point_index))
    if source_ps is None or slave_ps is None:
        return []
    data = _find_binding_record(target_obj, target_point_index, slave_obj, slave_point_index)
    basis = _stored_binding_plane(data) if data is not None else None
    if basis is None:
        return []
    source_pipe = get_pipe_object_for_curve(target_obj)
    slave_pipe = get_pipe_object_for_curve(slave_obj)
    source_count = len(source_ps.cross_section_verts)
    slave_count = len(slave_ps.cross_section_verts)
    source_ring = _nearest_pipe_ring(source_pipe, target_obj, int(target_point_index), source_count)
    slave_ring = _nearest_pipe_ring(slave_pipe, slave_obj, int(slave_point_index), slave_count)
    if not source_ring or not slave_ring:
        return []

    _captured_center, source_u, source_v, _normal = basis
    # The 2D anchor is the bound curve point, not the ring centroid. A profile
    # edit changes the shape and may change the ring's average vertex position;
    # using that average would make the entire child appear to drift/scale.
    source_center = _world_point(target_obj, int(target_point_index))
    if source_center is None:
        source_center = _captured_center
    # The conversion scale is captured at bind time. Recomputing it from the
    # edited source shape makes one moved vertex resize the whole child overlay.
    world_per_widget = float(data.get('display_world_per_unit', 1.0))
    if abs(world_per_widget) < 1.0e-8:
        world_per_widget = 1.0
    # Project around the target ring center, not the child's current centroid.
    # The target center is the binding anchor in both 3D and 2D.
    slave_center = source_center

    # Project the actual slave ring, not its ungenerated profile data. This is
    # what makes 2D overlap exactly reflect 3D overlap.
    result = []
    for world in slave_ring:
        radial = world - slave_center
        result.append((radial.dot(source_u) / world_per_widget,
                       radial.dot(source_v) / world_per_widget))
    return result


def get_bound_edit_target(target_obj, target_point_index, screen_x, screen_y, cx, cy, sf, alignment_angle, flip_h, max_dist=14.0):
    """Find a bound slave vertex in the target editor's screen projection."""
    best = None
    best_dist = max_dist * max_dist
    for slave_obj, slave_idx, ps in get_bound_sections_for_target(target_obj, target_point_index):
        offsets = get_bound_section_display_offsets(
            target_obj, target_point_index, slave_obj, slave_idx,
        )
        for vert_idx, vert in enumerate(ps.cross_section_verts):
            if getattr(vert, 'is_ghost', False):
                continue
            if vert_idx >= len(offsets):
                continue
            ox, oy = offsets[vert_idx]
            cos_a = math.cos(alignment_angle)
            sin_a = math.sin(alignment_angle)
            rx = ox * cos_a - oy * sin_a
            ry = ox * sin_a + oy * cos_a
            if flip_h:
                rx = -rx
            px = cx + rx * sf
            py = cy + ry * sf
            dist = (px - screen_x) ** 2 + (py - screen_y) ** 2
            if dist <= best_dist:
                best_dist = dist
                best = (slave_obj, slave_idx, vert_idx, ps)
    return best


def binding_description(curve_obj):
    bindings = _get_bindings(curve_obj)
    return bindings[0] if bindings else None


class HAIRPIPE_OT_bind_cross_curve(bpy.types.Operator):
    bl_idname = 'hair_pipe.bind_cross_curve'
    bl_label = '绑定跨曲线横截面'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(_selected_curves(context)) == 2

    def execute(self, context):
        slave, error = create_binding(context)
        if error:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}
        self.report({'INFO'}, f'已绑定 {slave.name} 的横截面')
        return {'FINISHED'}


class HAIRPIPE_OT_unbind_cross_curve(bpy.types.Operator):
    bl_idname = 'hair_pipe.unbind_cross_curve'
    bl_label = '解除跨曲线横截面绑定'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(_get_binding(obj) for obj in _selected_curves(context))

    def execute(self, context):
        removed = remove_binding(context)
        if not removed:
            self.report({'ERROR'}, '当前选择没有跨曲线绑定')
            return {'CANCELLED'}
        self.report({'INFO'}, f'已解除 {removed} 个跨曲线绑定')
        return {'FINISHED'}


classes = (HAIRPIPE_OT_bind_cross_curve, HAIRPIPE_OT_unbind_cross_curve)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError):
            pass
