import json
import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader
from bpy.props import EnumProperty
from bpy_extras import view3d_utils

from .operators import (
    apply_group_color_mode,
    get_context_curve_object,
    get_pipe_object_for_curve,
    get_tail_object_for_curve,
    get_pipe_source_curve,
    get_tail_source_curve,
)


_STATE_KEY = "hair_pipe_display_mode_state"
_border_draw_handle = None


def is_display_mode(context):
    scene = getattr(context, "scene", None)
    return bool(scene is not None and scene.get("hair_pipe_display_mode_active", False))


def iter_hair_curves():
    for obj in bpy.data.objects:
        if obj.type == 'CURVE' and obj.get("hair_pipe_base_name"):
            yield obj


def hair_family(curve):
    return tuple(obj for obj in (
        curve,
        get_pipe_object_for_curve(curve),
        get_tail_object_for_curve(curve),
    ) if obj is not None)


def curve_hidden(curve):
    return bool(curve.get("hair_pipe_display_hidden", curve.hide_get()))


def display_material_for_curve(curve, hidden):
    collection = curve_group(curve, bpy.context.scene)
    base = bpy.data.materials.get("FiguHair Group Color " + collection.name)
    if not hidden or base is None:
        return base
    name = "FiguHair Hidden Preview " + collection.name
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
        material["hair_pipe_display_preview_temp"] = True
    material.diffuse_color = (*base.diffuse_color[:3], 0.18)
    if hasattr(material, "surface_render_method"):
        try:
            material.surface_render_method = 'DITHERED'
        except (TypeError, ValueError):
            pass
    return material


def display_material_for_object(obj):
    name = "FiguHair Hidden Object Preview"
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
        material["hair_pipe_display_object_preview_temp"] = True
    material.diffuse_color = (0.42, 0.42, 0.42, 0.18)
    if hasattr(material, "surface_render_method"):
        try:
            material.surface_render_method = 'DITHERED'
        except (TypeError, ValueError):
            pass
    return material


def restore_ordinary_object_materials(obj):
    scene = getattr(bpy.context, "scene", None)
    if scene is None or obj.type != 'MESH':
        return
    try:
        state = json.loads(scene.get(_STATE_KEY, "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return
    saved = state.get("ordinary_objects", {}).get(obj.name, {})
    obj.data.materials.clear()
    for name in saved.get("materials", []):
        obj.data.materials.append(bpy.data.materials.get(name) if name else None)


def current_group_material(obj):
    scene = getattr(bpy.context, "scene", None)
    if scene is None or obj.type != 'MESH' or not scene.hair_pipe_group_color_mode:
        return None
    collection = obj.users_collection[0] if obj.users_collection else scene.collection
    return bpy.data.materials.get("FiguHair Group Color " + collection.name)


def set_preview_style_object(obj, hidden):
    if obj is None or obj.type in {'CAMERA', 'LIGHT'}:
        return
    obj["hair_pipe_display_hidden"] = bool(hidden)
    obj.hide_viewport = False
    obj.hide_set(False)
    obj.display_type = 'TEXTURED'
    obj.show_in_front = False
    if hasattr(obj, "show_transparent"):
        obj.show_transparent = bool(hidden)
    if hidden:
        obj.color = (0.45, 0.45, 0.45, 0.22)
        if obj.type == 'MESH':
            obj.data.materials.clear()
            obj.data.materials.append(display_material_for_object(obj))
    else:
        obj.color = (obj.color[0], obj.color[1], obj.color[2], 1.0)
        material = current_group_material(obj)
        if obj.type == 'MESH' and material is not None:
            obj.data.materials.clear()
            obj.data.materials.append(material)
        else:
            restore_ordinary_object_materials(obj)


def set_preview_style(curve, hidden):
    curve["hair_pipe_display_hidden"] = bool(hidden)
    hidden_state = bool(hidden)
    for obj in hair_family(curve):
        obj.hide_viewport = False
        obj.hide_set(False)
    for mesh in (get_pipe_object_for_curve(curve), get_tail_object_for_curve(curve)):
        if mesh is None:
            continue
        mesh.display_type = 'TEXTURED'
        mesh.show_in_front = False
        if hidden_state:
            mesh.color = (0.55, 0.55, 0.55, 0.28)
        else:
            mesh.color = (mesh.color[0], mesh.color[1], mesh.color[2], 1.0)
        mesh.show_transparent = hidden_state
        material = display_material_for_curve(curve, hidden_state)
        if material is not None:
            mesh.data.materials.clear()
            mesh.data.materials.append(material)


def hovered_display_object(context, event):
    region = context.region
    region_data = context.region_data
    if region is None or region_data is None:
        return None
    origin = view3d_utils.region_2d_to_origin_3d(region, region_data, (event.mouse_region_x, event.mouse_region_y))
    direction = view3d_utils.region_2d_to_vector_3d(region, region_data, (event.mouse_region_x, event.mouse_region_y))
    hit, _loc, _normal, _face, obj, _matrix = context.scene.ray_cast(
        context.view_layer.depsgraph, origin, direction
    )
    return obj if hit else None


def curve_from_hit_object(obj):
    if obj is None:
        return None
    if obj.type == 'CURVE' and obj.get("hair_pipe_base_name"):
        return obj
    return get_pipe_source_curve(obj) or get_tail_source_curve(obj)


def target_hidden(target):
    curve = curve_from_hit_object(target)
    if curve is not None:
        return curve_hidden(curve)
    return bool(target.get("hair_pipe_display_hidden", target.hide_get() or target.hide_viewport))


def hovered_target_by_state(context, event, hidden_state):
    region = context.region
    region_data = context.region_data
    if region is None or region_data is None:
        return None
    coord = (event.mouse_region_x, event.mouse_region_y)
    origin = view3d_utils.region_2d_to_origin_3d(region, region_data, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, region_data, coord)
    remaining = 1000000.0
    for _step in range(128):
        hit, location, _normal, _face, obj, _matrix = context.scene.ray_cast(
            context.view_layer.depsgraph, origin, direction, distance=remaining
        )
        if not hit or obj is None:
            return None
        target = curve_from_hit_object(obj) or obj
        if target_hidden(target) == hidden_state:
            return target
        advance = max(0.0001, (location - origin).length + 0.0001)
        origin = location + direction * 0.0001
        remaining -= advance
        if remaining <= 0.0:
            break
    return None


def selected_display_targets(context):
    targets = []
    for obj in context.selected_objects:
        curve = curve_from_hit_object(obj)
        if curve is not None:
            if curve not in targets:
                targets.append(curve)
        elif obj.type not in {'CAMERA', 'LIGHT'} and obj not in targets:
            targets.append(obj)
    return targets


def set_display_target_hidden(target, hidden):
    if target is None:
        return
    curve = curve_from_hit_object(target)
    if curve is not None:
        set_preview_style(curve, hidden)
    else:
        set_preview_style_object(target, hidden)


def hovered_hair(context, event):
    region = context.region
    region_data = context.region_data
    if region is None or region_data is None:
        return None
    coord = (event.mouse_region_x, event.mouse_region_y)
    origin = view3d_utils.region_2d_to_origin_3d(region, region_data, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, region_data, coord)
    hit, _location, _normal, _face_index, hit_obj, _matrix = context.scene.ray_cast(
        context.view_layer.depsgraph, origin, direction
    )
    return curve_from_hit_object(hit_obj) if hit else None


def curve_group(curve, scene):
    return curve.users_collection[0] if curve.users_collection else scene.collection


def apply_group_visibility(context, source_curve, hidden):
    target_group = curve_group(source_curve, context.scene)
    for curve in iter_hair_curves():
        if curve_group(curve, context.scene) == target_group:
            set_preview_style(curve, hidden)


def enter_display_mode(context):
    scene = context.scene
    if is_display_mode(context):
        return True

    wd = getattr(context.window_manager, "hair_pipe_widget", None)
    widget_was_active = bool(wd is not None and wd.is_active)
    previous_mode = context.mode
    active_name = context.active_object.name if context.active_object is not None else ""
    selected_names = [obj.name for obj in context.selected_objects]

    if widget_was_active:
        try:
            bpy.ops.hair_pipe.widget_stop()
        except RuntimeError:
            wd.is_active = False
    if context.mode != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except RuntimeError:
            return False

    states = {}
    hidden_states = {}
    for curve in iter_hair_curves():
        family_states = {}
        for obj in hair_family(curve):
            family_states[obj.name] = {
                "hidden": bool(obj.hide_get()),
                "hide_viewport": bool(obj.hide_viewport),
                "display_type": obj.display_type,
                "show_in_front": bool(obj.show_in_front),
                "color": tuple(obj.color),
                "show_transparent": bool(getattr(obj, "show_transparent", False)),
                "materials": [material.name if material else None for material in obj.data.materials] if obj.type == 'MESH' else [],
            }
        states[curve.name] = family_states
        hidden_states[curve.name] = bool(curve.hide_get() or any(
            state["hidden"] or state["hide_viewport"] for state in family_states.values()
        ))

    ordinary_states = {
        obj.name: {
            "hidden": bool(obj.hide_get()),
            "hide_viewport": bool(obj.hide_viewport),
            "display_type": obj.display_type,
            "show_in_front": bool(obj.show_in_front),
            "color": tuple(obj.color),
            "show_transparent": bool(getattr(obj, "show_transparent", False)),
        }
        for obj in bpy.data.objects
        if obj.type not in {'CAMERA', 'LIGHT'} and curve_from_hit_object(obj) is None
    }

    # Build group-color materials first, then apply the transparent hidden
    # preview so entering the mode cannot overwrite pre-existing hidden hairs.
    if not scene.hair_pipe_group_color_mode:
        scene.hair_pipe_group_color_mode = True
    apply_group_color_mode(scene, True)
    for curve in iter_hair_curves():
        set_preview_style(curve, hidden_states.get(curve.name, False))
    for obj_name, saved in ordinary_states.items():
        obj = bpy.data.objects.get(obj_name)
        if obj is not None:
            set_preview_style_object(obj, bool(saved["hidden"] or saved["hide_viewport"]))

    scene[_STATE_KEY] = json.dumps({
        "objects": states,
        "previous_mode": previous_mode,
        "active": active_name,
        "selected": selected_names,
        "widget": widget_was_active,
        "group_color": bool(scene.hair_pipe_group_color_mode),
        "ordinary_objects": ordinary_states,
    })
    scene["hair_pipe_display_mode_active"] = True
    return True


def exit_display_mode(context):
    scene = context.scene
    try:
        state = json.loads(scene.get(_STATE_KEY, "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        state = {}

    for curve in iter_hair_curves():
        hidden = curve_hidden(curve)
        saved_family = state.get("objects", {}).get(curve.name, {})
        for obj in hair_family(curve):
            saved = saved_family.get(obj.name, {})
            obj.display_type = saved.get("display_type", 'TEXTURED')
            obj.show_in_front = bool(saved.get("show_in_front", False))
            if "color" in saved:
                obj.color = tuple(saved["color"])
            if hasattr(obj, "show_transparent"):
                obj.show_transparent = bool(saved.get("show_transparent", False))
            if obj.type == 'MESH' and "materials" in saved:
                obj.data.materials.clear()
                for name in saved["materials"]:
                    obj.data.materials.append(bpy.data.materials.get(name) if name else None)
            obj.hide_viewport = bool(saved.get("hide_viewport", False))
            obj.hide_set(hidden)
        if "hair_pipe_display_hidden" in curve:
            del curve["hair_pipe_display_hidden"]

    for obj_name, saved in state.get("ordinary_objects", {}).items():
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            continue
        final_hidden = bool(obj.get("hair_pipe_display_hidden", saved.get("hidden", False)))
        obj.display_type = saved.get("display_type", 'TEXTURED')
        obj.show_in_front = bool(saved.get("show_in_front", False))
        obj.color = tuple(saved.get("color", tuple(obj.color)))
        if hasattr(obj, "show_transparent"):
            obj.show_transparent = bool(saved.get("show_transparent", False))
        if obj.type == 'MESH' and "materials" in saved:
            obj.data.materials.clear()
            for name in saved["materials"]:
                obj.data.materials.append(bpy.data.materials.get(name) if name else None)
        obj.hide_viewport = bool(saved.get("hide_viewport", False))
        obj.hide_set(final_hidden)
        if "hair_pipe_display_hidden" in obj:
            del obj["hair_pipe_display_hidden"]

    scene["hair_pipe_display_mode_active"] = False
    # V mode always owns the group-color preview switch. Leaving V restores
    # normal materials and leaves the sidebar toggle visibly disabled.
    if scene.hair_pipe_group_color_mode:
        scene.hair_pipe_group_color_mode = False
    if _STATE_KEY in scene:
        del scene[_STATE_KEY]
    for material in list(bpy.data.materials):
        if material.get("hair_pipe_display_preview_temp") or material.get("hair_pipe_display_object_preview_temp"):
            if material.users == 0:
                bpy.data.materials.remove(material)

    for obj in context.selected_objects:
        obj.select_set(False)
    for name in state.get("selected", []):
        obj = bpy.data.objects.get(name)
        if obj is not None and context.view_layer.objects.get(name) is not None:
            obj.select_set(True)
    active = bpy.data.objects.get(state.get("active", ""))
    if active is not None and context.view_layer.objects.get(active.name) is not None:
        context.view_layer.objects.active = active


def draw_display_help():
    context = bpy.context
    scene = getattr(context, "scene", None)
    if scene is None or not scene.get("hair_pipe_display_mode_active", False):
        return
    region = getattr(context, "region", None)
    if region is None:
        return
    font_id = 0
    blf.size(font_id, 20)
    blf.color(font_id, 0.88, 0.88, 0.92, 0.95)
    lines = (
        "显示编辑模式",
        "T  隐藏鼠标下对象",
        "F  显示鼠标下对象",
        "R  切换头发组",
        "H  隐藏全部",
        "Alt+H  显示全部",
        "V  退出模式",
    )
    x_margin = 90.0
    y_margin = 85.0
    y = y_margin
    for line in reversed(lines):
        width, height = blf.dimensions(font_id, line)
        blf.position(font_id, x_margin, y, 0)
        blf.draw(font_id, line)
        y += height + 4.0


def draw_mode_border():
    context = bpy.context
    region = getattr(context, "region", None)
    if region is None:
        return
    scene = getattr(context, "scene", None)
    wd = getattr(getattr(context, "window_manager", None), "hair_pipe_widget", None)
    if scene is not None and scene.get("hair_pipe_display_mode_active", False):
        color = (0.62, 0.18, 1.0, 1.0)
    elif wd is not None and wd.is_active:
        try:
            if not (
                wd.bound_area_pointer == str(context.area.as_pointer())
                and wd.bound_region_pointer == str(region.as_pointer())
            ):
                return
        except (AttributeError, ReferenceError):
            return
        color = (1.0, 0.32, 0.03, 1.0)
    else:
        return
    inset = 2.0
    width = max(1.0, region.width - inset)
    height = max(1.0, region.height - inset)
    vertices = (
        (inset, inset), (width, inset),
        (width, inset), (width, height),
        (width, height), (inset, height),
        (inset, height), (inset, inset),
    )
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(2.0)
    batch = batch_for_shader(shader, 'LINES', {"pos": vertices})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def ensure_border_handler():
    global _border_draw_handle
    if _border_draw_handle is None:
        _border_draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            draw_mode_border, (), 'WINDOW', 'POST_PIXEL'
        )
        bpy.types.SpaceView3D.draw_handler_add(draw_display_help, (), 'WINDOW', 'POST_PIXEL')


def remove_border_handler():
    global _border_draw_handle
    if _border_draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_border_draw_handle, 'WINDOW')
        _border_draw_handle = None


def redraw(context):
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


class HAIRPIPE_OT_display_edit_mode(bpy.types.Operator):
    bl_idname = "hair_pipe.display_edit_mode"
    bl_label = "显示编辑模式"
    bl_description = "快速隐藏或显示鼠标下的头发及头发组"
    bl_options = {'REGISTER'}

    def invoke(self, context, event):
        if is_display_mode(context):
            exit_display_mode(context)
            redraw(context)
            return {'FINISHED'}
        if not enter_display_mode(context):
            return {'CANCELLED'}
        self._trigger_released = False
        context.window_manager.modal_handler_add(self)
        context.area.header_text_set("显示编辑模式 | T 隐藏鼠标下对象 | F 显示鼠标下对象 | R 切换头发组 | H 隐藏全部 | Alt+H 显示全部 | V 退出")
        redraw(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if not is_display_mode(context):
            context.area.header_text_set(None)
            return {'FINISHED'}
        if context.mode != 'OBJECT':
            exit_display_mode(context)
            context.area.header_text_set(None)
            redraw(context)
            return {'PASS_THROUGH'}
        if event.type == 'V' and event.value == 'RELEASE':
            self._trigger_released = True
            return {'RUNNING_MODAL'}
        if event.type == 'V' and event.value == 'PRESS' and self._trigger_released:
            exit_display_mode(context)
            context.area.header_text_set(None)
            redraw(context)
            return {'FINISHED'}
        if event.type == 'C' and event.value == 'PRESS':
            exit_display_mode(context)
            context.area.header_text_set(None)
            result = bpy.ops.hair_pipe.widget_interact('INVOKE_DEFAULT')
            redraw(context)
            return {'FINISHED'} if 'CANCELLED' not in result else {'CANCELLED'}
        if event.type == 'TAB' and event.value == 'PRESS':
            exit_display_mode(context)
            context.area.header_text_set(None)
            redraw(context)
            return {'FINISHED'}
        if event.type == 'T' and event.value == 'PRESS':
            target = hovered_target_by_state(context, event, False)
            if target is not None:
                set_display_target_hidden(target, True)
                redraw(context)
            return {'RUNNING_MODAL'}
        if event.type == 'F' and event.value == 'PRESS':
            target = hovered_target_by_state(context, event, True)
            if target is not None:
                set_display_target_hidden(target, False)
                redraw(context)
            return {'RUNNING_MODAL'}
        if event.type == 'R' and event.value == 'PRESS':
            curve = hovered_hair(context, event)
            if curve is not None:
                apply_group_visibility(context, curve, not curve_hidden(curve))
                redraw(context)
            return {'RUNNING_MODAL'}
        if event.type == 'H' and event.value == 'PRESS' and event.alt:
            for curve in iter_hair_curves():
                set_preview_style(curve, False)
            for obj in context.view_layer.objects:
                if curve_from_hit_object(obj) is None:
                    set_preview_style_object(obj, False)
            redraw(context)
            return {'RUNNING_MODAL'}
        if event.type == 'H' and event.value == 'PRESS' and not event.alt:
            for curve in iter_hair_curves():
                set_preview_style(curve, True)
            for obj in context.view_layer.objects:
                if curve_from_hit_object(obj) is None:
                    set_preview_style_object(obj, True)
            redraw(context)
            return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}


class HAIRPIPE_OT_set_editor_mode(bpy.types.Operator):
    bl_idname = "hair_pipe.set_editor_mode"
    bl_label = "FiguHair 模式"

    mode: EnumProperty(items=(
        ('OBJECT', "物体模式", "返回物体模式"),
        ('CROSS_SECTION', "横截面编辑模式", "进入横截面编辑模式"),
        ('DISPLAY', "显示编辑模式", "进入显示编辑模式"),
    ))

    def execute(self, context):
        if self.mode == 'DISPLAY':
            return bpy.ops.hair_pipe.display_edit_mode('INVOKE_DEFAULT')
        if is_display_mode(context):
            exit_display_mode(context)
        curve = get_context_curve_object(context)
        if self.mode == 'OBJECT':
            wd = getattr(context.window_manager, "hair_pipe_widget", None)
            if wd is not None and wd.is_active:
                bpy.ops.hair_pipe.widget_stop()
            if context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            return {'FINISHED'}
        if curve is None:
            return {'CANCELLED'}
        if context.mode == 'OBJECT':
            bpy.ops.object.mode_set(mode='EDIT')
        return bpy.ops.hair_pipe.widget_interact('INVOKE_DEFAULT')


def draw_mode_header(self, context):
    curve = get_context_curve_object(context)
    if curve is None and not is_display_mode(context):
        return
    layout = self.layout
    if is_display_mode(context):
        text, icon = "显示编辑模式", 'HIDE_OFF'
    else:
        wd = getattr(context.window_manager, "hair_pipe_widget", None)
        if wd is not None and wd.is_active:
            text, icon = "横截面编辑模式", 'MOD_CURVE'
        else:
            text, icon = "FiguHair 模式", 'CURVE_DATA'
    layout.operator_menu_enum("hair_pipe.set_editor_mode", "mode", text=text, icon=icon)


classes = (HAIRPIPE_OT_display_edit_mode, HAIRPIPE_OT_set_editor_mode)
_addon_keymaps = []


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_HT_header.append(draw_mode_header)
    ensure_border_handler()
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon if wm is not None else None
    if kc is not None:
        km = kc.keymaps.get('3D View') or kc.keymaps.new(name='3D View', space_type='VIEW_3D')
        if not any(item.idname == 'hair_pipe.display_edit_mode' for item in km.keymap_items):
            kmi = km.keymap_items.new('hair_pipe.display_edit_mode', 'V', 'PRESS')
            _addon_keymaps.append((km, kmi))


def unregister():
    remove_border_handler()
    try:
        bpy.types.VIEW3D_HT_header.remove(draw_mode_header)
    except (AttributeError, ValueError):
        pass
    for km, kmi in reversed(_addon_keymaps):
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _addon_keymaps.clear()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
