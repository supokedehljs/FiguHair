import time
import bpy
from bpy.app.handlers import persistent
from .curve_data import ensure_curve_defaults, is_curve_edit_mode
from .hair_lifecycle import (
    generated_pipe_vertices,
    get_curve_from_figuhair_root,
    get_pipe_object_for_curve,
    get_pipe_source_curve,
)
from .pipe_generation import generate_pipe_mesh
from .point_data import sync_point_settings, sync_active_point_from_selection
from .widget_cache import invalidate_pipe_mesh_cache
from .binding import apply_all_bindings, apply_bound_frames_to_generated_vertices, align_binding_ring_planes, repair_all_binding_planes
def _clear_all_existing_crease_once():
    try:
        from .pipe_ops import clear_boulder_crease
        import bpy as _bpy
        for obj in list(_bpy.data.objects):
            if getattr(obj, 'type', None) == 'MESH' and obj.get('hair_pipe_source_curve'):
                try:
                    clear_boulder_crease(obj)
                except Exception:
                    pass
    except Exception:
        pass
    return None


from .selection import (
    redirect_pipe_selection,
    sync_selected_curve_visibility,
)


_is_redirecting_selection = False
_last_rebuild_time = 0.0
_rebuild_guard = False
_visibility_guard = False
_root_visibility_states = {}
_last_selection_signature = None
_last_visibility_sync_time = 0.0
_pending_rebuilds = set()
_REBUILD_TIMER_INTERVAL = 0.025
_last_rebuild_queue_time = 0.0
_active_edit_signature = None


def _curve_edit_signature(curve_obj):
    """Cheap fingerprint for Curve Edit Mode changes.

    Blender may omit depsgraph notifications for some edit drags, so the
    active curve is checked every timer tick. The fingerprint prevents that
    fallback check from rebuilding the mesh when nothing actually changed.
    """
    try:
        values = []
        for spline in curve_obj.data.splines:
            points = spline.bezier_points if spline.type == 'BEZIER' else spline.points
            for point in points:
                co = point.co
                values.extend((round(float(co.x), 7), round(float(co.y), 7), round(float(co.z), 7)))
                if spline.type == 'BEZIER':
                    for handle_name in ('handle_left', 'handle_right'):
                        handle = getattr(point, handle_name)
                        values.extend((round(float(handle.x), 7), round(float(handle.y), 7), round(float(handle.z), 7)))
        return tuple(values)
    except (AttributeError, RuntimeError, ReferenceError):
        return None


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
    if not bool(getattr(settings, 'auto_update', True)) and not fast:
        return
    if len(settings.point_settings) == 0:
        return

    pipe_obj = get_pipe_object_for_curve(curve_obj)
    if pipe_obj is None:
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
        verts = apply_bound_frames_to_generated_vertices(curve_obj, verts)

        update_mesh_data_in_place(pipe_obj.data, verts, faces, settings.smooth_shading)
        curve_obj['hair_pipe_mesh_revision'] = int(curve_obj.get('hair_pipe_mesh_revision', 0)) + 1
        invalidate_pipe_mesh_cache(curve_obj)
        # 重建后若细分被意外移除则补回
        try:
            from .pipe_ops import ensure_pipe_subdivision_modifier
            if pipe_obj.modifiers.get("FiguHair Catmull-Clark") is None:
                ensure_pipe_subdivision_modifier(pipe_obj, bool(settings.default_subdiv), int(settings.subdivision_levels))
            else:
                # 同步显隐与层级
                m = pipe_obj.modifiers.get("FiguHair Catmull-Clark")
                try:
                    if not pipe_obj.get('hair_pipe_widget_basemesh_state'):
                        m.show_viewport = bool(settings.default_subdiv)
                    m.levels = int(settings.subdivision_levels)
                    m.render_levels = int(settings.subdivision_levels)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            from .pipe_ops import clear_boulder_crease
            clear_boulder_crease(pipe_obj)
        except Exception:
            pass
        _last_rebuild_time = time.perf_counter()
    finally:
        _rebuild_guard = False


@persistent
def selection_redirect_callback(scene):
    global _is_redirecting_selection
    if _is_redirecting_selection:
        return
    context = bpy.context
    # Box-select can add meshes to selected_objects without changing active_object.
    # Trigger redirect if any FiguHair mesh is selected, not only when active is mesh.
    has_mesh = False
    target = None
    for obj in getattr(context, 'selected_objects', ()):
        if obj is None or obj.type != 'MESH':
            continue
        curve = get_pipe_source_curve(obj)
        if curve is not None and hasattr(curve, 'hair_pipe_settings') and curve.hair_pipe_settings.plugin_enabled:
            has_mesh = True
            target = obj
            break
    if not has_mesh:
        return
    _is_redirecting_selection = True
    try:
        redirect_pipe_selection(context, target or context.active_object)
    finally:
        _is_redirecting_selection = False


@persistent
def update_pipe_callback(scene):
    """Queue changed curves; mesh generation is merged by the timer below."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    queued = set()

    for update in depsgraph.updates:
        update_id = update.id
        curve_obj = None

        if isinstance(update_id, bpy.types.Object) and update_id.type == 'CURVE':
            curve_obj = update_id.original if hasattr(update_id, 'original') else update_id
        elif isinstance(update_id, bpy.types.Curve):
            curve_data = update_id.original if hasattr(update_id, 'original') else update_id
            for obj in bpy.data.objects:
                if obj.type == 'CURVE' and obj.data == curve_data:
                    curve_obj = obj
                    break

        if curve_obj is None or curve_obj.name in queued:
            continue
        settings = getattr(curve_obj, 'hair_pipe_settings', None)
        if settings is None or not bool(getattr(settings, 'auto_update', True)):
            continue
        _pending_rebuilds.add(curve_obj.name)
        queued.add(curve_obj.name)


def rebuild_queue_timer():
    """Rebuild each changed curve once, then apply bindings once.

    The old order applied bindings before rebuilding the edited curve and then
    aligned the same slave again. That produced two alternating ring states
    during every mouse move. Keep the write order deterministic.
    """
    global _last_rebuild_queue_time
    global _active_edit_signature
    rebuilt = []
    active = getattr(bpy.context, 'active_object', None)
    active_name = getattr(active, 'name', None)

    # Blender does not reliably emit an object/data depsgraph update for
    # every Curve Edit Mode drag. Always service the active edit curve as well
    # as the queued set, otherwise the curve can appear disconnected from its
    # generated mesh.
    names = []
    if active is not None and active.type == 'CURVE' and is_curve_edit_mode(active):
        if bool(getattr(active.hair_pipe_settings, 'auto_update', True)):
            signature = _curve_edit_signature(active)
            if signature != _active_edit_signature:
                names.append(active_name)
                _active_edit_signature = signature
    names.extend(name for name in _pending_rebuilds if name not in names)
    for name in names:
        _pending_rebuilds.discard(name)
        curve_obj = bpy.data.objects.get(name)
        if curve_obj is None or curve_obj.type != 'CURVE':
            continue
        editing = is_curve_edit_mode(curve_obj)
        if editing:
            sync_active_point_from_selection(curve_obj)
        rebuild_existing_pipe(curve_obj, fast=editing)
        rebuilt.append(curve_obj)

    # Only after source geometry is current may dependent curves be updated.
    bound_changed = apply_all_bindings()
    for bound_curve in bound_changed:
        if bound_curve not in rebuilt:
            rebuild_existing_pipe(bound_curve, fast=True)
            rebuilt.append(bound_curve)
        invalidate_pipe_mesh_cache(bound_curve)

    for curve_obj in rebuilt:
        invalidate_pipe_mesh_cache(curve_obj)

    if rebuilt:
        _last_rebuild_queue_time = time.perf_counter()
        screen = getattr(bpy.context, 'screen', None)
        if screen is not None:
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    return _REBUILD_TIMER_INTERVAL


_handler_registered = False
_timer_registered = False


def _has_figuhair_mesh_selected(context):
    for obj in getattr(context, 'selected_objects', ()):
        if obj is None or obj.type != 'MESH':
            continue
        curve = get_pipe_source_curve(obj)
        if curve is not None and hasattr(curve, 'hair_pipe_settings') and curve.hair_pipe_settings.plugin_enabled:
            return True
    return False


def _first_figuhair_mesh_selected(context):
    for obj in getattr(context, 'selected_objects', ()):
        if obj is None or obj.type != 'MESH':
            continue
        curve = get_pipe_source_curve(obj)
        if curve is not None and hasattr(curve, 'hair_pipe_settings') and curve.hair_pipe_settings.plugin_enabled:
            return obj
    return None


def selection_sync_timer():
    global _is_redirecting_selection, _last_selection_signature, _last_visibility_sync_time
    try:
        context = bpy.context
        obj = getattr(context, 'active_object', None)
        selected_signature = tuple(sorted(item.name for item in context.selected_objects))
        selection_changed = selected_signature != _last_selection_signature
        if selection_changed:
            _last_selection_signature = selected_signature

        has_mesh = _has_figuhair_mesh_selected(context)
        if has_mesh and not _is_redirecting_selection:
            mesh_obj = _first_figuhair_mesh_selected(context) or obj
            _is_redirecting_selection = True
            try:
                redirect_pipe_selection(context, mesh_obj)
            finally:
                _is_redirecting_selection = False
        elif obj is not None and obj.type == 'CURVE' and is_curve_edit_mode(obj):
            # Selection changes do not alter generated geometry. Rebuilding here
            # duplicated the depsgraph queue and caused periodic viewport stalls.
            sync_active_point_from_selection(obj)
            screen = getattr(context, 'screen', None)
            if screen is not None:
                for area in screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()

        now = time.perf_counter()
        if selection_changed or now - _last_visibility_sync_time > 0.5:
            sync_selected_curve_visibility(context)
            sync_figuhair_visibility()
            _last_visibility_sync_time = now
    except AttributeError:
        pass
    return 0.25


def rebuild_all_figuhair_after_undo():
    """Restore generated-pipe links after Blender undo/redo restores IDs."""
    try:
        global _pending_rebuilds
        _pending_rebuilds.clear()
        curves = [obj for obj in bpy.data.objects
                   if obj.type == 'CURVE' and hasattr(obj, 'hair_pipe_settings')]
        # Restore source-driven control points before rebuilding slave meshes.
        apply_all_bindings()
        for curve in curves:
            settings = curve.hair_pipe_settings
            sync_point_settings(curve)
            pipe = get_pipe_object_for_curve(curve)
            if pipe is None:
                continue
            rebuild_existing_pipe(curve, fast=False)
            invalidate_pipe_mesh_cache(curve)
        apply_all_bindings()
        for curve in curves:
            if curve.type == 'CURVE':
                align_binding_ring_planes(curve)
                invalidate_pipe_mesh_cache(curve)
                try:
                    curve.update_tag()
                    curve.data.update_tag()
                except (AttributeError, RuntimeError):
                    pass
        screen = getattr(bpy.context, 'screen', None)
        if screen is not None:
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except (AttributeError, RuntimeError, ReferenceError):
        pass
    return None


@persistent
def undo_redo_post(_dummy):
    if not bpy.app.timers.is_registered(rebuild_all_figuhair_after_undo):
        bpy.app.timers.register(rebuild_all_figuhair_after_undo, first_interval=0.05)


def repair_bindings_after_load():
    try:
        changed = apply_all_bindings()
        repaired = repair_all_binding_planes()
        for obj in changed + repaired:
            invalidate_pipe_mesh_cache(obj)
        screen = getattr(bpy.context, 'screen', None)
        if screen is not None:
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except (AttributeError, RuntimeError):
        pass
    return None


@persistent
def ensure_handlers_after_load(scene):
    register_handler()
    if not bpy.app.timers.is_registered(repair_bindings_after_load):
        bpy.app.timers.register(repair_bindings_after_load, first_interval=0.5)


def register_handler():
    global _handler_registered, _timer_registered

    if update_pipe_callback not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(update_pipe_callback)
    if selection_redirect_callback not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(selection_redirect_callback)
    if ensure_handlers_after_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(ensure_handlers_after_load)
    if undo_redo_post not in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.append(undo_redo_post)
    if undo_redo_post not in bpy.app.handlers.redo_post:
        bpy.app.handlers.redo_post.append(undo_redo_post)
    _handler_registered = True

    if not bpy.app.timers.is_registered(selection_sync_timer):
        bpy.app.timers.register(selection_sync_timer, persistent=True)
    if not bpy.app.timers.is_registered(rebuild_queue_timer):
        bpy.app.timers.register(rebuild_queue_timer, persistent=True, first_interval=_REBUILD_TIMER_INTERVAL)
    try:
        if not bpy.app.timers.is_registered(_clear_all_existing_crease_once):
            bpy.app.timers.register(_clear_all_existing_crease_once, first_interval=0.5)
    except Exception:
        pass
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
        if undo_redo_post in bpy.app.handlers.undo_post:
            bpy.app.handlers.undo_post.remove(undo_redo_post)
        if undo_redo_post in bpy.app.handlers.redo_post:
            bpy.app.handlers.redo_post.remove(undo_redo_post)
        _handler_registered = False

    if bpy.app.timers.is_registered(selection_sync_timer):
        try:
            bpy.app.timers.unregister(selection_sync_timer)
        except ValueError:
            pass
    if bpy.app.timers.is_registered(rebuild_queue_timer):
        try:
            bpy.app.timers.unregister(rebuild_queue_timer)
        except ValueError:
            pass
    _pending_rebuilds.clear()
    _timer_registered = False
