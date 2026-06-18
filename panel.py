import bpy
from .operators import sync_point_settings, sync_active_point_from_selection, is_curve_edit_mode, get_curve_point_by_global_index


class HAIRPIPE_PT_main_panel(bpy.types.Panel):
    bl_label = "FiguHair"
    bl_idname = "HAIRPIPE_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "FiguHair"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'CURVE'

    def draw(self, context):
        layout = self.layout
        curve_obj = context.active_object
        settings = curve_obj.hair_pipe_settings
        sync_point_settings(curve_obj)
        if is_curve_edit_mode(curve_obj):
            sync_active_point_from_selection(curve_obj)

        box = layout.box()
        box.label(text="生成", icon='MESH_CYLINDER')
        row = box.row(align=True)
        row.scale_y = 1.35
        row.operator("hair_pipe.generate_pipe", text="生成 / 更新管线")
        box.prop(settings, "auto_update", text="自动更新")

        box = layout.box()
        box.label(text="默认形状", icon='MESH_CIRCLE')
        row = box.row(align=True)
        row.prop(settings, "default_radius", text="半径")
        row.prop(settings, "default_segments", text="段数")
        box.prop(settings, "smooth_shading", text="平滑")
        box.prop(settings, "cap_ends", text="封口")

        box = layout.box()
        box.label(text="常用操作", icon='TOOL_SETTINGS')
        row = box.row(align=True)
        row.operator("hair_pipe.reset_all_cross_sections", text="全部重置")
        row.operator("hair_pipe.taper_linear", text="线性变细")


class HAIRPIPE_PT_point_select_panel(bpy.types.Panel):
    bl_label = "当前曲线点"
    bl_idname = "HAIRPIPE_PT_point_select_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "FiguHair"
    bl_parent_id = "HAIRPIPE_PT_main_panel"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'CURVE'

    def draw(self, context):
        layout = self.layout
        curve_obj = context.active_object
        settings = curve_obj.hair_pipe_settings
        sync_point_settings(curve_obj)
        if is_curve_edit_mode(curve_obj):
            sync_active_point_from_selection(curve_obj)

        if len(settings.point_settings) == 0:
            layout.label(text="没有曲线点", icon='INFO')
            return

        layout.prop(settings, "active_point_index", text="点序号")
        if is_curve_edit_mode(curve_obj):
            layout.label(text="编辑模式下会跟随选中的点", icon='RESTRICT_SELECT_OFF')


class HAIRPIPE_PT_cross_section_panel(bpy.types.Panel):
    bl_label = "横截面"
    bl_idname = "HAIRPIPE_PT_cross_section_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "FiguHair"
    bl_parent_id = "HAIRPIPE_PT_main_panel"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE':
            return False
        s = obj.hair_pipe_settings
        return len(s.point_settings) > 0 and s.active_point_index < len(s.point_settings)

    def draw(self, context):
        layout = self.layout
        curve_obj = context.active_object
        settings = curve_obj.hair_pipe_settings
        if is_curve_edit_mode(curve_obj):
            sync_active_point_from_selection(curve_obj)
        ps = settings.point_settings[settings.active_point_index]
        curve_point = get_curve_point_by_global_index(curve_obj, settings.active_point_index)
        widget_data = context.window_manager.hair_pipe_widget

        layout.label(text=f"正在编辑：点 {settings.active_point_index}", icon='CURVE_DATA')

        box = layout.box()
        box.label(text="横截面编辑器", icon='EDITMODE_HLT')
        row = box.row(align=True)
        if widget_data.is_active:
            row.operator("hair_pipe.widget_stop", text="关闭编辑器", icon='PANEL_CLOSE')
        else:
            row.operator("hair_pipe.widget_interact", text="打开编辑器", icon='MOUSE_LMB')
        box.label(text="按住 Ctrl+Shift+X：临时打开，松开 X 退出", icon='INFO')

        box = layout.box()
        box.label(text="曲线点控制", icon='IPO_BEZIER')
        if curve_point is not None:
            row = box.row(align=True)
            row.prop(curve_point, "radius", text="半径")
            row.prop(curve_point, "tilt", text="倾斜")
            box.label(text="快捷键：Alt+S 半径，Ctrl+T 倾斜", icon='INFO')
        else:
            box.label(text="请在编辑模式中选择曲线点", icon='INFO')

        box = layout.box()
        box.label(text="额外调整", icon='MOD_SIMPLEDEFORM')
        row = box.row(align=True)
        row.prop(ps, "scale", text="缩放")
        row.prop(ps, "rotation", text="旋转")

        box = layout.box()
        box.label(text="形状点", icon='MESH_CIRCLE')
        box.prop(ps, "active_vert_index", text="当前点")
        for i, cv in enumerate(ps.cross_section_verts):
            row = box.row(align=True)
            row.label(text=f"{i}")
            row.prop(cv, "offset_x", text="X")
            row.prop(cv, "offset_y", text="Y")

        row = layout.row(align=True)
        row.operator("hair_pipe.add_cs_vert", text="添加点", icon='ADD')
        row.operator("hair_pipe.remove_cs_vert", text="删除点", icon='REMOVE')
        row = layout.row(align=True)
        row.operator("hair_pipe.reset_cross_section", text="重置圆形", icon='LOOP_BACK')
        row.operator("hair_pipe.copy_cs_to_all", text="复制到全部", icon='DUPLICATE')


classes = (
    HAIRPIPE_PT_main_panel,
    HAIRPIPE_PT_point_select_panel,
    HAIRPIPE_PT_cross_section_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
