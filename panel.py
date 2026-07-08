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
            layout.label(text="\u8bf7\u9009\u62e9\u66f2\u7ebf\u6216 FiguHair \u9884\u89c8\u7f51\u683c", icon='INFO')
            return

        try:
            settings = curve_obj.hair_pipe_settings
            edit_mode = is_curve_edit_mode(curve_obj)
        except Exception as exc:
            layout.label(text="FiguHair \u72b6\u6001\u521d\u59cb\u5316\u5931\u8d25", icon='ERROR')
            layout.label(text=str(exc)[:80], icon='INFO')
            return

        box = layout.box()
        box.label(text="\u751f\u6210", icon='MESH_CYLINDER')
        row = box.row(align=True)
        row.scale_y = 1.35
        row.operator("hair_pipe.generate_pipe", text="\u751f\u6210 / \u66f4\u65b0\u7ba1\u7ebf")
        row2 = box.row(align=True)
        row2.scale_y = 1.2
        row2.operator("hair_pipe.duplicate_hair", text="复制头发", icon='DUPLICATE')
        row3 = box.row(align=True)
        row3.scale_y = 1.2
        row3.operator("hair_pipe.merge_hair_for_export", text="导出合并网格", icon='EXPORT')
        mode_text = "\u53ea\u9009\u66f2\u7ebf\u6a21\u5f0f" if settings.redirect_selection else "\u5934\u53d1\u7f51\u683c\u53ef\u9009\u6a21\u5f0f"
        row = box.row(align=True)
        row.prop(settings, "redirect_selection", text=mode_text, toggle=True)

        box = layout.box()
        box.label(text="\u9ed8\u8ba4\u8bbe\u7f6e", icon='MESH_CIRCLE')
        box.prop(settings, "pipe_resolution", text="\u8fc7\u6e21\u7ec6\u5206")
        box.prop(settings, "transition_mode", text="\u622a\u9762\u8fc7\u6e21")
        box.prop(settings, "transition_strength", text="\u8fc7\u6e21\u5f3a\u5ea6")
        box.prop(settings, "strong_smoothing", text="\u5f3a\u529b\u5e73\u6ed1")
        if settings.strong_smoothing:
            box.prop(settings, "strong_smoothing_iterations", text="\u5e73\u6ed1\u6b21\u6570")
        box.prop(settings, "smooth_shading", text="\u5e73\u6ed1\u7740\u8272")
        row = box.row(align=True)
        row.prop(settings, "subdivision_levels", text="细分层级")
        icon = 'HIDE_OFF' if settings.default_subdiv else 'HIDE_ON'
        row.prop(settings, "default_subdiv", text="", icon=icon, toggle=True)

        from .operators import get_tail_object_for_curve
        tail_box = layout.box()
        tail_box.label(text="\u672b\u7aef\u7f51\u683c", icon='MESH_CONE')
        hide_all_row = tail_box.row(align=True)
        hide_all_row.scale_y = 1.1
        hide_all_row.operator("hair_pipe.hide_all_tail_meshes", text="隐藏所有", icon='HIDE_ON')
        tail_obj = get_tail_object_for_curve(curve_obj)
        if tail_obj is None:
            row = tail_box.row(align=True)
            row.scale_y = 1.2
            row.operator("hair_pipe.create_tail_mesh", text="\u751f\u6210\u672b\u7aef\u7f51\u683c", icon='ADD')
        else:
            row = tail_box.row(align=True)
            row.operator("hair_pipe.edit_tail_mesh", text="\u7f16\u8f91", icon='EDITMODE_HLT')
            row.operator("hair_pipe.toggle_tail_visibility", text="", icon='HIDE_OFF' if not tail_obj.hide_viewport else 'HIDE_ON')
            row.operator("hair_pipe.remove_tail_mesh", text="", icon='TRASH')

        if not edit_mode:
            return

        header_box = layout.box()
        header_box.prop(settings, "auto_update", text="\u7f16\u8f91\u6a21\u5f0f\u64cd\u4f5c", icon='EDITMODE_HLT',
                        emboss=False)

        if not settings.auto_update:
            return

        box = header_box.box()
        box.label(text="\u622a\u9762\u8fc7\u6e21\u5e73\u6ed1", icon='IPO_BEZIER')
        row = box.row(align=True)
        row.scale_y = 1.25
        op = row.operator("hair_pipe.apply_edge_flow", text="\u622a\u9762\u8fb9\u6d41")
        op.mode = settings.edge_flow_mode
        op.power = settings.edge_flow_power
        op.blend = settings.edge_flow_blend
        row = box.row(align=True)
        row.scale_y = 1.1
        row.operator("hair_pipe.equalize_point_distance", text="\u66f2\u7ebf\u5e73\u6ed1", icon='SMOOTHCURVE')

        row = box.row(align=True)
        row.operator("hair_pipe.copy_cross_section", text="\u590d\u5236", icon='COPYDOWN')
        row.operator("hair_pipe.paste_cross_section", text="\u7c98\u8d34", icon='PASTEDOWN')

        transition_box = header_box.box()
        transition_box.label(text="横截面过渡", icon='IPO_EASE_IN_OUT')
        active_idx = min(settings.active_point_index, len(settings.point_settings) - 1)
        active_ps = settings.point_settings[active_idx]
        if getattr(active_ps, "use_transition", False):
            transition_box.label(text="当前点状态：过渡模式", icon='CHECKMARK')
        else:
            transition_box.label(text="当前点状态：正常模式", icon='RADIOBUT_OFF')
        row = transition_box.row(align=True)
        row.scale_y = 1.35
        row.operator("hair_pipe.toggle_cross_section_transition", text="切换横截面过渡模式", icon='IPO_EASE_IN_OUT')
        transition_box.label(text="可选择一个或多个曲线点后切换", icon='INFO')

        box = header_box.box()
        box.label(text="\u6a2a\u622a\u9762\u7f16\u8f91\u5668", icon='MOUSE_LMB')
        widget_data = getattr(context.window_manager, "hair_pipe_widget", None)
        if widget_data is None:
            box.label(text="\u6a2a\u622a\u9762\u7f16\u8f91\u5668\u672a\u521d\u59cb\u5316\uff0c\u8bf7\u91cd\u65b0\u52a0\u8f7d\u63d2\u4ef6", icon='ERROR')
            return
        row = box.row(align=True)
        if getattr(active_ps, "use_transition", False):
            row.enabled = False
            row.operator("hair_pipe.widget_interact", text="过渡模式下无法编辑横截面", icon='LOCKED')
        elif widget_data.is_active:
            row.operator("hair_pipe.widget_stop", text="\u5173\u95ed\u7f16\u8f91\u5668", icon='PANEL_CLOSE')
        else:
            row.operator("hair_pipe.widget_interact", text="\u6253\u5f00\u7f16\u8f91\u5668", icon='MOUSE_LMB')


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
