import bpy
from bpy.types import AddonPreferences
from bpy.props import EnumProperty, FloatProperty

WIDGET_MODE_ITEMS = [
    ('TOGGLE', "\u5f00\u5173\u6a21\u5f0f", "\u70b9\u51fb\u6253\u5f00\uff0c\u518d\u70b9\u51fb\u5173\u95ed"),
    ('HOLD', "\u6309\u4f4f\u6a21\u5f0f", "\u6309\u4e0b\u6253\u5f00\uff0c\u677e\u5f00\u5173\u95ed"),
]


class HairPipePreferences(AddonPreferences):
    bl_idname = "hair_curve_pipe"

    widget_mode: EnumProperty(
        name="\u7f16\u8f91\u5668\u6a21\u5f0f",
        items=WIDGET_MODE_ITEMS,
        default='HOLD',
    )
    widget_offset_x: FloatProperty(
        name="左右",
        description="横截面编辑器显示区域的水平偏移，保存偏好设置后下次启动保持",
        default=0.0,
        min=-1.0,
        max=1.0,
        precision=2,
    )
    widget_offset_y: FloatProperty(
        name="上下",
        description="横截面编辑器显示区域的垂直偏移，保存偏好设置后下次启动保持",
        default=0.0,
        min=-1.0,
        max=1.0,
        precision=2,
    )
    widget_area_scale: FloatProperty(
        name="大小",
        description="横截面编辑器显示区域的整体大小，保存偏好设置后下次启动保持",
        default=1.0,
        min=0.35,
        max=1.8,
        precision=2,
    )

    def draw(self, context):
        layout = self.layout

        row = layout.row()
        row.label(text="\u6a2a\u622a\u9762\u7f16\u8f91\u5668\u89e6\u53d1\u6a21\u5f0f:")
        row.prop(self, "widget_mode", text="")

        layout.label(text="横截面编辑器布局:")
        row = layout.row(align=True)
        row.prop(self, "widget_offset_x", text="左右")
        row.prop(self, "widget_offset_y", text="上下")
        row.prop(self, "widget_area_scale", text="大小")

        layout.separator()
        layout.label(text="\u5feb\u6377\u952e\u8bbe\u7f6e", icon='KEYINGSET')
        layout.label(text="\u5728\u4e0b\u65b9\u76f4\u63a5\u70b9\u51fb\u5feb\u6377\u952e\u533a\u57df\u5f55\u5236\u65b0\u6309\u952e", icon='INFO')

        col = layout.column()
        wm = context.window_manager
        kc = wm.keyconfigs.user
        if kc is None:
            kc = wm.keyconfigs.addon

        km = None
        if kc is not None:
            for k in kc.keymaps:
                if k.name == '3D View':
                    km = k
                    break

        if km is None:
            layout.label(text="\u672a\u627e\u5230 3D View keymap", icon='ERROR')
            return

        ops_to_show = [
            ("hair_pipe.generate_pipe", "\u751f\u6210/\u66f4\u65b0\u7ba1\u7ebf"),
            ("hair_pipe.toggle_redirect_selection", "\u53ea\u9009\u66f2\u7ebf\u6a21\u5f0f"),
            ("hair_pipe.toggle_solo_display", "单独显示"),
            ("hair_pipe.apply_edge_flow", "\u5e94\u7528\u8fb9\u6d41"),
            ("hair_pipe.equalize_point_distance", "\u8ddd\u79bb\u5e73\u5747\u5316"),
            ("hair_pipe.edit_tail_mesh", "\u672b\u7aef\u7f51\u683c\u7f16\u8f91\u6a21\u5f0f"),
            ("hair_pipe.widget_interact", "\u7f16\u8f91\u5668(\u5f00\u5173)"),
            ("hair_pipe.widget_hold", "\u7f16\u8f91\u5668(\u6309\u4f4f)"),
            ("hair_pipe.copy_cross_section", "\u590d\u5236\u622a\u9762"),
            ("hair_pipe.paste_cross_section", "\u7c98\u8d34\u622a\u9762"),
        ]

        for idname, label in ops_to_show:
            kmi = next((item for item in km.keymap_items if item.idname == idname), None)
            row = col.row(align=True)
            row.scale_y = 1.15
            if kmi is not None:
                row.prop(kmi, "active", text="")
            else:
                disabled = row.row()
                disabled.enabled = False
                disabled.label(text="", icon='CHECKBOX_DEHLT')
            name_row = row.row()
            name_row.enabled = bool(kmi is not None and kmi.active)
            name_row.label(text=label)
            shortcut_text = "点击录入快捷键"
            if kmi is not None and kmi.type != 'NONE':
                parts = []
                if kmi.ctrl:
                    parts.append("Ctrl")
                if kmi.shift:
                    parts.append("Shift")
                if kmi.alt:
                    parts.append("Alt")
                parts.append(kmi.type.replace('_', ' ').title())
                shortcut_text = " + ".join(parts)
            capture = row.operator("hair_pipe.capture_shortcut", text=shortcut_text, icon='EVENT_A')
            capture.operator_idname = idname


class HAIRPIPE_OT_capture_shortcut(bpy.types.Operator):
    bl_idname = "hair_pipe.capture_shortcut"
    bl_label = "录入快捷键"
    bl_description = "点击后按下新的键盘快捷键，Esc 取消，Backspace 清除"

    operator_idname: bpy.props.StringProperty()
    _kmi = None

    def invoke(self, context, event):
        wm = context.window_manager
        kc = wm.keyconfigs.user or wm.keyconfigs.addon
        if kc is None:
            return {'CANCELLED'}
        km = kc.keymaps.get('3D View')
        if km is None:
            km = kc.keymaps.new(name='3D View', space_type='VIEW_3D')
        self._kmi = next((item for item in km.keymap_items if item.idname == self.operator_idname), None)
        if self._kmi is None:
            self._kmi = km.keymap_items.new(self.operator_idname, 'NONE', 'PRESS')
        context.window_manager.modal_handler_add(self)
        context.window.cursor_modal_set('EYEDROPPER')
        context.area.header_text_set("请按下新的快捷键（可组合 Ctrl / Shift / Alt）；Esc 取消，Backspace 清除")
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.value != 'PRESS':
            return {'RUNNING_MODAL'}
        if event.type == 'ESC':
            context.window.cursor_modal_restore()
            context.area.header_text_set(None)
            return {'CANCELLED'}
        if event.type in {'BACK_SPACE', 'DEL'}:
            self._kmi.type = 'NONE'
        elif event.type in {'LEFT_CTRL', 'RIGHT_CTRL', 'LEFT_SHIFT', 'RIGHT_SHIFT', 'LEFT_ALT', 'RIGHT_ALT', 'OSKEY'}:
            return {'RUNNING_MODAL'}
        elif event.type in {'LEFTMOUSE', 'RIGHTMOUSE', 'MIDDLEMOUSE', 'MOUSEMOVE', 'TIMER'}:
            return {'RUNNING_MODAL'}
        else:
            self._kmi.type = event.type
            self._kmi.value = 'PRESS'
            self._kmi.ctrl = event.ctrl
            self._kmi.shift = event.shift
            self._kmi.alt = event.alt
            self._kmi.oskey = event.oskey
            self._kmi.active = True
        context.window.cursor_modal_restore()
        context.area.header_text_set(None)
        context.area.tag_redraw()
        return {'FINISHED'}


class HAIRPIPE_OT_add_keymap_item(bpy.types.Operator):
    """Add a new keymap item for this operator"""
    bl_idname = "hair_pipe.add_keymap_item"
    bl_label = "\u6dfb\u52a0\u5feb\u6377\u952e"

    operator_idname: bpy.props.StringProperty()

    def execute(self, context):
        wm = context.window_manager
        kc = wm.keyconfigs.user
        if kc is None:
            kc = wm.keyconfigs.addon
        if kc is None:
            return {'CANCELLED'}
        km = None
        for k in kc.keymaps:
            if k.name == '3D View':
                km = k
                break
        if km is None:
            km = kc.keymaps.new(name='3D View', space_type='VIEW_3D')
        km.keymap_items.new(self.operator_idname, 'NONE', 'PRESS')
        return {'FINISHED'}


_addon_keymaps = []


_register_keymaps_retries = 0

def register_keymaps():
    global _register_keymaps_retries
    wm = getattr(bpy.context, 'window_manager', None)
    if wm is None:
        if _register_keymaps_retries < 10:
            _register_keymaps_retries += 1
            def _defer_register():
                register_keymaps()
                return None
            bpy.app.timers.register(_defer_register, first_interval=0.5)
        return
    kc = wm.keyconfigs.addon
    if kc is None:
        return

    km = kc.keymaps.new(name='3D View', space_type='VIEW_3D')

    prefs = bpy.context.preferences.addons.get("hair_curve_pipe")
    widget_mode = 'HOLD'
    if prefs is not None:
        widget_mode = prefs.preferences.widget_mode

    if widget_mode == 'HOLD':
        kmi = km.keymap_items.new('hair_pipe.widget_hold', 'X', 'PRESS', ctrl=True, shift=True)
    else:
        kmi = km.keymap_items.new('hair_pipe.widget_interact', 'X', 'PRESS', ctrl=True, shift=True)
    _addon_keymaps.append((km, kmi))

    kmi = km.keymap_items.new('hair_pipe.toggle_solo_display', 'NONE', 'PRESS')
    _addon_keymaps.append((km, kmi))
    _register_keymaps_retries = 0


def unregister_keymaps():
    for km, kmi in _addon_keymaps:
        km.keymap_items.remove(kmi)
    _addon_keymaps.clear()


classes = (
    HairPipePreferences,
    HAIRPIPE_OT_capture_shortcut,
    HAIRPIPE_OT_add_keymap_item,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    register_keymaps()


def unregister():
    unregister_keymaps()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
