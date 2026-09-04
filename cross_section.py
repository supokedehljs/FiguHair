def add_cross_section_vertex_after(point_setting, idx, is_ghost=False):
    csv = point_setting.cross_section_verts
    n = len(csv)
    if n < 2:
        return False
    idx = max(0, min(idx, n - 1))
    idx_next = (idx + 1) % n
    v = csv.add()
    v.offset_x = (csv[idx].offset_x + csv[idx_next].offset_x) * 0.5
    v.offset_y = (csv[idx].offset_y + csv[idx_next].offset_y) * 0.5
    v.is_ghost = is_ghost
    target = idx + 1
    for i in range(len(csv) - 1, target, -1):
        csv.move(i, i - 1)
    point_setting.active_vert_index = target
    return True


def get_curve_spline_point_ranges(curve_obj):
    ranges = []
    offset = 0
    for spline in curve_obj.data.splines:
        count = len(spline.bezier_points) if spline.type == 'BEZIER' else len(spline.points)
        ranges.append((offset, offset + count))
        offset += count
    return ranges


def get_active_spline_point_range(curve_obj, settings):
    active_idx = min(max(0, settings.active_point_index), max(0, len(settings.point_settings) - 1))
    for start, end in get_curve_spline_point_ranges(curve_obj):
        if start <= active_idx < end:
            return start, end
    return 0, len(settings.point_settings)


def add_cross_section_vertex_after_all(settings, idx, point_range=None):
    start, end = point_range or (0, len(settings.point_settings))
    active_idx = min(settings.active_point_index, len(settings.point_settings) - 1)
    for point_idx in range(start, end):
        point_setting = settings.point_settings[point_idx]
        add_cross_section_vertex_after(point_setting, idx, point_idx != active_idx)


def remove_cross_section_vertex_all(settings, idx, point_range=None):
    start, end = point_range or (0, len(settings.point_settings))
    point_settings = settings.point_settings[start:end]
    if any(len(point_setting.cross_section_verts) <= 3 for point_setting in point_settings):
        return False
    for point_setting in point_settings:
        csv = point_setting.cross_section_verts
        remove_idx = max(0, min(idx, len(csv) - 1))
        csv.remove(remove_idx)
        point_setting.active_vert_index = min(remove_idx, len(csv) - 1)
    return True


def normalize_cross_section_topology(settings, curve_obj=None):
    if len(settings.point_settings) == 0:
        return
    if curve_obj is not None:
        ranges = get_curve_spline_point_ranges(curve_obj)
        for start, end in ranges:
            if start >= len(settings.point_settings):
                continue
            end = min(end, len(settings.point_settings))
            target_count = len(settings.point_settings[start].cross_section_verts)
            if target_count < 3:
                continue
            for point_idx in range(start, end):
                point_setting = settings.point_settings[point_idx]
                csv = point_setting.cross_section_verts
                while len(csv) < target_count and len(csv) >= 2:
                    insert_idx = max(0, len(csv) - 1)
                    add_cross_section_vertex_after(point_setting, insert_idx)
                while len(csv) > target_count and len(csv) > 3:
                    csv.remove(len(csv) - 1)
                if point_setting.active_vert_index >= len(csv):
                    point_setting.active_vert_index = len(csv) - 1
        return
    target_count = len(settings.point_settings[0].cross_section_verts)
    if target_count < 3:
        return
    for point_setting in settings.point_settings:
        csv = point_setting.cross_section_verts
        while len(csv) < target_count and len(csv) >= 2:
            insert_idx = max(0, len(csv) - 1)
            add_cross_section_vertex_after(point_setting, insert_idx)
        while len(csv) > target_count and len(csv) > 3:
            csv.remove(len(csv) - 1)
        if point_setting.active_vert_index >= len(csv):
            point_setting.active_vert_index = len(csv) - 1
