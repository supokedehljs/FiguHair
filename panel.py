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

    def draw_unavailable_settings(self, context, layout):
        disabled = layout.column()
        disabled.enabled = False

        box = disabled.box()
        box.label(text="默认设置", icon='MESH_CIRCLE')
        for label in ("滚转算法", "强力平滑", "平滑次数", "平滑着色", "细分层级"):
            box.label(text=label)

        edit_box = disabled.box()
        edit_box.label(text="编辑模式操作", icon='EDITMODE_HLT')
        row = edit_box.row(align=True)
        row.operator("hair_pipe.apply_edge_flow", text="截面边流")
        row.operator("hair_pipe.equalize_point_distance", text="曲线平滑", icon='SMOOTHCURVE')
        row.operator("hair_pipe.reverse_curve_direction", text="翻转方向", icon='ARROW_LEFTRIGHT')
        row = edit_box.row(align=True)
        row.operator("hair_pipe.copy_cross_section", text="复制", icon='COPYDOWN')
        row.operator("hair_pipe.paste_cross_section", text="粘贴", icon='PASTEDOWN')
        edit_box.operator("hair_pipe.widget_interact", text="打开编辑器", icon='MOUSE_LMB')

    def draw(self, context):
        layout = self.layout
        curve_obj = get_context_curve_object(context)

        box = layout.box()
        box.label(text="通用", icon='MESH_CYLINDER')
        row = box.row(align=True)
        row.enabled = curve_obj is not None
        row.scale_y = 1.35
        row.operator("hair_pipe.generate_pipe", text="生成 / 更新管线")
        row2 = box.row(align=True)
        row2.enabled = curve_obj is not None
        row2.scale_y = 1.2
        row2.operator("hair_pipe.duplicate_hair", text="复制头发", icon='DUPLICATE')
        row2.operator("hair_pipe.delete_hair", text="删除头发", icon='TRASH')
        row3 = box.row(align=True)
        row3.enabled = curve_obj is not None
        row3.scale_y = 1.2
        row3.operator("hair_pipe.merge_hair_for_export", text="导出合并网格", icon='EXPORT')
        row = box.row(align=True)
        row.scale_y = 1.2
        row.operator("hair_pipe.mesh_to_hair_curve", text="管状网格转头发曲线", icon='CURVE_DATA')

        if curve_obj is None:
            layout.label(text="未选择 FiguHair 头发；设置暂不可编辑", icon='INFO')
            settings = None
            edit_mode = False
        else:
            try:
                settings = curve_obj.hair_pipe_settings
                edit_mode = is_curve_edit_mode(curve_obj)
            except Exception as exc:
                layout.label(text="FiguHair 状态初始化失败", icon='ERROR')
                layout.label(text=str(exc)[:80], icon='INFO')
                settings = None
                edit_mode = False

        context_available = settings is not None
        context_box = box.column()
        context_box.enabled = context_available
        row = context_box.row(align=True)
        row.operator("hair_pipe.toggle_solo_display", text="单独显示", icon='HIDE_OFF')

        if settings is None:
            self.draw_unavailable_settings(context, layout)
            return

        mode_text = "只选曲线模式" if settings.redirect_selection else "头发网格可选模式"
        row = box.row(align=True)
        op = row.operator("hair_pipe.toggle_redirect_selection", text=mode_text, depress=settings.redirect_selection)

        box = layout.box()
        box.label(text="默认设置", icon='MESH_CIRCLE')
        box.prop(settings, "roll_mode", text="滚转算法")
        box.prop(settings, "strong_smoothing", text="强力平滑")
        if settings.strong_smoothing:
            box.prop(settings, "strong_smoothing_iterations", text="平滑次数")
        box.prop(settings, "smooth_shading", text="平滑着色")
        row = box.row(align=True)
        row.prop(settings, "subdivision_levels", text="细分层级")
        icon = 'HIDE_OFF' if settings.default_subdiv else 'HIDE_ON'
        row.prop(settings, "default_subdiv", text="", icon=icon, toggle=True)

        header_box = layout.box()
        header_box.enabled = edit_mode
        header_box.prop(settings, "auto_update", text="编辑模式操作", icon='EDITMODE_HLT', emboss=False)

        edit_controls_enabled = edit_mode and settings.auto_update and len(settings.point_settings) > 0
        active_idx = min(settings.active_point_index, len(settings.point_settings) - 1) if settings.point_settings else -1
        active_ps = settings.point_settings[active_idx] if active_idx >= 0 else None
        widget_data = getattr(context.window_manager, "hair_pipe_widget", None)

        box = header_box.box()
        box.enabled = edit_controls_enabled
        row = box.row(align=True)
        row.scale_y = 1.25
        op = row.operator("hair_pipe.apply_edge_flow", text="截面边流")
        op.mode = settings.edge_flow_mode
        op.power = settings.edge_flow_power
        op.blend = settings.edge_flow_blend
        row.operator("hair_pipe.equalize_point_distance", text="曲线平滑", icon='SMOOTHCURVE')
        row.operator("hair_pipe.reverse_curve_direction", text="翻转方向", icon='ARROW_LEFTRIGHT')

        row = box.row(align=True)
        row.operator("hair_pipe.copy_cross_section", text="复制", icon='COPYDOWN')
        row.operator("hair_pipe.paste_cross_section", text="粘贴", icon='PASTEDOWN')

        if widget_data is None:
            box.label(text="横截面编辑器未初始化，请重新加载插件", icon='ERROR')
        else:
            row = box.row(align=True)
            if active_ps is None:
                row.enabled = False
                row.operator("hair_pipe.widget_interact", text="没有可编辑的横截面", icon='LOCKED')
            elif getattr(active_ps, "use_transition", False):
                row.enabled = False
                row.operator("hair_pipe.widget_interact", text="过渡模式下无法编辑横截面", icon='LOCKED')
            elif widget_data.is_active:
                row.operator("hair_pipe.widget_stop", text="关闭编辑器", icon='PANEL_CLOSE')
                row = box.row(align=True)
                row.operator("hair_pipe.widget_toggle_ghost", text="设置为幽灵点")
                row.operator("hair_pipe.widget_make_normal", text="设置为正常点")
            else:
                row.operator("hair_pipe.widget_interact", text="打开编辑器", icon='MOUSE_LMB')


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
