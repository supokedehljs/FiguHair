import bpy
import gpu
import math
import blf
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
from bpy.props import IntProperty, FloatProperty, BoolProperty
from bpy.types import PropertyGroup
from mathutils import Vector
from .operators import get_selected_curve_point_indices


_draw_handle = None
_addon_keymaps = []


class HairPipeWidgetSettings(PropertyGroup):
    """Runtime state for the cross-section widget"""
    widget_center_x: FloatProperty(default=0.0)
    widget_center_y: FloatProperty(default=0.0)
    widget_size: FloatProperty(default=320.0)
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
    toggle_button_x0: FloatProperty(default=0.0)
    toggle_button_y0: FloatProperty(default=0.0)
    toggle_button_x1: FloatProperty(default=0.0)
    toggle_button_y1: FloatProperty(default=0.0)
    flip_button_x0: FloatProperty(default=0.0)
    flip_button_y0: FloatProperty(default=0.0)
    flip_button_x1: FloatProperty(default=0.0)
    flip_button_y1: FloatProperty(default=0.0)
    flip_horizontal: BoolProperty(default=False)
    selected_verts: bpy.props.StringProperty(default="")
    box_select_active: BoolProperty(default=False)
    box_x0: FloatProperty(default=0.0)
    box_y0: FloatProperty(default=0.0)
    box_x1: FloatProperty(default=0.0)
    box_y1: FloatProperty(default=0.0)
    transform_mode: bpy.props.StringProperty(default="")
    transform_start_x: FloatProperty(default=0.0)
    transform_start_y: FloatProperty(default=0.0)
    transform_initial_offsets: bpy.props.StringProperty(default="")



def get_selected_widget_verts(wd):
    raw = wd.selected_verts.strip()
    if not raw:
        return set()
    return set(int(x) for x in raw.split(",") if x.strip().isdigit())


def set_selected_widget_verts(wd, indices):
    wd.selected_verts = ",".join(str(i) for i in sorted(indices))


def store_transform_offsets(wd, verts, indices):
    parts = []
    for i in indices:
        if i < len(verts):
            parts.append(str(verts[i].offset_x) + ":" + str(verts[i].offset_y))
        else:
            parts.append("0:0")
    wd.transform_initial_offsets = ";".join(parts)


def get_transform_offsets(wd):
    raw = wd.transform_initial_offsets.strip()
    if not raw:
        return []
    result = []
    for part in raw.split(";"):
        xy = part.split(":")
        if len(xy) == 2:
            result.append((float(xy[0]), float(xy[1])))
    return result


def get_curve_start_world_position(obj):
    if obj is None or obj.type != 'CURVE':
        return None
    if len(obj.data.splines) == 0:
        return None
    spline = obj.data.splines[0]
    if spline.type == 'BEZIER':
        if len(spline.bezier_points) == 0:
            return None
        return obj.matrix_world @ spline.bezier_points[0].co
    if len(spline.points) == 0:
        return None
    return obj.matrix_world @ Vector(spline.points[0].co[:3])


def draw_curve_start_marker(context, obj):
    region = context.region
    region_data = context.region_data
    if region is None or region_data is None:
        return
    start_world = get_curve_start_world_position(obj)
    if start_world is None:
        return
    pos = view3d_utils.location_3d_to_region_2d(region, region_data, start_world)
    if pos is None:
        return

    x, y = pos.x, pos.y
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.point_size_set(18.0)
    batch = batch_for_shader(shader, 'POINTS', {"pos": [(x, y)]})
    shader.bind()
    shader.uniform_float("color", (0.1, 1.0, 0.15, 1.0))
    batch.draw(shader)

    marker_lines = [
        (x - 10.0, y), (x + 10.0, y),
        (x, y - 10.0), (x, y + 10.0),
    ]
    gpu.state.line_width_set(2.0)
    batch = batch_for_shader(shader, 'LINES', {"pos": marker_lines})
    shader.bind()
    shader.uniform_float("color", (0.1, 1.0, 0.15, 1.0))
    batch.draw(shader)

    font_id = 0
    blf.size(font_id, 14)
    blf.color(font_id, 0.1, 1.0, 0.15, 1.0)
    blf.position(font_id, x + 12.0, y + 8.0, 0)
    blf.draw(font_id, "Start")

    gpu.state.point_size_set(1.0)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def rounded_rect_points(x0, y0, x1, y1, radius=8.0, segments=5):
    radius = max(0.0, min(radius, (x1 - x0) * 0.5, (y1 - y0) * 0.5))
    centers = (
        (x1 - radius, y1 - radius, 0.0),
        (x0 + radius, y1 - radius, math.pi * 0.5),
        (x0 + radius, y0 + radius, math.pi),
        (x1 - radius, y0 + radius, math.pi * 1.5),
    )
    points = []
    for cx, cy, start_angle in centers:
        for step in range(segments + 1):
            angle = start_angle + step * (math.pi * 0.5 / segments)
            points.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
    return points


def draw_rounded_rect(shader, x0, y0, x1, y1, radius, fill_color, border_color=None):
    points = rounded_rect_points(x0, y0, x1, y1, radius)
    center = ((x0 + x1) * 0.5, (y0 + y1) * 0.5)
    vertices = [center] + points
    indices = []
    for i in range(1, len(vertices)):
        indices.append((0, i, 1 if i == len(vertices) - 1 else i + 1))
    batch = batch_for_shader(shader, 'TRIS', {"pos": vertices}, indices=indices)
    shader.bind()
    shader.uniform_float("color", fill_color)
    batch.draw(shader)

    if border_color is not None:
        lines = []
        for i, point in enumerate(points):
            lines.append(point)
            lines.append(points[(i + 1) % len(points)])
        gpu.state.line_width_set(1.4)
        batch = batch_for_shader(shader, 'LINES', {"pos": lines})
        shader.bind()
        shader.uniform_float("color", border_color)
        batch.draw(shader)


def draw_widget_button(shader, x0, y0, x1, y1, fill_color=None, enabled=True, active=False):
    if not enabled:
        fill = (0.10, 0.105, 0.11, 0.78)
        border = (0.28, 0.28, 0.30, 0.55)
        inner = (1.0, 1.0, 1.0, 0.035)
    elif active:
        fill = (0.24, 0.31, 0.38, 0.94)
        border = (0.62, 0.72, 0.84, 0.78)
        inner = (1.0, 1.0, 1.0, 0.075)
    else:
        fill = (0.145, 0.15, 0.16, 0.90)
        border = (0.52, 0.52, 0.54, 0.62)
        inner = (1.0, 1.0, 1.0, 0.055)
    radius = min((y1 - y0) * 0.5 - 1.0, 15.0)
    draw_rounded_rect(shader, x0, y0, x1, y1, radius, fill, border)
    draw_rounded_rect(shader, x0 + 1.5, y0 + 1.5, x1 - 1.5, y1 - 1.5, max(1.0, radius - 1.5), (0.0, 0.0, 0.0, 0.0), inner)


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
    update_ghost_vertices(ps)
    curve_point = get_active_curve_point(context)
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
    draw_curve_start_marker(context, obj)

    cx = wd.widget_center_x
    cy = wd.widget_center_y
    size = wd.widget_size
    if size < 10:
        return

    padding = 18
    half = size / 2.0 - padding
    alignment_angle = get_view_alignment_angle(context)
    flip_h = wd.flip_horizontal

    base_radius = settings.default_radius * get_cross_section_effective_scale(curve_point, ps)
    if base_radius < 1e-6:
        base_radius = 0.05
    if wd.widget_scale_factor <= 1e-8:
        wd.widget_scale_factor = half / (base_radius * 2.4)
    sf = wd.widget_scale_factor

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')

    region = context.region
    dim_w = region.width if region is not None else size * 2.0
    dim_h = region.height if region is not None else size * 2.0
    dim_bg = [(0.0, 0.0), (dim_w, 0.0), (dim_w, dim_h), (0.0, dim_h)]
    batch = batch_for_shader(shader, 'TRIS', {"pos": dim_bg}, indices=[(0, 1, 2), (0, 2, 3)])
    shader.bind()
    shader.uniform_float("color", (0.0, 0.0, 0.0, 0.42))
    batch.draw(shader)

    x0, y0 = cx - half - padding, cy - half - padding
    x1, y1 = cx + half + padding, cy + half + padding

    gpu.state.line_width_set(1.0)
    grid = [(cx - half, cy), (cx + half, cy), (cx, cy - half), (cx, cy + half)]
    batch = batch_for_shader(shader, 'LINES', {"pos": grid})
    shader.bind()
    shader.uniform_float("color", (0.35, 0.35, 0.35, 0.55))
    batch.draw(shader)

    ref_r = settings.default_radius * get_cross_section_effective_scale(curve_point, ps) * sf
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
        ix, iy = get_effective_offset(verts[i], curve_point, ps)
        jx, jy = get_effective_offset(verts[j], curve_point, ps)
        outline.append(effective_to_widget(ix, iy, cx, cy, sf, alignment_angle, flip_h))
        outline.append(effective_to_widget(jx, jy, cx, cy, sf, alignment_angle, flip_h))
    gpu.state.line_width_set(2.5)
    batch = batch_for_shader(shader, 'LINES', {"pos": outline})
    shader.bind()
    shader.uniform_float("color", (1.0, 0.8, 0.05, 1.0))
    batch.draw(shader)

    effective_points = [get_effective_offset(v, curve_point, ps) for v in verts]
    smooth_effective = chaikin_closed(effective_points, 3)
    smooth_widget_points = [effective_to_widget(x, y, cx, cy, sf, alignment_angle, flip_h) for x, y in smooth_effective]
    smooth_lines = make_smooth_preview_lines(smooth_widget_points)
    if smooth_lines:
        gpu.state.line_width_set(2.0)
        batch = batch_for_shader(shader, 'LINES', {"pos": smooth_lines})
        shader.bind()
        shader.uniform_float("color", (0.0, 0.95, 1.0, 0.9))
        batch.draw(shader)

    normal_pts = []
    ghost_pts = []
    for v in verts:
        ox, oy = get_effective_offset(v, curve_point, ps)
        point = effective_to_widget(ox, oy, cx, cy, sf, alignment_angle, flip_h)
        if getattr(v, 'is_ghost', False):
            ghost_pts.append(point)
        else:
            normal_pts.append(point)
    if ghost_pts:
        gpu.state.point_size_set(10.0)
        batch = batch_for_shader(shader, 'POINTS', {"pos": ghost_pts})
        shader.bind()
        shader.uniform_float("color", (0.45, 0.65, 1.0, 0.55))
        batch.draw(shader)
    if normal_pts:
        gpu.state.point_size_set(12.0)
        batch = batch_for_shader(shader, 'POINTS', {"pos": normal_pts})
        shader.bind()
        shader.uniform_float("color", (1.0, 1.0, 1.0, 1.0))
        batch.draw(shader)

    aidx = ps.active_vert_index
    if 0 <= aidx < n:
        gpu.state.point_size_set(18.0)
        ax, ay = get_effective_offset(verts[aidx], curve_point, ps)
        ap = [effective_to_widget(ax, ay, cx, cy, sf, alignment_angle, flip_h)]
        batch = batch_for_shader(shader, 'POINTS', {"pos": ap})
        shader.bind()
        if getattr(verts[aidx], 'is_ghost', False):
            shader.uniform_float("color", (0.55, 0.75, 1.0, 0.95))
        else:
            shader.uniform_float("color", (0.0, 0.95, 1.0, 1.0))
        batch.draw(shader)

    sel_indices = get_selected_widget_verts(wd)
    if sel_indices:
        sel_pts = []
        for si in sel_indices:
            if 0 <= si < n:
                sx, sy = get_effective_offset(verts[si], curve_point, ps)
                sel_pts.append(effective_to_widget(sx, sy, cx, cy, sf, alignment_angle, flip_h))
        if sel_pts:
            gpu.state.point_size_set(22.0)
            batch = batch_for_shader(shader, 'POINTS', {"pos": sel_pts})
            shader.bind()
            shader.uniform_float("color", (1.0, 0.5, 0.0, 0.7))
            batch.draw(shader)

    if wd.box_select_active:
        bx0r = min(wd.box_x0, wd.box_x1)
        by0r = min(wd.box_y0, wd.box_y1)
        bx1r = max(wd.box_x0, wd.box_x1)
        by1r = max(wd.box_y0, wd.box_y1)
        box_lines = [
            (bx0r, by0r), (bx1r, by0r),
            (bx1r, by0r), (bx1r, by1r),
            (bx1r, by1r), (bx0r, by1r),
            (bx0r, by1r), (bx0r, by0r),
        ]
        gpu.state.line_width_set(1.5)
        batch = batch_for_shader(shader, 'LINES', {"pos": box_lines})
        shader.bind()
        shader.uniform_float("color", (1.0, 1.0, 1.0, 0.8))
        batch.draw(shader)

    button_w = 110.0
    button_h = 36.0
    gap = 10.0
    by0 = y0 - button_h - 12.0
    by1 = by0 + button_h
    total_w = button_w * 4.0 + gap * 3.0
    add_x0 = cx - total_w * 0.5
    add_x1 = add_x0 + button_w
    rem_x0 = add_x1 + gap
    rem_x1 = rem_x0 + button_w
    tog_x0 = rem_x1 + gap
    tog_x1 = tog_x0 + button_w
    flip_x0 = tog_x1 + gap
    flip_x1 = flip_x0 + button_w
    wd.add_button_x0 = add_x0
    wd.add_button_y0 = by0
    wd.add_button_x1 = add_x1
    wd.add_button_y1 = by1
    wd.remove_button_x0 = rem_x0
    wd.remove_button_y0 = by0
    wd.remove_button_x1 = rem_x1
    wd.remove_button_y1 = by1
    wd.toggle_button_x0 = tog_x0
    wd.toggle_button_y0 = by0
    wd.toggle_button_x1 = tog_x1
    wd.toggle_button_y1 = by1
    wd.flip_button_x0 = flip_x0
    wd.flip_button_y0 = by0
    wd.flip_button_x1 = flip_x1
    wd.flip_button_y1 = by1

    can_remove = all(len(point_setting.cross_section_verts) > 3 for point_setting in settings.point_settings)
    active_is_ghost = 0 <= ps.active_vert_index < n and getattr(verts[ps.active_vert_index], 'is_ghost', False)
    draw_widget_button(shader, add_x0, by0, add_x1, by1, (0.08, 0.42, 0.28, 0.96))
    draw_widget_button(shader, rem_x0, by0, rem_x1, by1, (0.52, 0.16, 0.14, 0.96) if can_remove else (0.16, 0.16, 0.16, 0.86), can_remove)
    draw_widget_button(shader, tog_x0, by0, tog_x1, by1, (0.12, 0.34, 0.62, 0.96) if active_is_ghost else (0.22, 0.24, 0.30, 0.96), True, active_is_ghost)
    draw_widget_button(shader, flip_x0, by0, flip_x1, by1, (0.46, 0.30, 0.10, 0.96) if flip_h else (0.28, 0.24, 0.18, 0.96), True, flip_h)

    font_id = 0
    blf.size(font_id, 16)
    blf.color(font_id, 0.88, 0.94, 1.0, 0.95)
    blf.position(font_id, 18.0, 24.0, 0)
    blf.draw(font_id, "青色线：细分预览｜蓝色点：幽灵点｜中键点击边：插入新点")
    blf.size(font_id, 15)
    blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
    blf.position(font_id, add_x0 + 39.0, by0 + 11.0, 0)
    blf.draw(font_id, "添加")
    blf.color(font_id, 1.0, 1.0, 1.0, 1.0 if can_remove else 0.38)
    blf.position(font_id, rem_x0 + 39.0, by0 + 11.0, 0)
    blf.draw(font_id, "删除")
    blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
    blf.position(font_id, tog_x0 + 31.0, by0 + 11.0, 0)
    blf.draw(font_id, "幽灵点")
    blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
    blf.position(font_id, flip_x0 + 23.0, by0 + 11.0, 0)
    blf.draw(font_id, "水平翻转")

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
    wd.widget_size = min(region.width, region.height) * 0.62
    wd.widget_center_x = region.width / 2.0
    wd.widget_center_y = region.height / 2.0
    wd.widget_scale_factor = 0.0
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


def get_cross_section_effective_transform(curve_point, point_setting):
    curve_radius = getattr(curve_point, 'radius', 1.0) if curve_point is not None else 1.0
    curve_tilt = getattr(curve_point, 'tilt', 0.0) if curve_point is not None else 0.0
    scale = max(1e-8, curve_radius * point_setting.scale)
    rotation = math.radians(point_setting.rotation) + curve_tilt
    return scale, rotation


def get_cross_section_effective_scale(curve_point, point_setting):
    scale, _rotation = get_cross_section_effective_transform(curve_point, point_setting)
    return scale


def get_effective_offset(vertex, curve_point, point_setting):
    scale, rotation = get_cross_section_effective_transform(curve_point, point_setting)
    x = vertex.offset_x * scale
    y = vertex.offset_y * scale
    cos_r = math.cos(rotation)
    sin_r = math.sin(rotation)
    return x * cos_r - y * sin_r, x * sin_r + y * cos_r


def catmull_rom_2d(p0, p1, p2, p3, t):
    t2 = t * t
    t3 = t2 * t
    x = 0.5 * (
        2.0 * p1[0]
        + (-p0[0] + p2[0]) * t
        + (2.0 * p0[0] - 5.0 * p1[0] + 4.0 * p2[0] - p3[0]) * t2
        + (-p0[0] + 3.0 * p1[0] - 3.0 * p2[0] + p3[0]) * t3
    )
    y = 0.5 * (
        2.0 * p1[1]
        + (-p0[1] + p2[1]) * t
        + (2.0 * p0[1] - 5.0 * p1[1] + 4.0 * p2[1] - p3[1]) * t2
        + (-p0[1] + 3.0 * p1[1] - 3.0 * p2[1] + p3[1]) * t3
    )
    return x, y


def update_ghost_vertices(point_setting):
    verts = point_setting.cross_section_verts
    count = len(verts)
    if count < 3:
        return
    real_indices = [i for i, v in enumerate(verts) if not getattr(v, 'is_ghost', False)]
    real_count = len(real_indices)
    if real_count < 2:
        return
    for real_pos, start_idx in enumerate(real_indices):
        end_idx = real_indices[(real_pos + 1) % real_count]
        gap = (end_idx - start_idx - 1) % count
        if gap <= 0:
            continue
        prev_idx = real_indices[(real_pos - 1) % real_count]
        next_idx = real_indices[(real_pos + 2) % real_count]
        p0 = (verts[prev_idx].offset_x, verts[prev_idx].offset_y)
        p1 = (verts[start_idx].offset_x, verts[start_idx].offset_y)
        p2 = (verts[end_idx].offset_x, verts[end_idx].offset_y)
        p3 = (verts[next_idx].offset_x, verts[next_idx].offset_y)
        for step in range(1, gap + 1):
            ghost_idx = (start_idx + step) % count
            ghost_vert = verts[ghost_idx]
            if not getattr(ghost_vert, 'is_ghost', False):
                continue
            t = step / (gap + 1)
            ghost_vert.offset_x, ghost_vert.offset_y = catmull_rom_2d(p0, p1, p2, p3, t)


def chaikin_closed(points, iterations=3):
    if len(points) < 3:
        return points
    result = list(points)
    for _ in range(max(1, iterations)):
        refined = []
        count = len(result)
        for i in range(count):
            x0, y0 = result[i]
            x1, y1 = result[(i + 1) % count]
            refined.append((x0 * 0.75 + x1 * 0.25, y0 * 0.75 + y1 * 0.25))
            refined.append((x0 * 0.25 + x1 * 0.75, y0 * 0.25 + y1 * 0.75))
        result = refined
    return result


def make_smooth_preview_lines(points):
    if len(points) < 2:
        return []
    lines = []
    count = len(points)
    for i in range(count):
        lines.append(points[i])
        lines.append(points[(i + 1) % count])
    return lines


def set_vertex_from_effective_offset(vertex, effective_x, effective_y, curve_point, point_setting):
    scale, rotation = get_cross_section_effective_transform(curve_point, point_setting)
    cos_r = math.cos(rotation)
    sin_r = math.sin(rotation)
    local_x = effective_x * cos_r + effective_y * sin_r
    local_y = -effective_x * sin_r + effective_y * cos_r
    vertex.offset_x = local_x / scale
    vertex.offset_y = local_y / scale


def apply_active_vertex_edit_to_selected_points(context, source_ps, vert_idx):
    obj = context.active_object
    if obj is None or obj.type != 'CURVE':
        return
    settings = obj.hair_pipe_settings
    selected = get_selected_curve_point_indices(obj)
    if len(selected) <= 1:
        return
    active_idx = settings.active_point_index
    if vert_idx < 0 or vert_idx >= len(source_ps.cross_section_verts):
        return
    src_vert = source_ps.cross_section_verts[vert_idx]
    for point_idx in selected:
        if point_idx == active_idx or point_idx >= len(settings.point_settings):
            continue
        target_ps = settings.point_settings[point_idx]
        if vert_idx >= len(target_ps.cross_section_verts):
            continue
        target_vert = target_ps.cross_section_verts[vert_idx]
        target_vert.offset_x = src_vert.offset_x
        target_vert.offset_y = src_vert.offset_y
        target_vert.is_ghost = getattr(src_vert, 'is_ghost', False)
        target_ps.active_vert_index = min(source_ps.active_vert_index, len(target_ps.cross_section_verts) - 1)
        update_ghost_vertices(target_ps)


def get_active_curve_point(context):
    obj = context.active_object
    if obj is None or obj.type != 'CURVE':
        return None
    settings = obj.hair_pipe_settings
    target_index = settings.active_point_index
    global_idx = 0
    for spline in obj.data.splines:
        points = spline.bezier_points if spline.type == 'BEZIER' else spline.points
        for point in points:
            if global_idx == target_index:
                return point
            global_idx += 1
    return None


def safe_normalized(vector, fallback=None):
    if vector.length >= 1e-8:
        return vector.normalized()
    if fallback is not None and fallback.length >= 1e-8:
        return fallback.normalized()
    return Vector((0, 0, 1))


def get_cross_section_frame(tangent):
    tangent = safe_normalized(tangent)
    if tangent.z < -0.999999:
        normal = Vector((0, -1, 0))
    else:
        a = 1.0 / (1.0 + tangent.z)
        b = -tangent.x * tangent.y * a
        normal = Vector((1.0 - tangent.x * tangent.x * a, b, -tangent.x))
        if normal.length < 1e-8:
            normal = Vector((1, 0, 0))
    normal = normal - tangent * normal.dot(tangent)
    if normal.length < 1e-8:
        normal = Vector((1, 0, 0))
        normal = normal - tangent * normal.dot(tangent)
    normal.normalize()
    binormal = tangent.cross(normal).normalized()
    return normal, binormal


def get_active_curve_point_world_position(context):
    obj = context.active_object
    if obj is None or obj.type != 'CURVE':
        return None
    point = get_active_curve_point(context)
    if point is None:
        return None
    if hasattr(point, 'co') and len(point.co) == 4:
        return obj.matrix_world @ Vector(point.co[:3])
    return obj.matrix_world @ point.co


def get_active_curve_tangent(context):
    obj = context.active_object
    if obj is None or obj.type != 'CURVE':
        return Vector((0, 0, 1))

    settings = obj.hair_pipe_settings
    target_index = settings.active_point_index
    global_idx = 0
    for spline in obj.data.splines:
        if spline.type == 'BEZIER':
            points = spline.bezier_points
            for idx, point in enumerate(points):
                if global_idx == target_index:
                    prev_tangent = None
                    next_tangent = None
                    if spline.use_cyclic_u or idx > 0:
                        prev_tangent = point.co - point.handle_left
                    if spline.use_cyclic_u or idx < len(points) - 1:
                        next_tangent = point.handle_right - point.co
                    if prev_tangent is not None and next_tangent is not None:
                        return safe_normalized(obj.matrix_world.to_3x3() @ (prev_tangent + next_tangent), obj.matrix_world.to_3x3() @ next_tangent)
                    if next_tangent is not None:
                        return safe_normalized(obj.matrix_world.to_3x3() @ next_tangent)
                    if prev_tangent is not None:
                        return safe_normalized(obj.matrix_world.to_3x3() @ prev_tangent)
                global_idx += 1
        else:
            points = spline.points
            for idx, point in enumerate(points):
                if global_idx == target_index:
                    co = Vector(point.co[:3])
                    prev_tangent = None
                    next_tangent = None
                    if spline.use_cyclic_u or idx > 0:
                        prev_idx = (idx - 1) % len(points)
                        prev_tangent = co - Vector(points[prev_idx].co[:3])
                    if spline.use_cyclic_u or idx < len(points) - 1:
                        next_idx = (idx + 1) % len(points)
                        next_tangent = Vector(points[next_idx].co[:3]) - co
                    if prev_tangent is not None and next_tangent is not None:
                        return safe_normalized(obj.matrix_world.to_3x3() @ (prev_tangent + next_tangent), obj.matrix_world.to_3x3() @ next_tangent)
                    if next_tangent is not None:
                        return safe_normalized(obj.matrix_world.to_3x3() @ next_tangent)
                    if prev_tangent is not None:
                        return safe_normalized(obj.matrix_world.to_3x3() @ prev_tangent)
                global_idx += 1
    return Vector((0, 0, 1))


def get_view_direction_marker(context, marker_radius):
    direction = get_view_direction_unit(context)
    if direction is None:
        return None
    return direction.x * marker_radius, direction.y * marker_radius


def get_active_curve_stable_frame(context):
    obj = context.active_object
    if obj is None or obj.type != 'CURVE':
        return None

    settings = obj.hair_pipe_settings
    target_index = settings.active_point_index
    global_idx = 0
    world_3x3 = obj.matrix_world.to_3x3()

    for spline in obj.data.splines:
        if spline.type == 'BEZIER':
            points = spline.bezier_points

            def point_tangent(idx):
                point = points[idx]
                prev_tangent = None
                next_tangent = None
                if spline.use_cyclic_u or idx > 0:
                    prev_tangent = point.co - point.handle_left
                    if prev_tangent.length < 1e-8:
                        prev_idx = (idx - 1) % len(points)
                        prev_tangent = point.co - points[prev_idx].co
                if spline.use_cyclic_u or idx < len(points) - 1:
                    next_tangent = point.handle_right - point.co
                    if next_tangent.length < 1e-8:
                        next_idx = (idx + 1) % len(points)
                        next_tangent = points[next_idx].co - point.co
                if prev_tangent is not None and next_tangent is not None:
                    return safe_normalized(prev_tangent + next_tangent, next_tangent)
                if next_tangent is not None:
                    return safe_normalized(next_tangent)
                if prev_tangent is not None:
                    return safe_normalized(prev_tangent)
                return Vector((0, 0, 1))
        else:
            points = spline.points

            def point_tangent(idx):
                co = Vector(points[idx].co[:3])
                prev_tangent = None
                next_tangent = None
                if spline.use_cyclic_u or idx > 0:
                    prev_idx = (idx - 1) % len(points)
                    prev_tangent = co - Vector(points[prev_idx].co[:3])
                if spline.use_cyclic_u or idx < len(points) - 1:
                    next_idx = (idx + 1) % len(points)
                    next_tangent = Vector(points[next_idx].co[:3]) - co
                if prev_tangent is not None and next_tangent is not None:
                    return safe_normalized(prev_tangent + next_tangent, next_tangent)
                if next_tangent is not None:
                    return safe_normalized(next_tangent)
                if prev_tangent is not None:
                    return safe_normalized(prev_tangent)
                return Vector((0, 0, 1))

        local_count = len(points)
        if target_index < global_idx or target_index >= global_idx + local_count:
            global_idx += local_count
            continue

        target_local_idx = target_index - global_idx
        tangent = point_tangent(0)
        normal, binormal = get_cross_section_frame(tangent)
        prev_tangent = tangent
        for idx in range(1, target_local_idx + 1):
            tangent = safe_normalized(point_tangent(idx), prev_tangent)
            try:
                transport = prev_tangent.rotation_difference(tangent)
                normal = transport @ normal
            except ValueError:
                pass
            normal = normal - tangent * normal.dot(tangent)
            if normal.length < 1e-8:
                normal, binormal = get_cross_section_frame(tangent)
            else:
                normal.normalize()
                binormal = tangent.cross(normal).normalized()
            prev_tangent = tangent

        world_normal = safe_normalized(world_3x3 @ normal)
        world_binormal = safe_normalized(world_3x3 @ binormal)
        return world_normal, world_binormal

    return None


def get_view_direction_unit(context):
    region_data = context.region_data
    if region_data is None:
        return None
    center = get_active_curve_point_world_position(context)
    if center is None:
        return None

    view_direction = safe_normalized(region_data.view_rotation @ Vector((0, 0, -1)))
    to_camera_side = -view_direction
    stable_frame = get_active_curve_stable_frame(context)
    if stable_frame is None:
        tangent = get_active_curve_tangent(context)
        stable_frame = get_cross_section_frame(tangent)
    normal, binormal = stable_frame
    projected = Vector((to_camera_side.dot(normal), to_camera_side.dot(binormal)))
    if projected.length < 1e-8:
        return None
    projected.normalize()
    return projected


def get_view_alignment_angle(context):
    direction = get_view_direction_unit(context)
    if direction is None:
        return 0.0
    return -math.pi / 2.0 - math.atan2(direction.y, direction.x)


def rotate_2d(x, y, angle):
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    return x * cos_a - y * sin_a, x * sin_a + y * cos_a


def effective_to_widget(x, y, cx, cy, sf, alignment_angle, flip_h=False):
    rx, ry = rotate_2d(x, y, alignment_angle)
    if flip_h:
        rx = -rx
    return cx + rx * sf, cy + ry * sf


def widget_to_effective(mx, my, cx, cy, sf, alignment_angle, flip_h=False):
    sx = (mx - cx) / sf
    sy = (my - cy) / sf
    if flip_h:
        sx = -sx
    return rotate_2d(sx, sy, -alignment_angle)


def add_cross_section_vertex(ps, settings):
    verts = ps.cross_section_verts
    n = len(verts)
    active_point_index = settings.active_point_index
    if n < 2:
        for idx, point_setting in enumerate(settings.point_settings):
            v = point_setting.cross_section_verts.add()
            v.offset_x = settings.default_radius
            v.offset_y = 0.0
            v.is_ghost = idx != active_point_index
            point_setting.active_vert_index = len(point_setting.cross_section_verts) - 1
        return

    idx = max(0, min(ps.active_vert_index, n - 1))
    add_cross_section_vertex_after_all(settings, active_point_index, idx)


def add_cross_section_vertex_after(ps, idx, is_ghost=False):
    verts = ps.cross_section_verts
    n = len(verts)
    idx = max(0, min(idx, n - 1))
    idx_next = (idx + 1) % n
    v = verts.add()
    v.offset_x = (verts[idx].offset_x + verts[idx_next].offset_x) * 0.5
    v.offset_y = (verts[idx].offset_y + verts[idx_next].offset_y) * 0.5
    v.is_ghost = is_ghost
    target = idx + 1
    for i in range(len(verts) - 1, target, -1):
        verts.move(i, i - 1)
    ps.active_vert_index = target


def add_cross_section_vertex_after_all(settings, active_index, idx):
    for point_idx, point_setting in enumerate(settings.point_settings):
        if len(point_setting.cross_section_verts) >= 2:
            add_cross_section_vertex_after(point_setting, idx, point_idx != active_index)


def insert_cross_section_vertex_on_edge(ps, edge_idx, local_x, local_y, curve_point=None, is_ghost=False):
    verts = ps.cross_section_verts
    n = len(verts)
    edge_idx = max(0, min(edge_idx, n - 1))
    v = verts.add()
    if curve_point is None:
        v.offset_x = local_x
        v.offset_y = local_y
    else:
        set_vertex_from_effective_offset(v, local_x, local_y, curve_point, ps)
    v.is_ghost = is_ghost
    target = edge_idx + 1
    for i in range(len(verts) - 1, target, -1):
        verts.move(i, i - 1)
    ps.active_vert_index = target


def insert_cross_section_vertex_on_edge_at_ratio(ps, edge_idx, edge_t, is_ghost=True):
    verts = ps.cross_section_verts
    n = len(verts)
    edge_idx = max(0, min(edge_idx, n - 1))
    idx_next = (edge_idx + 1) % n
    local_x = verts[edge_idx].offset_x * (1.0 - edge_t) + verts[idx_next].offset_x * edge_t
    local_y = verts[edge_idx].offset_y * (1.0 - edge_t) + verts[idx_next].offset_y * edge_t
    insert_cross_section_vertex_on_edge(ps, edge_idx, local_x, local_y, is_ghost=is_ghost)


def insert_cross_section_vertex_on_edge_all(settings, active_index, edge_idx, local_x, local_y, edge_t, curve_point):
    for idx, point_setting in enumerate(settings.point_settings):
        if len(point_setting.cross_section_verts) < 2:
            continue
        if idx == active_index:
            insert_cross_section_vertex_on_edge(point_setting, edge_idx, local_x, local_y, curve_point, is_ghost=False)
        else:
            insert_cross_section_vertex_on_edge_at_ratio(point_setting, edge_idx, edge_t, is_ghost=True)


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


def find_nearest_cross_section_edge(verts, mx, my, cx, cy, sf, curve_point, point_setting, alignment_angle, flip_h=False):
    closest_idx = -1
    closest_dist = 18.0
    closest_local = (0.0, 0.0)
    closest_t = 0.5
    n = len(verts)
    for i in range(n):
        j = (i + 1) % n
        ix, iy = get_effective_offset(verts[i], curve_point, point_setting)
        jx, jy = get_effective_offset(verts[j], curve_point, point_setting)
        ax, ay = effective_to_widget(ix, iy, cx, cy, sf, alignment_angle, flip_h)
        bx, by = effective_to_widget(jx, jy, cx, cy, sf, alignment_angle, flip_h)
        dist, hit_x, hit_y, edge_t = distance_point_to_segment(mx, my, ax, ay, bx, by)
        if dist < closest_dist:
            closest_dist = dist
            closest_idx = i
            closest_local = widget_to_effective(hit_x, hit_y, cx, cy, sf, alignment_angle, flip_h)
            closest_t = edge_t
    return closest_idx, closest_local, closest_t


def find_nearest_cross_section_vertex(verts, mx, my, cx, cy, sf, curve_point, point_setting, alignment_angle, max_dist=24.0, flip_h=False):
    closest_idx = -1
    closest_dist = max_dist
    for i, v in enumerate(verts):
        ox, oy = get_effective_offset(v, curve_point, point_setting)
        px, py = effective_to_widget(ox, oy, cx, cy, sf, alignment_angle, flip_h)
        dist = math.sqrt((mx - px) ** 2 + (my - py) ** 2)
        if dist < closest_dist:
            closest_dist = dist
            closest_idx = i
    return closest_idx


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
    update_ghost_vertices(ps)
    curve_point = get_active_curve_point(context)
    verts = ps.cross_section_verts
    if len(verts) < 3:
        operator._finish(context)
        return {'CANCELLED'}

    cx = wd.widget_center_x
    cy = wd.widget_center_y
    sf = wd.widget_scale_factor
    alignment_angle = get_view_alignment_angle(context)
    flip_h = wd.flip_horizontal
    mx, my = operator._get_local_mouse(event, wd)
    half = wd.widget_size / 2.0
    inside_widget = abs(mx - cx) <= half and abs(my - cy) <= half
    inside_add_button = is_inside_rect(mx, my, wd.add_button_x0, wd.add_button_y0, wd.add_button_x1, wd.add_button_y1)
    inside_remove_button = is_inside_rect(
        mx, my, wd.remove_button_x0, wd.remove_button_y0, wd.remove_button_x1, wd.remove_button_y1
    )
    inside_toggle_button = is_inside_rect(
        mx, my, wd.toggle_button_x0, wd.toggle_button_y0, wd.toggle_button_x1, wd.toggle_button_y1
    )
    inside_flip_button = is_inside_rect(
        mx, my, wd.flip_button_x0, wd.flip_button_y0, wd.flip_button_x1, wd.flip_button_y1
    )
    inside_controls = inside_add_button or inside_remove_button or inside_toggle_button or inside_flip_button

    if event.type == 'MIDDLEMOUSE' and event.value == 'PRESS':
        if inside_widget and sf > 0.001:
            edge_idx, local_pos, edge_t = find_nearest_cross_section_edge(
                verts, mx, my, cx, cy, sf, curve_point, ps, alignment_angle, flip_h
            )
            if edge_idx >= 0:
                insert_cross_section_vertex_on_edge_all(
                    settings, settings.active_point_index, edge_idx, local_pos[0], local_pos[1], edge_t, curve_point
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
        if inside_toggle_button:
            if 0 <= ps.active_vert_index < len(verts):
                verts[ps.active_vert_index].is_ghost = not getattr(verts[ps.active_vert_index], 'is_ghost', False)
                update_ghost_vertices(ps)
            wd.drag_vert_index = -1
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if inside_flip_button:
            wd.flip_horizontal = not wd.flip_horizontal
            wd.drag_vert_index = -1
            redraw_view3d(context)
            return {'RUNNING_MODAL'}

        closest_idx = find_nearest_cross_section_vertex(
            verts, mx, my, cx, cy, sf, curve_point, ps, alignment_angle, flip_h=flip_h
        )
        if closest_idx >= 0:
            ps.active_vert_index = closest_idx
            if event.shift:
                sel = get_selected_widget_verts(wd)
                if closest_idx in sel:
                    sel.discard(closest_idx)
                else:
                    sel.add(closest_idx)
                set_selected_widget_verts(wd, sel)
            else:
                set_selected_widget_verts(wd, {closest_idx})
            if getattr(verts[closest_idx], 'is_ghost', False):
                wd.drag_vert_index = -1
            else:
                wd.drag_vert_index = closest_idx
            redraw_view3d(context)
            return {'RUNNING_MODAL'}

        if not inside_widget:
            if close_on_key_release or inside_controls:
                return {'RUNNING_MODAL'}
            operator._finish(context)
            return {'FINISHED'}

        return {'RUNNING_MODAL'}

    if event.type == 'MOUSEMOVE':
        if 0 <= wd.drag_vert_index < len(verts) and sf > 0.001 and not getattr(verts[wd.drag_vert_index], 'is_ghost', False):
            effective_x, effective_y = widget_to_effective(mx, my, cx, cy, sf, alignment_angle, flip_h)
            set_vertex_from_effective_offset(verts[wd.drag_vert_index], effective_x, effective_y, curve_point, ps)
            update_ghost_vertices(ps)
            apply_active_vertex_edit_to_selected_points(context, ps, wd.drag_vert_index)
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

    # B - Box Select
    if event.type == 'B' and event.value == 'PRESS' and inside_widget and not wd.transform_mode:
        wd.box_select_active = True
        wd.box_x0 = mx
        wd.box_y0 = my
        wd.box_x1 = mx
        wd.box_y1 = my
        redraw_view3d(context)
        return {'RUNNING_MODAL'}

    if wd.box_select_active:
        if event.type == 'MOUSEMOVE':
            wd.box_x1 = mx
            wd.box_y1 = my
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            bx0 = min(wd.box_x0, wd.box_x1)
            by0 = min(wd.box_y0, wd.box_y1)
            bx1 = max(wd.box_x0, wd.box_x1)
            by1 = max(wd.box_y0, wd.box_y1)
            selected = set()
            for i, v in enumerate(verts):
                ox, oy = get_effective_offset(v, curve_point, ps)
                px, py = effective_to_widget(ox, oy, cx, cy, sf, alignment_angle, flip_h)
                if bx0 <= px <= bx1 and by0 <= py <= by1:
                    selected.add(i)
            if event.shift:
                selected = selected | get_selected_widget_verts(wd)
            set_selected_widget_verts(wd, selected)
            wd.box_select_active = False
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            wd.box_select_active = False
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}

    # G - Grab selected
    if event.type == 'G' and event.value == 'PRESS' and not wd.transform_mode:
        sel = get_selected_widget_verts(wd)
        if not sel and 0 <= ps.active_vert_index < len(verts):
            sel = {ps.active_vert_index}
            set_selected_widget_verts(wd, sel)
        if sel:
            wd.transform_mode = "GRAB"
            wd.transform_start_x = mx
            wd.transform_start_y = my
            store_transform_offsets(wd, verts, sorted(sel))
            return {'RUNNING_MODAL'}

    # R - Rotate selected
    if event.type == 'R' and event.value == 'PRESS' and not wd.transform_mode:
        sel = get_selected_widget_verts(wd)
        if not sel and 0 <= ps.active_vert_index < len(verts):
            sel = {ps.active_vert_index}
            set_selected_widget_verts(wd, sel)
        if sel:
            wd.transform_mode = "ROTATE"
            wd.transform_start_x = mx
            wd.transform_start_y = my
            store_transform_offsets(wd, verts, sorted(sel))
            return {'RUNNING_MODAL'}

    # Transform in progress
    if wd.transform_mode:
        sel = sorted(get_selected_widget_verts(wd))
        initial = get_transform_offsets(wd)
        if event.type == 'MOUSEMOVE':
            if wd.transform_mode == "GRAB":
                dx_w = mx - wd.transform_start_x
                dy_w = my - wd.transform_start_y
                dx_e, dy_e = widget_to_effective(cx + dx_w, cy + dy_w, cx, cy, sf, alignment_angle, flip_h)
                for ip, vi in enumerate(sel):
                    if vi < len(verts) and ip < len(initial) and not getattr(verts[vi], 'is_ghost', False):
                        verts[vi].offset_x = initial[ip][0] + dx_e
                        verts[vi].offset_y = initial[ip][1] + dy_e
            elif wd.transform_mode == "ROTATE":
                a_start = math.atan2(wd.transform_start_y - cy, wd.transform_start_x - cx)
                a_now = math.atan2(my - cy, mx - cx)
                angle = a_now - a_start
                cos_a = math.cos(angle)
                sin_a = math.sin(angle)
                cnt = max(1, len(initial))
                ctr_x = sum(o[0] for o in initial) / cnt
                ctr_y = sum(o[1] for o in initial) / cnt
                for ip, vi in enumerate(sel):
                    if vi < len(verts) and ip < len(initial) and not getattr(verts[vi], 'is_ghost', False):
                        rx = initial[ip][0] - ctr_x
                        ry = initial[ip][1] - ctr_y
                        verts[vi].offset_x = ctr_x + rx * cos_a - ry * sin_a
                        verts[vi].offset_y = ctr_y + rx * sin_a + ry * cos_a
            update_ghost_vertices(ps)
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            wd.transform_mode = ""
            for vi in sel:
                if vi < len(verts):
                    apply_active_vertex_edit_to_selected_points(context, ps, vi)
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            for ip, vi in enumerate(sel):
                if vi < len(verts) and ip < len(initial):
                    verts[vi].offset_x = initial[ip][0]
                    verts[vi].offset_y = initial[ip][1]
            wd.transform_mode = ""
            update_ghost_vertices(ps)
            redraw_view3d(context)
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}

    # A - Select All / Deselect All
    if event.type == 'A' and event.value == 'PRESS' and inside_widget:
        sel = get_selected_widget_verts(wd)
        if len(sel) == len(verts):
            set_selected_widget_verts(wd, set())
        else:
            set_selected_widget_verts(wd, set(range(len(verts))))
        redraw_view3d(context)
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
