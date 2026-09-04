"""tail_utils — 末端网格连接/重拓扑纯函数（已停用的 tail 功能，仅保留委托）。"""
import math
import bpy  # noqa: F401
from mathutils import Vector
from .mesh_utils import (
    flatten_ring_points,
    resample_ring_points,
    rebuild_mesh_safely,
)


def estimate_tail_direction_from_vertices(verts, segments):
    if len(verts) >= segments * 2:
        last_center = sum((Vector(v) for v in verts[-segments:]), Vector((0.0, 0.0, 0.0))) / segments
        prev_center = sum((Vector(v) for v in verts[-segments * 2:-segments]), Vector((0.0, 0.0, 0.0))) / segments
        direction = last_center - prev_center
        if direction.length > 1e-8:
            return direction.normalized()
    return Vector((0.0, 0.0, 1.0))


def create_tail_mesh_geometry(last_ring, direction):
    segments = len(last_ring)
    center = sum((Vector(v) for v in last_ring), Vector((0.0, 0.0, 0.0))) / segments
    radius = max((Vector(v) - center).length for v in last_ring) if segments > 0 else 0.05
    length = max(radius * 1.8, 0.05)
    tip_ring = [Vector(v) + direction * length for v in last_ring]
    verts = [Vector(v) for v in last_ring] + tip_ring
    faces = []
    for i in range(segments):
        j = (i + 1) % segments
        faces.append((i, j, segments + j, segments + i))
    faces.append(tuple(range(segments, segments * 2)))
    return verts, faces


def get_stored_tail_connection_ring(tail_obj, segments):
    values = tail_obj.get("hair_pipe_tail_connection_ring")
    if values is None or len(values) != segments * 3:
        return None
    return [Vector((values[i], values[i + 1], values[i + 2])) for i in range(0, len(values), 3)]


def store_tail_connection_state(tail_obj, last_ring, direction, lower_ring_count=None):
    tail_obj["hair_pipe_tail_direction"] = tuple(direction)
    tail_obj["hair_pipe_tail_connection_ring"] = flatten_ring_points(last_ring)
    if lower_ring_count is not None:
        tail_obj["hair_pipe_tail_lower_ring_count"] = int(lower_ring_count)


def build_tail_connection_basis(ring, direction):
    count = len(ring)
    center = sum((Vector(v) for v in ring), Vector((0.0, 0.0, 0.0))) / count
    z_axis = direction.normalized() if direction.length > 1e-8 else Vector((0.0, 0.0, 1.0))
    x_axis = Vector(ring[0]) - center
    x_axis = x_axis - z_axis * x_axis.dot(z_axis)
    if x_axis.length < 1e-8:
        for point in ring[1:]:
            x_axis = Vector(point) - center
            x_axis = x_axis - z_axis * x_axis.dot(z_axis)
            if x_axis.length >= 1e-8:
                break
    if x_axis.length < 1e-8:
        x_axis = z_axis.cross(Vector((0.0, 0.0, 1.0)))
        if x_axis.length < 1e-8:
            x_axis = z_axis.cross(Vector((0.0, 1.0, 0.0)))
    x_axis.normalize()
    y_axis = z_axis.cross(x_axis)
    if y_axis.length < 1e-8:
        y_axis = Vector((0.0, 1.0, 0.0))
    y_axis.normalize()
    avg_radius = sum((Vector(v) - center).length for v in ring) / count
    return center, x_axis, y_axis, z_axis, max(avg_radius, 1e-8)


def transform_tail_vertices_by_connection(vertices, old_ring, new_ring, old_direction, new_direction):
    old_center, old_x, old_y, old_z, old_radius = build_tail_connection_basis(old_ring, old_direction)
    new_center, new_x, new_y, new_z, new_radius = build_tail_connection_basis(new_ring, new_direction)
    scale = new_radius / old_radius
    transformed = []
    for vertex in vertices:
        offset = Vector(vertex) - old_center
        local_x = offset.dot(old_x)
        local_y = offset.dot(old_y)
        local_z = offset.dot(old_z)
        transformed.append(new_center + new_x * local_x * scale + new_y * local_y * scale + new_z * local_z * scale)
    return transformed


def rebuild_tail_grid(mesh, transformed_vertices, old_segments, new_segments, last_ring):
    if old_segments < 3 or new_segments < 3:
        return False
    if len(transformed_vertices) % old_segments != 0:
        return False
    ring_count = len(transformed_vertices) // old_segments
    if ring_count < 2:
        return False
    new_verts = []
    for ring_idx in range(ring_count):
        old_ring = transformed_vertices[ring_idx * old_segments:(ring_idx + 1) * old_segments]
        if ring_idx == 0:
            new_ring = [Vector(v) for v in last_ring]
        else:
            new_ring = resample_ring_points(old_ring, new_segments)
        new_verts.extend(new_ring)
    faces = []
    for ring_idx in range(ring_count - 1):
        base = ring_idx * new_segments
        next_base = (ring_idx + 1) * new_segments
        for i in range(new_segments):
            j = (i + 1) % new_segments
            faces.append((base + i, base + j, next_base + j, next_base + i))
    faces.append(tuple(range((ring_count - 1) * new_segments, ring_count * new_segments)))
    rebuild_mesh_safely(mesh, new_verts, faces)
    return True


def get_tail_pose_rotation(tail_obj, mesh, old_segments, new_direction):
    old_direction = None
    stored_direction = tail_obj.get("hair_pipe_tail_direction")
    if stored_direction is not None and len(stored_direction) == 3:
        direction = Vector(stored_direction)
        if direction.length > 1e-8:
            old_direction = direction.normalized()
    if old_direction is None and len(mesh.vertices) > old_segments:
        old_center = sum((v.co.copy() for v in mesh.vertices[:old_segments]), Vector((0.0, 0.0, 0.0))) / old_segments
        tail_center = sum((v.co.copy() for v in mesh.vertices[old_segments:]), Vector((0.0, 0.0, 0.0))) / (len(mesh.vertices) - old_segments)
        direction = tail_center - old_center
        if direction.length > 1e-8:
            old_direction = direction.normalized()
    if old_direction is not None and new_direction.length > 1e-8:
        try:
            return old_direction.rotation_difference(new_direction.normalized()).to_matrix()
        except Exception:
            return None
    return None


def infer_inserted_ring_index(old_ring, new_ring):
    old_count = len(old_ring)
    new_count = len(new_ring)
    if new_count != old_count + 1:
        return None
    best_index = 0
    best_score = None
    for insert_index in range(new_count):
        score = 0.0
        for old_index in range(old_count):
            new_index = old_index if old_index < insert_index else old_index + 1
            score += (Vector(old_ring[old_index]) - Vector(new_ring[new_index])).length_squared
        if best_score is None or score < best_score:
            best_score = score
            best_index = insert_index
    return best_index


def infer_removed_ring_index(old_ring, new_ring):
    old_count = len(old_ring)
    new_count = len(new_ring)
    if new_count != old_count - 1:
        return None
    best_index = 0
    best_score = None
    for removed_index in range(old_count):
        score = 0.0
        for new_index in range(new_count):
            old_index = new_index if new_index < removed_index else new_index + 1
            score += (Vector(old_ring[old_index]) - Vector(new_ring[new_index])).length_squared
        if best_score is None or score < best_score:
            best_score = score
            best_index = removed_index
    return best_index


def make_tail_bridge_faces(new_segments, old_segments, old_ring=None, new_ring=None):
    if new_segments == old_segments:
        faces = []
        for i in range(new_segments):
            j = (i + 1) % new_segments
            faces.append((i, j, old_segments + j, old_segments + i))
        return faces
    if new_segments > old_segments:
        insert_idx = infer_inserted_ring_index(old_ring or [], new_ring or []) if old_ring and new_ring else 0
        faces = []
        for i in range(new_segments):
            if i == insert_idx:
                continue
            j = (i + 1) % new_segments
            src_i = i if i < insert_idx else i - 1
            src_j = j if j < insert_idx else j - 1
            faces.append((i, j, old_segments + src_j, old_segments + src_i))
        return faces
    removed_idx = infer_removed_ring_index(old_ring or [], new_ring or []) if old_ring and new_ring else 0
    faces = []
    for i in range(old_segments):
        if i == removed_idx:
            continue
        j = (i + 1) % old_segments
        dst_i = i if i < removed_idx else i - 1
        dst_j = j if j < removed_idx else j - 1
        faces.append((dst_i, dst_j, old_segments + j, old_segments + i))
    return faces


def remap_tail_face_after_connection_change(face, old_segments, new_segments):
    if old_segments == new_segments:
        return face
    return face


def infer_tail_lower_ring_count(mesh, connection_count):
    if connection_count <= 0 or mesh is None or len(mesh.vertices) == 0:
        return 0
    vert_count = len(mesh.vertices)
    if vert_count % connection_count == 0:
        return vert_count // connection_count - 1
    return max(0, vert_count // max(1, connection_count) - 1)


def retopologize_tail_connection(tail_obj, last_ring, old_segments, new_segments, new_direction):
    if old_segments == new_segments:
        return True
    mesh = tail_obj.data
    verts = [v.co.copy() for v in mesh.vertices]
    old_ring = get_stored_tail_connection_ring(tail_obj, old_segments) or verts[:old_segments]
    old_direction = Vector(tail_obj.get("hair_pipe_tail_direction", (0, 0, 1)))
    transformed = transform_tail_vertices_by_connection(verts, old_ring, last_ring, old_direction, new_direction)
    return rebuild_tail_grid(mesh, transformed, old_segments, new_segments, last_ring)


def update_tail_mesh_connection(tail_obj, last_ring, segments, new_direction):
    mesh = tail_obj.data
    old_segments = len(get_stored_tail_connection_ring(tail_obj, segments) or []) or segments
    if old_segments != segments:
        retopologize_tail_connection(tail_obj, last_ring, old_segments, segments, new_direction)
    else:
        verts = [v.co.copy() for v in mesh.vertices]
        old_ring = get_stored_tail_connection_ring(tail_obj, segments) or verts[:segments]
        old_direction = Vector(tail_obj.get("hair_pipe_tail_direction", (0, 0, 1)))
        transformed = transform_tail_vertices_by_connection(verts, old_ring, last_ring, old_direction, new_direction)
        for v, co in zip(mesh.vertices, transformed):
            v.co = co
        mesh.update()
    store_tail_connection_state(tail_obj, last_ring, new_direction)


def update_tail_mesh_for_curve(curve_obj, settings, pipe_verts):
    from .hair_lifecycle import get_tail_object_for_curve
    tail_obj = get_tail_object_for_curve(curve_obj)
    if tail_obj is None or not pipe_verts:
        return
    segments = len(settings.point_settings[0].cross_section_verts) if settings.point_settings else 0
    if segments < 3:
        return
    last_ring = pipe_verts[-segments:]
    direction = estimate_tail_direction_from_vertices(pipe_verts, segments)
    update_tail_mesh_connection(tail_obj, last_ring, segments, direction)
