import math
from mathutils import Vector
from .math_utils import catmull_rom_2d


def update_ghost_vertices(point_setting):
    verts = point_setting.cross_section_verts
    count = len(verts)
    if count < 3:
        return
    real_indices = [i for i, v in enumerate(verts) if not getattr(v, 'is_ghost', False)]
    real_count = len(real_indices)
    if real_count < 2:
        return

    for real_pos, start_idx in enumerate(real_indices):
        end_idx = real_indices[(real_pos + 1) % real_count]
        gap = (end_idx - start_idx - 1) % count
        if gap <= 0:
            continue

        prev_idx = real_indices[(real_pos - 1) % real_count]
        next_idx = real_indices[(real_pos + 2) % real_count]
        p0 = Vector((verts[prev_idx].offset_x, verts[prev_idx].offset_y))
        p1 = Vector((verts[start_idx].offset_x, verts[start_idx].offset_y))
        p2 = Vector((verts[end_idx].offset_x, verts[end_idx].offset_y))
        p3 = Vector((verts[next_idx].offset_x, verts[next_idx].offset_y))

        chord = p2 - p1
        chord_length = chord.length
        if chord_length < 1e-8:
            for step in range(1, gap + 1):
                ghost_idx = (start_idx + step) % count
                ghost_vert = verts[ghost_idx]
                if getattr(ghost_vert, 'is_ghost', False):
                    ghost_vert.offset_x = p1.x
                    ghost_vert.offset_y = p1.y
            continue

        chord_dir = chord / chord_length
        chord_normal = Vector((-chord_dir.y, chord_dir.x))
        adjacent_length = min((p1 - p0).length, (p3 - p2).length)
        close_ratio = chord_length / max(chord_length, adjacent_length, 1e-8)
        direct_chord = chord_length <= adjacent_length * 0.2
        max_offset = chord_length * min(0.25, 0.5 * close_ratio)

        for step in range(1, gap + 1):
            ghost_idx = (start_idx + step) % count
            ghost_vert = verts[ghost_idx]
            if not getattr(ghost_vert, 'is_ghost', False):
                continue

            t = step / (gap + 1)
            linear = p1 + chord * t
            if direct_chord:
                result = linear
            else:
                candidate = Vector(catmull_rom_2d(p0, p1, p2, p3, t))
                offset = (candidate - linear).dot(chord_normal)
                offset = max(-max_offset, min(max_offset, offset))
                result = linear + chord_normal * offset

            ghost_vert.offset_x = result.x
            ghost_vert.offset_y = result.y


def update_all_ghost_vertices(settings):
    for point_setting in settings.point_settings:
        update_ghost_vertices(point_setting)
