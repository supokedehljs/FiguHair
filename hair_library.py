import bpy
import json
import os
import math
import shutil
import time
import uuid
from datetime import datetime
from bpy.props import StringProperty, BoolProperty, CollectionProperty, IntProperty, FloatProperty
from bpy.types import PropertyGroup
import bpy.utils.previews
import gpu
import blf
from gpu_extras.batch import batch_for_shader

try:
    from PIL import ImageGrab
except Exception:
    ImageGrab = None


LIBRARY_DIR_NAME = "figuhair_library"
INDEX_FILE_NAME = "index.json"
THUMB_DIR_NAME = "thumbnails"
ASSET_DIR_NAME = "assets"


_library_previews = None
_draw_handle = None
_overlay_bounds = []
_image_cache = {}


class HairLibraryEntryItem(PropertyGroup):
    entry_id: StringProperty(name="ID", default="")
    name: StringProperty(name="Name", default="")
    blend_path: StringProperty(name="Blend Path", default="")
    thumbnail_path: StringProperty(name="Thumbnail Path", default="")
    created_at: StringProperty(name="Created At", default="")


class HairLibraryOverlayState(PropertyGroup):
    is_open: BoolProperty(name="Is Open", default=False)
    active_entry_index: IntProperty(name="Active Entry Index", default=0)
    card_scale: FloatProperty(name="Card Scale", default=1.0, min=0.5, max=2.0)
    entries: CollectionProperty(type=HairLibraryEntryItem)


class HairLibraryState(PropertyGroup):
    active_entry_index: IntProperty(name="Active Entry Index", default=0)
    entries: CollectionProperty(type=HairLibraryEntryItem)


def get_library_root():
    base = bpy.utils.user_resource('SCRIPTS', path="addons", create=True)
    if not base:
        base = bpy.path.abspath("//")
    root = os.path.join(base, "hair_curve_pipe", LIBRARY_DIR_NAME)
    os.makedirs(root, exist_ok=True)
    os.makedirs(os.path.join(root, ASSET_DIR_NAME), exist_ok=True)
    return root


def get_index_path():
    return os.path.join(get_library_root(), INDEX_FILE_NAME)


def load_index():
    path = get_index_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_index(entries):
    with open(get_index_path(), "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def _fill_entry_collection(collection, entries):
    collection.clear()
    for entry in entries:
        item = collection.add()
        item.entry_id = entry.get("id", "")
        item.name = entry.get("name", "")
        item.blend_path = entry.get("blend_path", "")
        item.thumbnail_path = entry.get("thumbnail_path", "")
        item.created_at = entry.get("created_at", "")


def sync_state_entries(state):
    _fill_entry_collection(state.entries, load_index())
    if state.active_entry_index >= len(state.entries):
        state.active_entry_index = len(state.entries) - 1


def sync_overlay_entries(state):
    _fill_entry_collection(state.entries, load_index())
    if state.active_entry_index >= len(state.entries):
        state.active_entry_index = len(state.entries) - 1


def get_library_preview_icon(previews, entry):
    thumb_path = entry.thumbnail_path
    if thumb_path and os.path.exists(thumb_path):
        icon_key = entry.entry_id
        if icon_key not in previews:
            try:
                previews.load(icon_key, thumb_path, 'IMAGE')
            except Exception:
                return 0
        return previews[icon_key].icon_id
    return 0


def get_curve_bundle_objects(curve_obj):
    from .operators import get_pipe_object_for_curve, get_tail_object_for_curve, get_figuhair_root
    root_obj = get_figuhair_root(curve_obj)
    if root_obj is None:
        return []
    objs = [root_obj, curve_obj]
    pipe_obj = get_pipe_object_for_curve(curve_obj)
    tail_obj = get_tail_object_for_curve(curve_obj)
    if pipe_obj is not None:
        objs.append(pipe_obj)
    if tail_obj is not None:
        objs.append(tail_obj)
    return [obj for obj in objs if obj is not None]


def _save_clipboard_thumbnail(asset_base_path):
    if ImageGrab is None:
        return ""
    try:
        image = ImageGrab.grabclipboard()
    except Exception:
        image = None
    if image is None:
        return ""
    thumb_path = asset_base_path + ".png"
    try:
        image.save(thumb_path)
        return thumb_path
    except Exception:
        return ""


def save_current_hair_to_library(context, entry_name):
    curve_obj = context.active_object
    if curve_obj is None or curve_obj.type != 'CURVE':
        return None
    bundle = get_curve_bundle_objects(curve_obj)
    if not bundle:
        return None

    entry_id = uuid.uuid4().hex[:12]
    asset_base_name = f"{entry_name}_{entry_id}"
    asset_base_path = os.path.join(get_library_root(), ASSET_DIR_NAME, asset_base_name)
    blend_path = asset_base_path + ".blend"
    bpy.data.libraries.write(blend_path, set(bundle), path_remap='RELATIVE', fake_user=True)
    thumbnail_path = _save_clipboard_thumbnail(asset_base_path)

    entries = load_index()
    entries.append({
        "id": entry_id,
        "name": entry_name,
        "blend_path": blend_path,
        "thumbnail_path": thumbnail_path,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    })
    save_index(entries)
    return entry_id


def _remap_modifier_object_references(obj, object_map):
    for modifier in obj.modifiers:
        for prop in modifier.bl_rna.properties:
            if prop.is_readonly or prop.identifier == "rna_type":
                continue
            try:
                value = getattr(modifier, prop.identifier)
            except Exception:
                continue
            if value in object_map:
                try:
                    setattr(modifier, prop.identifier, object_map[value])
                except Exception:
                    pass


def _is_imported_figuhair_root(obj):
    return obj is not None and obj.type == 'EMPTY' and bool(obj.get("hair_pipe_root", False))


def _prepare_imported_hair_bundle(context, created):
    from .operators import get_next_figuhair_base_name, ensure_tail_modifier_stack

    roots = [obj for obj in created if _is_imported_figuhair_root(obj)]
    processed = []
    for root_obj in roots:
        family = [root_obj] + list(root_obj.children_recursive)
        curve_obj = next((obj for obj in family if obj.type == 'CURVE'), None)
        if curve_obj is None:
            continue
        pipe_obj = next((obj for obj in family if obj.type == 'MESH' and not obj.name.endswith(" Tail")), None)
        tail_obj = next((obj for obj in family if obj.type == 'MESH' and obj.name.endswith(" Tail")), None)
        if tail_obj is None:
            tail_obj = next((obj for obj in family if obj.type == 'MESH' and obj.get("hair_pipe_tail_source_curve")), None)

        old_to_new = {obj: obj for obj in family}
        new_base = get_next_figuhair_base_name()
        root_obj.name = new_base
        root_obj["hair_pipe_root"] = True
        curve_obj.name = new_base + " Curve"
        curve_obj.data.name = curve_obj.name
        curve_obj["hair_pipe_base_name"] = new_base
        curve_obj["hair_pipe_root"] = root_obj.name
        curve_obj.parent = root_obj

        if pipe_obj is not None:
            pipe_obj.name = new_base + " Mesh"
            pipe_obj.data = pipe_obj.data.copy()
            pipe_obj.data.name = pipe_obj.name
            pipe_obj["hair_pipe_source_curve"] = curve_obj.name
            pipe_obj.parent = root_obj
            _remap_modifier_object_references(pipe_obj, old_to_new)

        if tail_obj is not None:
            tail_obj.name = new_base + " Tail"
            tail_obj.data = tail_obj.data.copy()
            tail_obj.data.name = tail_obj.name
            tail_obj["hair_pipe_tail_source_curve"] = curve_obj.name
            tail_obj.parent = root_obj
            _remap_modifier_object_references(tail_obj, old_to_new)

        if pipe_obj is not None and tail_obj is not None:
            try:
                ensure_tail_modifier_stack(pipe_obj, tail_obj, curve_obj.hair_pipe_settings)
            except Exception:
                pass

        processed.extend(family)

    for obj in created:
        if obj in processed:
            continue
        if obj.type == 'CURVE' and obj.get("hair_pipe_base_name"):
            new_base = get_next_figuhair_base_name()
            obj.name = new_base + " Curve"
            obj.data.name = obj.name
            obj["hair_pipe_base_name"] = new_base
            obj["hair_pipe_root"] = ""

    return created


def append_hair_from_library(context, entry_id):
    entry = next((e for e in load_index() if e.get("id") == entry_id), None)
    if entry is None:
        return False
    blend_path = entry.get("blend_path")
    if not blend_path or not os.path.exists(blend_path):
        return False
    with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
        data_to.objects = list(data_from.objects)
    created = [obj for obj in data_to.objects if obj is not None]
    created = _prepare_imported_hair_bundle(context, created)
    scene_collection = context.collection or context.scene.collection
    for obj in created:
        if obj.name not in scene_collection.objects:
            scene_collection.objects.link(obj)
    for obj in created:
        obj.select_set(False)
    curve_obj = next((obj for obj in created if obj.type == 'CURVE'), None)
    if curve_obj is not None:
        curve_obj.select_set(True)
        context.view_layer.objects.active = curve_obj
    return True


def remove_hair_library_entry(entry_id):
    entries = load_index()
    entry = next((e for e in entries if e.get("id") == entry_id), None)
    if entry is None:
        return False
    for path in (entry.get("blend_path", ""), entry.get("thumbnail_path", "")):
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
    save_index([e for e in entries if e.get("id") != entry_id])
    return True


def _load_thumbnail_image(path):
    if not path or not os.path.exists(path):
        return None
    image = _image_cache.get(path)
    if image is not None and image.name in bpy.data.images:
        return image
    try:
        image = bpy.data.images.load(path, check_existing=True)
        _image_cache[path] = image
        return image
    except Exception:
        return None


def _draw_image_rect(image, x0, y0, x1, y1):
    if image is None:
        return False
    try:
        shader = gpu.shader.from_builtin('IMAGE')
        batch = batch_for_shader(shader, 'TRI_FAN', {
            "pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
            "texCoord": [(0, 0), (1, 0), (1, 1), (0, 1)],
        })
        gpu.state.blend_set('ALPHA')
        shader.bind()
        shader.uniform_sampler("image", image.bindcode)
        batch.draw(shader)
        return True
    except Exception:
        return False


def _rounded_rect(shader, x0, y0, x1, y1, r, color):
    r = min(r, (x1 - x0) * 0.5, (y1 - y0) * 0.5)
    verts = []
    steps = 8
    for cx, cy, a0, a1 in [
        (x0 + r, y0 + r, 180.0, 270.0),
        (x1 - r, y0 + r, 270.0, 360.0),
        (x1 - r, y1 - r, 0.0, 90.0),
        (x0 + r, y1 - r, 90.0, 180.0),
    ]:
        for i in range(steps + 1):
            t = i / steps
            ang = math.radians(a0 + (a1 - a0) * t)
            verts.append((cx + math.cos(ang) * r, cy + math.sin(ang) * r))
    batch = batch_for_shader(shader, 'TRI_FAN', {"pos": verts})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _find_entry_from_pos(x, y):
    for x0, y0, x1, y1, idx in _overlay_bounds:
        if x0 <= x <= x1 and y0 <= y <= y1:
            return idx
    return -1


def _event_over_overlay(event, context):
    region = None
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            for reg in area.regions:
                if reg.type == 'WINDOW':
                    region = reg
                    break
            if region:
                break
    if region is None:
        return False
    return 0 <= event.mouse_region_x <= region.width and 0 <= event.mouse_region_y <= region.height


def _draw_overlay():
    global _overlay_bounds
    _overlay_bounds = []
    wm = bpy.context.window_manager
    overlay = getattr(wm, "hair_pipe_library_overlay", None)
    if overlay is None or not overlay.is_open:
        return
    state = overlay
    sync_overlay_entries(state)
    region = None
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            for reg in area.regions:
                if reg.type == 'WINDOW':
                    region = reg
                    break
            if region:
                break
    if region is None:
        return
    width, height = region.width, region.height
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')

    margin = 42
    inner_x0 = margin
    inner_y0 = margin
    inner_x1 = width - margin
    inner_y1 = height - margin
    verts = [(inner_x0, inner_y0), (inner_x1, inner_y0), (inner_x1, inner_y1), (inner_x0, inner_y1)]
    batch = batch_for_shader(shader, 'TRI_FAN', {"pos": verts})
    shader.bind()
    shader.uniform_float("color", (0.05, 0.05, 0.06, 0.88))
    batch.draw(shader)

    font_id = 0
    blf.size(font_id, 18)
    blf.color(font_id, 0.96, 0.97, 1.0, 1.0)
    blf.position(font_id, inner_x0 + 18, inner_y1 - 30, 0)
    blf.draw(font_id, "头发库")
    blf.size(font_id, 11)
    blf.color(font_id, 0.68, 0.72, 0.78, 0.95)
    blf.position(font_id, inner_x0 + 88, inner_y1 - 28, 0)
    blf.draw(font_id, "单击选择 / 双击导入 / 滚轮调整卡片 / V 或 ESC 关闭")

    card_scale = max(0.5, min(2.0, state.card_scale))
    base_cols = 7
    cols = max(3, int(base_cols / card_scale))
    gap = max(8, int(12 / card_scale))
    usable_w = inner_x1 - inner_x0 - gap * (cols - 1) - 36
    card_w = min(176.0, (usable_w / cols) * card_scale)
    card_h = card_w
    radius = max(8.0, card_w * 0.09)
    y_top = inner_y1 - 58

    for idx, entry in enumerate(state.entries):
        col = idx % cols
        row = idx // cols
        x0 = inner_x0 + 20 + col * (card_w + gap)
        y0 = y_top - row * (card_h + gap) - card_h
        x1 = x0 + card_w
        y1 = y0 + card_h
        if y1 < inner_y0:
            continue
        _overlay_bounds.append((x0, y0, x1, y1, idx))
        bg = (0.16, 0.16, 0.18, 0.96) if idx != state.active_entry_index else (0.22, 0.28, 0.38, 0.98)
        _rounded_rect(shader, x0, y0, x1, y1, radius, bg)

        preview_pad = 8
        preview_h = card_h * 0.66
        preview_x0 = x0 + preview_pad
        preview_y0 = y1 - preview_pad - preview_h
        preview_x1 = x1 - preview_pad
        preview_y1 = y1 - preview_pad
        _rounded_rect(shader, preview_x0, preview_y0, preview_x1, preview_y1, max(5.0, radius * 0.65), (0.09, 0.09, 0.105, 0.92))
        thumb_image = _load_thumbnail_image(entry.thumbnail_path)
        if not _draw_image_rect(thumb_image, preview_x0 + 2, preview_y0 + 2, preview_x1 - 2, preview_y1 - 2):
            blf.size(font_id, 9)
            blf.color(font_id, 0.52, 0.55, 0.62, 0.9)
            blf.position(font_id, preview_x0 + 10, preview_y0 + (preview_y1 - preview_y0) * 0.5, 0)
            blf.draw(font_id, "无缩略图")

        blf.size(font_id, max(9, int(10 * min(card_scale, 1.2))))
        blf.color(font_id, 0.94, 0.95, 0.98, 1.0)
        blf.position(font_id, x0 + 9, y0 + 22, 0)
        blf.draw(font_id, (entry.name or "Unnamed")[:18])
        blf.size(font_id, 8)
        blf.color(font_id, 0.64, 0.67, 0.72, 0.85)
        blf.position(font_id, x0 + 9, y0 + 9, 0)
        blf.draw(font_id, "双击导入")

    gpu.state.blend_set('NONE')


def ensure_draw_handler():
    global _draw_handle
    if _draw_handle is None:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(_draw_overlay, (), 'WINDOW', 'POST_PIXEL')


def remove_draw_handler():
    global _draw_handle
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None


class HAIRPIPE_OT_library_overlay_toggle(bpy.types.Operator):
    bl_idname = "hair_pipe.library_overlay_toggle"
    bl_label = "头发库"
    bl_options = {'REGISTER'}

    def invoke(self, context, event):
        overlay = context.window_manager.hair_pipe_library_overlay
        if overlay.is_open:
            overlay.is_open = False
            remove_draw_handler()
            if context.area:
                context.area.tag_redraw()
            return {'FINISHED'}
        overlay.is_open = True
        sync_overlay_entries(overlay)
        ensure_draw_handler()
        context.window_manager.modal_handler_add(self)
        if context.area:
            context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def execute(self, context):
        overlay = context.window_manager.hair_pipe_library_overlay
        overlay.is_open = not overlay.is_open
        if overlay.is_open:
            sync_overlay_entries(overlay)
            ensure_draw_handler()
        else:
            remove_draw_handler()
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}

    def modal(self, context, event):
        overlay = context.window_manager.hair_pipe_library_overlay
        if not overlay.is_open:
            remove_draw_handler()
            return {'FINISHED'}

        if event.type in {'V', 'ESC'} and event.value == 'PRESS':
            overlay.is_open = False
            remove_draw_handler()
            if context.area:
                context.area.tag_redraw()
            return {'FINISHED'}

        if event.type in {'WHEELUPMOUSE', 'NUMPAD_PLUS', 'PLUS'} and event.value == 'PRESS':
            overlay.card_scale = min(2.0, overlay.card_scale + 0.08)
            if context.area:
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        if event.type in {'WHEELDOWNMOUSE', 'NUMPAD_MINUS', 'MINUS'} and event.value == 'PRESS':
            overlay.card_scale = max(0.5, overlay.card_scale - 0.08)
            if context.area:
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value in {'PRESS', 'DOUBLE_CLICK'}:
            idx = _find_entry_from_pos(event.mouse_region_x, event.mouse_region_y)
            if idx >= 0:
                overlay.active_entry_index = idx
                if context.area:
                    context.area.tag_redraw()
                is_double = event.value == 'DOUBLE_CLICK' or (time.time() - getattr(self, '_last_click_time', 0.0) < 0.35 and getattr(self, '_last_click_index', -1) == idx)
                self._last_click_time = time.time()
                self._last_click_index = idx
                if is_double:
                    entry = overlay.entries[idx]
                    if append_hair_from_library(context, entry.entry_id):
                        overlay.is_open = False
                        remove_draw_handler()
                        if context.area:
                            context.area.tag_redraw()
                        return {'FINISHED'}
                return {'RUNNING_MODAL'}
            return {'RUNNING_MODAL'}

        if event.type in {'MIDDLEMOUSE', 'RIGHTMOUSE'}:
            return {'RUNNING_MODAL'}

        return {'RUNNING_MODAL'}


class HAIRPIPE_OT_library_overlay_card_scale_up(bpy.types.Operator):
    bl_idname = "hair_pipe.library_overlay_card_scale_up"
    bl_label = "卡片放大"
    bl_options = {'REGISTER'}

    def execute(self, context):
        overlay = context.window_manager.hair_pipe_library_overlay
        overlay.card_scale = min(2.0, overlay.card_scale + 0.1)
        return {'FINISHED'}


class HAIRPIPE_OT_library_overlay_card_scale_down(bpy.types.Operator):
    bl_idname = "hair_pipe.library_overlay_card_scale_down"
    bl_label = "卡片缩小"
    bl_options = {'REGISTER'}

    def execute(self, context):
        overlay = context.window_manager.hair_pipe_library_overlay
        overlay.card_scale = max(0.5, overlay.card_scale - 0.1)
        return {'FINISHED'}


class HAIRPIPE_OT_library_overlay_select(bpy.types.Operator):
    bl_idname = "hair_pipe.library_overlay_select"
    bl_label = "选择条目"
    bl_options = {'REGISTER'}

    entry_index: IntProperty(default=-1)

    def execute(self, context):
        context.window_manager.hair_pipe_library_overlay.active_entry_index = self.entry_index
        return {'FINISHED'}


class HAIRPIPE_OT_library_overlay_click(bpy.types.Operator):
    bl_idname = "hair_pipe.library_overlay_click"
    bl_label = "点击头发库"
    bl_options = {'REGISTER'}

    double_click: BoolProperty(default=False)

    def invoke(self, context, event):
        if not _event_over_overlay(event, context):
            return {'PASS_THROUGH'}
        idx = _find_entry_from_pos(event.mouse_region_x, event.mouse_region_y)
        if idx < 0:
            return {'PASS_THROUGH'}
        overlay = context.window_manager.hair_pipe_library_overlay
        overlay.active_entry_index = idx
        if self.double_click:
            return bpy.ops.hair_pipe.library_overlay_insert('INVOKE_DEFAULT')
        return {'FINISHED'}


class HAIRPIPE_OT_library_overlay_insert(bpy.types.Operator):
    bl_idname = "hair_pipe.library_overlay_insert"
    bl_label = "导入头发"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        overlay = context.window_manager.hair_pipe_library_overlay
        if not (0 <= overlay.active_entry_index < len(overlay.entries)):
            return {'CANCELLED'}
        entry = overlay.entries[overlay.active_entry_index]
        if not append_hair_from_library(context, entry.entry_id):
            self.report({'ERROR'}, "插入失败")
            return {'CANCELLED'}
        overlay.is_open = False
        remove_draw_handler()
        return {'FINISHED'}


class HAIRPIPE_OT_library_delete(bpy.types.Operator):
    bl_idname = "hair_pipe.library_delete"
    bl_label = "删除头发库条目"
    bl_options = {'REGISTER', 'UNDO'}

    entry_id: StringProperty(name="Entry ID")

    def execute(self, context):
        if not remove_hair_library_entry(self.entry_id):
            self.report({'ERROR'}, "删除失败")
            return {'CANCELLED'}
        sync_state_entries(context.window_manager.hair_pipe_library_state)
        sync_overlay_entries(context.window_manager.hair_pipe_library_overlay)
        return {'FINISHED'}


class HAIRPIPE_OT_library_save_current(bpy.types.Operator):
    bl_idname = "hair_pipe.library_save_current"
    bl_label = "保存到头发库"
    bl_options = {'REGISTER', 'UNDO'}

    entry_name: StringProperty(name="名称", default="Hair")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "entry_name", text="名称")
        layout.label(text="保存时会自动读取剪贴板图片作为缩略图", icon='IMAGE_DATA')
        layout.label(text="请先截图并复制到剪贴板，再点击确定", icon='INFO')

    def execute(self, context):
        entry_id = save_current_hair_to_library(context, self.entry_name.strip() or "Hair")
        if entry_id is None:
            self.report({'ERROR'}, "无法保存当前头发")
            return {'CANCELLED'}
        sync_state_entries(context.window_manager.hair_pipe_library_state)
        sync_overlay_entries(context.window_manager.hair_pipe_library_overlay)
        return {'FINISHED'}


classes = (
    HairLibraryEntryItem,
    HairLibraryState,
    HairLibraryOverlayState,
    HAIRPIPE_OT_library_overlay_toggle,
    HAIRPIPE_OT_library_overlay_card_scale_up,
    HAIRPIPE_OT_library_overlay_card_scale_down,
    HAIRPIPE_OT_library_overlay_select,
    HAIRPIPE_OT_library_overlay_click,
    HAIRPIPE_OT_library_overlay_insert,
    HAIRPIPE_OT_library_delete,
    HAIRPIPE_OT_library_save_current,
)


def register():
    global _library_previews
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.hair_pipe_library_state = bpy.props.PointerProperty(type=HairLibraryState)
    bpy.types.WindowManager.hair_pipe_library_overlay = bpy.props.PointerProperty(type=HairLibraryOverlayState)
    bpy.types.WindowManager.hair_pipe_library_preview_cache = bpy.props.PointerProperty(type=HairLibraryState)
    _library_previews = bpy.utils.previews.new()


def unregister():
    global _library_previews
    remove_draw_handler()
    _image_cache.clear()
    if _library_previews is not None:
        bpy.utils.previews.remove(_library_previews)
        _library_previews = None
    del bpy.types.WindowManager.hair_pipe_library_state
    del bpy.types.WindowManager.hair_pipe_library_overlay
    del bpy.types.WindowManager.hair_pipe_library_preview_cache
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
