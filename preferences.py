import bpy
from bpy.types import AddonPreferences
from bpy.props import EnumProperty

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

    def draw(self, context):
        layout = self.layout

        row = layout.row()
        row.label(text="\u6a2a\u622a\u9762\u7f16\u8f91\u5668\u89e6\u53d1\u6a21\u5f0f:")
        row.prop(self, "widget_mode", text="")

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
            ("hair_pipe.apply_edge_flow", "\u5e94\u7528\u8fb9\u6d41"),
            ("hair_pipe.equalize_point_distance", "\u8ddd\u79bb\u5e73\u5747\u5316"),
            ("hair_pipe.widget_interact", "\u7f16\u8f91\u5668(\u5f00\u5173)"),
            ("hair_pipe.widget_hold", "\u7f16\u8f91\u5668(\u6309\u4f4f)"),
            ("hair_pipe.copy_cross_section", "\u590d\u5236\u622a\u9762"),
            ("hair_pipe.paste_cross_section", "\u7c98\u8d34\u622a\u9762"),
        ]

        for idname, label in ops_to_show:
            found = False
            for kmi in km.keymap_items:
                if kmi.idname == idname:
                    box = col.box()
                    row = box.row(align=True)
                    row.label(text=label)
                    row.prop(kmi, "type", text="", full_event=True)
                    row.prop(kmi, "active", text="")
                    found = True
                    break
            if not found:
                box = col.box()
                row = box.row(align=True)
                row.label(text=label)
                row.label(text="(\u672a\u8bbe\u7f6e)")
                row.operator("hair_pipe.add_keymap_item", text="", icon='ADD').operator_idname = idname


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


def register_keymaps():
    wm = bpy.context.window_manager
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


def unregister_keymaps():
    for km, kmi in _addon_keymaps:
        km.keymap_items.remove(kmi)
    _addon_keymaps.clear()


classes = (
    HairPipePreferences,
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
