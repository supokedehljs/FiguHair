import bpy
from .operators import (
    is_curve_edit_mode,
    get_curve_point_by_global_index,
    get_context_curve_object,
)
from .hair_library import (
    HAIRPIPE_OT_library_save_current,
    HAIRPIPE_OT_library_overlay_toggle,
    HAIRPIPE_OT_library_open_folder,
    sync_state_entries,
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

        box = layout.box()
        box.label(text="通用", icon='MESH_CYLINDER')
        if curve_obj is not None:
            row = box.row(align=True)
            row.scale_y = 1.35
            row.operator("hair_pipe.generate_pipe", text="生成 / 更新管线")
            row2 = box.row(align=True)
            row2.scale_y = 1.2
            row2.operator("hair_pipe.duplicate_hair", text="复制头发", icon='DUPLICATE')
            row2.operator("hair_pipe.delete_hair", text="删除头发", icon='TRASH')
            row3 = box.row(align=True)
            row3.scale_y = 1.2
            row3.operator("hair_pipe.merge_hair_for_export", text="导出合并网格", icon='EXPORT')
        row = box.row(align=True)
        row.scale_y = 1.2
        row.operator("hair_pipe.mesh_to_hair_curve", text="管状网格转头发曲线", icon='CURVE_DATA')

        if curve_obj is None:
            layout.label(text="请选择曲线、FiguHair 预览网格，或普通管状网格进行转换", icon='INFO')
            return

        try:
            settings = curve_obj.hair_pipe_settings
            edit_mode = is_curve_edit_mode(curve_obj)
        except Exception as exc:
            layout.label(text="FiguHair 状态初始化失败", icon='ERROR')
            layout.label(text=str(exc)[:80], icon='INFO')
            return
        row = box.row(align=True)
        row.operator("hair_pipe.toggle_solo_display", text="单独显示", icon='HIDE_OFF')
        row = box.row(align=True)
        row.operator("hair_pipe.library_save_current", text="保存到头发库", icon='FILE_TICK')
        row = box.row(align=True)
        row.operator("hair_pipe.library_overlay_toggle", text="打开头发库", icon='ASSET_MANAGER')
        row.operator("hair_pipe.library_open_folder", text="打开文件夹", icon='FILE_FOLDER')

        lib_state = getattr(context.window_manager, "hair_pipe_library_state", None)
        if lib_state is not None:
            sync_state_entries(lib_state)
            if len(lib_state.entries) > 0:
                box.label(text=f"库中共有 {len(lib_state.entries)} 个头发", icon='FILE_BLEND')
        mode_text = "只选曲线模式" if settings.redirect_selection else "头发网格可选模式"
        row = box.row(align=True)
        op = row.operator("hair_pipe.toggle_redirect_selection", text=mode_text, depress=settings.redirect_selection)

        box = layout.box()
        box.label(text="默认设置", icon='MESH_CIRCLE')
        box.prop(settings, "pipe_resolution", text="过渡细分")
        box.prop(settings, "transition_mode", text="截面过渡")
        box.prop(settings, "transition_strength", text="过渡强度")
        box.prop(settings, "strong_smoothing", text="强力平滑")
        if settings.strong_smoothing:
            box.prop(settings, "strong_smoothing_iterations", text="平滑次数")
        box.prop(settings, "smooth_shading", text="平滑着色")
        row = box.row(align=True)
        row.prop(settings, "subdivision_levels", text="细分层级")
        icon = 'HIDE_OFF' if settings.default_subdiv else 'HIDE_ON'
        row.prop(settings, "default_subdiv", text="", icon=icon, toggle=True)

        from .operators import get_tail_object_for_curve
        tail_box = layout.box()
        tail_box.label(text="末端网格", icon='MESH_CONE')
        hide_all_row = tail_box.row(align=True)
        hide_all_row.scale_y = 1.1
        hide_all_row.operator("hair_pipe.hide_all_tail_meshes", text="隐藏所有", icon='HIDE_ON')
        tail_obj = get_tail_object_for_curve(curve_obj)
        if tail_obj is None:
            row = tail_box.row(align=True)
            row.scale_y = 1.2
            row.operator("hair_pipe.create_tail_mesh", text="生成末端网格", icon='ADD')
        else:
            row = tail_box.row(align=True)
            row.operator("hair_pipe.edit_tail_mesh", text="编辑", icon='EDITMODE_HLT')
            row.operator("hair_pipe.toggle_tail_visibility", text="", icon='HIDE_OFF' if not tail_obj.hide_viewport else 'HIDE_ON')
            row.operator("hair_pipe.remove_tail_mesh", text="", icon='TRASH')

        if not edit_mode:
            return

        header_box = layout.box()
        header_box.prop(settings, "auto_update", text="编辑模式操作", icon='EDITMODE_HLT', emboss=False)

        if not settings.auto_update:
            return

        active_idx = min(settings.active_point_index, len(settings.point_settings) - 1)
        active_ps = settings.point_settings[active_idx]
        widget_data = getattr(context.window_manager, "hair_pipe_widget", None)

        box = header_box.box()
        row = box.row(align=True)
        row.scale_y = 1.25
        op = row.operator("hair_pipe.apply_edge_flow", text="截面边流")
        op.mode = settings.edge_flow_mode
        op.power = settings.edge_flow_power
        op.blend = settings.edge_flow_blend
        row.operator("hair_pipe.equalize_point_distance", text="曲线平滑", icon='SMOOTHCURVE')

        row = box.row(align=True)
        row.operator("hair_pipe.copy_cross_section", text="复制", icon='COPYDOWN')
        row.operator("hair_pipe.paste_cross_section", text="粘贴", icon='PASTEDOWN')

        row = box.row(align=True)
        row.scale_y = 1.2
        row.operator("hair_pipe.toggle_cross_section_transition", text=("切换到点正常模式" if getattr(active_ps, "use_transition", False) else "切换到点过渡模式"), icon='IPO_EASE_IN_OUT')

        addon_entry = context.preferences.addons.get("hair_curve_pipe")
        widget_layout = addon_entry.preferences if addon_entry is not None else settings
        row = box.row(align=True)
        row.prop(widget_layout, "widget_offset_x", text="左右")
        row.prop(widget_layout, "widget_offset_y", text="上下")
        row.prop(widget_layout, "widget_area_scale", text="大小")

        if widget_data is None:
            box.label(text="横截面编辑器未初始化，请重新加载插件", icon='ERROR')
        else:
            row = box.row(align=True)
            if getattr(active_ps, "use_transition", False):
                row.enabled = False
                row.operator("hair_pipe.widget_interact", text="过渡模式下无法编辑横截面", icon='LOCKED')
            elif widget_data.is_active:
                row.operator("hair_pipe.widget_stop", text="关闭编辑器", icon='PANEL_CLOSE')
                row = box.row(align=True)
                row.operator("hair_pipe.widget_add_vertex", text="添加")
                row.operator("hair_pipe.widget_remove_vertex", text="删除")
                row = box.row(align=True)
                row.operator("hair_pipe.widget_toggle_ghost", text="设置为幽灵点")
                row.operator("hair_pipe.widget_make_normal", text="设置为正常点")
                row = box.row(align=True)
                row.operator("hair_pipe.widget_toggle_smooth_preview", text="细分预览", depress=widget_data.show_smooth_preview)
                row.operator("hair_pipe.widget_toggle_flip", text="水平翻转", depress=widget_data.flip_horizontal)
                row.operator("hair_pipe.widget_toggle_grid", text="显示网格", depress=widget_data.show_full_mesh_grid)
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
