import math
from mathutils import Vector


def safe_normalized(vector, fallback=None):
    vector = Vector(vector)
    length = vector.length
    if length < 1e-8:
        if fallback is not None:
            fallback = Vector(fallback)
            if fallback.length > 1e-8:
                return fallback.normalized()
        return Vector((0.0, 0.0, 1.0))
    return vector / length


def get_cross_section_frame(tangent):
    tangent = safe_normalized(tangent)
    up = Vector((0.0, 0.0, 1.0))
    if abs(tangent.dot(up)) > 0.999:
        up = Vector((0.0, 1.0, 0.0))
    normal = tangent.cross(up)
    if normal.length < 1e-8:
        normal = Vector((1.0, 0.0, 0.0))
    else:
        normal.normalize()
    binormal = tangent.cross(normal).normalized()
    return normal, binormal


def catmull_rom_vector(p0, p1, p2, p3, t):
    t2 = t * t
    t3 = t2 * t
    return 0.5 * (
        (2.0 * p1)
        + (-p0 + p2) * t
        + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2
        + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3
    )


def catmull_rom_tangent_vector(p0, p1, p2, p3, t):
    t2 = t * t
    p0 = Vector(p0)
    p1 = Vector(p1)
    p2 = Vector(p2)
    p3 = Vector(p3)
    return 0.5 * (
        (-p0 + p2)
        + 2.0 * (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t
        + 3.0 * (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t2
    )


def catmull_rom_value(v0, v1, v2, v3, t):
    t2 = t * t
    t3 = t2 * t
    return 0.5 * ((2.0 * v1) + (-v0 + v2) * t + (2.0 * v0 - 5.0 * v1 + 4.0 * v2 - v3) * t2 + (-v0 + 3.0 * v1 - 3.0 * v2 + v3) * t3)


def catmull_rom_2d(p0, p1, p2, p3, t):
    x = catmull_rom_value(p0.x, p1.x, p2.x, p3.x, t)
    y = catmull_rom_value(p0.y, p1.y, p2.y, p3.y, t)
    return Vector((x, y))


def lerp_angle(a, b, t):
    delta = (b - a + 180.0) % 360.0 - 180.0
    return a + delta * t


def lerp_radians(a, b, t):
    return math.radians(lerp_angle(math.degrees(a), math.degrees(b), t))
