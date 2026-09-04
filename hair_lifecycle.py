import bpy
from mathutils import Matrix, Vector


def get_next_figuhair_base_name():
    used_names = {obj.name for obj in bpy.data.objects}
    index = 1
    while True:
        name = f"FiguHair {index:02d}"
        if name not in used_names:
            return name
        index += 1


def get_curve_from_figuhair_root(root_obj):
    if root_obj is None:
        return None
    if root_obj.type == 'CURVE' and hasattr(root_obj, 'hair_pipe_settings'):
        return root_obj
    for child in root_obj.children:
        if child.type == 'CURVE' and hasattr(child, 'hair_pipe_settings'):
            return child
    return None


def get_figuhair_root(curve_obj):
    if curve_obj is None or curve_obj.type != 'CURVE':
        return None
    return curve_obj


def ensure_figuhair_root(curve_obj):
    if curve_obj is None or curve_obj.type != 'CURVE':
        return None
    base_name = curve_obj.get("hair_pipe_base_name")
    if not base_name:
        base_name = get_next_figuhair_base_name()
        curve_obj["hair_pipe_base_name"] = base_name
    if curve_obj.parent is not None:
        world_matrix = curve_obj.matrix_world.copy()
        curve_obj.parent = None
        curve_obj.matrix_world = world_matrix
    curve_obj.name = base_name + " Curve"
    curve_obj["hair_pipe_root"] = curve_obj.name
    return curve_obj


def get_pipe_mesh_name(curve_obj):
    return curve_obj.name + "_FiguHair"


def get_tail_mesh_name(curve_obj):
    return curve_obj.name + "_FiguHairTail"


def get_pipe_source_curve(pipe_obj):
    if pipe_obj is None or pipe_obj.type != 'MESH':
        return None
    if pipe_obj.parent is not None and pipe_obj.parent.type == 'CURVE':
        return pipe_obj.parent
    source_name = pipe_obj.get("hair_pipe_source_curve")
    curve_obj = bpy.data.objects.get(source_name) if source_name else None
    return curve_obj if curve_obj is not None and curve_obj.type == 'CURVE' else None


def get_tail_source_curve(tail_obj):
    return None


def get_pipe_object_for_curve(curve_obj):
    if curve_obj is None or curve_obj.type != 'CURVE':
        return None
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        if obj.get("hair_pipe_source_curve") == curve_obj.name:
            return obj
        if obj.parent == curve_obj and obj.name.endswith((" Mesh", "_FiguHair")):
            return obj
    for name in (get_pipe_mesh_name(curve_obj), curve_obj.name + "_FiguHair"):
        obj = bpy.data.objects.get(name)
        if obj is not None and obj.type == 'MESH':
            return obj
    return None


def get_tail_object_for_curve(curve_obj):
    return None


def generated_pipe_vertices(verts, curve_obj):
    return [Vector(vert) for vert in verts]


def set_generated_object_transform(obj, curve_obj):
    if obj is None:
        return
    obj.parent = curve_obj
    obj.matrix_parent_inverse = Matrix.Identity(4)
    obj.matrix_basis = Matrix.Identity(4)


def get_hair_root_object(curve_obj):
    root_obj = get_figuhair_root(curve_obj)
    if root_obj is not None:
        return root_obj
    if curve_obj is None:
        return None
    if curve_obj.parent is not None and curve_obj.parent.type == 'EMPTY' and curve_obj.parent.get("hair_pipe_root"):
        return curve_obj.parent
    root_name = curve_obj.name + "_FiguHair"
    obj = bpy.data.objects.get(root_name)
    if obj is not None and obj.type == 'EMPTY' and obj.get("hair_pipe_root"):
        return obj
    return None


def get_hair_family_objects(curve_obj):
    if curve_obj is None:
        return []
    objects = [curve_obj]
    for obj in (get_pipe_object_for_curve(curve_obj),):
        if obj is not None and obj not in objects:
            objects.append(obj)
    return objects


def delete_generated_for_curve(curve_obj):
    if curve_obj is None:
        return 0
    generated = []
    for obj in list(bpy.data.objects):
        if obj.type != 'MESH':
            continue
        source = obj.get("hair_pipe_source_curve") or obj.get("hair_pipe_tail_source_curve")
        if source == curve_obj.name or obj.parent == curve_obj:
            generated.append(obj)
    for obj in {item for item in generated}:
        bpy.data.objects.remove(obj, do_unlink=True)
    return len(generated)


def get_context_curve_object(context):
    candidates = [
        getattr(context, 'object', None),
        getattr(context, 'active_object', None),
    ]
    active_collection = getattr(getattr(context, 'view_layer', None), 'objects', None)
    if active_collection is not None:
        candidates.append(getattr(active_collection, 'active', None))
    candidates.extend(getattr(context, 'selected_objects', ()))
    for obj in candidates:
        if obj is None or not hasattr(obj, 'type'):
            continue
        if obj.type == 'CURVE' and hasattr(obj, 'hair_pipe_settings'):
            return obj
        if obj.type == 'EMPTY':
            curve = get_curve_from_figuhair_root(obj)
            if curve is not None:
                return curve
        curve = get_pipe_source_curve(obj) or get_tail_source_curve(obj)
        if curve is not None:
            return curve
    return None
