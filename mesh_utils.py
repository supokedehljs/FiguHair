"""mesh_utils — 纯网格工具，无 Blender 对象依赖以外的循环。"""
import bpy  # noqa: F401
from mathutils import Vector


def sanitize_faces(faces, vertex_count):
    clean_faces = []
    seen = set()
    for face in faces:
        clean = []
        for index in face:
            if isinstance(index, int) and 0 <= index < vertex_count and index not in clean:
                clean.append(index)
        if len(clean) < 3:
            continue
        key = tuple(clean)
        reverse_key = tuple(reversed(clean))
        if key in seen or reverse_key in seen:
            continue
        seen.add(key)
        clean_faces.append(tuple(clean))
    return clean_faces


def shade_mesh_smooth(mesh):
    for polygon in mesh.polygons:
        polygon.use_smooth = True


def rebuild_mesh_safely(mesh, verts, faces):
    clean_verts = [Vector(v) for v in verts]
    clean_faces = sanitize_faces(faces, len(clean_verts))
    mesh.clear_geometry()
    mesh.from_pydata(clean_verts, [], clean_faces)
    try:
        mesh.validate(clean_customdata=False)
    except Exception:
        try:
            mesh.validate()
        except Exception:
            pass
    mesh.update()
    shade_mesh_smooth(mesh)


def verts_to_world_space(verts, curve_obj):
    return [curve_obj.matrix_world @ Vector(v) for v in verts]


def flatten_ring_points(ring):
    values = []
    for point in ring:
        vector = Vector(point)
        values.extend((vector.x, vector.y, vector.z))
    return values


def resample_ring_points(ring, new_count):
    old_count = len(ring)
    if old_count == new_count:
        return [Vector(v) for v in ring]
    result = []
    for i in range(new_count):
        pos = i * old_count / new_count
        idx0 = int(int(pos) % old_count)
        idx1 = (idx0 + 1) % old_count
        t = pos - int(pos)
        result.append(Vector(ring[idx0]).lerp(Vector(ring[idx1]), t))
    return result
