import bpy
import math
from mathutils import Vector, Matrix
from .hair_lifecycle import (
    get_next_figuhair_base_name as lifecycle_get_next_figuhair_base_name,
    get_figuhair_root as lifecycle_get_figuhair_root,
    ensure_figuhair_root as lifecycle_ensure_figuhair_root,
    get_pipe_mesh_name as lifecycle_get_pipe_mesh_name,
    get_pipe_object_for_curve as lifecycle_get_pipe_object_for_curve,
    get_context_curve_object as lifecycle_get_context_curve_object,
    set_generated_object_transform as lifecycle_set_generated_object_transform,
    generated_pipe_vertices as lifecycle_generated_pipe_vertices,
)
from .curve_data import ensure_curve_defaults as curve_ensure_curve_defaults, get_curve_points_data as curve_get_curve_points_data, is_curve_edit_mode as curve_is_curve_edit_mode
from .point_data import sync_point_settings as point_sync_point_settings
from .pipe_generation import generate_pipe_mesh as pipe_generate_pipe_mesh
from .cross_section import normalize_cross_section_topology as cross_section_normalize_cross_section_topology
from .ghost import update_all_ghost_vertices as ghost_update_all_ghost_vertices
from .math_utils import safe_normalized as math_safe_normalized, get_cross_section_frame as math_get_cross_section_frame
from .sampling import get_bezier_control_tangent as sampling_get_bezier_control_tangent
from .frames import build_minimal_twist_rings as frames_build_minimal_twist_rings
from .selection import ensure_selected_curve_visible as selection_ensure_selected_curve_visible

# tail modifier stack is defined in this module (previously erroneously imported from tail_utils)


def ensure_tail_edit_proxy(tail_obj):
    proxy_name = tail_obj.name + " Edit"
    proxy_obj = bpy.data.objects.get(proxy_name)
    if proxy_obj is not None and proxy_obj.data == tail_obj.data:
        proxy_obj["hair_pipe_tail_edit_proxy_source"] = tail_obj.name
        proxy_obj.parent = None
        proxy_obj.matrix_world = Matrix.Identity(4)
        proxy_obj.display_type = 'TEXTURED'
        proxy_obj.show_in_front = False
        proxy_obj.hide_render = True
        return proxy_obj
    for obj in bpy.data.objects:
        if obj.get("hair_pipe_tail_edit_proxy_source") == tail_obj.name and obj.data == tail_obj.data:
            obj.name = proxy_name
            obj.parent = None
            obj.matrix_world = Matrix.Identity(4)
            obj.display_type = 'TEXTURED'
            obj.show_in_front = False
            obj.hide_render = True
            return obj
    proxy_obj = bpy.data.objects.new(proxy_name, tail_obj.data)
    target_collection = tail_obj.users_collection[0] if tail_obj.users_collection else bpy.context.scene.collection
    target_collection.objects.link(proxy_obj)
    proxy_obj["hair_pipe_tail_edit_proxy_source"] = tail_obj.name
    proxy_obj.parent = None
    proxy_obj.matrix_world = Matrix.Identity(4)
    proxy_obj.display_type = 'TEXTURED'
    proxy_obj.show_in_front = False
    proxy_obj.hide_render = True
    return proxy_obj



def detach_keep_world(obj):
    if obj is None or obj.parent is None:
        return
    world_matrix = obj.matrix_world.copy()
    obj.parent = None
    obj.matrix_world = world_matrix



def parent_keep_world(obj, parent_obj):
    world_matrix = obj.matrix_world.copy()
    obj.parent = parent_obj
    obj.matrix_world = world_matrix



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



def _endpoint_driven_frames(centers, raw_tangents, is_cyclic=False, start_normal=None, roll_mode='START_FIXED'):
    if not raw_tangents:
        return []
    if is_cyclic or start_normal is None:
        return _minimal_twist_frames_from_tangents(raw_tangents, is_cyclic)
    first_tangent = safe_normalized(raw_tangents[0])
    anchor_normal = start_normal.copy()
    anchor_normal = anchor_normal - first_tangent * anchor_normal.dot(first_tangent)
    if anchor_normal.length < 1e-8:
        anchor_normal, _tmp = get_cross_section_frame(first_tangent)
    else:
        anchor_normal.normalize()
    anchor_binormal = first_tangent.cross(anchor_normal)
    if anchor_binormal.length < 1e-8:
        _unused_normal, anchor_binormal = get_cross_section_frame(first_tangent)
    else:
        anchor_binormal.normalize()
    frames = []
    for raw_tangent in raw_tangents:
        tangent = safe_normalized(raw_tangent, first_tangent)
        dot = max(-1.0, min(1.0, first_tangent.dot(tangent)))
        if dot > 0.9995:
            normal = anchor_normal - tangent * anchor_normal.dot(tangent)
            if normal.length < 1e-8:
                normal = anchor_binormal - tangent * anchor_binormal.dot(tangent)
        elif dot < -0.9995:
            normal = -anchor_normal - tangent * (-anchor_normal).dot(tangent)
            if normal.length < 1e-8:
                normal = anchor_binormal - tangent * anchor_binormal.dot(tangent)
        else:
            try:
                q = first_tangent.rotation_difference(tangent)
                normal = q @ anchor_normal
            except Exception:
                normal = anchor_normal - tangent * anchor_normal.dot(tangent)
                if normal.length < 1e-8:
                    normal = anchor_binormal - tangent * anchor_binormal.dot(tangent)
        normal = normal - tangent * normal.dot(tangent)
        if normal.length < 1e-8:
            normal, binormal = get_cross_section_frame(tangent)
        else:
            normal.normalize()
            binormal = tangent.cross(normal).normalized()
        frames.append((tangent, normal, binormal))
    return frames



def ensure_pipe_subdivision_modifier(pipe_obj, show_viewport=True, levels=2):
    modifier = pipe_obj.modifiers.get("FiguHair Catmull-Clark")
    if modifier is None:
        modifier = pipe_obj.modifiers.new("FiguHair Catmull-Clark", 'SUBSURF')
    levels = max(0, min(int(levels), 6))
    modifier.subdivision_type = 'CATMULL_CLARK'
    modifier.levels = levels
    modifier.render_levels = levels
    modifier.show_viewport = show_viewport
    modifier.show_render = True
    # Catmull-Clark 在极度拉长的管段上会鼓胀；启用边界锐化可抑制端部外翻
    try:
        modifier.use_limit_surface = True
        if hasattr(modifier, 'use_creases'):
            pass
    except Exception:
        pass
    return modifier


def _configure_subdiv_edge_crease(pipe_obj, segments):
    # 已移除纵向折痕功能：不再对任何边加 crease，保持 Catmull-Clark 正常圆顺
    try:
        clear_boulder_crease(pipe_obj)
    except Exception:
        pass


def clear_boulder_crease(pipe_obj):
    """清除所有纵向/任意边的 crease，恢复细分后的圆顺效果。"""
    if pipe_obj is None or getattr(pipe_obj, "type", None) != 'MESH':
        return
    mesh = getattr(pipe_obj, "data", None)
    if mesh is None or len(getattr(mesh, "edges", [])) == 0:
        return
    try:
        if "crease_edge" in mesh.attributes:
            try:
                attr = mesh.attributes["crease_edge"]
                vals = [0.0] * len(mesh.edges)
                try:
                    attr.data.foreach_set("value", vals)
                except Exception:
                    for i in range(len(vals)):
                        try: attr.data[i].value = 0.0
                        except: pass
            except Exception:
                pass
        for e in mesh.edges:
            try: e.crease = 0.0
            except: pass
        try: mesh.update()
        except: pass
        try: pipe_obj.update_tag()
        except: pass
    except Exception:
        pass


def apply_boulder_crease_to_pipe(pipe_obj, curve_obj=None, segments_override=None):
    """兼容旧调用：现在一律清除折痕，不再制造棱角。"""
    clear_boulder_crease(pipe_obj)


def move_modifier_before(pipe_obj, modifier, before_modifier):
    if modifier is None or before_modifier is None or modifier == before_modifier:
        return
    names = [mod.name for mod in pipe_obj.modifiers]
    if modifier.name not in names or before_modifier.name not in names:
        return
    from_index = names.index(modifier.name)
    to_index = names.index(before_modifier.name)
    if from_index > to_index:
        pipe_obj.modifiers.move(from_index, to_index)


def ensure_tail_join_geometry_nodes(pipe_obj, tail_obj):
    if pipe_obj is None or tail_obj is None:
        return None
    modifier = pipe_obj.modifiers.get("FiguHair Join Tail")
    if modifier is None:
        modifier = pipe_obj.modifiers.new("FiguHair Join Tail", 'NODES')

    group = modifier.node_group
    if group is None or not group.get("figuhair_tail_join") or group.get("figuhair_tail_join_version", 0) < 2:
        group = bpy.data.node_groups.new(pipe_obj.name + " Tail Join", 'GeometryNodeTree')
        group["figuhair_tail_join"] = True
        group["figuhair_tail_join_version"] = 2
        try:
            group.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
            group.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
        except Exception:
            pass

        nodes = group.nodes
        links = group.links
        nodes.clear()
        group_input = nodes.new('NodeGroupInput')
        group_input.location = (-520, 0)
        object_info = nodes.new('GeometryNodeObjectInfo')
        object_info.location = (-520, -180)
        join_geometry = nodes.new('GeometryNodeJoinGeometry')
        join_geometry.location = (-250, -70)
        merge_by_distance = nodes.new('GeometryNodeMergeByDistance')
        merge_by_distance.location = (40, -70)
        group_output = nodes.new('NodeGroupOutput')
        group_output.location = (340, -70)
        try:
            object_info.inputs['Object'].default_value = tail_obj
        except Exception:
            pass
        try:
            object_info.inputs['As Instance'].default_value = False
        except Exception:
            pass
        try:
            merge_by_distance.inputs['Distance'].default_value = 0.0001
        except Exception:
            pass
        try:
            links.new(group_input.outputs['Geometry'], join_geometry.inputs['Geometry'])
            links.new(object_info.outputs['Geometry'], join_geometry.inputs['Geometry'])
            links.new(join_geometry.outputs['Geometry'], merge_by_distance.inputs['Geometry'])
            links.new(merge_by_distance.outputs['Geometry'], group_output.inputs['Geometry'])
        except Exception:
            pass
        modifier.node_group = group
    else:
        for node in group.nodes:
            if node.bl_idname == 'GeometryNodeObjectInfo':
                try:
                    node.inputs['Object'].default_value = tail_obj
                except Exception:
                    pass
    return modifier


def ensure_tail_modifier_stack(pipe_obj, tail_obj, settings=None):
    join_modifier = ensure_tail_join_geometry_nodes(pipe_obj, tail_obj)
    show_viewport = True if settings is None else settings.default_subdiv
    levels = 2 if settings is None else settings.subdivision_levels
    subdiv_modifier = ensure_pipe_subdivision_modifier(pipe_obj, show_viewport, levels)
    move_modifier_before(pipe_obj, join_modifier, subdiv_modifier)
    return join_modifier, subdiv_modifier


def get_last_ring_from_pipe_vertices(verts, settings):
    if not verts or len(settings.point_settings) == 0:
        return None
    last_setting = settings.point_settings[-1]
    segments = len(last_setting.cross_section_verts)
    if segments < 3 or len(verts) < segments:
        return None
    return list(verts[-segments:]), segments


# removed alias wrapper def estimate_tail_direction_from_vertices(*args, **kwargs): — kept in operators.py
# removed alias wrapper def create_tail_mesh_geometry(*args, **kwargs): — kept in operators.py
# removed alias wrapper def flatten_ring_points(*args, **kwargs): — kept in operators.py
# removed alias wrapper def get_stored_tail_connection_ring(*args, **kwargs): — kept in operators.py
# removed alias wrapper def store_tail_connection_state(*args, **kwargs): — kept in operators.py
# removed alias wrapper def build_tail_connection_basis(*args, **kwargs): — kept in operators.py
# removed alias wrapper def transform_tail_vertices_by_connection(*args, **kwargs): — kept in operators.py
# removed alias wrapper def resample_ring_points(*args, **kwargs): — kept in operators.py
# removed alias wrapper def rebuild_tail_grid(*args, **kwargs): — kept in operators.py
# removed alias wrapper def get_tail_pose_rotation(*args, **kwargs): — kept in operators.py
# removed alias wrapper def sanitize_faces(*args, **kwargs): — kept in operators.py
# removed alias wrapper def rebuild_mesh_safely(*args, **kwargs): — kept in operators.py
# removed alias wrapper def shade_mesh_smooth(*args, **kwargs): — kept in operators.py
# removed alias wrapper def infer_inserted_ring_index(*args, **kwargs): — kept in operators.py
# removed alias wrapper def infer_removed_ring_index(*args, **kwargs): — kept in operators.py
# removed alias wrapper def make_tail_bridge_faces(*args, **kwargs): — kept in operators.py
def remap_index_after_connection_change(index, old_segments, new_segments, inserted_index=None):
    if index >= old_segments:
        return index - old_segments + new_segments
    if inserted_index is None:
        return index
    return index if index < inserted_index else index + 1


def split_face_for_inserted_connection_point(face, before_new, after_new, inserted_index):
    count = len(face)
    if count < 3:
        return []
    for i, current in enumerate(face):
        nxt = face[(i + 1) % count]
        if current == before_new and nxt == after_new:
            expanded = list(face)
            expanded.insert(i + 1, inserted_index)
            if len(face) == 4:
                lower_a = face[(i - 1) % count]
                lower_b = face[(i + 2) % count]
                return [
                    (before_new, inserted_index, lower_a),
                    (inserted_index, after_new, lower_b, lower_a),
                ]
            return [tuple(expanded)]
        if current == after_new and nxt == before_new:
            expanded = list(face)
            expanded.insert(i + 1, inserted_index)
            if len(face) == 4:
                lower_a = face[(i - 1) % count]
                lower_b = face[(i + 2) % count]
                return [
                    (after_new, inserted_index, lower_a),
                    (inserted_index, before_new, lower_b, lower_a),
                ]
            return [tuple(expanded)]
    return [tuple(face)]


def remap_bridge_faces_for_single_insert(old_faces, old_segments, new_segments, old_ring, new_ring):
    inserted_index = infer_inserted_ring_index(old_ring, new_ring)
    before_old = (inserted_index - 1) % old_segments
    after_old = before_old + 1
    if after_old >= old_segments:
        after_old = 0
    before_new = remap_index_after_connection_change(before_old, old_segments, new_segments, inserted_index)
    after_new = remap_index_after_connection_change(after_old, old_segments, new_segments, inserted_index)

    faces = []
    for old_face in old_faces:
        remapped = []
        has_connection_vertex = False
        for index in old_face:
            if index < old_segments:
                has_connection_vertex = True
            remapped.append(remap_index_after_connection_change(index, old_segments, new_segments, inserted_index))
        if has_connection_vertex:
            faces.extend(split_face_for_inserted_connection_point(remapped, before_new, after_new, inserted_index))
        else:
            faces.append(tuple(remapped))
    return [tuple(face) for face in faces if len(set(face)) >= 3]


def face_uses_first_ring(face, old_segments):
    return any(index < old_segments for index in face)


# removed alias wrapper def remap_tail_face_after_connection_change(*args, **kwargs): — kept in operators.py
# removed alias wrapper def infer_tail_lower_ring_count(*args, **kwargs): — kept in operators.py
# removed alias wrapper def retopologize_tail_connection(*args, **kwargs): — kept in operators.py
# removed alias wrapper def update_tail_mesh_connection(*args, **kwargs): — kept in operators.py
# removed alias wrapper def update_tail_mesh_for_curve(*args, **kwargs): — kept in operators.py
def configure_pipe_object(pipe_obj, curve_obj):
    root_obj = ensure_figuhair_root(curve_obj)
    base_name = curve_obj.get("hair_pipe_base_name", root_obj.name)

    root_obj.name = base_name
    curve_obj.name = base_name + " Curve"
    curve_obj.data.name = base_name + " Curve"
    pipe_obj.name = base_name + " Mesh"
    pipe_obj.data.name = pipe_obj.name

    pipe_obj["hair_pipe_source_curve"] = curve_obj.name
    if root_obj is not curve_obj:
        parent_keep_world(curve_obj, root_obj)
    set_generated_object_transform(pipe_obj, curve_obj)

    pipe_obj.show_in_front = False
    pipe_obj.hide_select = False
    # 必须确保细分修改器存在（修复添加头发没有细分的问题）
    try:
        ensure_pipe_subdivision_modifier(
            pipe_obj,
            bool(curve_obj.hair_pipe_settings.default_subdiv),
            int(curve_obj.hair_pipe_settings.subdivision_levels),
        )
    except Exception as _e:
        print(f"[FiguHair] ensure subdiv failed: {_e}")
        try:
            ensure_pipe_subdivision_modifier(pipe_obj, True, 2)
        except Exception:
            pass
    # 已移除纵向折痕：确保网格无 crease，保持圆顺
    try:
        clear_boulder_crease(pipe_obj)
    except Exception:
        pass
    # 强制刷新
    try:
        pipe_obj.update_tag()
        if hasattr(pipe_obj.data, "update_tag"):
            pipe_obj.data.update_tag()
    except Exception:
        pass
    pipe_obj.select_set(False)


def ensure_selected_curve_visible(curve_obj):
    return selection_ensure_selected_curve_visible(curve_obj)
def sync_selected_curve_visibility(context):
    return selection_sync_selected_curve_visibility(context)
def redirect_pipe_selection(context, pipe_obj=None):
    return selection_redirect_pipe_selection(context, pipe_obj)
def get_curve_point_by_global_index(curve_obj, target_index):
    return edit_get_curve_point_by_global_index(curve_obj, target_index)
def edge_flow_t(mode, t, power):
    return edit_edge_flow_t(mode, t, power)
def lerp_angle(a, b, t):
    return math_lerp_angle(a, b, t)
def lerp_radians(a, b, t):
    return math_lerp_radians(a, b, t)
def find_previous_edge_flow_source_index(point_settings, idx, target_indices):
    return edit_find_previous_edge_flow_source_index(point_settings, idx, target_indices)
def find_next_edge_flow_source_index(point_settings, idx, target_indices):
    return edit_find_next_edge_flow_source_index(point_settings, idx, target_indices)
def apply_edge_flow_to_target_indices(curve_obj, settings, target_indices, mode, power, blend):
    return edit_apply_edge_flow_to_target_indices(curve_obj, settings, target_indices, mode, power, blend)
def _edge_key(a, b):
    return (a, b) if a < b else (b, a)


def _ordered_boundary_loops(mesh):
    edge_faces = {}
    for poly in mesh.polygons:
        verts = list(poly.vertices)
        for idx, v0 in enumerate(verts):
            v1 = verts[(idx + 1) % len(verts)]
            edge_faces.setdefault(_edge_key(v0, v1), []).append(poly.index)

    boundary_adj = {}
    for edge, faces in edge_faces.items():
        if len(faces) == 1:
            a, b = edge
            boundary_adj.setdefault(a, []).append(b)
            boundary_adj.setdefault(b, []).append(a)

    loops = []
    visited_edges = set()
    for start, neighbors in boundary_adj.items():
        for first_next in neighbors:
            edge = _edge_key(start, first_next)
            if edge in visited_edges:
                continue
            loop = [start]
            prev = start
            cur = first_next
            visited_edges.add(edge)
            while True:
                loop.append(cur)
                next_candidates = [v for v in boundary_adj.get(cur, []) if v != prev]
                if not next_candidates:
                    break
                nxt = next_candidates[0]
                next_edge = _edge_key(cur, nxt)
                if nxt == start:
                    visited_edges.add(next_edge)
                    break
                if next_edge in visited_edges:
                    break
                visited_edges.add(next_edge)
                prev, cur = cur, nxt
            if len(loop) >= 3:
                loops.append(loop)
    return loops


def _mesh_edge_maps(mesh):
    edge_to_faces = {}
    vertex_to_edges = {}
    for poly in mesh.polygons:
        verts = list(poly.vertices)
        for idx, v0 in enumerate(verts):
            v1 = verts[(idx + 1) % len(verts)]
            key = _edge_key(v0, v1)
            edge_to_faces.setdefault(key, []).append(poly.index)
            vertex_to_edges.setdefault(v0, set()).add(key)
            vertex_to_edges.setdefault(v1, set()).add(key)
    return edge_to_faces, vertex_to_edges


def _connected_unvisited_edges(seed_edge, available_edges):
    component = set()
    stack = [seed_edge]
    while stack:
        edge = stack.pop()
        if edge in component or edge not in available_edges:
            continue
        component.add(edge)
        a, b = edge
        for other in available_edges:
            if other in component:
                continue
            if a in other or b in other:
                stack.append(other)
    return component


def _order_cycle_edges(edges):
    if not edges:
        return None
    adj = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    if any(len(neighbors) != 2 for neighbors in adj.values()):
        return None
    start = next(iter(adj))
    loop = [start]
    prev = None
    cur = start
    for _ in range(len(adj)):
        neighbors = adj[cur]
        nxt = neighbors[0] if neighbors[0] != prev else neighbors[1]
        if nxt == start:
            return loop if len(loop) == len(adj) else None
        if nxt in loop:
            return None
        loop.append(nxt)
        prev, cur = cur, nxt
    return None


def _ring_from_cap_faces(mesh):
    candidates = []
    for poly in mesh.polygons:
        if len(poly.vertices) >= 3:
            candidates.append((poly.index, list(poly.vertices)))
    return max(candidates, key=lambda item: len(item[1])) if candidates else (None, None)


def _extract_rings_by_ordered_quads(mesh, start_ring, edge_to_faces, initially_used_faces=None):
    rings = [start_ring]
    used_faces = set(initially_used_faces or [])
    max_steps = max(1, len(mesh.polygons) + 1)
    for _ in range(max_steps):
        next_ring, step_faces = _step_ring_by_ordered_quads(mesh, rings[-1], used_faces, edge_to_faces)
        if next_ring is None:
            break
        if set(next_ring) == set(rings[-1]):
            break
        rings.append(next_ring)
        used_faces.update(step_faces)
    return rings if len(rings) >= 2 else None


def extract_tube_rings_from_mesh(mesh):
    edge_to_faces, vertex_to_edges = _mesh_edge_maps(mesh)
    boundary_loops = _ordered_boundary_loops(mesh)
    cap_face_index = None
    if boundary_loops:
        start_ring = max(boundary_loops, key=len)
    else:
        cap_face_index, start_ring = _ring_from_cap_faces(mesh)
    if not start_ring or len(start_ring) < 3:
        return None

    quad_rings = _extract_rings_by_ordered_quads(
        mesh,
        start_ring,
        edge_to_faces,
        {cap_face_index} if cap_face_index is not None else None,
    )
    if quad_rings and len(quad_rings) >= 3:
        return quad_rings

    rings = [start_ring]
    current_ring = start_ring
    used_edges = set(_edge_key(current_ring[i], current_ring[(i + 1) % len(current_ring)]) for i in range(len(current_ring)))
    used_vertices = set(current_ring)
    max_steps = max(1, len(mesh.vertices))

    for _ in range(max_steps):
        candidate_edges = set()
        for vert_idx in current_ring:
            for edge in vertex_to_edges.get(vert_idx, set()):
                if edge not in used_edges:
                    candidate_edges.add(edge)
        if not candidate_edges:
            break

        best_loop = None
        best_component = None
        for seed in list(candidate_edges):
            component = _connected_unvisited_edges(seed, candidate_edges)
            loop = _order_cycle_edges(component)
            if not loop:
                continue
            outside_count = sum(1 for v in loop if v not in used_vertices)
            if outside_count == 0:
                continue
            if best_loop is None or outside_count > sum(1 for v in best_loop if v not in used_vertices):
                best_loop = loop
                best_component = component
        if not best_loop or not best_component:
            break

        if len(best_loop) != len(start_ring):
            break
        rings.append(best_loop)
        used_edges.update(best_component)
        used_vertices.update(best_loop)
        current_ring = best_loop

    if len(rings) >= 3:
        return rings

    open_rings = _extract_open_tube_rings_by_faces(mesh, boundary_loops, edge_to_faces)
    if open_rings and len(open_rings) > len(rings):
        return open_rings
    return rings if len(rings) >= 2 else None


def _extract_open_tube_rings_by_faces(mesh, loops, edge_to_faces):
    if not loops:
        return None
    start_ring = max(loops, key=len)
    rings = [start_ring]
    used_faces = set()
    max_steps = max(1, len(mesh.polygons) + 1)
    for _ in range(max_steps):
        next_ring, step_faces = _step_ring_by_ordered_quads(mesh, rings[-1], used_faces, edge_to_faces)
        if next_ring is None:
            break
        rings.append(next_ring)
        used_faces.update(step_faces)
        next_set = set(next_ring)
        if any(next_set == set(loop) for loop in loops if set(loop) != set(start_ring)):
            break
    if len(rings) < 2:
        return None
    return rings


def _step_ring_by_ordered_quads(mesh, ring, used_faces, edge_to_faces):
    count = len(ring)
    step_faces = []
    ring_set = set(ring)
    next_by_current = {}

    for idx in range(count):
        a = ring[idx]
        b = ring[(idx + 1) % count]
        face_index = None
        for candidate in edge_to_faces.get(_edge_key(a, b), []):
            if candidate not in used_faces and len(mesh.polygons[candidate].vertices) == 4:
                face_index = candidate
                break
        if face_index is None:
            return None, []

        verts = list(mesh.polygons[face_index].vertices)
        if sum(1 for v in verts if v in ring_set) != 2:
            return None, []

        try:
            a_pos = verts.index(a)
            b_pos = verts.index(b)
        except ValueError:
            return None, []

        if verts[(a_pos + 1) % 4] == b:
            next_a = verts[(a_pos - 1) % 4]
            next_b = verts[(b_pos + 1) % 4]
        elif verts[(b_pos + 1) % 4] == a:
            next_a = verts[(a_pos + 1) % 4]
            next_b = verts[(b_pos - 1) % 4]
        else:
            return None, []

        if next_a in ring_set or next_b in ring_set or next_a == next_b:
            return None, []
        if next_by_current.get(a, next_a) != next_a or next_by_current.get(b, next_b) != next_b:
            return None, []
        next_by_current[a] = next_a
        next_by_current[b] = next_b
        step_faces.append(face_index)

    if len(next_by_current) != count:
        return None, []
    next_ring = [next_by_current[vert_idx] for vert_idx in ring]
    if len(set(next_ring)) != count:
        return None, []
    return next_ring, step_faces


def _ring_center_from_indices(ring, positions):
    center = Vector((0.0, 0.0, 0.0))
    for vert_idx in ring:
        center += positions[vert_idx]
    return center / max(1, len(ring))


def _best_aligned_ring_order(previous_ring, current_ring, positions, previous_center, current_center):
    count = len(current_ring)
    if count <= 2 or len(previous_ring) != count:
        return current_ring
    previous_offsets = [positions[v] - previous_center for v in previous_ring]
    best_score = None
    best_ring = current_ring
    for flip in (False, True):
        candidate = list(reversed(current_ring)) if flip else list(current_ring)
        for shift in range(count):
            ordered = candidate[shift:] + candidate[:shift]
            score = 0.0
            for idx, vert_idx in enumerate(ordered):
                offset = positions[vert_idx] - current_center
                score += (offset - previous_offsets[idx]).length_squared
            if best_score is None or score < best_score:
                best_score = score
                best_ring = ordered
    return best_ring


def _align_ring_orders(rings, positions, centers):
    if not rings:
        return rings
    aligned = [list(rings[0])]
    for idx in range(1, len(rings)):
        aligned.append(_best_aligned_ring_order(
            aligned[-1],
            list(rings[idx]),
            positions,
            centers[idx - 1],
            centers[idx],
        ))
    return aligned


def _curve_tangent_at_center(centers, idx):
    if len(centers) <= 1:
        return Vector((0.0, 0.0, 1.0))
    if idx == 0:
        return centers[1] - centers[0]
    if idx == len(centers) - 1:
        return centers[-1] - centers[-2]
    return centers[idx + 1] - centers[idx - 1]


def _minimal_twist_frames_for_centers_legacy_unused(centers):
    if not centers:
        return []
    first_tangent = safe_normalized(_curve_tangent_at_center(centers, 0))
    normal, binormal = get_cross_section_frame(first_tangent)
    frames = [(first_tangent, normal.copy(), binormal.copy())]
    prev_tangent = first_tangent
    for idx in range(1, len(centers)):
        tangent = safe_normalized(_curve_tangent_at_center(centers, idx), prev_tangent)
        if prev_tangent.length >= 1e-8 and tangent.length >= 1e-8:
            try:
                transport = prev_tangent.rotation_difference(tangent)
                normal = transport @ normal
            except ValueError:
                pass
        normal = normal - tangent * normal.dot(tangent)
        if normal.length < 1e-8:
            normal, binormal = get_cross_section_frame(tangent)
        else:
            normal.normalize()
            binormal = tangent.cross(normal).normalized()
        frames.append((tangent, normal.copy(), binormal.copy()))
        prev_tangent = tangent
    return frames


def _conversion_frames_for_start_fixed(centers):
    """Use the exact START-fixed frame convention used after conversion."""
    if not centers:
        return [], None, None
    tangents = [_curve_tangent_at_center(centers, idx) for idx in range(len(centers))]
    first_tangent = safe_normalized(tangents[0])
    anchor_normal, _anchor_binormal = get_cross_section_frame(first_tangent)
    frames = _endpoint_driven_frames(
        centers, tangents, False, anchor_normal, 'START_FIXED',
    )
    return frames, anchor_normal, first_tangent


def _signed_polygon_area_2d(points):
    area = 0.0
    count = len(points)
    for idx in range(count):
        x0, y0 = points[idx]
        x1, y1 = points[(idx + 1) % count]
        area += x0 * y1 - x1 * y0
    return area * 0.5


def make_hair_curve_from_tube_mesh(context, mesh_obj):
    depsgraph = context.evaluated_depsgraph_get()
    eval_obj = mesh_obj.evaluated_get(depsgraph)
    mesh = bpy.data.meshes.new_from_object(eval_obj, depsgraph=depsgraph)
    try:
        rings = extract_tube_rings_from_mesh(mesh)
        if not rings:
            return None, "无法识别管状网格：需要清晰的横截面边环，建议使用四边面管状拓扑"

        world_positions = [mesh_obj.matrix_world @ vert.co for vert in mesh.vertices]
        centers = [_ring_center_from_indices(ring, world_positions) for ring in rings]
        frames, start_anchor_normal, start_anchor_tangent = _conversion_frames_for_start_fixed(centers)

        curve_data = bpy.data.curves.new(mesh_obj.name + "_Curve", 'CURVE')
        curve_data.dimensions = '3D'
        curve_data.resolution_u = 1
        spline = curve_data.splines.new('NURBS')
        spline.points.add(len(centers) - 1)
        spline.order_u = min(4, len(centers))
        spline.use_endpoint_u = True
        for idx, center in enumerate(centers):
            spline.points[idx].co = (center.x, center.y, center.z, 1.0)
            spline.points[idx].radius = 1.0
            spline.points[idx].tilt = 0.0
            spline.points[idx].select = (idx == 0)

        curve_obj = bpy.data.objects.new(mesh_obj.name + "_FiguHairCurve", curve_data)
        target_collection = mesh_obj.users_collection[0] if mesh_obj.users_collection else context.scene.collection
        target_collection.objects.link(curve_obj)
        curve_obj.matrix_world = Matrix.Identity(4)
        curve_obj["hair_pipe_base_name"] = mesh_obj.name + " Restored"
        ensure_figuhair_root(curve_obj)
        ensure_curve_defaults(curve_obj)
        settings = curve_obj.hair_pipe_settings
        settings.pipe_resolution = 0
        settings.default_segments = len(rings[0])
        settings.default_subdiv = True
        settings.subdivision_levels = 2
        settings.redirect_selection = True
        settings.roll_mode = 'START_FIXED'
        if start_anchor_normal is not None:
            curve_obj["hair_pipe_start_roll_anchor_normal"] = tuple(start_anchor_normal)
            curve_obj["hair_pipe_start_roll_anchor_tangent"] = tuple(start_anchor_tangent)
        sync_point_settings(curve_obj)

        first_area_checked = False
        reverse_all_sections = False
        for idx, ring in enumerate(rings):
            _, normal, binormal = frames[idx]
            raw_offsets = []
            for vert_idx in ring:
                offset = world_positions[vert_idx] - centers[idx]
                raw_offsets.append((offset.dot(normal), offset.dot(binormal)))
            if not first_area_checked and len(raw_offsets) >= 3:
                reverse_all_sections = _signed_polygon_area_2d(raw_offsets) < 0.0
                first_area_checked = True
            if reverse_all_sections:
                raw_offsets = list(reversed(raw_offsets))

            ps = settings.point_settings[idx]
            ps.cross_section_verts.clear()
            ps.rotation = 0.0
            ps.scale = 1.0
            for offset_x, offset_y in raw_offsets:
                v = ps.cross_section_verts.add()
                v.offset_x = offset_x
                v.offset_y = offset_y
                v.is_ghost = False
            ps.active_vert_index = 0

        normalize_cross_section_topology(settings, curve_obj)
        update_all_ghost_vertices(settings)
        if len(settings.point_settings) > 0:
            settings.active_point_index = 0
        mesh_obj["hair_pipe_import_source"] = True
        if "hair_pipe_source_curve" in mesh_obj:
            del mesh_obj["hair_pipe_source_curve"]
        mesh_obj.hide_select = False
        return curve_obj, None
    finally:
        bpy.data.meshes.remove(mesh)


class HAIRPIPE_OT_mesh_to_hair_curve(bpy.types.Operator):
    """Convert selected quad tube meshes back into FiguHair curves"""
    bl_idname = "hair_pipe.mesh_to_hair_curve"
    bl_label = "管状网格转头发曲线"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        mesh_objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not mesh_objects:
            self.report({'ERROR'}, "请选择一个或多个管状网格")
            return {'CANCELLED'}

        converted_curves = []
        errors = []
        for mesh_obj in mesh_objects:
            curve_obj, error = make_hair_curve_from_tube_mesh(context, mesh_obj)
            if error:
                errors.append(f"{mesh_obj.name}: {error}")
                continue

            for obj in context.selected_objects:
                obj.select_set(False)
            curve_obj.select_set(True)
            context.view_layer.objects.active = curve_obj
            result = bpy.ops.hair_pipe.generate_pipe()
            if 'FINISHED' not in result:
                errors.append(f"{mesh_obj.name}: 生成 FiguHair 管线失败")
                curve_data = curve_obj.data
                bpy.data.objects.remove(curve_obj, do_unlink=True)
                if curve_data.users == 0:
                    bpy.data.curves.remove(curve_data)
                continue

            converted_curves.append(curve_obj)
            mesh_data = mesh_obj.data
            bpy.data.objects.remove(mesh_obj, do_unlink=True)
            if mesh_data.users == 0:
                bpy.data.meshes.remove(mesh_data)

        for obj in context.selected_objects:
            obj.select_set(False)
        for curve_obj in converted_curves:
            curve_obj.select_set(True)
        if converted_curves:
            context.view_layer.objects.active = converted_curves[-1]

        if errors and not converted_curves:
            self.report({'ERROR'}, errors[0])
            return {'CANCELLED'}
        if errors:
            self.report({'WARNING'}, f"已转换 {len(converted_curves)} 个网格，{len(errors)} 个失败")
            return {'FINISHED'}

        self.report({'INFO'}, f"已从 {len(converted_curves)} 个管状网格生成 FiguHair 头发曲线")
        return {'FINISHED'}


class HAIRPIPE_OT_generate_pipe(bpy.types.Operator):
    """Generate pipe mesh from curve with per-point custom cross-sections"""
    bl_idname = "hair_pipe.generate_pipe"
    bl_label = "Generate Hair Pipe"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return get_context_curve_object(context) is not None

    def execute(self, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            self.report({'ERROR'}, "Select a curve or its FiguHair preview mesh")
            return {'CANCELLED'}
        settings = curve_obj.hair_pipe_settings
        ensure_curve_defaults(curve_obj)
        sync_point_settings(curve_obj)
        verts, faces = generate_pipe_mesh(curve_obj, settings)
        if verts is None:
            self.report({'ERROR'}, "Could not generate pipe from curve")
            return {'CANCELLED'}
        verts = generated_pipe_vertices(verts, curve_obj)
        mesh_name = get_pipe_mesh_name(curve_obj)
        existing_obj = get_pipe_object_for_curve(curve_obj)
        if existing_obj:
            mesh = existing_obj.data
            mesh.clear_geometry()
            mesh.from_pydata(verts, [], faces)
            mesh.update()
            pipe_obj = existing_obj
        else:
            mesh = bpy.data.meshes.new(mesh_name)
            mesh.from_pydata(verts, [], faces)
            mesh.update()
            pipe_obj = bpy.data.objects.new(mesh_name, mesh)
            context.collection.objects.link(pipe_obj)
        if settings.smooth_shading:
            for poly in mesh.polygons:
                poly.use_smooth = True
        configure_pipe_object(pipe_obj, curve_obj)
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


classes = (
    HAIRPIPE_OT_mesh_to_hair_curve,
    HAIRPIPE_OT_generate_pipe,
    HAIRPIPE_OT_sync_points,
)
