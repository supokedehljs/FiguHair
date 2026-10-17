import bpy
from bpy.types import AddonPreferences
from bpy.props import FloatProperty

# 常用命令：(操作符 idname, 面板上显示的名字)。注册成键位映射里的条目后，
# 就能在 偏好设置 > 键位映射 里直接给它们分配快捷键。
QUICK_COMMANDS = (
    ("figuhair.draw_hair_curve", "添加头发"),
    ("figuhair.widget_interact", "横截面编辑器（开/关）"),
    ("figuhair.toggle_solo_display", "单独显示"),
    ("figuhair.merge_hair_for_export", "合并所有头发"),
    ("figuhair.mesh_to_hair_curve", "发管转曲线"),
    ("figuhair.apply_edge_flow", "截面边流"),
    ("figuhair.reverse_curve_direction", "翻转方向"),
    ("figuhair.smooth_curve_points", "曲线平滑"),
    ("figuhair.auto_simplify_cross_section", "自动简化"),
    ("figuhair.widget_smooth_selected_vertices", "平滑横截面顶点"),
    ("figuhair.copy_cross_section", "复制横截面"),
    ("figuhair.paste_cross_section", "粘贴横截面"),
    ("figuhair.widget_toggle_ghost", "设置为幽灵点"),
    ("figuhair.widget_make_normal", "设置为正常点"),
)

DEFAULT_KEYMAP = {
    "figuhair.widget_interact": {"type": 'X', "value": 'PRESS', "ctrl": True, "shift": True},
    "figuhair.toggle_solo_display": {"type": 'F', "value": 'PRESS', "ctrl": True},
}


def shortcut_text(idname):
    keys = DEFAULT_KEYMAP.get(idname)
    if not keys:
        return ""
    parts = []
    if keys.get("ctrl"):
        parts.append("Ctrl")
    if keys.get("shift"):
        parts.append("Shift")
    if keys.get("alt"):
        parts.append("Alt")
    parts.append(keys.get("type", ""))
    return "+".join(part for part in parts if part)


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
    bl_idname = "figuhair"

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
        box = layout.box()
        box.label(text="横截面编辑器布局")
        row = box.row(align=True)
        row.prop(self, "widget_offset_x", text="左右")
        row.prop(self, "widget_offset_y", text="上下")
        row.prop(self, "widget_area_scale", text="大小")

        layout.separator()
        box = layout.box()
        box.label(text="常用命令快捷键", icon='KEYINGSET')
        box.label(text="在 键位映射 中搜索下面的命令名或 idname 即可分配快捷键", icon='INFO')
        column = box.column(align=True)
        for idname, label in QUICK_COMMANDS:
            row = column.row()
            split = row.split(factor=0.62)
            split.label(text=label)
            split.label(text=shortcut_text(idname) or "未设置")
        box.operator("screen.userpref_show", text="打开键位映射", icon='PREFERENCES').section = 'KEYMAP'


_addon_keymaps = []
_register_keymaps_retries = 0


def register_keymaps():
    global _register_keymaps_retries
    wm = getattr(bpy.context, 'window_manager', None)
    if wm is None or wm.keyconfigs.addon is None:
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
    for idname, _label in QUICK_COMMANDS:
        keys = DEFAULT_KEYMAP.get(idname, {"type": 'NONE', "value": 'PRESS'})
        try:
            kmi = km.keymap_items.new(idname, **keys)
        except (TypeError, ValueError, RuntimeError):
            continue
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
