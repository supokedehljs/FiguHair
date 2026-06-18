import bpy
import gpu
import math
import blf
from gpu_extras.batch import batch_for_shader
from bpy.props import IntProperty, FloatProperty, BoolProperty
from bpy.types import PropertyGroup


_draw_handle = None
_addon_keymaps = []


class HairPipeWidgetSettings(PropertyGroup):
    """Runtime state for the cross-section widget"""
    widget_center_x: FloatProperty(default=0.0)
    widget_center_y: FloatProperty(default=0.0)
    widget_size: FloatProperty(default=250.0)
    widget_scale_factor: FloatProperty(default=1.0)
    is_active: BoolProperty(default=False)
    drag_vert_index: IntProperty(default=-1)
    region_offset_x: IntProperty(default=0)
    region_offset_y: IntProperty(default=0)
    hold_key_mode: BoolProperty(default=False)
    add_button_x0: FloatProperty(default=0.0)
    add_button_y0: FloatProperty(default=0.0)
    add_button_x1: FloatProperty(default=0.0)
    add_button_y1: FloatProperty(default=0.0)
    remove_button_x0: FloatProperty(default=0.0)
    remove_button_y0: FloatProperty(default=0.0)
    remove_button_x1: FloatProperty(default=0.0)
    remove_button_y1: FloatProperty(default=0.0)


def draw_widget_callback():
    """Draw the cross-section widget overlay in 3D viewport"""
    try:
        context = bpy.context
    except Exception:
        return

    obj = context.active_object
    if obj is None or obj.type != 'CURVE':
        return
    if not hasattr(obj, 'hair_pipe_settings'):
        return

    settings = obj.hair_pipe_settings
    if len(settings.point_settings) == 0:
        return
    if settings.active_point_index >= len(settings.point_settings):
        return

    ps = settings.point_settings[settings.active_point_index]
    verts = ps.cross_section_verts
    n = len(verts)
    if n < 3:
        return

    wm = context.window_manager
    if not hasattr(wm, 'hair_pipe_widget'):
        return
    wd = wm.hair_pipe_widget
    if not wd.is_active:
        return

    cx = wd.widget_center_x
    cy = wd.widget_center_y
    size = wd.widget_size
    if size < 10:
        return

    padding = 18
    half = size / 2.0 - padding

    max_off = max((max(abs(v.offset_x), abs(v.offset_y)) for v in verts), default=0.05)
    if max_off < 1e-6:
        max_off = 0.05
    sf = half / (max_off * 1.2)
    wd.widget_scale_factor = sf

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')

    x0, y0 = cx - half - padding, cy - half - padding
    x1, y1 = cx + half + padding, cy + half + padding
    bg = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    batch = batch_for_shader(shader, 'TRIS', {"pos": bg}, indices=[(0, 1, 2), (0, 2, 3)])
    shader.bind()
    shader.uniform_float("color", (0.08, 0.08, 0.08, 0.94))
    batch.draw(shader)

    gpu.state.line_width_set(1.5)
    brd = [bg[0], bg[1], bg[1], bg[2], bg[2], bg[3], bg[3], bg[0]]
    batch = batch_for_shader(shader, 'LINES', {"pos": brd})
    shader.bind()
    shader.uniform_float("color", (0.55, 0.55, 0.55, 1.0))
    batch.draw(shader)

    gpu.state.line_width_set(1.0)
    grid = [(cx - half, cy), (cx + half, cy), (cx, cy - half), (cx, cy + half)]
    batch = batch_for_shader(shader, 'LINES', {"pos": grid})
    shader.bind()
    shader.uniform_float("color", (0.25, 0.25, 0.25, 0.7))
    batch.draw(shader)

    ref_r = settings.default_radius * sf
    circ = []
    for i in range(64):
        a0 = 2 * math.pi * i / 64
        a1 = 2 * math.pi * ((i + 1) % 64) / 64
        circ.append((cx + math.cos(a0) * ref_r, cy + math.sin(a0) * ref_r))
        circ.append((cx + math.cos(a1) * ref_r, cy + math.sin(a1) * ref_r))
    batch = batch_for_shader(shader, 'LINES', {"pos": circ})
    shader.bind()
    shader.uniform_float("color", (0.45, 0.45, 0.2, 0.45))
    batch.draw(shader)

    outline = []
    for i in range(n):
        j = (i + 1) % n
        outline.append((cx + verts[i].offset_x * sf, cy + verts[i].offset_y * sf))
        outline.append((cx + verts[j].offset_x * sf, cy + verts[j].offset_y * sf))
    gpu.state.line_width_set(2.5)
    batch = batch_for_shader(shader, 'LINES', {"pos": outline})
    shader.bind()
    shader.uniform_float("color", (1.0, 0.8, 0.05, 1.0))
    batch.draw(shader)

    gpu.state.point_size_set(12.0)
    pts = [(cx + v.offset_x * sf, cy + v.offset_y * sf) for v in verts]
    batch = batch_for_shader(shader, 'POINTS', {"pos": pts})
    shader.bind()
    shader.uniform_float("color", (1.0, 1.0, 1.0, 1.0))
    batch.draw(shader)

    aidx = ps.active_vert_index
    if 0 <= aidx < n:
        gpu.state.point_size_set(18.0)
        ap = [(cx + verts[aidx].offset_x * sf, cy + verts[aidx].offset_y * sf)]
        batch = batch_for_shader(shader, 'POINTS', {"pos": ap})
        shader.bind()
        shader.uniform_float("color", (0.0, 0.95, 1.0, 1.0))
        batch.draw(shader)

    button_w = 74.0
    button_h = 28.0
    gap = 10.0
    by0 = y0 - button_h - 10.0
    by1 = by0 + button_h
    add_x0 = cx - button_w - gap * 0.5
    add_x1 = add_x0 + button_w
    rem_x0 = cx + gap * 0.5
    rem_x1 = rem_x0 + button_w
    wd.add_button_x0 = add_x0
    wd.add_button_y0 = by0
    wd.add_button_x1 = add_x1
    wd.add_button_y1 = by1
    wd.remove_button_x0 = rem_x0
    wd.remove_button_y0 = by0
    wd.remove_button_x1 = rem_x1
    wd.remove_button_y1 = by1

    add_bg = [(add_x0, by0), (add_x1, by0), (add_x1, by1), (add_x0, by1)]
    batch = batch_for_shader(shader, 'TRIS', {"pos": add_bg}, indices=[(0, 1, 2), (0, 2, 3)])
    shader.bind()
    shader.uniform_float("color", (0.12, 0.38, 0.18, 0.95))
    batch.draw(shader)

    can_remove = all(len(point_setting.cross_section_verts) > 3 for point_setting in settings.point_settings)
    rem_bg = [(rem_x0, by0), (rem_x1, by0), (rem_x1, by1), (rem_x0, by1)]
    batch = batch_for_shader(shader, 'TRIS', {"pos": rem_bg}, indices=[(0, 1, 2), (0, 2, 3)])
    shader.bind()
    shader.uniform_float("color", (0.42, 0.14, 0.12, 0.95) if can_remove else (0.18, 0.18, 0.18, 0.85))
    batch.draw(shader)

    button_lines = [
        (add_x0, by0), (add_x1, by0), (add_x1, by0), (add_x1, by1),
        (add_x1, by1), (add_x0, by1), (add_x0, by1), (add_x0, by0),
        (rem_x0, by0), (rem_x1, by0), (rem_x1, by0), (rem_x1, by1),
        (rem_x1, by1), (rem_x0, by1), (rem_x0, by1), (rem_x0, by0),
    ]
    gpu.state.line_width_set(1.0)
    batch = batch_for_shader(shader, 'LINES', {"pos": button_lines})
    shader.bind()
    shader.uniform_float("color", (0.75, 0.75, 0.75, 1.0))
    batch.draw(shader)

    font_id = 0
    blf.size(font_id, 12)
    blf.color(font_id, 0.82, 0.82, 0.82, 0.9)
    blf.position(font_id, x0 + 10.0, by1 + 8.0, 0)
    blf.draw(font_id, "Middle click an edge to insert a point")
    blf.size(font_id, 14)
    blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
    blf.position(font_id, add_x0 + 17.0, by0 + 7.0, 0)
    blf.draw(font_id, "+ Add")
    blf.color(font_id, 1.0, 1.0, 1.0, 1.0 if can_remove else 0.35)
    blf.position(font_id, rem_x0 + 18.0, by0 + 7.0, 0)
    blf.draw(font_id, "- Del")

    gpu.state.line_width_set(1.0)
    gpu.state.point_size_set(1.0)
    gpu.state.blend_set('NONE')


def ensure_draw_handler():
    global _draw_handle
    if _draw_handle is None:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            draw_widget_callback, (), 'WINDOW', 'POST_PIXEL'
        )


def remove_draw_handler():
    global _draw_handle
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None


def get_view3d_window_region(context):
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            for region in area.regions:
                if region.type == 'WINDOW':
                    return area, region
    return None, None


def setup_widget(context):
    wd = context.window_manager.hair_pipe_widget
    area, region = get_view3d_window_region(context)
    if region is None:
        return False

    wd.region_offset_x = region.x
    wd.region_offset_y = region.y
    wd.widget_size = min(region.width, region.height) * 0.5
    wd.widget_center_x = region.width / 2.0
    wd.widget_center_y = region.height / 2.0
    wd.is_active = True
    wd.drag_vert_index = -1
    ensure_draw_handler()
    redraw_view3d(context)
    return True


def redraw_view3d(context):
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


def is_inside_rect(x, y, x0, y0, x1, y1):
    return x0 <= x <= x1 and y0 <= y <= y1


def add_cross_section_vertex(ps, settings):
    verts = ps.cross_section_verts
    n = len(verts)
    if n < 2:
        for point_setting in settings.point_settings:
            v = point_setting.cross_section_verts.add()
            v.offset_x = settings.default_radius
            v.offset_y = 0.0
            point_setting.active_vert_index = len(point_setting.cross_section_verts) - 1
        return

    idx = max(0, min(ps.active_vert_index, n - 1))
    add_cross_section_vertex_after_all(settings, idx)


def add_cross_section_vertex_after(ps, idx):
    verts = ps.cross_section_verts
    n = len(verts)
    idx = max(0, min(idx, n - 1))
    idx_next = (idx + 1) % n
    v = verts.add()
    v.offset_x = (verts[idx].offset_x + verts[idx_next].offset_x) * 0.5
    v.offset_y = (verts[idx].offset_y + verts[idx_next].offset_y) * 0.5
    target = idx + 1
    for i in range(len(verts) - 1, target, -1):
        verts.move(i, i - 1)
    ps.active_vert_index = target


def add_cross_section_vertex_after_all(settings, idx):
    for point_setting in settings.point_settings:
        if len(point_setting.cross_section_verts) >= 2:
            add_cross_section_vertex_after(point_setting, idx)


def insert_cross_section_vertex_on_edge(ps, edge_idx, local_x, local_y):
    verts = ps.cross_section_verts
    n = len(verts)
    edge_idx = max(0, min(edge_idx, n - 1))
    v = verts.add()
    v.offset_x = local_x
    v.offset_y = local_y
    target = edge_idx + 1
    for i in range(len(verts) - 1, target, -1):
        verts.move(i, i - 1)
    ps.active_vert_index = target


def insert_cross_section_vertex_on_edge_at_ratio(ps, edge_idx, edge_t):
    verts = ps.cross_section_verts
    n = len(verts)
    edge_idx = max(0, min(edge_idx, n - 1))
    idx_next = (edge_idx + 1) % n
    local_x = verts[edge_idx].offset_x * (1.0 - edge_t) + verts[idx_next].offset_x * edge_t
    local_y = verts[edge_idx].offset_y * (1.0 - edge_t) + verts[idx_next].offset_y * edge_t
    insert_cross_section_vertex_on_edge(ps, edge_idx, local_x, local_y)


def insert_cross_section_vertex_on_edge_all(settings, active_index, edge_idx, local_x, local_y, edge_t):
    for idx, point_setting in enumerate(settings.point_settings):
        if len(point_setting.cross_section_verts) < 2:
            continue
        if idx == active_index:
            insert_cross_section_vertex_on_edge(point_setting, edge_idx, local_x, local_y)
        else:
            insert_cross_section_vertex_on_edge_at_ratio(point_setting, edge_idx, edge_t)


def distance_point_to_segment(px, py, ax, ay, bx, by):
    abx = bx - ax
    aby = by - ay
    apx = px - ax
    apy = py - ay
    ab_len_sq = abx * abx + aby * aby
    if ab_len_sq < 1e-8:
        return math.sqrt((px - ax) ** 2 + (py - ay) ** 2), ax, ay, 0.0
    t = max(0.0, min(1.0, (apx * abx + apy * aby) / ab_len_sq))
    cx = ax + abx * t
    cy = ay + aby * t
    return math.sqrt((px - cx) ** 2 + (py - cy) ** 2), cx, cy, t


def find_nearest_cross_section_edge(verts, mx, my, cx, cy, sf):
    closest_idx = -1
    closest_dist = 18.0
    closest_local = (0.0, 0.0)
    closest_t = 0.5
    n = len(verts)
    for i in range(n):
        j = (i + 1) % n
        ax = cx + verts[i].offset_x * sf
        ay = cy + verts[i].offset_y * sf
        bx = cx + verts[j].offset_x * sf
        by = cy + verts[j].offset_y * sf
        dist, hit_x, hit_y, edge_t = distance_point_to_segment(mx, my, ax, ay, bx, by)
        if dist < closest_dist:
            closest_dist = dist
            closest_idx = i
            closest_local = ((hit_x - cx) / sf, (hit_y - cy) / sf)
            closest_t = edge_t
    return closest_idx, closest_local, closest_t


def remove_cross_section_vertex(ps):
    verts = ps.cross_section_verts
    if len(verts) <= 3:
        return False
    idx = max(0, min(ps.active_vert_index, len(verts) - 1))
    verts.remove(idx)
    ps.active_vert_index = min(idx, len(verts) - 1)
    return True


def remove_cross_section_vertex_all(settings, remove_idx):
    if any(len(point_setting.cross_section_verts) <= 3 for point_setting in settings.point_settings):
        return False
    for point_setting in settings.point_settings:
        verts = point_setting.cross_section_verts
        idx = max(0, min(remove_idx, len(verts) - 1))
        verts.remove(idx)
        point_setting.active_vert_index = min(idx, len(verts) - 1)
    return True


class HAIRPIPE_OT_widget_interact(bpy.types.Operator):
    """Open interactive cross-section editor overlay in the 3D viewport"""
    bl_idname = "hair_pipe.widget_interact"
    bl_label = "编辑横截面"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE':
            return False
        s = obj.hair_pipe_settings
        if len(s.point_settings) == 0:
            return False
        if s.active_point_index >= len(s.point_settings):
            return False
        ps = s.point_settings[s.active_point_index]
        return len(ps.cross_section_verts) >= 3

    def invoke(self, context, event):
        if not setup_widget(context):
            self.report({'ERROR'}, "未找到 3D 视图")
            return {'CANCELLED'}
        wd = context.window_manager.hair_pipe_widget
        wd.hold_key_mode = False
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _get_local_mouse(self, event, wd):
        return event.mouse_x - wd.region_offset_x, event.mouse_y - wd.region_offset_y

    def modal(self, context, event):
        return handle_widget_modal(self, context, event, close_on_key_release=False)

    def _finish(self, context):
        wd = context.window_manager.hair_pipe_widget
        wd.is_active = False
        wd.drag_vert_index = -1
        redraw_view3d(context)


class HAIRPIPE_OT_widget_hold(bpy.types.Operator):
    """Hold shortcut to temporarily show and edit the cross-section widget"""
    bl_idname = "hair_pipe.widget_hold"
    bl_label = "按住编辑横截面"

    @classmethod
    def poll(cls, context):
        return HAIRPIPE_OT_widget_interact.poll(context)

    def invoke(self, context, event):
        if not setup_widget(context):
            self.report({'ERROR'}, "未找到 3D 视图")
            return {'CANCELLED'}
        wd = context.window_manager.hair_pipe_widget
        wd.hold_key_mode = True
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _get_local_mouse(self, event, wd):
        return event.mouse_x - wd.region_offset_x, event.mouse_y - wd.region_offset_y

    def modal(self, context, event):
        return handle_widget_modal(self, context, event, close_on_key_release=True)

    def _finish(self, context):
        wd = context.window_manager.hair_pipe_widget
        wd.is_active = False
        wd.drag_vert_index = -1
        wd.hold_key_mode = False
        redraw_view3d(context)


def handle_widget_modal(operator, context, event, close_on_key_release=False):
    wd = context.window_manager.hair_pipe_widget

    if not wd.is_active:
        operator._finish(context)
        return {'FINISHED'}

    if close_on_key_release and event.type == 'X' and event.value == 'RELEASE':
        operator._finish(context)
        return {'FINISHED'}

    obj = context.active_object
    if obj is None or obj.type != 'CURVE':
        operator._finish(context)
        return {'CANCELLED'}

    settings = obj.hair_pipe_settings
    if settings.active_point_index >= len(settings.point_settings):
        operator._finish(context)
        return {'CANCELLED'}

    ps = settings.point_settings[settings.active_point_index]
    verts = ps.cross_section_verts
    if len(verts) < 3:
        operator._finish(context)
        return {'CANCELLED'}

    cx = wd.widget_center_x
    cy = wd.widget_center_y
    sf = wd.widget_scale_factor
    mx, my = operator._get_local_mouse(event, wd)
    half = wd.widget_size / 2.0
    inside_widget = abs(mx - cx) <= half and abs(my - cy) <= half
    inside_add_button = is_inside_rect(mx, my, wd.add_button_x0, wd.add_button_y0, wd.add_button_x1, wd.add_button_y1)
    inside_remove_button = is_inside_rect(
        mx, my, wd.remove_button_x0, wd.remove_button_y0, wd.remove_button_x1, wd.remove_button_y1
    )
    inside_controls = inside_add_button or inside_remove_button

    if event.type == 'MIDDLEMOUSE' and event.value == 'PRESS':
        if inside_widget and sf > 0.001:
            edge_idx, local_pos, edge_t = find_nearest_cross_section_edge(verts, mx, my, cx, cy, sf)
            if edge_idx >= 0:
                insert_cross_section_vertex_on_edge_all(
                    settings, settings.active_point_index, edge_idx, local_pos[0], local_pos[1], edge_t
                )
                wd.drag_vert_index = -1
                redraw_view3d(context)
                return {'RUNNING_MODAL'}
        if inside_widget or inside_controls:
            return {'RUNNING_MODAL'}

    if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
        if inside_add_button:
            add_cross_section_vertex(ps, settings)
            wd.drag_vert_index = -1
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if inside_remove_button:
            remove_cross_section_vertex_all(settings, ps.active_vert_index)
            wd.drag_vert_index = -1
            redraw_view3d(context)
            return {'RUNNING_MODAL'}

        if not inside_widget:
            if close_on_key_release or inside_controls:
                return {'RUNNING_MODAL'}
            operator._finish(context)
            return {'FINISHED'}

        closest_idx = -1
        closest_dist = 24.0
        for i, v in enumerate(verts):
            px = cx + v.offset_x * sf
            py = cy + v.offset_y * sf
            dist = math.sqrt((mx - px) ** 2 + (my - py) ** 2)
            if dist < closest_dist:
                closest_dist = dist
                closest_idx = i

        if closest_idx >= 0:
            wd.drag_vert_index = closest_idx
            ps.active_vert_index = closest_idx
            redraw_view3d(context)
        return {'RUNNING_MODAL'}

    if event.type == 'MOUSEMOVE':
        if 0 <= wd.drag_vert_index < len(verts) and sf > 0.001:
            verts[wd.drag_vert_index].offset_x = (mx - cx) / sf
            verts[wd.drag_vert_index].offset_y = (my - cy) / sf
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if inside_widget or inside_controls:
            return {'RUNNING_MODAL'}

    if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
        wd.drag_vert_index = -1
        redraw_view3d(context)
        return {'RUNNING_MODAL'}

    if event.type in {'RIGHTMOUSE', 'ESC'}:
        operator._finish(context)
        return {'FINISHED'}

    if (inside_widget or inside_controls) and event.type in {'LEFTMOUSE', 'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
        return {'RUNNING_MODAL'}

    return {'PASS_THROUGH'}


class HAIRPIPE_OT_widget_stop(bpy.types.Operator):
    """Close the interactive cross-section editor"""
    bl_idname = "hair_pipe.widget_stop"
    bl_label = "关闭横截面编辑器"

    def execute(self, context):
        wd = context.window_manager.hair_pipe_widget
        wd.is_active = False
        wd.drag_vert_index = -1
        wd.hold_key_mode = False
        redraw_view3d(context)
        return {'FINISHED'}


classes = (
    HairPipeWidgetSettings,
    HAIRPIPE_OT_widget_interact,
    HAIRPIPE_OT_widget_hold,
    HAIRPIPE_OT_widget_stop,
)


def register_keymaps():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc is None:
        return
    km = kc.keymaps.new(name='3D View', space_type='VIEW_3D')
    kmi = km.keymap_items.new('hair_pipe.widget_hold', 'X', 'PRESS', ctrl=True, shift=True)
    _addon_keymaps.append((km, kmi))


def unregister_keymaps():
    for km, kmi in _addon_keymaps:
        km.keymap_items.remove(kmi)
    _addon_keymaps.clear()


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.hair_pipe_widget = bpy.props.PointerProperty(
        type=HairPipeWidgetSettings
    )
    ensure_draw_handler()
    register_keymaps()


def unregister():
    unregister_keymaps()
    remove_draw_handler()
    del bpy.types.WindowManager.hair_pipe_widget
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
