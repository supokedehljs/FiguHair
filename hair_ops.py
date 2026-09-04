"""hair_ops — 头发对象族操作（hide/show/local_view/delete/duplicate）"""
import bpy
from mathutils import Vector
from .hair_lifecycle import (
    get_next_figuhair_base_name,
    get_curve_from_figuhair_root,
    get_figuhair_root,
    get_pipe_object_for_curve,
    get_tail_object_for_curve,
    get_pipe_source_curve,
    get_tail_source_curve,
    get_context_curve_object,
    set_generated_object_transform,
)
# tail modifier stack lives in pipe_ops (not tail_utils) — import lazily to avoid cycle
try:
    from .pipe_ops import ensure_tail_modifier_stack as _ensure_tail_mod  # noqa: F401
except Exception:  # pragma: no cover - Blender startup order
    _ensure_tail_mod = None


def _is_pipe_mesh_obj(obj):
    if obj.type != 'MESH':
        return False
    if obj.get("hair_pipe_source_curve"):
        return True
    if obj.name.endswith(" Mesh") and obj.parent is not None and obj.parent.type == 'EMPTY':
        return bool(obj.parent.get("hair_pipe_root"))
    if obj.name.endswith("_FiguHair"):
        return True
    return False


def _is_tail_mesh_only_obj(obj):
    if obj.type != 'MESH':
        return False
    if obj.get("hair_pipe_tail_source_curve"):
        return True
    if obj.name.endswith(" Tail") and obj.parent is not None and obj.parent.type == 'EMPTY':
        return bool(obj.parent.get("hair_pipe_root"))
    if obj.name.endswith("_FiguHairTail"):
        return True
    return False


def _is_figuhair_family_obj(obj):
    if _is_pipe_mesh_obj(obj) or _is_tail_mesh_only_obj(obj):
        return True
    if obj.type == 'CURVE' and obj.get("hair_pipe_base_name"):
        return True
    if obj.type == 'EMPTY' and obj.get("hair_pipe_root"):
        return True
    return False


class HAIRPIPE_OT_hide_hair(bpy.types.Operator):
    """Hide selected complete FiguHair sets"""
    bl_idname = "hair_pipe.hide_hair"
    bl_label = "隐藏头发"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and get_context_curve_object(context) is not None

    def execute(self, context):
        curves = []
        for obj in list(context.selected_objects):
            curve_obj = (
                obj if obj.type == 'CURVE'
                else get_curve_from_figuhair_root(obj) if obj.type == 'EMPTY'
                else get_pipe_source_curve(obj) or get_tail_source_curve(obj)
            )
            if curve_obj is not None and curve_obj not in curves:
                curves.append(curve_obj)
        for curve_obj in curves:
            root_obj = get_figuhair_root(curve_obj)
            family = (
                root_obj,
                curve_obj,
                get_pipe_object_for_curve(curve_obj),
                get_tail_object_for_curve(curve_obj),
            )
            for o in family:
                if o is not None:
                    o.hide_set(True)
        return {'FINISHED'}


class HAIRPIPE_OT_show_all_hair(bpy.types.Operator):
    """Show all complete FiguHair sets"""
    bl_idname = "hair_pipe.show_all_hair"
    bl_label = "显示全部头发"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        bpy.ops.object.hide_view_clear(select=False)
        for obj in bpy.data.objects:
            if _is_figuhair_family_obj(obj):
                obj.hide_viewport = False
                obj.hide_set(False)
        return {'FINISHED'}


class HAIRPIPE_OT_family_local_view(bpy.types.Operator):
    """Toggle Blender local view for complete FiguHair sets"""
    bl_idname = "hair_pipe.family_local_view"
    bl_label = "整套头发单独显示"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (
            context.mode == 'OBJECT'
            and context.area is not None
            and context.area.type == 'VIEW_3D'
            and get_context_curve_object(context) is not None
        )

    def execute(self, context):
        if getattr(context.space_data, "local_view", None) is not None:
            bpy.ops.view3d.localview()
            return {'FINISHED'}
        curves = []
        for obj in list(context.selected_objects):
            curve_obj = (
                obj if obj.type == 'CURVE'
                else get_curve_from_figuhair_root(obj) if obj.type == 'EMPTY'
                else get_pipe_source_curve(obj) or get_tail_source_curve(obj)
            )
            if curve_obj is not None and curve_obj not in curves:
                curves.append(curve_obj)
        if not curves:
            curve_obj = get_context_curve_object(context)
            if curve_obj is not None:
                curves.append(curve_obj)
        family = []
        for curve_obj in curves:
            for o in (
                get_figuhair_root(curve_obj),
                curve_obj,
                get_pipe_object_for_curve(curve_obj),
                get_tail_object_for_curve(curve_obj),
            ):
                if o is not None and o not in family:
                    family.append(o)
        for o in list(context.selected_objects):
            o.select_set(False)
        for o in family:
            o.hide_set(False)
            o.select_set(True)
        bpy.ops.view3d.localview()
        for o in family:
            o.select_set(False)
        for curve_obj in curves:
            curve_obj.select_set(True)
        if curves:
            context.view_layer.objects.active = curves[-1]
        return {'FINISHED'}


class HAIRPIPE_OT_delete_hair(bpy.types.Operator):
    """Delete selected complete FiguHair hair sets"""
    bl_idname = "hair_pipe.delete_hair"
    bl_label = "删除头发"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return get_context_curve_object(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        selected_objects = list(getattr(context, 'selected_objects', ()))
        curve_objects = []
        seen_curves = set()

        def add_curve(curve_obj):
            if curve_obj is not None and curve_obj.type == 'CURVE' and curve_obj.name not in seen_curves:
                curve_objects.append(curve_obj)
                seen_curves.add(curve_obj.name)

        for obj in selected_objects:
            if obj is None:
                continue
            if obj.type == 'CURVE':
                add_curve(obj)
            elif obj.type == 'EMPTY':
                add_curve(get_curve_from_figuhair_root(obj))
            else:
                add_curve(get_pipe_source_curve(obj))
                add_curve(get_tail_source_curve(obj))
        if not curve_objects:
            add_curve(get_context_curve_object(context))
        objects_to_delete = []
        seen_objects = set()

        def add_object(obj):
            if obj is not None and obj.name not in seen_objects:
                objects_to_delete.append(obj)
                seen_objects.add(obj.name)

        for curve_obj in curve_objects:
            root_obj = get_figuhair_root(curve_obj)
            pipe_obj = get_pipe_object_for_curve(curve_obj)
            tail_obj = get_tail_object_for_curve(curve_obj)
            if root_obj is not None:
                for child in list(root_obj.children):
                    add_object(child)
                add_object(root_obj)
            add_object(pipe_obj)
            add_object(tail_obj)
            add_object(curve_obj)
        if not objects_to_delete:
            self.report({'WARNING'}, "没有找到可删除的头发")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass
        mesh_data = []
        curve_data = []
        for obj in objects_to_delete:
            data = getattr(obj, 'data', None)
            if obj.type == 'MESH' and data is not None:
                mesh_data.append(data)
            elif obj.type == 'CURVE' and data is not None:
                curve_data.append(data)
        for obj in objects_to_delete:
            if obj.name in bpy.data.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in mesh_data:
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        for curve in curve_data:
            if curve.users == 0:
                bpy.data.curves.remove(curve)
        self.report({'INFO'}, f"已删除 {len(curve_objects)} 个头发")
        return {'FINISHED'}


class HAIRPIPE_OT_duplicate_hair(bpy.types.Operator):
    """Duplicate the entire hair (root empty, curve, pipe mesh, tail mesh) and rename"""
    bl_idname = "hair_pipe.duplicate_hair"
    bl_label = "复制头发"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return get_context_curve_object(context) is not None

    def execute(self, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            return {'CANCELLED'}
        root_obj = get_figuhair_root(curve_obj)
        pipe_obj = get_pipe_object_for_curve(curve_obj)
        tail_obj = get_tail_object_for_curve(curve_obj)
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        src_curve_matrix = curve_obj.matrix_world.copy()
        src_pipe_matrix = pipe_obj.matrix_world.copy() if pipe_obj else None
        src_tail_matrix = tail_obj.matrix_world.copy() if tail_obj else None
        new_base = get_next_figuhair_base_name()
        target_col = (
            curve_obj.users_collection[0]
            if curve_obj.users_collection
            else context.scene.collection
        )
        new_curve_data = curve_obj.data.copy()
        new_curve_data.name = new_base + " Curve"
        new_curve = bpy.data.objects.new(new_base + " Curve", new_curve_data)
        new_curve["hair_pipe_base_name"] = new_base
        target_col.objects.link(new_curve)
        new_curve.matrix_world = src_curve_matrix
        new_curve["hair_pipe_root"] = new_curve.name
        src_s = curve_obj.hair_pipe_settings
        dst_s = new_curve.hair_pipe_settings
        for attr in (
            'default_radius', 'default_segments', 'pipe_resolution',
            'transition_mode', 'transition_strength',
            'strong_smoothing', 'strong_smoothing_iterations',
            'smooth_shading', 'auto_update', 'cap_ends', 'default_subdiv',
            'redirect_selection', 'edge_flow_mode', 'edge_flow_power',
            'edge_flow_blend', 'active_point_index',
        ):
            try:
                setattr(dst_s, attr, getattr(src_s, attr))
            except (AttributeError, TypeError):
                pass
        dst_s.point_settings.clear()
        for src_ps in src_s.point_settings:
            dst_ps = dst_s.point_settings.add()
            dst_ps.scale = src_ps.scale
            dst_ps.rotation = src_ps.rotation
            dst_ps.active_vert_index = src_ps.active_vert_index
            dst_ps.cross_section_verts.clear()
            for sv in src_ps.cross_section_verts:
                dv = dst_ps.cross_section_verts.add()
                dv.offset_x = sv.offset_x
                dv.offset_y = sv.offset_y
                dv.is_ghost = sv.is_ghost
        new_pipe = None
        if pipe_obj is not None:
            new_pipe_data = pipe_obj.data.copy()
            new_pipe_data.name = new_base + " Mesh"
            new_pipe = bpy.data.objects.new(new_base + " Mesh", new_pipe_data)
            new_pipe["hair_pipe_source_curve"] = new_curve.name
            new_pipe.show_in_front = pipe_obj.show_in_front
            new_pipe.hide_select = pipe_obj.hide_select
            new_pipe.hide_viewport = pipe_obj.hide_viewport
            new_pipe.display_type = pipe_obj.display_type
            target_col.objects.link(new_pipe)
            new_pipe.parent = None
            new_pipe.matrix_world = src_pipe_matrix
            for mod in pipe_obj.modifiers:
                if mod.name == "FiguHair Join Tail":
                    continue
                new_mod = new_pipe.modifiers.new(mod.name, mod.type)
                for attr in dir(mod):
                    if attr.startswith('_') or attr in {'bl_rna', 'rna_type', 'name', 'type', 'node_group'}:
                        continue
                    try:
                        setattr(new_mod, attr, getattr(mod, attr))
                    except (AttributeError, TypeError):
                        pass
        new_tail = None
        if tail_obj is not None:
            new_tail_data = tail_obj.data.copy()
            new_tail_data.name = new_base + " Tail"
            new_tail = bpy.data.objects.new(new_base + " Tail", new_tail_data)
            new_tail["hair_pipe_tail_source_curve"] = new_curve.name
            new_tail["hair_pipe_tail_ring_count"] = tail_obj.get("hair_pipe_tail_ring_count", 0)
            for key in (
                "hair_pipe_tail_direction", "hair_pipe_tail_connection_ring",
                "hair_pipe_tail_lower_ring_count", "hair_pipe_tail_user_hidden",
            ):
                val = tail_obj.get(key)
                if val is not None:
                    new_tail[key] = val
            new_tail.show_in_front = False
            new_tail.hide_render = True
            new_tail.hide_viewport = tail_obj.hide_viewport
            new_tail.display_type = tail_obj.display_type
            target_col.objects.link(new_tail)
            new_tail.parent = None
            new_tail.matrix_world = src_tail_matrix
            if new_pipe is not None and _ensure_tail_mod is not None:
                try:
                    _ensure_tail_mod(new_pipe, new_tail, new_curve.hair_pipe_settings)
                except Exception:
                    pass
        if new_pipe is not None:
            set_generated_object_transform(new_pipe, new_curve)
        if new_tail is not None:
            set_generated_object_transform(new_tail, new_curve)
        for o in context.selected_objects:
            o.select_set(False)
        new_curve.select_set(True)
        context.view_layer.objects.active = new_curve
        self.report({'INFO'}, f"已复制头发: {new_base}")
        return {'FINISHED'}


def _copy_spline_to_curve(source_spline, target_data, transform):
    target = target_data.splines.new(source_spline.type)
    if source_spline.type == 'BEZIER':
        target.bezier_points.add(max(0, len(source_spline.bezier_points) - 1))
        for source, destination in zip(source_spline.bezier_points, target.bezier_points):
            destination.co = transform @ source.co
            destination.handle_left = transform @ source.handle_left
            destination.handle_right = transform @ source.handle_right
            destination.handle_left_type = source.handle_left_type
            destination.handle_right_type = source.handle_right_type
            destination.radius = source.radius
            destination.tilt = source.tilt
    else:
        target.points.add(max(0, len(source_spline.points) - 1))
        for source, destination in zip(source_spline.points, target.points):
            co = transform @ Vector(source.co[:3])
            destination.co = (co.x, co.y, co.z, source.co[3])
            destination.radius = source.radius
            destination.tilt = source.tilt
        if source_spline.type == 'NURBS':
            target.order_u = source_spline.order_u
            target.use_endpoint_u = source_spline.use_endpoint_u
    target.use_cyclic_u = source_spline.use_cyclic_u
    target.resolution_u = source_spline.resolution_u
    return target


class HAIRPIPE_OT_merge_hair_for_export(bpy.types.Operator):
    """将场景中所有 FiguHair 头发网格合并为一个导出网格（不修改原物体，合并结果不带细分）"""
    bl_idname = "hair_pipe.merge_hair_for_export"
    bl_label = "导出合并网格"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        # 兼容旧版“选中合并”：优先用选中集推导；由于 FiguHair 开启时网格不可选（hide_select），
        # selected_objects 常为空或只有曲线，因此回退到全场景收集，避免“请选择至少一个FiguHair网格”误报
        selected_pipe = [o for o in getattr(context, 'selected_objects', []) if _is_pipe_mesh_obj(o)]
        selected_curves = []
        for o in getattr(context, 'selected_objects', []):
            if o is None:
                continue
            if o.type == 'CURVE' and hasattr(o, 'hair_pipe_settings'):
                selected_curves.append(o)
            elif o.type == 'EMPTY':
                c = get_curve_from_figuhair_root(o)
                if c is not None:
                    selected_curves.append(c)
            elif o.type == 'MESH':
                c = get_pipe_source_curve(o) or get_tail_source_curve(o)
                if c is not None:
                    selected_curves.append(c)
        # 去重
        uniq = {}
        for c in selected_curves:
            uniq[c.name] = c
        selected_curves = list(uniq.values())

        pipe_objs = []
        if selected_pipe:
            pipe_objs = list(selected_pipe)
        elif selected_curves:
            for c in selected_curves:
                po = get_pipe_object_for_curve(c)
                if po is not None and po not in pipe_objs:
                    pipe_objs.append(po)
        # 选中集仍为空 -> 合并全场景所有头发网格（符合用户直觉：按一次就把所有头发合为一个）
        if not pipe_objs:
            pipe_objs = [o for o in bpy.data.objects if _is_pipe_mesh_obj(o)]
        if not pipe_objs:
            self.report({'WARNING'}, "场景中没有可合并的 FiguHair 网格（请先生成管线）")
            return {'CANCELLED'}
        # 去重并过滤无效
        seen = set()
        uniq_pipes = []
        for o in pipe_objs:
            if o is None or o.name in seen or o.type != 'MESH':
                continue
            seen.add(o.name)
            uniq_pipes.append(o)
        pipe_objs = uniq_pipes
        if not pipe_objs:
            self.report({'WARNING'}, "没有找到可合并的 FiguHair 网格")
            return {'CANCELLED'}

        merged_verts = []
        merged_faces = []
        vert_offset = 0
        # 用基础网格（不应用修改器），确保“合成的不要有细分”
        for obj in pipe_objs:
            mesh = obj.data
            if mesh is None or len(mesh.vertices) == 0:
                continue
            # 世界空间顶点，原物体保持不变
            mtx = obj.matrix_world
            verts = [mtx @ v.co for v in mesh.vertices]
            merged_verts.extend(verts)
            for poly in mesh.polygons:
                face = tuple(vert_offset + idx for idx in poly.vertices)
                if len(face) >= 3:
                    merged_faces.append(face)
            vert_offset += len(verts)
        if not merged_verts or not merged_faces:
            self.report({'WARNING'}, "FiguHair 网格为空，无法合并")
            return {'CANCELLED'}
        merged_mesh = bpy.data.meshes.new("HairMerged")
        try:
            merged_mesh.from_pydata(merged_verts, [], merged_faces)
            merged_mesh.update()
            # 保留平滑着色，与原管一致但不带细分修改器
            try:
                for poly in merged_mesh.polygons:
                    poly.use_smooth = True
            except Exception:
                pass
        except Exception as exc:
            self.report({'ERROR'}, f"合并网格失败: {exc}")
            return {'CANCELLED'}
        # 命名避免冲突
        base_name = "HairMerged"
        name = base_name
        idx = 1
        while bpy.data.objects.get(name) is not None:
            idx += 1
            name = f"{base_name}.{idx:03d}"
        merged_obj = bpy.data.objects.new(name, merged_mesh)
        # 明确不带任何修改器
        # 链接到当前集合
        try:
            coll = context.collection
            if coll is None:
                coll = context.scene.collection
            coll.objects.link(merged_obj)
        except Exception:
            context.scene.collection.objects.link(merged_obj)
        merged_obj.display_type = 'TEXTURED'
        merged_obj.show_in_front = False
        # 不隐藏原物体，保持“原本的不要改变”
        for o in list(getattr(context, 'selected_objects', [])):
            try:
                o.select_set(False)
            except Exception:
                pass
        try:
            merged_obj.select_set(True)
            context.view_layer.objects.active = merged_obj
        except Exception:
            pass
        self.report({'INFO'}, f"已合并 {len(pipe_objs)} 个头发网格为: {merged_obj.name}（不含细分，已保留原物体）")
        return {'FINISHED'}


class HAIRPIPE_OT_toggle_plugin_enabled(bpy.types.Operator):
    """全局开关 FiguHair（与偏好设置中的插件启用等效）"""
    bl_idname = "hair_pipe.toggle_plugin_enabled"
    bl_label = "切换 FiguHair 启用"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            from .operators import apply_plugin_enabled_state, is_plugin_enabled
            new_val = not bool(is_plugin_enabled())
            # 若场景中尚无任何头发曲线，则以当前上下文曲线为准
            has_any = any(o.type == 'CURVE' and hasattr(o, 'hair_pipe_settings') for o in bpy.data.objects)
            if not has_any:
                curve_obj = get_context_curve_object(context)
                if curve_obj is not None and hasattr(curve_obj, 'hair_pipe_settings'):
                    curve_obj.hair_pipe_settings.plugin_enabled = new_val
                    self.report({'INFO'}, "FiguHair 已开启" if new_val else "FiguHair 已关闭")
                    return {'FINISHED'}
            apply_plugin_enabled_state(new_val)
            # 强制刷新视口与可选性
            try:
                for area in getattr(context.screen, 'areas', []):
                    if getattr(area, 'type', None) == 'VIEW_3D':
                        area.tag_redraw()
            except Exception:
                pass
            self.report({'INFO'}, "FiguHair 已开启" if new_val else "FiguHair 已关闭")
        except Exception as exc:
            self.report({'ERROR'}, f"切换失败: {exc}")
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (
    HAIRPIPE_OT_hide_hair,
    HAIRPIPE_OT_show_all_hair,
    HAIRPIPE_OT_family_local_view,
    HAIRPIPE_OT_delete_hair,
    HAIRPIPE_OT_duplicate_hair,
    HAIRPIPE_OT_merge_hair_for_export,
    HAIRPIPE_OT_toggle_plugin_enabled,
)
