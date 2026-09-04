import time
from .pipe_generation import generate_pipe_mesh

_WIDGET_MESH_THROTTLE = 0.035
_last_widget_mesh_time = 0.0
_pipe_mesh_cache = {}

def get_cached_pipe_mesh(obj):
    """Reuse generated geometry while the curve and cross-section data are unchanged."""
    if obj is None:
        return None, None
    settings = obj.hair_pipe_settings
    signature = [len(settings.point_settings), tuple(value for row in obj.matrix_world for value in row)]
    for spline in obj.data.splines:
        points = spline.bezier_points if spline.type == 'BEZIER' else spline.points
        signature.extend(
            (tuple(point.co), getattr(point, 'radius', 1.0), getattr(point, 'tilt', 0.0))
            for point in points
        )
    for point_setting in settings.point_settings:
        signature.extend((
            len(point_setting.cross_section_verts),
            point_setting.scale,
            point_setting.rotation,
            getattr(point_setting, 'bridge_offset', 0),
        ))
        signature.extend(
            (vertex.offset_x, vertex.offset_y, bool(getattr(vertex, 'is_ghost', False)))
            for vertex in point_setting.cross_section_verts
        )
    signature = hash(repr(signature))
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


