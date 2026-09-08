import bpy
from .hair_lifecycle import get_pipe_source_curve


def ensure_selected_curve_visible(curve_obj):
    """Legacy compatibility: selection highlighting is draw-overlay only."""
    return curve_obj is not None and curve_obj.type == 'CURVE'


def sync_selected_curve_visibility(context):
    """Selection is rendered by the 3D overlay; do not mutate curve objects."""
    return False


def force_sync_selected_curve_visibility(context):
    return False


def _collect_pipe_selection_from_context(context, active_curve):
    selected_curves = []
    selected_meshes = []
    seen = set()
    for obj in list(getattr(context, 'selected_objects', [])):
        if obj is None or getattr(obj, 'name', None) in seen:
            continue
        if obj.type == 'CURVE' and hasattr(obj, 'hair_pipe_settings'):
            selected_curves.append(obj)
            seen.add(obj.name)
        elif obj.type == 'MESH':
            source_curve = get_pipe_source_curve(obj)
            if (
                source_curve is not None
                and getattr(source_curve, 'hair_pipe_settings', None)
                and source_curve.hair_pipe_settings.plugin_enabled
            ):
                selected_meshes.append(obj)
                if source_curve.name not in seen:
                    selected_curves.append(source_curve)
                    seen.add(source_curve.name)
                seen.add(obj.name)
    if active_curve is not None and active_curve.name not in seen:
        selected_curves.append(active_curve)
    # OBJECT mode box-select already updated selected_objects when this timer/handler fires,
    # so the active object alone is not sufficient - include every selected mesh that belongs to FiguHair.
    # The above loop already gathered them via selected_objects; keep active_curve as fallback for click-only.
    return selected_curves, selected_meshes


def redirect_pipe_selection(context, pipe_obj=None):
    pipe_obj = pipe_obj or getattr(context, 'active_object', None)
    if pipe_obj is None:
        return False
    active_curve = get_pipe_source_curve(pipe_obj)
    if active_curve is None:
        return False
    if not getattr(active_curve, 'hair_pipe_settings', None) or not active_curve.hair_pipe_settings.plugin_enabled:
        return False
    if context.view_layer.objects.get(active_curve.name) is None:
        return False
    if getattr(context, 'mode', 'OBJECT') != 'OBJECT':
        return False
    selected_curves, selected_meshes = _collect_pipe_selection_from_context(context, active_curve)
    # Also handle the case where the user box-selected multiple pipes but none became active_object
    # (active_object may be an unrelated non-FiguHair object after the selection op).
    # In that case selected_curves already contains all hair curves from selected_objects.
    # If active_curve came from pipe_obj but pipe_obj is not in selected_meshes, keep it above;
    # otherwise we still cover box-select-only selections.
    selected_curves = [c for c in dict.fromkeys(selected_curves) if context.view_layer.objects.get(c.name) is not None]
    if not selected_curves:
        return False
    for mesh_obj in selected_meshes:
        try:
            mesh_obj.select_set(False)
        except Exception:
            pass
    # For box-select, also deselect any additional FiguHair meshes that were selected but not yet collected
    # (e.g. when hide_select is momentarily disabled by other code).
    for obj in list(getattr(context, 'selected_objects', [])):
        if obj.type == 'MESH' and obj not in selected_meshes:
            src = get_pipe_source_curve(obj)
            if src is not None and getattr(src, 'hair_pipe_settings', None) and src.hair_pipe_settings.plugin_enabled:
                try:
                    obj.select_set(False)
                except Exception:
                    pass
    for curve in selected_curves:
        try:
            curve.hide_set(False)
            curve.select_set(True)
        except Exception:
            pass
    # Selection visibility is synchronized by the selection timer only when
    # the actual selection signature changes. Do not rescan/write all curves here.
    # Prefer the curve that was under the click/box as active, fallback to first selected hair curve.
    try:
        if active_curve is not None and active_curve.name in {c.name for c in selected_curves}:
            context.view_layer.objects.active = active_curve
        elif selected_curves:
            context.view_layer.objects.active = selected_curves[0]
    except Exception:
        pass
    return True


def force_sync_selected_curve_visibility(context):
    """Reconcile front-display state after an editor restores object properties."""
    global _last_visible_selection
    _last_visible_selection = set()
    return sync_selected_curve_visibility(context)
