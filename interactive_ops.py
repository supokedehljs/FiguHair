import bpy
import gpu
import math
from mathutils import Vector
from gpu_extras.batch import batch_for_shader
from bpy.props import IntProperty, FloatProperty, BoolProperty, StringProperty
from bpy_extras import view3d_utils
from .hair_lifecycle import get_next_figuhair_base_name, ensure_figuhair_root, get_context_curve_object
from .curve_data import ensure_curve_defaults, is_curve_edit_mode, get_selected_curve_point_indices
from .point_data import sync_point_settings, _point_setting_to_data, _apply_point_setting_data
from .ghost import update_ghost_vertices, update_all_ghost_vertices


class HAIRPIPE_OT_cross_section_spread(bpy.types.Operator):
    """Spread the active cross-section along neighboring curve points with the wheel"""
    bl_idname = "hair_pipe.cross_section_spread"
    bl_label = "横截面传递"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    _curve_obj = None
    _source_idx = -1
    _lower = -1
    _upper = -1
    _original_data = None
    _source_data = None
    _original_selected_indices = None

    def update_range_highlight(self):
        global_idx = 0
        for spline in self._curve_obj.data.splines:
            points = spline.bezier_points if spline.type == 'BEZIER' else spline.points
            for point in points:
                selected = self._lower <= global_idx <= self._upper
                if spline.type == 'BEZIER':
                    point.select_control_point = selected
                    point.select_left_handle = selected
                    point.select_right_handle = selected
                else:
                    point.select = selected
                global_idx += 1

    @classmethod
    def poll(cls, context):
        curve_obj = get_context_curve_object(context)
        widget = getattr(context.window_manager, "hair_pipe_widget", None)
        return (
            curve_obj is not None
            and is_curve_edit_mode(curve_obj)
            and widget is not None
            and widget.is_active
            and len(curve_obj.hair_pipe_settings.point_settings) > 0
        )

    def apply_range(self, old_lower, old_upper):
        settings = self._curve_obj.hair_pipe_settings
        changed_indices = set(range(min(old_lower, self._lower), max(old_upper, self._upper) + 1))
        for idx in changed_indices:
            data = self._source_data if self._lower <= idx <= self._upper else self._original_data[idx]
            _apply_point_setting_data(settings.point_settings[idx], data, settings)
        for idx in changed_indices:
            update_ghost_vertices(settings.point_settings[idx])
        self._curve_obj.data.update_tag()
        self._curve_obj.update_tag()

    def finish(self, context, cancelled=False):
        if cancelled:
            settings = self._curve_obj.hair_pipe_settings
            for idx, data in enumerate(self._original_data):
                _apply_point_setting_data(settings.point_settings[idx], data, settings)
            update_all_ghost_vertices(settings)
        select_indices = self._original_selected_indices or [self._source_idx]
        global_idx = 0
        for spline in self._curve_obj.data.splines:
            points = spline.bezier_points if spline.type == 'BEZIER' else spline.points
            for point in points:
                selected = global_idx in select_indices
                if spline.type == 'BEZIER':
                    point.select_control_point = selected
                    point.select_left_handle = selected
                    point.select_right_handle = selected
                else:
                    point.select = selected
                global_idx += 1
        self._curve_obj.data.update_tag()
        self._curve_obj.update_tag()
        context.view_layer.update()
        if not cancelled:
            bpy.ops.ed.undo_push(message="横截面传递")
        context.area.header_text_set(None)
        context.window.cursor_modal_restore()
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        return {'CANCELLED'} if cancelled else {'FINISHED'}

    def invoke(self, context, event):
        self._curve_obj = get_context_curve_object(context)
        try:
            from .widget_operator import push_widget_undo
            push_widget_undo(context, "横截面传递")
        except (ImportError, AttributeError):
            pass
        settings = self._curve_obj.hair_pipe_settings
        self._source_idx = max(0, min(settings.active_point_index, len(settings.point_settings) - 1))
        self._lower = self._source_idx
        self._upper = self._source_idx
        self._original_data = [_point_setting_to_data(point_setting) for point_setting in settings.point_settings]
        self._source_data = _point_setting_to_data(settings.point_settings[self._source_idx])
        self._original_selected_indices = get_selected_curve_point_indices(self._curve_obj)
        context.window_manager.modal_handler_add(self)
        context.window.cursor_modal_set('SCROLL_XY')
        context.area.header_text_set("横截面传递：滚轮向两侧复制 | 左键/Enter 确认 | 右键/Esc 取消")
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            return self.finish(context, cancelled=True)
        if event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            return self.finish(context)
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            old_lower, old_upper = self._lower, self._upper
            last_idx = len(self._original_data) - 1
            if event.type == 'WHEELUPMOUSE':
                if self._upper > self._source_idx:
                    self._upper -= 1
                elif self._lower > 0:
                    self._lower -= 1
            else:
                if self._lower < self._source_idx:
                    self._lower += 1
                elif self._upper < last_idx:
                    self._upper += 1
            self.apply_range(old_lower, old_upper)
            self.update_range_highlight()
            context.area.header_text_set(
                f"横截面传递：{self._lower + 1}—{self._upper + 1}（来源 {self._source_idx + 1}） | 左键确认 | Esc 取消"
            )
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}




class HAIRPIPE_OT_draw_hair_curve(bpy.types.Operator):
    """Drag from a surface point to create a FiguHair curve"""
    bl_idname = "hair_pipe.draw_hair_curve"
    bl_label = "新建头发曲线"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    _start_world = None
    _start_normal = None
    _preview_curve = None
    _preview_mesh = None
    _points = None
    _radius = 0.012
    _draw_handle = None
    _hover_world = None

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.area is not None and context.area.type == 'VIEW_3D'

    def draw_path_preview(self, context):
        if not self._points:
            return
        region = context.region
        region_data = context.region_data
        if region is None or region_data is None:
            return
        world_points = list(self._points)
        if self._hover_world is not None:
            world_points.append(self._hover_world)
        screen_points = [
            view3d_utils.location_3d_to_region_2d(region, region_data, point)
            for point in world_points
        ]
        screen_points = [(point.x, point.y) for point in screen_points if point is not None]
        if not screen_points:
            return
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        if len(screen_points) >= 2:
            lines = []
            for idx in range(len(screen_points) - 1):
                lines.extend((screen_points[idx], screen_points[idx + 1]))
            gpu.state.line_width_set(2.0)
            batch = batch_for_shader(shader, 'LINES', {"pos": lines})
            shader.bind()
            shader.uniform_float("color", (1.0, 0.55, 0.05, 1.0))
            batch.draw(shader)
        gpu.state.point_size_set(7.0)
        batch = batch_for_shader(shader, 'POINTS', {"pos": screen_points})
        shader.bind()
        shader.uniform_float("color", (1.0, 0.85, 0.2, 1.0))
        batch.draw(shader)
        gpu.state.point_size_set(1.0)
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')

    def raycast_surface(self, context, event):
        region = context.region
        region_data = context.region_data
        coord = (event.mouse_region_x, event.mouse_region_y)
        origin = view3d_utils.region_2d_to_origin_3d(region, region_data, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, region_data, coord)
        hit, location, normal, _face_index, hit_obj, _matrix = context.scene.ray_cast(
            context.view_layer.depsgraph, origin, direction
        )
        if hit and hit_obj is not None and hit_obj.type == 'MESH':
            return location.copy(), normal.normalized()
        return None, None

    def get_drag_end(self, context, event):
        end_world, _normal = self.raycast_surface(context, event)
        if end_world is not None:
            return end_world
        if self._start_world is None:
            return None
        region = context.region
        region_data = context.region_data
        coord = (event.mouse_region_x, event.mouse_region_y)
        origin = view3d_utils.region_2d_to_origin_3d(region, region_data, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, region_data, coord)
        plane_normal = region_data.view_rotation @ Vector((0.0, 0.0, 1.0))
        denominator = direction.dot(plane_normal)
        if abs(denominator) <= 1e-8:
            return None
        return origin + direction * ((self._start_world - origin).dot(plane_normal) / denominator)

    def update_curve_points(self, curve_obj, hover_world=None):
        points = list(self._points or [])
        if hover_world is not None:
            points.append(hover_world)
        if not points:
            return
        spline = curve_obj.data.splines[0]
        while len(spline.points) < len(points):
            spline.points.add(1)
        for index, point in enumerate(spline.points):
            source = points[min(index, len(points) - 1)]
            point.co = (*source, 1.0)
        curve_obj.data.bevel_depth = max(0.001, self._radius)
        curve_obj.data.update_tag()

    def create_preview_curve(self, context, hover_world):
        points = list(self._points or []) + [hover_world]
        curve_data = bpy.data.curves.new("FiguHair Draw Preview", 'CURVE')
        curve_data.dimensions = '3D'
        curve_data.resolution_u = 1
        curve_data.bevel_depth = 0.0
        spline = curve_data.splines.new('POLY')
        spline.points.add(len(points) - 1)
        for point, world_co in zip(spline.points, points):
            point.co = (*world_co, 1.0)
        curve_obj = bpy.data.objects.new("FiguHair Draw Preview", curve_data)
        curve_obj["hair_pipe_draw_preview"] = True
        curve_obj.display_type = 'WIRE'
        curve_obj.color = (1.0, 0.55, 0.05, 1.0)
        context.collection.objects.link(curve_obj)
        return curve_obj

    def create_curve(self, context, end_world=None, preview=False):
        points = list(self._points or [])
        if end_world is not None:
            points.append(end_world)
        if len(points) < 2:
            return None
        base_name = get_next_figuhair_base_name()
        suffix = " Preview" if preview else " Curve"
        curve_data = bpy.data.curves.new(base_name + suffix, 'CURVE')
        curve_data.dimensions = '3D'
        curve_data.resolution_u = 16
        curve_data.render_resolution_u = 16
        spline = curve_data.splines.new('NURBS')
        spline.points.add(len(points) - 1)
        for point, world_co in zip(spline.points, points):
            point.co = (*world_co, 1.0)
        spline.order_u = min(3, len(points))
        spline.use_endpoint_u = True
        curve_obj = bpy.data.objects.new(base_name + suffix, curve_data)
        curve_obj["hair_pipe_base_name"] = base_name
        if preview:
            curve_obj["hair_pipe_draw_preview"] = True
        context.collection.objects.link(curve_obj)
        ensure_figuhair_root(curve_obj)
        ensure_curve_defaults(curve_obj)
        sync_point_settings(curve_obj)
        curve_obj.hair_pipe_settings.plugin_enabled = True
        curve_obj.hair_pipe_settings.pipe_resolution = 0
        curve_obj.hair_pipe_settings.default_radius = self._radius
        for point_setting in curve_obj.hair_pipe_settings.point_settings:
                for vertex_idx, vertex in enumerate(point_setting.cross_section_verts):
                    angle = math.tau * vertex_idx / max(1, len(point_setting.cross_section_verts))
                    vertex.offset_x = math.cos(angle) * self._radius
                    vertex.offset_y = math.sin(angle) * self._radius * 0.55
        if preview:
            curve_data.bevel_depth = max(0.001, self._radius)
            curve_data.bevel_resolution = 0
            curve_data.resolution_u = 1
            curve_data.render_resolution_u = 1
            curve_data.resolution_v = 0
            curve_obj.display_type = 'SOLID'
            curve_obj.show_wire = True
            curve_obj.show_all_edges = True
        for obj in context.selected_objects:
            obj.select_set(False)
        curve_obj.select_set(not preview)
        if not preview:
            try:
                context.view_layer.objects.active = curve_obj
            except Exception:
                pass
        if not preview:
            # 模态内不可调 bpy.ops（poll 需特定上下文）→ 直调生成逻辑，与 HAIRPIPE_OT_generate_pipe 一致
            try:
                from .pipe_generation import generate_pipe_mesh as _gen_pipe_mesh
                from .hair_lifecycle import generated_pipe_vertices as _gen_pipe_verts, get_pipe_mesh_name as _get_pipe_name, get_pipe_object_for_curve as _get_pipe_obj, set_generated_object_transform as _set_gen_xform
                from .pipe_ops import configure_pipe_object as _configure_pipe
                settings_for_pipe = curve_obj.hair_pipe_settings
                verts, faces = _gen_pipe_mesh(curve_obj, settings_for_pipe)
                if verts is not None:
                    verts = _gen_pipe_verts(verts, curve_obj)
                    mesh_name = _get_pipe_name(curve_obj)
                    existing_obj = _get_pipe_obj(curve_obj)
                    if existing_obj is not None:
                        mesh = existing_obj.data
                        try:
                            mesh.clear_geometry()
                        except Exception:
                            pass
                        mesh.from_pydata(verts, [], faces)
                        mesh.update()
                        pipe_obj = existing_obj
                    else:
                        mesh = bpy.data.meshes.new(mesh_name)
                        mesh.from_pydata(verts, [], faces)
                        mesh.update()
                        pipe_obj = bpy.data.objects.new(mesh_name, mesh)
                        try:
                            context.collection.objects.link(pipe_obj)
                        except Exception:
                            try:
                                context.scene.collection.objects.link(pipe_obj)
                            except Exception:
                                bpy.context.scene.collection.objects.link(pipe_obj)
                    if getattr(settings_for_pipe, 'smooth_shading', True):
                        try:
                            for poly in mesh.polygons:
                                poly.use_smooth = True
                        except Exception:
                            pass
                    try:
                        _configure_pipe(pipe_obj, curve_obj)
                    except Exception as _e:
                        print(f"[FiguHair] interactive configure failed: {_e}")
                        try:
                            _set_gen_xform(pipe_obj, curve_obj)
                        except Exception:
                            pass
                    # 模态内 _configure 可能被异常吞掉，二次保底确保细分一定存在
                    try:
                        from .pipe_ops import ensure_pipe_subdivision_modifier as _ensure_subd
                        _ensure_subd(pipe_obj, bool(settings_for_pipe.default_subdiv), int(settings_for_pipe.subdivision_levels))
                        try:
                            pipe_obj.update_tag()
                        except Exception:
                            pass
                    except Exception:
                        pass
                    try:
                        context.view_layer.update()
                    except Exception:
                        pass
            except Exception as exc:
                print(f"[FiguHair] draw: 直接生成管线失败: {exc}")
                import traceback as _tb
                _tb.print_exc()
                # 曲线已创建，仍视为成功，避免 modal 因 poll 失败整体取消
                pass
        return curve_obj

    def cleanup_preview(self):
        if self._draw_handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handle, 'WINDOW')
            self._draw_handle = None
        preview_curve = self._preview_curve
        preview_mesh = self._preview_mesh
        self._preview_curve = None
        self._preview_mesh = None
        if preview_mesh is not None and preview_mesh.name in bpy.data.objects:
            mesh_data = preview_mesh.data
            bpy.data.objects.remove(preview_mesh, do_unlink=True)
            if mesh_data is not None and mesh_data.users == 0:
                bpy.data.meshes.remove(mesh_data)
        if preview_curve is not None and preview_curve.name in bpy.data.objects:
            curve_data = preview_curve.data
            bpy.data.objects.remove(preview_curve, do_unlink=True)
            if curve_data is not None and curve_data.users == 0:
                bpy.data.curves.remove(curve_data)

    def invoke(self, context, event):
        if context.area is None or context.area.type != 'VIEW_3D':
            return {'CANCELLED'}
        self._start_world = None
        self._start_normal = None
        self._preview_curve = None
        self._preview_mesh = None
        self._points = []
        self._radius = 0.012
        self._hover_world = None
        self._draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_path_preview, (context,), 'WINDOW', 'POST_PIXEL'
        )
        context.window_manager.modal_handler_add(self)
        context.window.cursor_modal_set('CROSSHAIR')
        context.area.header_text_set("左键逐点添加 | 滚轮调整横截面宽度 | 空格/Enter 确认 | 右键/Esc 取消")
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self.cleanup_preview()
            context.window.cursor_modal_restore()
            context.area.header_text_set(None)
            return {'CANCELLED'}
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.value == 'PRESS':
            factor = 1.12 if event.type == 'WHEELUPMOUSE' else 1.0 / 1.12
            self._radius = max(0.001, min(10.0, self._radius * factor))
            if self._preview_curve is not None:
                self._preview_curve.data.update_tag()
            context.area.header_text_set(
                f"横截面宽度 {self._radius:.4f} | 左键逐点添加 | 空格/Enter 确认 | 右键/Esc 取消"
            )
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type in {'SPACE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            if len(self._points) < 3:
                self.report({'WARNING'}, "至少需要设置三个顶点")
                return {'RUNNING_MODAL'}
            self.cleanup_preview()
            if self.create_curve(context) is None:
                return {'RUNNING_MODAL'}
            context.window.cursor_modal_restore()
            context.area.header_text_set(None)
            return {'FINISHED'}
        if event.type == 'MOUSEMOVE':
            hover_world = self.get_drag_end(context, event)
            if hover_world is not None:
                self._hover_world = hover_world.copy()
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if not self._points:
                point_world, normal = self.raycast_surface(context, event)
                if point_world is not None:
                    self._start_world = point_world.copy()
                    self._start_normal = normal.copy() if normal is not None else None
            else:
                point_world = self.get_drag_end(context, event)
            if point_world is not None and (
                not self._points or (point_world - self._points[-1]).length >= 1e-5
            ):
                self._points.append(point_world.copy())
                self._hover_world = point_world.copy()
                context.area.header_text_set(
                    f"已设置 {len(self._points)} 个点 | 滚轮调整宽度 | 空格/Enter 确认 | 右键/Esc 取消"
                )
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}



classes = (
    HAIRPIPE_OT_cross_section_spread,
    HAIRPIPE_OT_draw_hair_curve,
)
