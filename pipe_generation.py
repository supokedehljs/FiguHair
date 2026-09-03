from .operators import generate_pipe_mesh as _legacy_generate_pipe_mesh


def generate_pipe_mesh(curve_obj, settings):
    return _legacy_generate_pipe_mesh(curve_obj, settings)
