import bpy
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
        layout.label(text="请在 Blender 键位映射中搜索 FiguHair 修改快捷键", icon='INFO')
        layout.label(text="单独显示：hair_pipe.toggle_solo_display")
        layout.label(text="编辑器（开关）：hair_pipe.widget_interact")


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
    kmi = km.keymap_items.new('hair_pipe.widget_interact', 'X', 'PRESS', ctrl=True, shift=True)
    _addon_keymaps.append((km, kmi))
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
        bpy.utils.register_class(cls)
    register_keymaps()


def unregister():
    unregister_keymaps()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
