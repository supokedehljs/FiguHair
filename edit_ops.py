import bpy
import math
from mathutils import Vector
from bpy.props import EnumProperty, FloatProperty
from .hair_lifecycle import get_context_curve_object, get_curve_from_figuhair_root, get_figuhair_root, get_pipe_object_for_curve, get_tail_object_for_curve, get_pipe_source_curve, get_tail_source_curve, get_hair_root_object, ensure_figuhair_root
from .curve_data import is_curve_edit_mode, get_selected_curve_point_indices, get_curve_points_data
from .point_data import sync_point_settings, _point_setting_to_data, _apply_point_setting_data, _curve_point_position_signatures, _store_curve_point_signatures
from .edit_utils import apply_edge_flow_to_target_indices, get_curve_point_by_global_index
from .sampling import get_bezier_control_tangent
from .ghost import update_all_ghost_vertices
from .math_utils import safe_normalized, lerp_angle
from .cross_section import normalize_cross_section_topology


class HAIRPIPE_OT_apply_edge_flow(bpy.types.Operator):
    """Rebuild selected curve control points from surrounding editable cross-sections"""
    bl_idname = "hair_pipe.apply_edge_flow"
    bl_label = "Apply Edge Flow"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        name="模式",
        description="How intermediate cross-sections are rebuilt",
        items=(
            ('LINEAR', "线性", "Even transition from first selected section to second selected section"),
            ('EASE', "缓入缓出", "Smoothstep transition"),
            ('SMOOTHER', "强平滑", "Smoother S-curve transition"),
            ('START', "偏向起点", "Stay closer to the first selected section for longer"),
            ('END', "偏向终点", "Move toward the second selected section earlier"),
            ('SINE', "正弦", "Soft sine based transition"),
        ),
        default='SMOOTHER',
    )
    power: FloatProperty(
        name="偏向强度",
        description="Controls bias strength for start/end weighted modes",
        default=2.0,
        min=0.1,
        max=8.0,
        precision=2,
    )
    blend: FloatProperty(
        name="重建强度",
        description="How strongly intermediate sections are replaced by the rebuilt transition",
        default=1.0,
        min=0.0,
        max=1.0,
        precision=3,
    )

    @classmethod
    def poll(cls, context):
        obj = get_context_curve_object(context)
        return obj is not None and obj.type == 'CURVE'

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "mode")
        if self.mode in {'START', 'END'}:
            layout.prop(self, "power")
        layout.prop(self, "blend")

    def execute(self, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            self.report({'ERROR'}, "Select a curve or its FiguHair preview mesh")
            return {'CANCELLED'}
        if not is_curve_edit_mode(curve_obj):
            self.report({'ERROR'}, "Enter curve Edit Mode and select one or more target control points")
            return {'CANCELLED'}

        sync_point_settings(curve_obj)
        settings = curve_obj.hair_pipe_settings
        selected = get_selected_curve_point_indices(curve_obj)
        target_indices = selected if selected else [settings.active_point_index]
        target_indices = [idx for idx in target_indices if 0 <= idx < len(settings.point_settings)]
        if not target_indices:
            self.report({'ERROR'}, "Select one or more target curve control points")
            return {'CANCELLED'}

        settings.edge_flow_mode = self.mode
        settings.edge_flow_power = self.power
        settings.edge_flow_blend = self.blend
        changed = apply_edge_flow_to_target_indices(
            curve_obj, settings, target_indices, self.mode, self.power, self.blend
        )
        if changed <= 0:
            self.report({'ERROR'}, "Selected targets need editable cross-sections before and after them")
            return {'CANCELLED'}
        settings.active_point_index = target_indices[-1]
        update_all_ghost_vertices(settings)
        self.report({'INFO'}, f"Rebuilt {changed} selected cross-sections")
        return {'FINISHED'}




def _reverse_cross_section_setting(point_setting, settings):
    data = _point_setting_to_data(point_setting)
    # Reversing a curve flips its tangent and therefore its binormal. Mirror
    # local Y and the signed rotation so the physical section stays unchanged.
    data["rotation"] = -data["rotation"]
    data["verts"] = [
        {
            "offset_x": vert["offset_x"],
            "offset_y": -vert["offset_y"],
            "is_ghost": vert.get("is_ghost", False),
        }
        for vert in reversed(data["verts"])
    ]
    _apply_point_setting_data(point_setting, data, settings)




def _reverse_spline_points(spline):
    if spline.type == 'BEZIER':
        saved = [
            (point.co.copy(), point.handle_left.copy(), point.handle_right.copy(), point.radius, point.tilt)
            for point in spline.bezier_points
        ]
        for point, (co, left, right, radius, tilt) in zip(spline.bezier_points, reversed(saved)):
            point.co = co
            point.handle_left = right
            point.handle_right = left
            point.radius = radius
            point.tilt = -tilt
    else:
        saved = [(point.co.copy(), point.radius, point.tilt) for point in spline.points]
        for point, (co, radius, tilt) in zip(spline.points, reversed(saved)):
            point.co = co
            point.radius = radius
            point.tilt = -tilt




class HAIRPIPE_OT_reverse_curve_direction(bpy.types.Operator):
    """Reverse the active hair curve without changing its visible sections"""
    bl_idname = "hair_pipe.reverse_curve_direction"
    bl_label = "翻转曲线方向"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        curve_obj = get_context_curve_object(context)
        return curve_obj is not None and is_curve_edit_mode(curve_obj)

    def execute(self, context):
        curve_obj = get_context_curve_object(context)
        if curve_obj is None:
            return {'CANCELLED'}
        try:
            curve_obj.update_from_editmode()
        except Exception:
            pass
        settings = curve_obj.hair_pipe_settings
        sync_point_settings(curve_obj)
        point_offset = 0
        for spline in curve_obj.data.splines:
            count = len(spline.bezier_points) if spline.type == 'BEZIER' else len(spline.points)
            section_settings = list(settings.point_settings[point_offset:point_offset + count])
            for point_setting in section_settings:
                _reverse_cross_section_setting(point_setting, settings)
            # RNA collection items cannot be reordered; exchange their data in place.
            section_data = [_point_setting_to_data(point_setting) for point_setting in reversed(section_settings)]
            for point_setting, data in zip(section_settings, section_data):
                _apply_point_setting_data(point_setting, data, settings)
            _reverse_spline_points(spline)
            point_offset += count

        settings.active_point_index = max(0, len(settings.point_settings) - 1 - settings.active_point_index)
        # Preserve the old world-space START reference as the new START anchor.
        splines_data = get_curve_points_data(curve_obj)
        if splines_data and len(splines_data[0]["points"]) > 1:
            first_spline = splines_data[0]
            first_points = first_spline["points"]
            if first_spline["type"] == 'BEZIER':
                new_start_tangent = get_bezier_control_tangent(first_points, 0, first_spline["cyclic"])
            else:
                new_start_tangent = safe_normalized(first_points[1]["co"] - first_points[0]["co"])
            curve_obj["hair_pipe_start_roll_anchor_tangent"] = tuple(new_start_tangent)
        curve_obj["hair_pipe_start_point_changed"] = False
        _store_curve_point_signatures(curve_obj, _curve_point_position_signatures(curve_obj))
        update_all_ghost_vertices(settings)
        try:
            curve_obj.update_from_editmode()
        except (AttributeError, RuntimeError):
            pass
        curve_obj.data.update_tag()
        curve_obj.update_tag()
        context.view_layer.update()
        self.report({'INFO'}, "曲线方向已翻转；横截面与滚转已保留")
        return {'FINISHED'}




class HAIRPIPE_OT_equalize_point_distance(bpy.types.Operator):
    """Redistribute selected curve points to be equally spaced along the curve"""
    bl_idname = "hair_pipe.equalize_point_distance"
    bl_label = "\u8ddd\u79bb\u5e73\u5747\u5316"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE':
            return False
        if obj.mode != 'EDIT':
            return False
        return True

    def execute(self, context):
        curve_obj = context.active_object
        curve_data = curve_obj.data
        for spline in curve_data.splines:
            if spline.type == 'BEZIER':
                points = spline.bezier_points
                selected_indices = [i for i, p in enumerate(points) if p.select_control_point]
            else:
                points = spline.points
                selected_indices = [i for i, p in enumerate(points) if p.select]
            if len(selected_indices) < 3:
                continue
            selected_indices.sort()
            first = selected_indices[0]
            last = selected_indices[-1]
            if last - first < 2:
                continue
            segment_lengths = []
            total_length = 0.0
            for i in range(first, last):
                if spline.type == 'BEZIER':
                    p0 = points[i].co
                    p1 = points[i + 1].co
                else:
                    p0 = points[i].co.xyz
                    p1 = points[i + 1].co.xyz
                seg_len = (p1 - p0).length
                segment_lengths.append(seg_len)
                total_length += seg_len
            if total_length < 1e-8:
                continue
            num_segments = last - first
            target_spacing = total_length / num_segments
            cumulative = [0.0]
            for seg_len in segment_lengths:
                cumulative.append(cumulative[-1] + seg_len)
            for idx in range(first + 1, last):
                target_dist = (idx - first) * target_spacing
                seg_idx = 0
                for s in range(len(cumulative) - 1):
                    if cumulative[s + 1] >= target_dist - 1e-10:
                        seg_idx = s
                        break
                else:
                    seg_idx = len(cumulative) - 2
                local_t = 0.0
                seg_len = cumulative[seg_idx + 1] - cumulative[seg_idx]
                if seg_len > 1e-10:
                    local_t = (target_dist - cumulative[seg_idx]) / seg_len
                local_t = max(0.0, min(1.0, local_t))
                real_idx_a = first + seg_idx
                real_idx_b = first + seg_idx + 1
                if spline.type == 'BEZIER':
                    co_a = points[real_idx_a].co
                    co_b = points[real_idx_b].co
                    new_co = co_a.lerp(co_b, local_t)
                    old_co = points[idx].co.copy()
                    offset = new_co - old_co
                    points[idx].co = new_co
                    points[idx].handle_left += offset
                    points[idx].handle_right += offset
                else:
                    co_a = points[real_idx_a].co.xyz
                    co_b = points[real_idx_b].co.xyz
                    new_co = co_a.lerp(co_b, local_t)
                    points[idx].co.x = new_co.x
                    points[idx].co.y = new_co.y
                    points[idx].co.z = new_co.z
        curve_data.update_tag()
        self.report({'INFO'}, "\u5df2\u5e73\u5747\u5316\u66f2\u7ebf\u70b9\u8ddd\u79bb")
        return {'FINISHED'}



classes = (
    HAIRPIPE_OT_apply_edge_flow,
    HAIRPIPE_OT_reverse_curve_direction,
    HAIRPIPE_OT_equalize_point_distance,
)
