import time
import bpy
from bpy.app.handlers import persistent
from .operators import (
    sync_point_settings,
    generate_pipe_mesh,
    sync_active_point_from_selection,
    is_curve_edit_mode,
    ensure_curve_defaults,
    get_pipe_object_for_curve,
    generated_pipe_vertices,
    redirect_pipe_selection,
    sync_selected_curve_visibility,
    get_curve_from_figuhair_root,
)


_is_redirecting_selection = False
_last_rebuild_time = 0.0
_last_rebuild_by_curve = {}
_rebuild_guard = False
_REBUILD_INTERVAL = 1.0 / 30.0
_visibility_guard = False
_root_visibility_states = {}


def update_mesh_data_in_place(mesh, verts, faces, smooth_shading):
    mesh.clear_geometry()
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    if smooth_shading:
        for poly in mesh.polygons:
            poly.use_smooth = True


def set_object_hidden(obj, hidden):
    if obj is None:
        return
    if not hidden:
        obj.hide_viewport = False
    try:
        obj.hide_set(hidden)
    except Exception:
        pass


def object_hidden(obj):
    return bool(obj is not None and obj.hide_get())


def sync_figuhair_visibility():
    global _visibility_guard
    if _visibility_guard:
        return

    _visibility_guard = True
    try:
        for root_obj in bpy.data.objects:
            if root_obj.type != 'EMPTY' or not root_obj.get("hair_pipe_root"):
                continue
            curve_obj = get_curve_from_figuhair_root(root_obj)
            if curve_obj is None:
                continue
            pipe_obj = get_pipe_object_for_curve(curve_obj)
            if pipe_obj is not None and pipe_obj.hide_select:
                pipe_obj.hide_select = False
            curve_overlay_hidden = bool(curve_obj.get("hair_pipe_widget_hide_curve_overlay", False))

            root_hidden = object_hidden(root_obj)
            curve_hidden = object_hidden(curve_obj)
            pipe_hidden = object_hidden(pipe_obj)

            previous = _root_visibility_states.get(root_obj.name)
            current_state = (root_hidden, curve_hidden, pipe_hidden)
            if previous is None:
                _root_visibility_states[root_obj.name] = current_state
                continue

            prev_root_hidden, prev_curve_hidden, prev_pipe_hidden = previous
            driven_hidden = None
            if root_hidden != prev_root_hidden:
                driven_hidden = root_hidden
            elif curve_hidden != prev_curve_hidden and not curve_overlay_hidden:
                driven_hidden = curve_hidden
            if driven_hidden is None and pipe_hidden != prev_pipe_hidden:
                driven_hidden = pipe_hidden

            if driven_hidden is not None:
                set_object_hidden(root_obj, driven_hidden)
                set_object_hidden(curve_obj, driven_hidden)
                set_object_hidden(pipe_obj, driven_hidden)
                current_state = (driven_hidden, driven_hidden, driven_hidden)

            if curve_overlay_hidden:
                current_state = (object_hidden(root_obj), object_hidden(curve_obj), object_hidden(pipe_obj))

            _root_visibility_states[root_obj.name] = current_state
    finally:
        _visibility_guard = False


def rebuild_existing_pipe(curve_obj, fast=False):
    global _last_rebuild_time, _rebuild_guard
    if _rebuild_guard:
        return

    settings = curve_obj.hair_pipe_settings
    if len(settings.point_settings) == 0:
        return

    pipe_obj = get_pipe_object_for_curve(curve_obj)
    if pipe_obj is None:
        return

    now = time.perf_counter()
    curve_key = curve_obj.as_pointer()
    if fast and now - _last_rebuild_by_curve.get(curve_key, 0.0) < _REBUILD_INTERVAL:
        return

    _rebuild_guard = True
    try:
        if not fast:
            ensure_curve_defaults(curve_obj)
            sync_point_settings(curve_obj)
        verts, faces = generate_pipe_mesh(curve_obj, settings)
        if verts is None:
            return
        verts = generated_pipe_vertices(verts, curve_obj)

        update_mesh_data_in_place(pipe_obj.data, verts, faces, settings.smooth_shading)
        _last_rebuild_time = time.perf_counter()
        _last_rebuild_by_curve[curve_key] = _last_rebuild_time
    finally:
        _rebuild_guard = False


@persistent
def selection_redirect_callback(scene):
    global _is_redirecting_selection
    if _is_redirecting_selection:
        return

    context = bpy.context
    active_obj = context.active_object
    if active_obj is None or active_obj.type != 'MESH':
        return

    _is_redirecting_selection = True
    try:
        redirect_pipe_selection(context, active_obj)
    finally:
        _is_redirecting_selection = False


@persistent
def update_pipe_callback(scene):
    """Depsgraph update handler for auto-updating pipes"""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    rebuilt = set()

    for update in depsgraph.updates:
        update_id = update.id
        curve_obj = None
        if hasattr(update, 'is_updated_geometry') and not update.is_updated_geometry:
            continue

        if isinstance(update_id, bpy.types.Object) and update_id.type == 'CURVE':
            curve_obj = update_id.original if hasattr(update_id, 'original') else update_id
        elif isinstance(update_id, bpy.types.Curve):
            curve_data = update_id.original if hasattr(update_id, 'original') else update_id
            for obj in bpy.data.objects:
                if obj.type == 'CURVE' and obj.data == curve_data:
                    curve_obj = obj
                    break

        if curve_obj is None or curve_obj.name in rebuilt:
            continue

        if is_curve_edit_mode(curve_obj):
            sync_active_point_from_selection(curve_obj)

        rebuild_existing_pipe(curve_obj, fast=True)
        rebuilt.add(curve_obj.name)


_handler_registered = False
_timer_registered = False


def selection_sync_timer():
    global _is_redirecting_selection
    try:
        obj = getattr(bpy.context, 'active_object', None)
        if obj is not None and obj.type == 'MESH' and not _is_redirecting_selection:
            # Selecting an object does not reliably emit a depsgraph update.
            # This timer is the authoritative fallback for clicks, including
            # Blender's ordinary duplicate operation on a FiguHair hierarchy.
            _is_redirecting_selection = True
            try:
                redirect_pipe_selection(bpy.context, obj)
            finally:
                _is_redirecting_selection = False
        elif obj is not None and obj.type == 'CURVE' and is_curve_edit_mode(obj):
            sync_active_point_from_selection(obj)
            if time.perf_counter() - _last_rebuild_time > 0.35:
                rebuild_existing_pipe(obj)
                screen = getattr(bpy.context, 'screen', None)
                if screen is not None:
                    for area in screen.areas:
                        if area.type == 'VIEW_3D':
                            area.tag_redraw()
        sync_selected_curve_visibility(bpy.context)
        sync_figuhair_visibility()
    except AttributeError:
        pass
    return 0.1


@persistent
def ensure_handlers_after_load(scene):
    register_handler()


def register_handler():
    global _handler_registered, _timer_registered

    if update_pipe_callback not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(update_pipe_callback)
    if selection_redirect_callback not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(selection_redirect_callback)
    if ensure_handlers_after_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(ensure_handlers_after_load)
    _handler_registered = True

    if not bpy.app.timers.is_registered(selection_sync_timer):
        bpy.app.timers.register(selection_sync_timer, persistent=True)
    _timer_registered = True


def unregister_handler():
    global _handler_registered, _timer_registered
    if _handler_registered:
        if update_pipe_callback in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(update_pipe_callback)
        if selection_redirect_callback in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(selection_redirect_callback)
        if ensure_handlers_after_load in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.remove(ensure_handlers_after_load)
        _handler_registered = False

    if bpy.app.timers.is_registered(selection_sync_timer):
        try:
            bpy.app.timers.unregister(selection_sync_timer)
        except ValueError:
            pass
    _timer_registered = False
