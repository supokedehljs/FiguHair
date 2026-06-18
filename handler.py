import bpy
from .operators import (
    sync_point_settings,
    generate_pipe_mesh,
    sync_active_point_from_selection,
    is_curve_edit_mode,
    ensure_curve_defaults,
    get_pipe_mesh_name,
    verts_to_world_space,
    configure_pipe_object,
    redirect_pipe_selection,
)


_is_redirecting_selection = False


def rebuild_existing_pipe(curve_obj):
    settings = curve_obj.hair_pipe_settings
    if not settings.auto_update:
        return
    if len(settings.point_settings) == 0:
        return

    mesh_name = get_pipe_mesh_name(curve_obj)
    pipe_obj = bpy.data.objects.get(mesh_name)
    if pipe_obj is None:
        return

    ensure_curve_defaults(curve_obj)
    sync_point_settings(curve_obj)
    verts, faces = generate_pipe_mesh(curve_obj, settings)
    if verts is None:
        return
    verts = verts_to_world_space(verts, curve_obj)

    mesh = bpy.data.meshes.new(mesh_name + "_temp")
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    if settings.smooth_shading:
        for poly in mesh.polygons:
            poly.use_smooth = True

    old_mesh = pipe_obj.data
    pipe_obj.data = mesh
    configure_pipe_object(pipe_obj, curve_obj)
    mesh.name = mesh_name
    if old_mesh and old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)


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


def update_pipe_callback(scene):
    """Depsgraph update handler for auto-updating pipes"""
    depsgraph = bpy.context.evaluated_depsgraph_get()

    for update in depsgraph.updates:
        obj = update.id
        if not isinstance(obj, bpy.types.Object):
            continue
        if obj.type != 'CURVE':
            continue

        original = obj.original if hasattr(obj, 'original') else obj
        if is_curve_edit_mode(original):
            sync_active_point_from_selection(original)
        rebuild_existing_pipe(original)


_handler_registered = False
_timer_registered = False


def selection_sync_timer():
    obj = bpy.context.active_object
    if obj is not None and obj.type == 'CURVE' and is_curve_edit_mode(obj):
        sync_active_point_from_selection(obj)
        rebuild_existing_pipe(obj)
        screen = bpy.context.screen
        if screen is not None:
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    return 0.2


def register_handler():
    global _handler_registered, _timer_registered
    if not _handler_registered:
        bpy.app.handlers.depsgraph_update_post.append(update_pipe_callback)
        bpy.app.handlers.depsgraph_update_post.append(selection_redirect_callback)
        _handler_registered = True
    if not _timer_registered:
        bpy.app.timers.register(selection_sync_timer, persistent=True)
        _timer_registered = True


def unregister_handler():
    global _handler_registered, _timer_registered
    if _handler_registered:
        if update_pipe_callback in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(update_pipe_callback)
        if selection_redirect_callback in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(selection_redirect_callback)
        _handler_registered = False
    if _timer_registered:
        try:
            bpy.app.timers.unregister(selection_sync_timer)
        except ValueError:
            pass
        _timer_registered = False
