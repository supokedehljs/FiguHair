import math
from .math_utils import catmull_rom_value


def ease_value(v0, v1, t):
    t = max(0.0, min(1.0, t))
    eased_t = t * t * (3.0 - 2.0 * t)
    return v0 * (1.0 - eased_t) + v1 * eased_t


def lerp_value(v0, v1, t):
    return v0 * (1.0 - t) + v1 * t


def mix_value(a, b, factor):
    factor = max(0.0, min(1.0, factor))
    return a * (1.0 - factor) + b * factor


def monotone_tangent(prev_value, value, next_value):
    left = value - prev_value
    right = next_value - value
    if left * right <= 0.0:
        return 0.0
    tangent = 0.5 * (left + right)
    limit = 2.0 * min(abs(left), abs(right))
    return max(-limit, min(limit, tangent))


def hermite_value(v0, v1, m0, m1, t):
    t2 = t * t
    t3 = t2 * t
    h00 = 2.0 * t3 - 3.0 * t2 + 1.0
    h10 = t3 - 2.0 * t2 + t
    h01 = -2.0 * t3 + 3.0 * t2
    h11 = t3 - t2
    return h00 * v0 + h10 * m0 + h01 * v1 + h11 * m1


def interpolate_section_value(prev_value, value0, value1, next_value, t, mode, strength):
    t = max(0.0, min(1.0, t))
    linear = lerp_value(value0, value1, t)
    if mode == 'LINEAR':
        return linear
    if mode == 'EASE':
        return mix_value(linear, ease_value(value0, value1, t), strength)
    m0 = monotone_tangent(prev_value, value0, value1)
    m1 = monotone_tangent(value0, value1, next_value)
    monotone = hermite_value(value0, value1, m0, m1, t)
    if mode == 'MONOTONE':
        return mix_value(linear, monotone, strength)
    catmull = catmull_rom_value(prev_value, value0, value1, next_value, t)
    if mode == 'CATMULL':
        return mix_value(linear, catmull, strength)
    if mode == 'BLEND':
        return mix_value(monotone, catmull, strength)
    return monotone
