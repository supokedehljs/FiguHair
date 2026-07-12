import bpy
import json
import os
import math
import shutil
import subprocess
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

try:
    import win32clipboard
except Exception:
    win32clipboard = None


LIBRARY_DIR_NAME = "figuhair_library"
INDEX_FILE_NAME = "index.json"
ASSET_DIR_NAME = "assets"


_library_previews = None
_draw_handle = None
_overlay_bounds = []
_overlay_button_bounds = []
_overlay_drag_bounds = None
_overlay_resize_bounds = None
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
    card_scale: FloatProperty(name="Card Scale", default=1.0, min=0.45, max=2.5)
    scroll_offset: FloatProperty(name="Scroll Offset", default=0.0, min=0.0)
    panel_offset_x: FloatProperty(name="Panel Offset X", default=0.0)
    panel_offset_y: FloatProperty(name="Panel Offset Y", default=0.0)
    panel_width: FloatProperty(name="Panel Width", default=980.0, min=420.0, max=1800.0)
    panel_height: FloatProperty(name="Panel Height", default=720.0, min=320.0, max=1200.0)
    is_dragging: BoolProperty(name="Dragging", default=False)
    is_resizing: BoolProperty(name="Resizing", default=False)
    drag_start_mouse_x: FloatProperty(name="Drag Start Mouse X", default=0.0)
    drag_start_mouse_y: FloatProperty(name="Drag Start Mouse Y", default=0.0)
    drag_start_panel_x: FloatProperty(name="Drag Start Panel X", default=0.0)
    drag_start_panel_y: FloatProperty(name="Drag Start Panel Y", default=0.0)
    resize_start_width: FloatProperty(name="Resize Start Width", default=980.0)
    resize_start_height: FloatProperty(name="Resize Start Height", default=720.0)
    resize_anchor_left: FloatProperty(name="Resize Anchor Left", default=0.0)
    resize_anchor_top: FloatProperty(name="Resize Anchor Top", default=0.0)
    selected_entry_ids: StringProperty(name="Selected Entries", default="")
    entries: CollectionProperty(type=HairLibraryEntryItem)


class HairLibraryState(PropertyGroup):
    active_entry_index: IntProperty(name="Active Entry Index", default=0)
    pending_thumbnail_path: StringProperty(name="Thumbnail", default="", subtype='FILE_PATH')
    selected_entry_ids: StringProperty(name="Selected Entries", default="")
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


def get_asset_dir():
    path = os.path.join(get_library_root(), ASSET_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def get_thumbnail_path_for_blend(blend_path):
    if not blend_path:
        return ""
    abs_blend_path = bpy.path.abspath(blend_path)
    base_path, _ext = os.path.splitext(abs_blend_path)
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        thumbnail_path = base_path + ext
        if os.path.exists(thumbnail_path):
            return thumbnail_path
    return base_path + ".png"


def load_index():
    path = get_index_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        entries = data if isinstance(data, list) else []
    except Exception:
        return []
    valid_entries = [entry for entry in entries if os.path.exists(entry.get("blend_path", ""))]
    if len(valid_entries) != len(entries):
        save_index(valid_entries)
    return valid_entries


def save_index(entries):
    with open(get_index_path(), "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def _fill_entry_collection(collection, entries):
    collection.clear()
    for entry in entries:
        blend_path = entry.get("blend_path", "")
        item = collection.add()
        item.entry_id = entry.get("id", "")
        item.name = entry.get("name", "")
        item.blend_path = blend_path
        item.thumbnail_path = get_thumbnail_path_for_blend(blend_path)
        item.created_at = entry.get("created_at", "")


def sync_state_entries(state):
    _fill_entry_collection(state.entries, load_index())
    if state.active_entry_index >= len(state.entries):
        state.active_entry_index = len(state.entries) - 1


def sync_overlay_entries(state):
    _fill_entry_collection(state.entries, load_index())
    if state.active_entry_index >= len(state.entries):
        state.active_entry_index = len(state.entries) - 1


def get_selected_library_entry_ids(state):
    return {entry_id for entry_id in state.selected_entry_ids.split(";") if entry_id}


def set_selected_library_entry_ids(state, selected_ids):
    state.selected_entry_ids = ";".join(sorted(selected_ids))


def toggle_selected_library_entry(state, entry_id):
    selected_ids = get_selected_library_entry_ids(state)
    if entry_id in selected_ids:
        selected_ids.remove(entry_id)
    else:
        selected_ids.add(entry_id)
    set_selected_library_entry_ids(state, selected_ids)


def get_preview_icon_for_path(path):
    global _library_previews
    if _library_previews is None:
        _library_previews = bpy.utils.previews.new()
    abs_path = bpy.path.abspath(path)
    if not abs_path or not os.path.exists(abs_path):
        return 0
    icon_key = "path:" + abs_path
    if icon_key not in _library_previews:
        try:
            _library_previews.load(icon_key, abs_path, 'IMAGE')
        except Exception:
            return 0
    return _library_previews[icon_key].icon_id


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


def _save_clipboard_thumbnail_with_powershell(target_path):
    if os.name != 'nt':
        return False
    escaped_target = target_path.replace("'", "''")
    ps_script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        "$img = [System.Windows.Forms.Clipboard]::GetImage(); "
        "if ($null -eq $img) { "
        "  $files = [System.Windows.Forms.Clipboard]::GetFileDropList(); "
        "  if ($files.Count -gt 0) { "
        "    foreach ($file in $files) { "
        "      if ($file -match '\\.(png|jpg|jpeg|bmp|webp)$') { "
        "        $img = [System.Drawing.Image]::FromFile($file); break; "
        "      } "
        "    } "
        "  } "
        "}; "
        "if ($null -eq $img) { exit 2 }; "
        f"$img.Save('{escaped_target}', [System.Drawing.Imaging.ImageFormat]::Png); "
        "$img.Dispose();"
    )
    commands = [
        ["powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        ["pwsh.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
    ]
    for command in commands:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0 and os.path.exists(target_path):
                return True
        except Exception:
            pass
    return False


def _save_clipboard_thumbnail_to_path(target_path):
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    if ImageGrab is not None:
        try:
            image = ImageGrab.grabclipboard()
        except Exception:
            image = None
        if isinstance(image, list):
            image_path = next((path for path in image if isinstance(path, str) and path.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp"))), "")
            if image_path and _copy_thumbnail_to_path(image_path, target_path):
                return True
        elif image is not None:
            try:
                if getattr(image, "mode", "") not in {"RGB", "RGBA"}:
                    image = image.convert("RGBA")
                image.save(target_path, format="PNG")
                return True
            except Exception:
                pass

    if _save_clipboard_thumbnail_with_powershell(target_path):
        return True

    if win32clipboard is not None:
        try:
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_DIB):
                    data = win32clipboard.GetClipboardData(win32clipboard.CF_DIB)
                    bmp_path = target_path + ".bmp"
                    with open(bmp_path, "wb") as f:
                        f.write(b"BM")
                        f.write((len(data) + 14).to_bytes(4, "little"))
                        f.write((0).to_bytes(4, "little"))
                        f.write((14 + 40).to_bytes(4, "little"))
                        f.write(data)
                    if ImageGrab is not None:
                        from PIL import Image
                        with Image.open(bmp_path) as image:
                            image.save(target_path)
                        os.remove(bmp_path)
                        return True
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            pass

    return False


def _copy_thumbnail_to_path(source_path, target_path):
    if not source_path or not os.path.exists(source_path):
        return False
    try:
        shutil.copy2(source_path, target_path)
        return True
    except Exception:
        return False


def save_current_hair_to_library(context, entry_name, thumbnail_source_path=""):
    curve_obj = context.active_object
    if curve_obj is None or curve_obj.type != 'CURVE':
        return None
    bundle = get_curve_bundle_objects(curve_obj)
    if not bundle:
        return None

    entry_id = uuid.uuid4().hex[:12]
    asset_base_name = f"{entry_name}_{entry_id}"
    asset_base_path = os.path.join(get_asset_dir(), asset_base_name)
    blend_path = asset_base_path + ".blend"
    thumbnail_path = get_thumbnail_path_for_blend(blend_path)
    bpy.data.libraries.write(blend_path, set(bundle), path_remap='RELATIVE', fake_user=True)
    _copy_thumbnail_to_path(thumbnail_source_path, thumbnail_path)

    entries = load_index()
    entries.append({
        "id": entry_id,
        "name": entry_name,
        "blend_path": blend_path,
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
    blend_path = entry.get("blend_path", "")
    thumbnail_path = get_thumbnail_path_for_blend(blend_path)
    for path in (blend_path, thumbnail_path):
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
        try:
            image.colorspace_settings.name = 'Non-Color'
        except Exception:
            pass
        image.alpha_mode = 'STRAIGHT'
        _image_cache[path] = image
        return image
    except Exception:
        return None


def _draw_image_rect(image, x0, y0, x1, y1):
    if image is None:
        return False
    try:
        texture = gpu.texture.from_image(image)
        shader = gpu.shader.from_builtin('IMAGE')
        batch = batch_for_shader(shader, 'TRI_FAN', {
            "pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
            "texCoord": [(0, 0), (1, 0), (1, 1), (0, 1)],
        })
        gpu.state.blend_set('ALPHA')
        shader.bind()
        shader.uniform_sampler("image", texture)
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
    global _overlay_bounds, _overlay_button_bounds, _overlay_drag_bounds, _overlay_resize_bounds
    _overlay_bounds = []
    _overlay_button_bounds = []
    _overlay_drag_bounds = None
    _overlay_resize_bounds = None
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

    panel_w = min(max(state.panel_width, 420.0), width - 32)
    panel_h = min(max(state.panel_height, 320.0), height - 32)
    inner_x0 = (width - panel_w) * 0.5 + state.panel_offset_x
    inner_y0 = (height - panel_h) * 0.5 + state.panel_offset_y
    inner_x0 = max(8, min(width - panel_w - 8, inner_x0))
    inner_y0 = max(8, min(height - panel_h - 8, inner_y0))
    inner_x1 = inner_x0 + panel_w
    inner_y1 = inner_y0 + panel_h
    _rounded_rect(shader, inner_x0 + 5, inner_y0 - 5, inner_x1 + 5, inner_y1 - 5, 12, (0.0, 0.0, 0.0, 0.28))
    _rounded_rect(shader, inner_x0, inner_y0, inner_x1, inner_y1, 12, (0.105, 0.105, 0.115, 0.94))
    _rounded_rect(shader, inner_x0 + 1, inner_y0 + 1, inner_x1 - 1, inner_y1 - 1, 11, (0.15, 0.15, 0.165, 0.34))

    drag_h = 34
    _overlay_drag_bounds = (inner_x0, inner_y1 - drag_h, inner_x1, inner_y1)
    _rounded_rect(shader, inner_x0, inner_y1 - drag_h, inner_x1, inner_y1, 12, (0.16, 0.16, 0.175, 0.96))
    blf.size(0, 12)
    blf.color(0, 0.72, 0.74, 0.78, 0.92)
    blf.position(0, inner_x0 + 18, inner_y1 - 23, 0)
    blf.draw(0, "FiguHair Library")

    resize_size = 22
    _overlay_resize_bounds = (inner_x1 - resize_size, inner_y0, inner_x1, inner_y0 + resize_size)
    for i in range(3):
        x0 = inner_x1 - 6 - i * 6
        y0 = inner_y0 + 5
        x1 = inner_x1 - 4
        y1 = inner_y0 + 7 + i * 6
        _rounded_rect(shader, x0, y0, x1, y1, 1, (0.56, 0.58, 0.62, 0.78))

    grid_x0 = inner_x0 + 18
    grid_x1 = inner_x1 - 18
    grid_y0 = inner_y0 + 18
    grid_y1 = inner_y1 - drag_h - 14
    card_size = max(96, min(360, 220 * state.card_scale))
    gap = max(10, min(28, 18 * state.card_scale))
    cols = max(1, int((grid_x1 - grid_x0 + gap) // (card_size + gap)))
    total_rows = max(1, math.ceil(len(state.entries) / cols))
    content_h = total_rows * card_size + (total_rows - 1) * gap
    view_h = grid_y1 - grid_y0
    max_scroll = max(0.0, content_h - view_h)
    state.scroll_offset = min(max(getattr(state, 'scroll_offset', 0.0), 0.0), max_scroll)
    y_start = grid_y1 - card_size + state.scroll_offset

    font_id = 0
    gpu.state.scissor_test_set(True)
    gpu.state.scissor_set(int(grid_x0), int(grid_y0), int(grid_x1 - grid_x0), int(grid_y1 - grid_y0))

    for idx, entry in enumerate(state.entries):
        col = idx % cols
        row = idx // cols
        x0 = grid_x0 + col * (card_size + gap)
        y0 = y_start - row * (card_size + gap)
        x1 = x0 + card_size
        y1 = y0 + card_size
        if y1 < grid_y0 or y0 > grid_y1:
            continue
        _overlay_bounds.append((x0, y0, x1, y1, idx))
        _rounded_rect(shader, x0, y0, x1, y1, 8, (0.08, 0.08, 0.09, 0.88))
        thumb_image = _load_thumbnail_image(get_thumbnail_path_for_blend(entry.blend_path))
        if not _draw_image_rect(thumb_image, x0 + 4, y0 + 4, x1 - 4, y1 - 4):
            _rounded_rect(shader, x0 + 4, y0 + 4, x1 - 4, y1 - 4, 6, (0.075, 0.08, 0.095, 1.0))
            label = "无缩略图"
            blf.size(font_id, 12)
            text_w, text_h = blf.dimensions(font_id, label)
            blf.color(font_id, 0.56, 0.60, 0.68, 0.9)
            blf.position(font_id, x0 + (card_size - text_w) * 0.5, y0 + (card_size - text_h) * 0.5, 0)
            blf.draw(font_id, label)

    gpu.state.scissor_test_set(False)

    if max_scroll > 1e-3:
        track_x0 = inner_x1 - 12
        track_x1 = inner_x1 - 6
        _rounded_rect(shader, track_x0, grid_y0, track_x1, grid_y1, 3, (0.18, 0.18, 0.20, 1.0))
        thumb_h = max(36, view_h * min(1.0, view_h / content_h))
        thumb_y1 = grid_y1 - (state.scroll_offset / max_scroll) * (view_h - thumb_h)
        thumb_y0 = thumb_y1 - thumb_h
        _rounded_rect(shader, track_x0, thumb_y0, track_x1, thumb_y1, 3, (0.58, 0.58, 0.62, 1.0))

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
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        overlay = context.window_manager.hair_pipe_library_overlay
        overlay.is_open = True
        overlay.selected_entry_ids = ""
        overlay.scroll_offset = 0.0
        sync_overlay_entries(overlay)
        ensure_draw_handler()
        context.window_manager.modal_handler_add(self)
        if context.area:
            context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def execute(self, context):
        return self.invoke(context, None)

    def modal(self, context, event):
        overlay = context.window_manager.hair_pipe_library_overlay
        if not overlay.is_open:
            remove_draw_handler()
            return {'FINISHED'}
        if event.type in {'ESC'} and event.value == 'PRESS':
            overlay.is_open = False
            remove_draw_handler()
            if context.area:
                context.area.tag_redraw()
            return {'FINISHED'}
        if event.type == 'WHEELUPMOUSE':
            if event.ctrl:
                overlay.card_scale = min(2.5, overlay.card_scale + 0.08)
            else:
                overlay.scroll_offset = max(0.0, overlay.scroll_offset - 72.0)
            if context.area:
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type == 'WHEELDOWNMOUSE':
            if event.ctrl:
                overlay.card_scale = max(0.45, overlay.card_scale - 0.08)
            else:
                overlay.scroll_offset += 72.0
            if context.area:
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if overlay.is_dragging and event.type == 'MOUSEMOVE':
            overlay.panel_offset_x = overlay.drag_start_panel_x + (event.mouse_region_x - overlay.drag_start_mouse_x)
            overlay.panel_offset_y = overlay.drag_start_panel_y + (event.mouse_region_y - overlay.drag_start_mouse_y)
            if context.area:
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if overlay.is_resizing and event.type == 'MOUSEMOVE':
            new_width = max(420.0, overlay.resize_start_width + (event.mouse_region_x - overlay.drag_start_mouse_x))
            new_height = max(320.0, overlay.resize_start_height - (event.mouse_region_y - overlay.drag_start_mouse_y))
            overlay.panel_width = new_width
            overlay.panel_height = new_height
            if context.region:
                region_w = context.region.width
                region_h = context.region.height
                overlay.panel_offset_x = overlay.resize_anchor_left - (region_w - new_width) * 0.5
                overlay.panel_offset_y = overlay.resize_anchor_top - new_height - (region_h - new_height) * 0.5
            if context.area:
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            overlay.is_dragging = False
            overlay.is_resizing = False
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            inside_window = False
            if _overlay_resize_bounds is not None:
                x0, y0, x1, y1 = _overlay_resize_bounds
                if x0 <= event.mouse_region_x <= x1 and y0 <= event.mouse_region_y <= y1:
                    overlay.is_resizing = True
                    overlay.drag_start_mouse_x = event.mouse_region_x
                    overlay.drag_start_mouse_y = event.mouse_region_y
                    overlay.resize_start_width = overlay.panel_width
                    overlay.resize_start_height = overlay.panel_height
                    if _overlay_drag_bounds is not None:
                        left, _bar_bottom, _right, top = _overlay_drag_bounds
                        overlay.resize_anchor_left = left
                        overlay.resize_anchor_top = top
                    return {'RUNNING_MODAL'}
            if _overlay_drag_bounds is not None:
                x0, y0, x1, y1 = _overlay_drag_bounds
                if x0 <= event.mouse_region_x <= x1 and y0 <= event.mouse_region_y <= y1:
                    inside_window = True
                    overlay.is_dragging = True
                    overlay.drag_start_mouse_x = event.mouse_region_x
                    overlay.drag_start_mouse_y = event.mouse_region_y
                    overlay.drag_start_panel_x = overlay.panel_offset_x
                    overlay.drag_start_panel_y = overlay.panel_offset_y
                    return {'RUNNING_MODAL'}
            idx = _find_entry_from_pos(event.mouse_region_x, event.mouse_region_y)
            if idx >= 0 and idx < len(overlay.entries):
                append_hair_from_library(context, overlay.entries[idx].entry_id)
                overlay.is_open = False
                remove_draw_handler()
                if context.area:
                    context.area.tag_redraw()
                return {'FINISHED'}
            if _overlay_drag_bounds is not None:
                x0, _y0, x1, y1 = _overlay_drag_bounds
                panel_left = x0
                panel_right = x1
                panel_top = y1
                panel_bottom = min(y for _x0, y, _x1, _y1, _idx in _overlay_bounds) if _overlay_bounds else y1 - overlay.panel_height
                inside_window = panel_left <= event.mouse_region_x <= panel_right and panel_bottom <= event.mouse_region_y <= panel_top
            if not inside_window:
                overlay.is_open = False
                remove_draw_handler()
                if context.area:
                    context.area.tag_redraw()
                return {'PASS_THROUGH'}
            return {'RUNNING_MODAL'}
        if event.type in {'MIDDLEMOUSE', 'RIGHTMOUSE', 'LEFTMOUSE'}:
            return {'PASS_THROUGH'}
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


class HAIRPIPE_OT_library_toggle_select_entry(bpy.types.Operator):
    bl_idname = "hair_pipe.library_toggle_select_entry"
    bl_label = "选择头发"
    bl_options = {'REGISTER'}

    entry_id: StringProperty(name="Entry ID")

    def execute(self, context):
        toggle_selected_library_entry(context.window_manager.hair_pipe_library_overlay, self.entry_id)
        return {'FINISHED'}


class HAIRPIPE_OT_library_delete_selected(bpy.types.Operator):
    bl_idname = "hair_pipe.library_delete_selected"
    bl_label = "删除选中头发"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        overlay = context.window_manager.hair_pipe_library_overlay
        selected_ids = get_selected_library_entry_ids(overlay)
        if not selected_ids:
            return {'CANCELLED'}
        for entry_id in list(selected_ids):
            remove_hair_library_entry(entry_id)
        overlay.selected_entry_ids = ""
        sync_state_entries(context.window_manager.hair_pipe_library_state)
        sync_overlay_entries(overlay)
        return {'FINISHED'}


class HAIRPIPE_OT_library_import_entry(bpy.types.Operator):
    bl_idname = "hair_pipe.library_import_entry"
    bl_label = "导入头发"
    bl_options = {'REGISTER', 'UNDO'}

    entry_id: StringProperty(name="Entry ID")

    def execute(self, context):
        if not append_hair_from_library(context, self.entry_id):
            self.report({'ERROR'}, "导入失败")
            return {'CANCELLED'}
        return {'FINISHED'}


class HAIRPIPE_OT_library_open_folder(bpy.types.Operator):
    bl_idname = "hair_pipe.library_open_folder"
    bl_label = "打开头发库文件夹"
    bl_options = {'REGISTER'}

    def execute(self, context):
        library_root = get_library_root()
        try:
            bpy.ops.wm.path_open(filepath=library_root)
        except Exception:
            try:
                os.startfile(library_root)
            except Exception:
                self.report({'ERROR'}, "无法打开头发库文件夹")
                return {'CANCELLED'}
        return {'FINISHED'}


class HAIRPIPE_OT_library_paste_thumbnail(bpy.types.Operator):
    bl_idname = "hair_pipe.library_paste_thumbnail"
    bl_label = "粘贴图片"
    bl_options = {'REGISTER'}

    def execute(self, context):
        state = context.window_manager.hair_pipe_library_state
        preview_path = os.path.join(get_asset_dir(), f"pending_thumbnail_{int(time.time() * 1000)}.png")
        if not _save_clipboard_thumbnail_to_path(preview_path):
            self.report({'ERROR'}, "没有读取到剪贴板图片")
            return {'CANCELLED'}
        old_preview_path = bpy.path.abspath(state.pending_thumbnail_path) if state.pending_thumbnail_path else ""
        state.pending_thumbnail_path = preview_path
        if old_preview_path and os.path.exists(old_preview_path) and os.path.basename(old_preview_path).startswith("pending_thumbnail_"):
            try:
                os.remove(old_preview_path)
            except Exception:
                pass
        if _library_previews is not None:
            try:
                _library_previews.clear()
            except Exception:
                pass
        _image_cache.pop(preview_path, None)
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
        state = context.window_manager.hair_pipe_library_state
        state.pending_thumbnail_path = ""
        return context.window_manager.invoke_props_dialog(self, width=520)

    def draw(self, context):
        layout = self.layout
        state = context.window_manager.hair_pipe_library_state
        layout.prop(self, "entry_name", text="名字")
        box = layout.box()
        row = box.row(align=True)
        row.label(text="图片", icon='IMAGE_DATA')
        row.operator("hair_pipe.library_paste_thumbnail", text="粘贴图片", icon='PASTEDOWN')
        if state.pending_thumbnail_path and os.path.exists(bpy.path.abspath(state.pending_thumbnail_path)):
            box.template_icon(icon_value=get_preview_icon_for_path(state.pending_thumbnail_path), scale=7.0)
        else:
            empty = box.box()
            empty.scale_y = 2.4
            empty.label(text="未粘贴图片", icon='IMAGE_DATA')

    def execute(self, context):
        state = context.window_manager.hair_pipe_library_state
        thumbnail_path = bpy.path.abspath(state.pending_thumbnail_path) if state.pending_thumbnail_path else ""
        entry_id = save_current_hair_to_library(context, self.entry_name.strip() or "Hair", thumbnail_path)
        if entry_id is None:
            self.report({'ERROR'}, "无法保存当前头发")
            return {'CANCELLED'}
        if thumbnail_path and os.path.exists(thumbnail_path) and os.path.basename(thumbnail_path).startswith("pending_thumbnail_"):
            try:
                os.remove(thumbnail_path)
            except Exception:
                pass
        state.pending_thumbnail_path = ""
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
    HAIRPIPE_OT_library_toggle_select_entry,
    HAIRPIPE_OT_library_delete_selected,
    HAIRPIPE_OT_library_import_entry,
    HAIRPIPE_OT_library_open_folder,
    HAIRPIPE_OT_library_paste_thumbnail,
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
