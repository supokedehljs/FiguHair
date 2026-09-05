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
    settings_changed = False
    if source_ps is not None and slave_ps is not None:
        source_scale = max(1.0e-6, float(source_ps.scale))
        scale_ratio = float(data.get('scale_ratio', 1.0))
        new_scale = source_scale * scale_ratio
        # The target section owns the orientation. Do not add the old
        # per-binding rotation offset: it made the 2D overlay disagree with
        # the generated 3D ring whenever the two curves had different values.
        new_rotation = float(data.get('slave_rotation', slave_ps.rotation))
        settings_changed = (
            abs(float(slave_ps.scale) - new_scale) > 1.0e-9 or
            abs(float(slave_ps.rotation) - new_rotation) > 1.0e-7
        )
        slave_ps.scale = new_scale
        slave_ps.rotation = new_rotation
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
        source_basis = _stored_binding_plane(data)
        tilt_changed = (
            stored_tilt is not None and
            abs(current_tilt - float(stored_tilt)) > 1.0e-7
        )
        if source_basis is None or tilt_changed:
            live_basis = _orthogonal_ring_basis(source_ring)
            if live_basis is not None:
                source_basis = live_basis
                data.update({
                    'plane_center': list(live_basis[0]),
                    'plane_u': list(live_basis[1]),
                    'plane_v': list(live_basis[2]),
                    'plane_normal': list(live_basis[3]),
                    'source_tilt': current_tilt,
                })
                binding_data_changed = True
        elif stored_tilt is None:
            # Upgrade old bindings without changing their existing orientation.
            data['source_tilt'] = current_tilt
            binding_data_changed = True
        if source_basis is None:
            continue
        _captured_center, source_u, source_v, _source_normal = source_basis
        source_center = _world_point(source, int(data.get('source_point', -1)))
        if source_center is None:
            source_center = _captured_center
        # The final ring is generated directly from the slave profile's 2D
        # coordinates in the frozen source axes. Never derive axes from the
        # current slave ring: moving one profile vertex would rotate that basis.
        scale = float(slave_ps.scale)
        rotation = math.radians(float(data.get('profile_rotation', 0.0)))
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
        for offset, vertex in enumerate(vertices[target_start:target_start + slave_count]):
            profile_vert = slave_ps.cross_section_verts[offset]
            raw_x = float(profile_vert.offset_x) * scale
            raw_y = float(profile_vert.offset_y) * scale
            x = raw_x * cos_r - raw_y * sin_r
            y = raw_x * sin_r + raw_y * cos_r
            desired = source_center + source_u * x + source_v * y
            vertex.co = inv_matrix @ desired
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
    data = {
        'source_curve': target.name,
        'source_point': int(target_index),
        'source_tilt': _point_tilt(target, target_index),
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


def get_bound_section_display_offsets(target_obj, target_point_index, slave_obj, slave_point_index):
    """Return the slave ring in the target widget's actual 3D ring basis."""
    source_ps = _point_setting(target_obj, int(target_point_index))
    slave_ps = _point_setting(slave_obj, int(slave_point_index))
    if source_ps is None or slave_ps is None:
        return []
    data = _find_binding_record(
        target_obj, target_point_index, slave_obj, slave_point_index,
    )
    basis = _stored_binding_plane(data) if data is not None else None
    if basis is None:
        return []
    # Keep the editor's coordinates object-local and stable. Do not derive a
    # display center from the generated ring: that would move all untouched
    # 2D points when only one profile vertex is edited.
    _center, _source_u, _source_v, _normal = basis
    scale_ratio = float(data.get('scale_ratio', 1.0)) if data else 1.0
    return [
        (float(vertex.offset_x) * scale_ratio,
         float(vertex.offset_y) * scale_ratio)
        for vertex in slave_ps.cross_section_verts
    ]


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
