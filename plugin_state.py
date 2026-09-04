import bpy

_PLUGIN_ENABLED_GUARD = False

def is_plugin_enabled():
    for obj in bpy.data.objects:
        if obj.type == 'CURVE' and hasattr(obj, 'hair_pipe_settings'):
            try:
                return bool(obj.hair_pipe_settings.plugin_enabled)
            except Exception:
                pass
    return True

def apply_plugin_enabled_state(enabled):
    global _PLUGIN_ENABLED_GUARD
    if _PLUGIN_ENABLED_GUARD:
        return
    _PLUGIN_ENABLED_GUARD = True
    try:
        enabled = bool(enabled)
        for obj in bpy.data.objects:
            if obj.type == 'CURVE' and hasattr(obj, 'hair_pipe_settings'):
                try:
                    if obj.hair_pipe_settings.plugin_enabled != enabled:
                        obj.hair_pipe_settings.plugin_enabled = enabled
                except Exception:
                    pass
            if obj.type == 'MESH' and obj.get("hair_pipe_source_curve"):
                try:
                    obj.hide_select = enabled
                except Exception:
                    pass
        try:
            from .view_ops import sync_global_redirect_selection
            for obj in bpy.data.objects:
                if obj.type == 'CURVE' and hasattr(obj, 'hair_pipe_settings') and obj.hair_pipe_settings.plugin_enabled == enabled:
                    try:
                        sync_global_redirect_selection(obj)
                    except Exception:
                        pass
                    break
        except Exception:
            pass
    finally:
        _PLUGIN_ENABLED_GUARD = False
