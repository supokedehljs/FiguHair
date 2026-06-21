"""Fix widget toggle: track trigger key in modal and close on same key press."""
import os

path = os.path.join(
    r"C:\Users\supokede\AppData\Roaming\Blender Foundation\Blender\5.0\scripts\addons\hair_curve_pipe",
    "widget_operator.py",
)

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Store the trigger key in invoke for toggle mode
old_invoke = '''    def invoke(self, context, event):
        if not setup_widget(context):
            self.report({'ERROR'}, "\\u672a\\u627e\\u5230 3D \\u89c6\\u56fe")
            return {'CANCELLED'}
        wd = context.window_manager.hair_pipe_widget
        wd.hold_key_mode = False
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _get_local_mouse(self, event, wd):
        return event.mouse_x - wd.region_offset_x, event.mouse_y - wd.region_offset_y

    def modal(self, context, event):
        return handle_widget_modal(self, context, event, close_on_key_release=False)'''

new_invoke = '''    def invoke(self, context, event):
        wd = context.window_manager.hair_pipe_widget
        if wd.is_active:
            wd.is_active = False
            wd.drag_vert_index = -1
            redraw_view3d(context)
            return {'FINISHED'}
        if not setup_widget(context):
            self.report({'ERROR'}, "\\u672a\\u627e\\u5230 3D \\u89c6\\u56fe")
            return {'CANCELLED'}
        wd.hold_key_mode = False
        self._trigger_key = event.type
        self._trigger_ctrl = event.ctrl
        self._trigger_shift = event.shift
        self._trigger_alt = event.alt
        self._just_opened = True
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _get_local_mouse(self, event, wd):
        return event.mouse_x - wd.region_offset_x, event.mouse_y - wd.region_offset_y

    def modal(self, context, event):
        if self._just_opened:
            if event.type == self._trigger_key and event.value == 'RELEASE':
                self._just_opened = False
            return {'RUNNING_MODAL'}
        if (event.type == self._trigger_key and event.value == 'PRESS'
                and event.ctrl == self._trigger_ctrl
                and event.shift == self._trigger_shift
                and event.alt == self._trigger_alt):
            self._finish(context)
            return {'FINISHED'}
        return handle_widget_modal(self, context, event, close_on_key_release=False)'''

if old_invoke in content:
    content = content.replace(old_invoke, new_invoke)
    print("[1] Fixed widget_interact toggle")
else:
    print("[1] SKIP - pattern not found")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Done.")
