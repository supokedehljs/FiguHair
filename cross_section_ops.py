import bpy
import math
from mathutils import Vector
from bpy.props import IntProperty, FloatProperty
from .cross_section import (
    add_cross_section_vertex_after_all as cross_section_add_cross_section_vertex_after_all,
    remove_cross_section_vertex_all as cross_section_remove_cross_section_vertex_all,
    get_active_spline_point_range as cross_section_get_active_spline_point_range,
)
from .hair_lifecycle import get_context_curve_object
from .curve_data import is_curve_edit_mode as curve_is_curve_edit_mode, get_selected_curve_point_indices as curve_get_selected_curve_point_indices
from .ghost import update_all_ghost_vertices as ghost_update_all_ghost_vertices
from .transition import find_previous_editable_point_index, find_next_editable_point_index, update_transition_point_values
from .point_data import sync_point_settings as point_sync_point_settings, init_cross_section_circle as point_init_cross_section_circle


def copy_point_cross_section(src, dst, rotation_offset=0.0):
    dst.cross_section_verts.clear()
    angle = math.radians(rotation_offset)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    for sv in src.cross_section_verts:
        v = dst.cross_section_verts.add()
        x = sv.offset_x
        y = sv.offset_y
        v.offset_x = x * cos_a - y * sin_a
        v.offset_y = x * sin_a + y * cos_a
        v.is_ghost = getattr(sv, 'is_ghost', False)
    dst.active_vert_index = min(src.active_vert_index, max(0, len(dst.cross_section_verts) - 1))
    dst.scale = src.scale
    dst.rotation = src.rotation




_HAIRPIPE_CROSS_SECTION_CLIPBOARD = None


class HAIRPIPE_OT_toggle_cross_section_transition(bpy.types.Operator):
    """Toggle transition mode for selected curve control points"""
    bl_idname = "hair_pipe.toggle_cross_section_transition"
    bl_label = "横截面过渡模式"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = get_context_curve_object(context)
        return obj is not None and obj.type == 'CURVE'

    def execute(self, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            self.report({'ERROR'}, "请选择曲线或 FiguHair 预览网格")
            return {'CANCELLED'}
        bpy.ops.ed.undo_push(message="截面边流")
        sync_point_settings(curve_obj)
        settings = curve_obj.hair_pipe_settings
        selected = get_selected_curve_point_indices(curve_obj) if is_curve_edit_mode(curve_obj) else []
        target_indices = selected if selected else [settings.active_point_index]
        target_indices = [idx for idx in target_indices if 0 <= idx < len(settings.point_settings)]
        if not target_indices:
            self.report({'ERROR'}, "没有可切换的曲线点")
            return {'CANCELLED'}

        should_enable = not all(settings.point_settings[idx].use_transition for idx in target_indices)
        changed = 0
        for idx in target_indices:
            prev_idx = find_previous_editable_point_index(settings.point_settings, idx)
            next_idx = find_next_editable_point_index(settings.point_settings, idx)
            if should_enable and (prev_idx is None or next_idx is None):
                continue
            settings.point_settings[idx].use_transition = should_enable
            changed += 1
        if changed == 0:
            self.report({'WARNING'}, "端点或没有前后正常横截面的点不能设为过渡模式")
            return {'CANCELLED'}
        update_transition_point_values(curve_obj, settings)
        update_all_ghost_vertices(settings)
        self.report({'INFO'}, "已开启横截面过渡模式" if should_enable else "已关闭横截面过渡模式")
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
        point_range = get_active_spline_point_range(context.active_object, settings)
        csv = ps.cross_section_verts
        n = len(csv)
        if n < 2:
            for point_idx, point_setting in enumerate(settings.point_settings):
                v = point_setting.cross_section_verts.add()
                v.offset_x = settings.default_radius
                v.offset_y = 0.0
                v.is_ghost = point_idx != settings.active_point_index
                point_setting.active_vert_index = len(point_setting.cross_section_verts) - 1
        else:
            add_cross_section_vertex_after_all(settings, ps.active_vert_index, point_range)
        update_all_ghost_vertices(settings)
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
        start, end = get_active_spline_point_range(obj, s)
        return all(len(ps.cross_section_verts) > 3 for ps in s.point_settings[start:end])

    def execute(self, context):
        settings = context.active_object.hair_pipe_settings
        ps = settings.point_settings[settings.active_point_index]
        point_range = get_active_spline_point_range(context.active_object, settings)
        remove_cross_section_vertex_all(settings, ps.active_vert_index, point_range)
        return {'FINISHED'}




class HAIRPIPE_OT_select_point(bpy.types.Operator):
    """Select a control point for editing"""
    bl_idname = "hair_pipe.select_point"
    bl_label = "Select Point"
    point_index: IntProperty()

    def execute(self, context):
        context.active_object.hair_pipe_settings.active_point_index = self.point_index
        return {'FINISHED'}




class HAIRPIPE_OT_copy_cross_section(bpy.types.Operator):
    """Copy the active point cross-section to the FiguHair clipboard"""
    bl_idname = "hair_pipe.copy_cross_section"
    bl_label = "复制横截面"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE':
            return False
        s = obj.hair_pipe_settings
        return s.active_point_index < len(s.point_settings)

    def execute(self, context):
        try:
            from .widget_operator import push_widget_undo
            push_widget_undo(context, "复制横截面")
        except Exception:
            pass
        global _HAIRPIPE_CROSS_SECTION_CLIPBOARD
        settings = context.active_object.hair_pipe_settings
        src = settings.point_settings[settings.active_point_index]
        _HAIRPIPE_CROSS_SECTION_CLIPBOARD = {
            "verts": [
                (v.offset_x, v.offset_y, getattr(v, 'is_ghost', False))
                for v in src.cross_section_verts
            ],
            "scale": src.scale,
            "rotation": src.rotation,
            "active_vert_index": src.active_vert_index,
        }
        self.report({'INFO'}, "已复制横截面")
        return {'FINISHED'}




class HAIRPIPE_OT_paste_cross_section(bpy.types.Operator):
    """Paste the copied cross-section to active or selected curve points"""
    bl_idname = "hair_pipe.paste_cross_section"
    bl_label = "粘贴横截面"
    bl_options = {'REGISTER', 'UNDO'}

    rotation_offset: FloatProperty(
        name="粘贴后旋转",
        description="Rotate pasted cross-section around its center in degrees",
        default=0.0,
        min=-360.0,
        max=360.0,
        precision=2,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE':
            return False
        if _HAIRPIPE_CROSS_SECTION_CLIPBOARD is None:
            return False
        s = obj.hair_pipe_settings
        return s.active_point_index < len(s.point_settings)

    def draw(self, context):
        self.layout.prop(self, "rotation_offset")

    def execute(self, context):
        try:
            from .widget_operator import push_widget_undo
            push_widget_undo(context, "粘贴横截面")
        except Exception:
            pass
        settings = context.active_object.hair_pipe_settings
        sync_point_settings(context.active_object)
        selected = get_selected_curve_point_indices(context.active_object) if is_curve_edit_mode(context.active_object) else []
        target_indices = selected if selected else [settings.active_point_index]
        target_indices = [idx for idx in target_indices if idx < len(settings.point_settings)]
        if not target_indices:
            return {'CANCELLED'}

        class ClipboardPointSetting:
            pass

        src = ClipboardPointSetting()
        src.cross_section_verts = []
        for x, y, is_ghost in _HAIRPIPE_CROSS_SECTION_CLIPBOARD["verts"]:
            class ClipboardVert:
                pass
            v = ClipboardVert()
            v.offset_x = x
            v.offset_y = y
            v.is_ghost = is_ghost
            src.cross_section_verts.append(v)
        src.scale = _HAIRPIPE_CROSS_SECTION_CLIPBOARD["scale"]
        src.rotation = _HAIRPIPE_CROSS_SECTION_CLIPBOARD["rotation"]
        src.active_vert_index = _HAIRPIPE_CROSS_SECTION_CLIPBOARD["active_vert_index"]

        for idx in target_indices:
            copy_point_cross_section(src, settings.point_settings[idx], self.rotation_offset)
        update_all_ghost_vertices(settings)
        self.report({'INFO'}, f"已粘贴到 {len(target_indices)} 个曲线点")
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
            copy_point_cross_section(src, ps)
        update_all_ghost_vertices(settings)
        self.report({'INFO'}, "Cross-section copied to all points")
        return {'FINISHED'}





classes = (
    HAIRPIPE_OT_toggle_cross_section_transition,
    HAIRPIPE_OT_reset_cross_section,
    HAIRPIPE_OT_reset_all_cross_sections,
    HAIRPIPE_OT_taper_linear,
    HAIRPIPE_OT_add_cs_vert,
    HAIRPIPE_OT_remove_cs_vert,
    HAIRPIPE_OT_select_point,
    HAIRPIPE_OT_copy_cross_section,
    HAIRPIPE_OT_paste_cross_section,
    HAIRPIPE_OT_copy_cs_to_all,
)
