import bpy
from .operators import (
    is_curve_edit_mode,
    get_curve_point_by_global_index,
    get_context_curve_object,
    get_hair_root_object,
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
        box.label(text="显示", icon='HIDE_OFF')
        for label in ("预览模式", "细分层级", "单独显示", "显示在最前"):
            box.label(text=label)

        edit_box = disabled.box()
        edit_box.label(text="编辑", icon='EDITMODE_HLT')
        edit_box.operator("figuhair.widget_interact", text="打开横截面编辑器", icon='MOUSE_LMB')
        row = edit_box.row(align=True)
        row.operator("figuhair.widget_smooth_selected_vertices", text="普通平滑", icon='MOD_SMOOTH')
        row.operator("figuhair.widget_smooth_selected_vertices", text="圆形平滑", icon='MESH_CIRCLE')
        row = edit_box.row(align=True)
        row.operator("figuhair.auto_simplify_cross_section", text="自动简化", icon='GHOST_ENABLED')
        row.operator("figuhair.apply_edge_flow", text="截面边流")
        row = edit_box.row(align=True)
        row.operator("figuhair.smooth_curve_points", text="曲线平滑", icon='SMOOTHCURVE')
        row.operator("figuhair.reverse_curve_direction", text="翻转方向", icon='ARROW_LEFTRIGHT')
        edit_box.label(text="自动更新管线")

        output_box = disabled.box()
        output_box.label(text="输出", icon='EXPORT')
        output_box.operator("figuhair.merge_hair_for_export", text="合并所有头发", icon='EXPORT')

        settings_box = disabled.box()
        settings_box.label(text="设置", icon='PREFERENCES')
        for label in ("材质选择", "滚转算法", "平滑着色"):
            settings_box.label(text=label)

    def draw(self, context):
        layout = self.layout
        curve_obj = get_context_curve_object(context)

        # ---------------- 创建 ----------------
        box = layout.box()
        box.label(text="创建", icon='MESH_CYLINDER')
        row = box.row(align=True)
        row.scale_y = 1.35
        row.operator("figuhair.draw_hair_curve", text="添加头发", icon='CURVE_DATA')
        row.operator("figuhair.mesh_to_hair_curve", text="发管转曲线", icon='CURVE_DATA')

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

        if settings is None:
            self.draw_unavailable_settings(context, layout)
            return

        widget_options = getattr(context.window_manager, "hair_pipe_widget", None)
        edit_controls_enabled = edit_mode and settings.auto_update and len(settings.point_settings) > 0
        active_idx = min(settings.active_point_index, len(settings.point_settings) - 1) if settings.point_settings else -1
        active_ps = settings.point_settings[active_idx] if active_idx >= 0 else None
        widget_ready = widget_options is not None and edit_controls_enabled and active_ps is not None
        widget_active = widget_ready and widget_options.is_active
        solo_root = get_hair_root_object(curve_obj)
        solo_active = bool(solo_root is not None and solo_root.get("hair_pipe_solo_active", False))

        # ---------------- 显示 ----------------
        display_box = layout.box()
        display_box.label(text="显示", icon='HIDE_OFF')
        mode_row = display_box.row(align=True)
        mode_row.scale_y = 1.3
        mode_row.enabled = widget_options is not None
        if widget_options is not None:
            mode_row.prop(widget_options, "preview_mode", expand=True)

        row = display_box.row(align=True)
        row.prop(settings, "subdivision_levels", text="细分层级")
        icon = 'HIDE_OFF' if settings.default_subdiv else 'HIDE_ON'
        row.prop(settings, "default_subdiv", text="", icon=icon, toggle=True)

        toggle_row = display_box.row(align=True)
        toggle_row.scale_y = 1.2
        toggle_row.operator(
            "figuhair.toggle_solo_display",
            text="单独显示",
            icon='SOLO_ON' if solo_active else 'SOLO_OFF',
            depress=solo_active,
        )
        if widget_options is not None:
            toggle_row.prop(widget_options, "preview_in_front", text="显示在最前", toggle=True)

        # ---------------- 编辑 ----------------
        edit_box = layout.box()
        edit_box.label(text="编辑", icon='EDITMODE_HLT')
        row = edit_box.row(align=True)
        row.scale_y = 1.35
        row.enabled = widget_ready
        if widget_active:
            row.operator("figuhair.widget_stop", text="关闭横截面编辑器", icon='PANEL_CLOSE')
        else:
            row.operator("figuhair.widget_interact", text="打开横截面编辑器", icon='MOUSE_LMB')

        edit_box.label(text="横截面")
        commands = edit_box.column(align=True)
        commands.enabled = edit_controls_enabled
        row = commands.row(align=True)
        row.scale_y = 1.2
        op = row.operator("figuhair.widget_smooth_selected_vertices", text="普通平滑", icon='MOD_SMOOTH')
        op.mode = 'NEIGHBOR'
        op = row.operator("figuhair.widget_smooth_selected_vertices", text="圆形平滑", icon='MESH_CIRCLE')
        op.mode = 'CIRCULAR'
        row = commands.row(align=True)
        row.scale_y = 1.2
        row.operator("figuhair.auto_simplify_cross_section", text="自动简化", icon='GHOST_ENABLED')
        op = row.operator("figuhair.apply_edge_flow", text="截面边流")
        op.mode = settings.edge_flow_mode
        op.power = settings.edge_flow_power
        op.blend = settings.edge_flow_blend

        edit_box.label(text="曲线")
        curve_commands = edit_box.column(align=True)
        curve_commands.enabled = edit_controls_enabled
        row = curve_commands.row(align=True)
        row.scale_y = 1.2
        row.operator("figuhair.smooth_curve_points", text="曲线平滑", icon='SMOOTHCURVE')
        row.operator("figuhair.reverse_curve_direction", text="翻转方向", icon='ARROW_LEFTRIGHT')

        auto_row = edit_box.row()
        auto_row.enabled = edit_mode
        auto_row.prop(settings, "auto_update", text="自动更新管线")

        # ---------------- 输出 ----------------
        output_box = layout.box()
        output_box.label(text="输出", icon='EXPORT')
        row = output_box.row(align=True)
        row.enabled = curve_obj is not None
        row.scale_y = 1.2
        row.operator("figuhair.merge_hair_for_export", text="合并所有头发", icon='EXPORT')

        # ---------------- 设置 ----------------
        settings_box = layout.box()
        settings_box.label(text="设置", icon='PREFERENCES')
        settings_box.prop(settings, "shared_hair_material", text="材质选择", icon='MATERIAL')
        settings_box.prop(settings, "roll_mode", text="滚转算法")
        settings_box.prop(settings, "smooth_shading", text="平滑着色")


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
