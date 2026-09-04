import bpy
from .hair_lifecycle import get_context_curve_object, get_curve_from_figuhair_root, get_figuhair_root, get_pipe_object_for_curve, get_tail_object_for_curve, get_pipe_source_curve, get_tail_source_curve, get_hair_root_object, get_pipe_source_curve as _get_pipe_source_curve_for_sync
from .curve_data import ensure_curve_defaults, get_selected_curve_point_indices, is_curve_edit_mode
from .point_data import sync_point_settings
from .pipe_generation import generate_pipe_mesh
from .hair_lifecycle import generated_pipe_vertices
from .hair_ops import _is_tail_mesh_only_obj
from .pipe_ops import ensure_tail_modifier_stack
from .tail_utils import update_tail_mesh_for_curve
from .selection import sync_selected_curve_visibility

_is_tail_mesh_only_obj = _is_tail_mesh_only_obj


def sync_global_redirect_selection(curve_obj=None):
    if curve_obj is None:
        return
    try:
        enabled = bool(curve_obj.hair_pipe_settings.redirect_selection)
    except Exception:
        return
    for obj in bpy.data.objects:
        if obj.type == 'CURVE' and hasattr(obj, 'hair_pipe_settings'):
            try:
                obj.hair_pipe_settings.redirect_selection = enabled
            except Exception:
                pass
        if obj.type == 'MESH':
            src = _get_pipe_source_curve_for_sync(obj)
            if src is not None and hasattr(src, 'hair_pipe_settings'):
                try:
                    obj.hide_select = bool(src.hair_pipe_settings.redirect_selection)
                except Exception:
                    pass


class HAIRPIPE_OT_apply_global_mesh_selectability(bpy.types.Operator):
    """Apply global mesh selectability to all FiguHair pipe meshes"""
    bl_idname = "hair_pipe.apply_global_mesh_selectability"
    bl_label = "应用网格不可选模式"

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is not None:
            sync_global_redirect_selection(curve_obj)
        return {'FINISHED'}




class HAIRPIPE_OT_toggle_redirect_selection(bpy.types.Operator):
    """Toggle global curve-only and mesh-selectable mode"""
    bl_idname = "hair_pipe.toggle_redirect_selection"
    bl_label = "网格不可选模式"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return get_context_curve_object(context) is not None

    def execute(self, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            return {'CANCELLED'}
        settings = curve_obj.hair_pipe_settings
        settings.redirect_selection = not settings.redirect_selection
        sync_global_redirect_selection(curve_obj)
        return {'FINISHED'}




class HAIRPIPE_OT_create_tail_mesh(bpy.types.Operator):
    """Create a tail mesh at the end of the curve"""
    bl_idname = "hair_pipe.create_tail_mesh"
    bl_label = "\u751f\u6210\u672b\u7aef\u7f51\u683c"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            return False
        pipe_obj = get_pipe_object_for_curve(curve_obj)
        if pipe_obj is None:
            return False
        return get_tail_object_for_curve(curve_obj) is None

    def execute(self, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            self.report({'ERROR'}, "\u672a\u627e\u5230\u66f2\u7ebf")
            return {'CANCELLED'}
        settings = curve_obj.hair_pipe_settings
        ensure_curve_defaults(curve_obj)
        sync_point_settings(curve_obj)
        verts, faces = generate_pipe_mesh(curve_obj, settings)
        if verts is None:
            self.report({'ERROR'}, "\u8bf7\u5148\u751f\u6210\u7ba1\u7ebf")
            return {'CANCELLED'}
        verts = generated_pipe_vertices(verts, curve_obj)
        tail_obj = update_tail_mesh_for_curve(curve_obj, settings, verts)
        if tail_obj is None:
            self.report({'ERROR'}, "\u65e0\u6cd5\u521b\u5efa\u672b\u7aef\u7f51\u683c")
            return {'CANCELLED'}
        pipe_obj = get_pipe_object_for_curve(curve_obj)
        if pipe_obj is not None:
            ensure_tail_modifier_stack(pipe_obj, tail_obj, settings)
        self.report({'INFO'}, "\u5df2\u521b\u5efa\u672b\u7aef\u7f51\u683c")
        return {'FINISHED'}




class HAIRPIPE_OT_remove_tail_mesh(bpy.types.Operator):
    """Remove the tail mesh"""
    bl_idname = "hair_pipe.remove_tail_mesh"
    bl_label = "\u5220\u9664\u672b\u7aef\u7f51\u683c"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            return False
        return get_tail_object_for_curve(curve_obj) is not None

    def execute(self, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            return {'CANCELLED'}
        tail_obj = get_tail_object_for_curve(curve_obj)
        if tail_obj is None:
            return {'CANCELLED'}
        pipe_obj = get_pipe_object_for_curve(curve_obj)
        if pipe_obj is not None:
            modifier = pipe_obj.modifiers.get("FiguHair Join Tail")
            if modifier is not None:
                pipe_obj.modifiers.remove(modifier)
        mesh_data = tail_obj.data
        bpy.data.objects.remove(tail_obj, do_unlink=True)
        if mesh_data is not None and mesh_data.users == 0:
            bpy.data.meshes.remove(mesh_data)
        self.report({'INFO'}, "\u5df2\u5220\u9664\u672b\u7aef\u7f51\u683c")
        return {'FINISHED'}




class HAIRPIPE_OT_toggle_tail_visibility(bpy.types.Operator):
    """Toggle tail mesh visibility"""
    bl_idname = "hair_pipe.toggle_tail_visibility"
    bl_label = "隐藏/显示末端网格"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            return False
        return get_tail_object_for_curve(curve_obj) is not None

    def execute(self, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            return {'CANCELLED'}
        tail_obj = get_tail_object_for_curve(curve_obj)
        if tail_obj is None:
            return {'CANCELLED'}
        new_hidden = not tail_obj.hide_get()
        tail_obj.hide_set(new_hidden)
        if not new_hidden:
            tail_obj.hide_viewport = False
        tail_obj.hide_render = True
        tail_obj["hair_pipe_tail_user_hidden"] = new_hidden
        tail_obj.show_in_front = not new_hidden
        return {'FINISHED'}




class HAIRPIPE_OT_hide_all_tail_meshes(bpy.types.Operator):
    """Hide all FiguHair tail meshes"""
    bl_idname = "hair_pipe.hide_all_tail_meshes"
    bl_label = "隐藏所有末端网格"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(_is_tail_mesh_only_obj(obj) for obj in bpy.data.objects)

    def execute(self, context):
        count = 0
        for tail_obj in bpy.data.objects:
            if not _is_tail_mesh_only_obj(tail_obj):
                continue
            tail_obj.hide_set(True)
            tail_obj.hide_render = True
            tail_obj["hair_pipe_tail_user_hidden"] = True
            tail_obj.show_in_front = False
            count += 1
        self.report({'INFO'}, f"已隐藏 {count} 个末端网格")
        return {'FINISHED'}




class HAIRPIPE_OT_toggle_solo_display(bpy.types.Operator):
    """Toggle solo display for the active hair set"""
    bl_idname = "hair_pipe.toggle_solo_display"
    bl_label = "单独显示"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        curve_obj = get_context_curve_object(context)
        return curve_obj is not None and curve_obj.type == 'CURVE'

    def execute(self, context):
        curves = []
        for obj in getattr(context, 'selected_objects', ()):
            if obj is None:
                continue
            curve_obj = None
            if obj.type == 'CURVE':
                curve_obj = obj
            elif obj.type == 'EMPTY':
                curve_obj = get_curve_from_figuhair_root(obj)
            else:
                curve_obj = get_pipe_source_curve(obj) or get_tail_source_curve(obj)
            if curve_obj is not None and curve_obj not in curves:
                curves.append(curve_obj)
        if not curves:
            curve_obj = get_context_curve_object(context)
            if curve_obj is not None:
                curves = [curve_obj]
        if not curves:
            return {'CANCELLED'}

        roots = []
        family_ids = set()
        solo_enabled = True
        for curve_obj in curves:
            root_obj = get_hair_root_object(curve_obj)
            if root_obj is None:
                continue
            roots.append(root_obj)
            solo_enabled = solo_enabled and not bool(root_obj.get("hair_pipe_solo_active", False))
            family_ids.add(root_obj.name)
            family_ids.add(curve_obj.name)
            pipe_obj = get_pipe_object_for_curve(curve_obj)
            tail_obj = get_tail_object_for_curve(curve_obj)
            if pipe_obj is not None:
                family_ids.add(pipe_obj.name)
            if tail_obj is not None:
                family_ids.add(tail_obj.name)

        if not roots:
            return {'CANCELLED'}

        if solo_enabled:
            for obj in context.view_layer.objects:
                obj["hair_pipe_solo_prev_hidden"] = obj.hide_get()
                obj.hide_set(obj.name not in family_ids)
            for root_obj in roots:
                root_obj["hair_pipe_solo_active"] = True
            self.report({'INFO'}, "已单独显示选中的头发")
        else:
            for obj in context.view_layer.objects:
                if "hair_pipe_solo_prev_hidden" not in obj:
                    continue
                prev_hidden = bool(obj.get("hair_pipe_solo_prev_hidden", False))
                obj.hide_set(prev_hidden)
                del obj["hair_pipe_solo_prev_hidden"]
            for root_obj in roots:
                if "hair_pipe_solo_active" in root_obj:
                    del root_obj["hair_pipe_solo_active"]
            self.report({'INFO'}, "已取消单独显示")
        return {'FINISHED'}




class HAIRPIPE_OT_edit_tail_mesh(bpy.types.Operator):
    """切换末端网格编辑模式与曲线编辑模式"""
    bl_idname = "hair_pipe.edit_tail_mesh"
    bl_label = "\u7f16\u8f91\u672b\u7aef\u7f51\u683c"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            return False
        return get_tail_object_for_curve(curve_obj) is not None

    def execute(self, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            return {'CANCELLED'}
        tail_obj = get_tail_object_for_curve(curve_obj)
        if tail_obj is None:
            return {'CANCELLED'}

        active = context.active_object
        mode = context.mode

        # Currently editing tail mesh -> return to curve edit mode
        if active == tail_obj and mode == 'EDIT_MESH':
            with context.temp_override(active_object=tail_obj, object=tail_obj):
                bpy.ops.object.mode_set(mode='OBJECT')
            # Restore user-intended hidden state
            user_hidden = bool(tail_obj.get("hair_pipe_tail_user_hidden", False))
            tail_obj.hide_viewport = False
            tail_obj.hide_set(user_hidden)
            tail_obj.show_in_front = not user_hidden
            for obj in list(context.selected_objects):
                obj.select_set(False)
            curve_obj.hide_set(False)
            curve_obj.select_set(True)
            context.view_layer.objects.active = curve_obj
            with context.temp_override(active_object=curve_obj, object=curve_obj):
                bpy.ops.object.mode_set(mode='EDIT')
            return {'FINISHED'}

        # Enter tail mesh edit mode
        if mode not in ('OBJECT',):
            bpy.ops.object.mode_set(mode='OBJECT')

        # Temporarily disable redirect_selection so handler does not fight us
        redirect_was = curve_obj.hair_pipe_settings.redirect_selection
        curve_obj.hair_pipe_settings.redirect_selection = False

        # Remember user-intended hidden state before revealing for edit
        tail_obj["hair_pipe_tail_user_hidden"] = bool(tail_obj.get("hair_pipe_tail_user_hidden", tail_obj.hide_get()))
        tail_obj.hide_set(False)
        tail_obj.hide_viewport = False
        # Ensure solid display, always in front
        tail_obj.display_type = 'TEXTURED'
        tail_obj.show_in_front = True
        for obj in list(context.selected_objects):
            obj.select_set(False)
        tail_obj.select_set(True)
        context.view_layer.objects.active = tail_obj
        with context.temp_override(active_object=tail_obj, object=tail_obj):
            bpy.ops.object.mode_set(mode='EDIT')

        curve_obj.hair_pipe_settings.redirect_selection = redirect_was
        return {'FINISHED'}



classes = (
    HAIRPIPE_OT_apply_global_mesh_selectability,
    HAIRPIPE_OT_toggle_redirect_selection,
    HAIRPIPE_OT_toggle_solo_display,
    HAIRPIPE_OT_create_tail_mesh,
    HAIRPIPE_OT_remove_tail_mesh,
    HAIRPIPE_OT_toggle_tail_visibility,
    HAIRPIPE_OT_hide_all_tail_meshes,
    HAIRPIPE_OT_edit_tail_mesh,
)
