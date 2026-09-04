import bpy
import rna_keymap_ui
from bpy.types import AddonPreferences
from bpy.props import FloatProperty


def update_widget_layout(self, context):
    wm = getattr(context, "window_manager", None)
    wd = getattr(wm, "hair_pipe_widget", None) if wm is not None else None
    if wd is None:
        return
    wd.fitted_point_index = -1
    screen = getattr(context, "screen", None)
    if screen is not None:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def draw_keymap_item(layout, keyconfig, keymap, keymap_item, label):
    """Use Blender's own Preferences > Keymap renderer."""
    if keymap_item is None or keymap is None or keyconfig is None:
        row = layout.row()
        row.label(text=label)
        row.label(text="未注册", icon='ERROR')
        return
    # draw_kmi supplies Blender's standard function name, mapping-type menu,
    # event editor, modifier region and the remove/reset X button.
    rna_keymap_ui.draw_kmi([], keyconfig, keymap, keymap_item, layout, 0)


def get_addon_keymap_items():
    result = {}
    wm = getattr(bpy.context, "window_manager", None)
    keyconfigs = getattr(wm, "keyconfigs", None) if wm is not None else None
    kc = getattr(keyconfigs, "addon", None) if keyconfigs is not None else None
    if kc is None:
        return kc, result
    for km in kc.keymaps:
        for kmi in km.keymap_items:
            if kmi.idname.startswith("hair_pipe."):
                result.setdefault(kmi.idname, []).append((km, kmi))
    return kc, result


class HairPipePreferences(AddonPreferences):
    bl_idname = "hair_curve_pipe"

    widget_offset_x: FloatProperty(
        name="左右",
        description="横截面编辑器显示区域的水平偏移",
        default=0.0,
        min=-1.0,
        max=1.0,
        precision=2,
        update=update_widget_layout,
    )
    widget_offset_y: FloatProperty(
        name="上下",
        description="横截面编辑器显示区域的垂直偏移",
        default=0.0,
        min=-1.0,
        max=1.0,
        precision=2,
        update=update_widget_layout,
    )
    widget_area_scale: FloatProperty(
        name="大小",
        description="横截面编辑器显示区域的整体大小",
        default=1.0,
        min=0.35,
        max=1.8,
        precision=2,
        update=update_widget_layout,
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text="横截面编辑器布局")
        row = layout.row(align=True)
        row.prop(self, "widget_offset_x", text="左右")
        row.prop(self, "widget_offset_y", text="上下")
        row.prop(self, "widget_area_scale", text="大小")

        layout.separator()
        layout.label(text="快捷键设置", icon='KEYINGSET')
        layout.label(text="以下快捷键可直接修改；也可在编辑 > 偏好设置 > 键位映射中搜索 FiguHair", icon='INFO')
        keyconfig, keymap_items = get_addon_keymap_items()
        keymap_entries = (
            ("hair_pipe.widget_interact", "横截面编辑器"),
            ("hair_pipe.hide_hair", "隐藏头发"),
            ("hair_pipe.show_all_hair", "显示全部头发"),
            ("hair_pipe.duplicate_hair", "复制头发"),
            ("hair_pipe.delete_hair", "删除头发"),
            ("hair_pipe.family_local_view", "头发局部视图"),
            ("hair_pipe.toggle_solo_display", "单独显示"),
        )
        for operator_id, label in keymap_entries:
            entries = keymap_items.get(operator_id, [])
            if entries:
                keymap, keymap_item = entries[0]
            else:
                keymap = keymap_item = None
            draw_keymap_item(layout, keyconfig, keymap, keymap_item, label)


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

    km = kc.keymaps.get('3D View')
    if km is None:
        km = kc.keymaps.new(name='3D View', space_type='VIEW_3D')
    existing = {(item.idname, item.type, item.value, item.ctrl, item.shift, item.alt) for item in km.keymap_items}
    if not any(item.idname == 'hair_pipe.widget_interact' for item in km.keymap_items):
        kmi = km.keymap_items.new('hair_pipe.widget_interact', 'C', 'PRESS')
        _addon_keymaps.append((km, kmi))
    if not any(item.idname == 'hair_pipe.toggle_solo_display' for item in km.keymap_items):
        kmi = km.keymap_items.new('hair_pipe.toggle_solo_display', 'NONE', 'PRESS')
        _addon_keymaps.append((km, kmi))
    _register_keymaps_retries = 0


def unregister_keymaps():
    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _addon_keymaps.clear()


classes = (HairPipePreferences,)


def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError as e:
            if "already registered" not in str(e):
                raise
    register_keymaps()


def unregister():
    unregister_keymaps()
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError):
            pass
