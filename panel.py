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

    def draw(self, context):
        layout = self.layout
        curve_obj = get_context_curve_object(context)
        settings = None
        edit_mode = False
        if curve_obj is not None:
            try:
                settings = curve_obj.hair_pipe_settings
                edit_mode = is_curve_edit_mode(curve_obj)
            except Exception as exc:
                layout.label(text="FiguHair 状态初始化失败", icon='ERROR')
                layout.label(text=str(exc)[:80], icon='INFO')

        widget_options = getattr(context.window_manager, "hair_pipe_widget", None)
        prefs = None
        try:
            addon_entry = context.preferences.addons.get("figuhair")
            prefs = addon_entry.preferences if addon_entry is not None else None
        except Exception:
            prefs = None

        edit_controls_enabled = bool(
            settings is not None
            and edit_mode
            and settings.auto_update
            and len(settings.point_settings) > 0
        )
        widget_ready = widget_options is not None and edit_controls_enabled
        widget_active = widget_ready and widget_options.is_active
        solo_root = get_hair_root_object(curve_obj) if curve_obj is not None else None
        solo_active = bool(solo_root is not None and solo_root.get("hair_pipe_solo_active", False))

        # ---------------- 创建 ----------------
        create_box = layout.box()
        create_box.label(text="创建")
        row = create_box.row(align=True)
        row.scale_y = 1.35
        split = row.split(factor=0.62, align=True)
        split.operator("figuhair.draw_hair_curve", text="添加头发")
        split.operator("figuhair.mesh_to_hair_curve", text="发管转曲线")

        # ---------------- 显示 ----------------
        display_box = layout.box()
        display_box.label(text="显示")
        display_box.label(text="预览模式")
        mode_area = display_box.column(align=True)
        mode_area.enabled = widget_options is not None
        if widget_options is not None:
            row = mode_area.row(align=True)
            row.prop(
                widget_options,
                "base_preview_enabled",
                text="去细分",
                toggle=True,
                icon='RADIOBUT_ON' if widget_options.preview_mode == 'BASE' else 'RADIOBUT_OFF',
            )
            row.label(text="平直着色 · 线框")
            row = mode_area.row(align=True)
            row.prop(
                widget_options,
                "subdiv_preview_enabled",
                text="细分",
                toggle=True,
                icon='RADIOBUT_ON' if widget_options.preview_mode == 'SUBDIV' else 'RADIOBUT_OFF',
            )
            row.label(text="平滑着色")
            if settings is not None:
                row = mode_area.row(align=True)
                row.separator(factor=1.0)
                row.prop(settings, "subdivision_levels", text="细分层级")
                row.prop(
                    settings,
                    "default_subdiv",
                    text="",
                    toggle=True,
                    icon='HIDE_OFF' if settings.default_subdiv else 'HIDE_ON',
                )

        display_box.separator()
        row = display_box.row(align=True)
        row.label(text="单独显示")
        sub = row.row(align=True)
        sub.alignment = 'RIGHT'
        sub.label(text="Ctrl+F")
        sub.operator(
            "figuhair.toggle_solo_display",
            text="",
            icon='CHECKBOX_HLT' if solo_active else 'CHECKBOX_DEHLT',
            depress=solo_active,
        )
        if widget_options is not None:
            row = display_box.row(align=True)
            row.label(text="显示在最前")
            sub = row.row(align=True)
            sub.alignment = 'RIGHT'
            sub.prop(
                widget_options,
                "preview_in_front",
                text="",
                toggle=True,
                icon='CHECKBOX_HLT' if widget_options.preview_in_front else 'CHECKBOX_DEHLT',
            )

        # ---------------- 编辑 ----------------
        edit_box = layout.box()
        header = edit_box.row(align=True)
        header.label(text="编辑")
        sub = header.row(align=True)
        sub.alignment = 'RIGHT'
        if edit_mode:
            sub.label(text="曲线编辑模式")
        else:
            sub.label(text="需选中头发并进入曲线编辑模式")

        row = edit_box.row(align=True)
        row.scale_y = 1.35
        row.enabled = widget_ready
        if widget_active:
            row.operator("figuhair.widget_stop", text="关闭横截面编辑器")
        else:
            row.operator("figuhair.widget_interact", text="打开横截面编辑器")

        edit_box.label(text="横截面")
        commands = edit_box.column(align=True)
        commands.enabled = edit_controls_enabled
        row = commands.row(align=True)
        op = row.operator("figuhair.widget_smooth_selected_vertices", text="普通平滑")
        op.mode = 'NEIGHBOR'
        op = row.operator("figuhair.widget_smooth_selected_vertices", text="圆形平滑")
        op.mode = 'CIRCULAR'
        row = commands.row(align=True)
        row.operator("figuhair.auto_simplify_cross_section", text="自动简化")
        op = row.operator("figuhair.apply_edge_flow", text="截面边流")
        if settings is not None:
            op.mode = settings.edge_flow_mode
            op.power = settings.edge_flow_power
            op.blend = settings.edge_flow_blend

        edit_box.label(text="曲线")
        curve_commands = edit_box.column(align=True)
        curve_commands.enabled = edit_controls_enabled
        row = curve_commands.row(align=True)
        row.operator("figuhair.smooth_curve_points", text="曲线平滑")
        row.operator("figuhair.reverse_curve_direction", text="翻转方向")

        if settings is not None:
            row = edit_box.row(align=True)
            row.enabled = edit_mode
            row.prop(
                settings,
                "auto_update",
                text="自动更新管线",
                toggle=True,
                icon='CHECKBOX_HLT' if settings.auto_update else 'CHECKBOX_DEHLT',
            )

        # ---------------- 输出 ----------------
        output_box = layout.box()
        output_box.label(text="输出")
        row = output_box.row(align=True)
        row.scale_y = 1.25
        row.operator("figuhair.merge_hair_for_export", text="合并所有头发")

        # ---------------- 设置（不常改动，可折叠） ----------------
        expanded = bool(prefs is not None and getattr(prefs, "settings_expanded", False))
        settings_box = layout.box()
        header = settings_box.row(align=True)
        if prefs is not None:
            header.prop(
                prefs,
                "settings_expanded",
                text="设置",
                emboss=False,
                icon='TRIA_DOWN' if expanded else 'TRIA_RIGHT',
            )
        else:
            header.label(text="设置")
        sub = header.row(align=True)
        sub.alignment = 'RIGHT'
        sub.label(text="不常改动")

        if expanded:
            if settings is None:
                settings_box.label(text="选择头发后可编辑", icon='INFO')
            else:
                column = settings_box.column(align=True)
                column.prop(settings, "shared_hair_material", text="材质")
                column.prop(settings, "roll_mode", text="滚转算法")
                row = settings_box.row(align=True)
                row.prop(
                    settings,
                    "smooth_shading",
                    text="平滑着色",
                    toggle=True,
                    icon='CHECKBOX_HLT' if settings.smooth_shading else 'CHECKBOX_DEHLT',
                )


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
