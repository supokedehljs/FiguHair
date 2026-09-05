import time
from .pipe_generation import generate_pipe_mesh

_WIDGET_MESH_THROTTLE = 0.035
_last_widget_mesh_time = 0.0
_pipe_mesh_cache = {}


def invalidate_pipe_mesh_cache(obj=None):
    """Invalidate one object's preview cache, or all caches when obj is omitted."""
    if obj is None:
        _pipe_mesh_cache.clear()
        return
    _pipe_mesh_cache.pop(obj.as_pointer(), None)

def get_cached_pipe_mesh(obj):
    """Reuse generated geometry while the curve and cross-section data are unchanged."""
    if obj is None:
        return None, None
    settings = obj.hair_pipe_settings
    # The handler increments this only after a real curve/settings update. This avoids
    # rebuilding the full signature on every POST_PIXEL draw call.
    revision = int(obj.get('hair_pipe_mesh_revision', 0))
    # Curve edits and property updates are observed by the depsgraph handler. The
    # revision replaces a full scan of every hair point on every viewport redraw.
    signature = hash((revision, tuple(value for row in obj.matrix_world for value in row)))
    cache_key = obj.as_pointer()
    cached = _pipe_mesh_cache.get(cache_key)
    if cached is not None and cached[0] == signature:
        return cached[1]
    global _last_widget_mesh_time
    now = time.perf_counter()
    if cached is not None and now - _last_widget_mesh_time < _WIDGET_MESH_THROTTLE:
        return cached[1]
    try:
        mesh = generate_pipe_mesh(obj, settings)
    except Exception:
        mesh = (None, None)
    if len(_pipe_mesh_cache) > 64:
        oldest = next(iter(_pipe_mesh_cache))
        _pipe_mesh_cache.pop(oldest, None)
    _pipe_mesh_cache[cache_key] = (signature, mesh)
    _last_widget_mesh_time = now
    return mesh


def clear_pipe_mesh_cache():
    _pipe_mesh_cache.clear()


