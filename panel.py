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
        for label in ("滚转算法", "平滑着色", "细分层级"):
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
        edit_box.operator("hair_pipe.cross_section_spread", text="横截面传递", icon='DUPLICATE')
        row = edit_box.row(align=True)
        row.operator("hair_pipe.widget_toggle_ghost", text="设置为幽灵点")
        row.operator("hair_pipe.widget_make_normal", text="设置为正常点")
        row = edit_box.row(align=True)
        op = row.operator("hair_pipe.widget_smooth_selected_vertices", text="普通平滑", icon='SMOOTHCURVE')
        op.mode = 'NEIGHBOR'
        op = row.operator("hair_pipe.widget_smooth_selected_vertices", text="圆形平滑", icon='MESH_CIRCLE')
        op.mode = 'CIRCULAR'

    def draw(self, context):
        layout = self.layout
        curve_obj = get_context_curve_object(context)

        enable_box = layout.box()
        if curve_obj is not None:
            settings = curve_obj.hair_pipe_settings
            enable_box.prop(
                settings,
                "plugin_enabled",
                text="FiguHair 已开启" if settings.plugin_enabled else "FiguHair 已关闭",
                icon='CHECKBOX_HLT' if settings.plugin_enabled else 'CHECKBOX_DEHLT',
                toggle=True,
            )
        else:
            enable_box.label(text="选择 FiguHair 曲线以切换插件", icon='INFO')

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

        group_box = layout.box()
        group_box.label(text="头发分组", icon='OUTLINER_COLLECTION')
        group_box.prop(context.scene, "hair_pipe_group_color_mode", text="分组颜色显示", toggle=True)
        group_box.operator("hair_pipe.create_group_from_selected", text="选中头发添加到新组", icon='ADD')
        group_box.operator("hair_pipe.move_selected_to_last_group", text="转移到最后选组", icon='FORWARD')
        group_box.operator("hair_pipe.randomize_selected_group_color", text="随机当前组颜色", icon='FILE_REFRESH')
        group_box.operator("hair_pipe.sync_parent_collections", text="爸爸去哪了", icon='FILE_PARENT')

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

        plugin_controls = layout.column()
        plugin_controls.enabled = settings.plugin_enabled

        box = plugin_controls.box()
        box.label(text="默认设置", icon='MESH_CIRCLE')
        box.prop(settings, "shared_hair_material", text="材质选择", icon='MATERIAL')
        box.prop(settings, "roll_mode", text="滚转算法")
        box.prop(settings, "smooth_shading", text="平滑着色")
        row = box.row(align=True)
        row.prop(settings, "subdivision_levels", text="细分层级")
        icon = 'HIDE_OFF' if settings.default_subdiv else 'HIDE_ON'
        row.prop(settings, "default_subdiv", text="", icon=icon, toggle=True)

        header_box = layout.box()
        auto_update_row = header_box.row()
        auto_update_row.enabled = edit_mode
        auto_update_row.prop(settings, "auto_update", text="编辑模式操作", icon='EDITMODE_HLT', emboss=False)

        edit_controls_enabled = edit_mode and settings.auto_update and len(settings.point_settings) > 0
        active_idx = min(settings.active_point_index, len(settings.point_settings) - 1) if settings.point_settings else -1
        active_ps = settings.point_settings[active_idx] if active_idx >= 0 else None
        widget_data = getattr(context.window_manager, "hair_pipe_widget", None)

        box = header_box.box()
        widget_options = getattr(context.window_manager, "hair_pipe_widget", None)
        display_options = box.column(align=True)
        display_options.enabled = widget_options is not None
        display_options.prop(widget_options, "base_preview_enabled", text="去细分显示")
        display_options.prop(widget_options, "subdiv_preview_enabled", text="细分显示")
        display_options.prop(widget_options, "solo_display_enabled", text="单独显示")
        display_options.prop(widget_options, "preview_in_front", text="显示在最前")

        controls = box.column()
        controls.enabled = edit_controls_enabled
        row = controls.row(align=True)
        row.scale_y = 1.25
        op = row.operator("hair_pipe.apply_edge_flow", text="截面边流")
        op.mode = settings.edge_flow_mode
        op.power = settings.edge_flow_power
        op.blend = settings.edge_flow_blend
        row.operator("hair_pipe.reverse_curve_direction", text="翻转方向", icon='ARROW_LEFTRIGHT')

        profile_box = header_box.box()
        profile_box.label(text="我的横截面库", icon='MESH_CIRCLE')
        row = profile_box.row(align=True)
        row.operator("hair_pipe.save_custom_profile", text="保存当前横截面", icon='ADD')
        if settings.custom_profile_data:
            row = profile_box.row(align=True)
            row.operator(
                "hair_pipe.toggle_custom_profile",
                text=settings.custom_profile_name,
                icon='RADIOBUT_ON' if settings.use_custom_profile else 'RADIOBUT_OFF',
                depress=settings.use_custom_profile,
            )
            row.label(text="缩略图", icon='MESH_CIRCLE')

        sliders = header_box.box()
        sliders.label(text="滑块区域", icon='DRIVER_DISTANCE')
        slider_controls = sliders.column(align=True)
        slider_controls.enabled = edit_controls_enabled
        slider_controls.prop(settings, "curve_smooth_slider", text="曲线平滑", icon='SMOOTHCURVE', slider=True)
        slider_controls.prop(settings, "auto_ghost_tolerance", text="自动简化", icon='GHOST_ENABLED', slider=True)
        slider_controls.prop(settings, "neighbor_smooth_slider", text="普通平滑", icon='MOD_SMOOTH', slider=True)
        slider_controls.prop(settings, "circular_smooth_slider", text="圆形平滑", icon='MESH_CIRCLE', slider=True)

        row = box.row(align=True)
        row.operator("hair_pipe.copy_cross_section", text="复制", icon='COPYDOWN')
        row.operator("hair_pipe.paste_cross_section", text="粘贴", icon='PASTEDOWN')

        widget_ready = widget_data is not None and edit_controls_enabled and active_ps is not None
        widget_active = widget_ready and widget_data.is_active
        row = box.row(align=True)
        row.enabled = widget_ready
        if widget_active:
            row.operator("hair_pipe.widget_stop", text="关闭编辑器", icon='PANEL_CLOSE')
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
