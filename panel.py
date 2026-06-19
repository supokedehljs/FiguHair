import bpy
from .operators import (
    is_curve_edit_mode,
    get_curve_point_by_global_index,
    get_context_curve_object,
)


class HAIRPIPE_PT_main_panel(bpy.types.Panel):
    bl_label = "FiguHair"
    bl_idname = "HAIRPIPE_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "FiguHair"

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        layout = self.layout
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            layout.label(text="请选择曲线或 FiguHair 预览网格", icon='INFO')
            return

        try:
            settings = curve_obj.hair_pipe_settings
            edit_mode = is_curve_edit_mode(curve_obj)
        except Exception as exc:
            layout.label(text="FiguHair 状态初始化失败", icon='ERROR')
            layout.label(text=str(exc)[:80], icon='INFO')
            return

        box = layout.box()
        box.label(text="生成", icon='MESH_CYLINDER')
        row = box.row(align=True)
        row.scale_y = 1.35
        row.operator("hair_pipe.generate_pipe", text="生成 / 更新管线")
        mode_text = "只选曲线模式" if settings.redirect_selection else "头发网格可选模式"
        row = box.row(align=True)
        row.prop(settings, "redirect_selection", text=mode_text, toggle=True)

        box = layout.box()
        box.label(text="默认形状", icon='MESH_CIRCLE')
        box.prop(settings, "pipe_resolution", text="过渡细分")
        box.prop(settings, "transition_mode", text="截面过渡")
        box.prop(settings, "transition_strength", text="过渡强度")
        box.prop(settings, "strong_smoothing", text="强力平滑")
        if settings.strong_smoothing:
            box.prop(settings, "strong_smoothing_iterations", text="平滑次数")
        box.prop(settings, "smooth_shading", text="平滑着色")
        box.prop(settings, "cap_ends", text="封口")

        if not edit_mode:
            return

        edit_box = layout.box()
        edit_box.label(text="编辑模式操作", icon='EDITMODE_HLT')

        box = edit_box.box()
        box.label(text="边流重建", icon='IPO_BEZIER')
        box.label(text="选择两个曲线点后应用", icon='INFO')
        box.prop(settings, "edge_flow_mode", text="模式")
        if settings.edge_flow_mode in {'START', 'END'}:
            box.prop(settings, "edge_flow_power", text="偏向强度")
        box.prop(settings, "edge_flow_blend", text="重建强度")
        row = box.row(align=True)
        row.scale_y = 1.25
        op = row.operator("hair_pipe.apply_edge_flow", text="应用边流")
        op.mode = settings.edge_flow_mode
        op.power = settings.edge_flow_power
        op.blend = settings.edge_flow_blend

        box = edit_box.box()
        box.label(text="横截面编辑器", icon='MOUSE_LMB')
        widget_data = getattr(context.window_manager, "hair_pipe_widget", None)
        if widget_data is None:
            box.label(text="横截面编辑器未初始化，请重新加载插件", icon='ERROR')
            return
        row = box.row(align=True)
        if widget_data.is_active:
            row.operator("hair_pipe.widget_stop", text="关闭编辑器", icon='PANEL_CLOSE')
        else:
            row.operator("hair_pipe.widget_interact", text="打开编辑器", icon='MOUSE_LMB')
        box.label(text="按住 Ctrl+Shift+X：临时打开，松开 X 退出", icon='INFO')

        box = edit_box.box()
        box.label(text="曲线点控制", icon='CURVE_DATA')
        curve_point = get_curve_point_by_global_index(curve_obj, settings.active_point_index)
        if curve_point is not None:
            row = box.row(align=True)
            row.prop(curve_point, "radius", text="半径")
            row.prop(curve_point, "tilt", text="倾斜")
            box.label(text="快捷键：Alt+S 半径，Ctrl+T 倾斜", icon='INFO')
        else:
            box.label(text="请在编辑模式中选择曲线点", icon='INFO')

        row = box.row(align=True)
        row.operator("hair_pipe.copy_cross_section", text="复制", icon='COPYDOWN')
        row.operator("hair_pipe.paste_cross_section", text="粘贴", icon='PASTEDOWN')

        row = box.row(align=True)
        row.operator("hair_pipe.reset_cross_section", text="重置圆形", icon='LOOP_BACK')
        row.operator("hair_pipe.copy_cs_to_all", text="复制到全部", icon='DUPLICATE')


classes = (
    HAIRPIPE_PT_main_panel,
)


def register():
    stale_panels = (
        getattr(bpy.types, "HAIRPIPE_PT_point_select_panel", None),
        getattr(bpy.types, "HAIRPIPE_PT_cross_section_panel", None),
    )
    for cls in stale_panels:
        if cls is not None:
            try:
                bpy.utils.unregister_class(cls)
            except RuntimeError:
                pass

    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
