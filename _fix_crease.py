import pathlib, re
base = pathlib.Path(r"C:\Users\User_AD\AppData\Roaming\Blender Foundation\Blender\5.1\scripts\addons\hair_curve_pipe")

# 1) pipe_ops.py — 彻底移除折痕逻辑，改为清除折痕（避免棱角）
p = base/"pipe_ops.py"
txt = p.read_text(encoding="utf-8")

# replace _configure_subdiv_edge_crease
old_cfg = """def _configure_subdiv_edge_crease(pipe_obj, segments):
    try:
        apply_boulder_crease_to_pipe(pipe_obj, None, segments)
    except Exception:
        pass"""
new_cfg = """def _configure_subdiv_edge_crease(pipe_obj, segments):
    # 已移除纵向折痕功能：不再对任何边加 crease，保持 Catmull-Clark 正常圆顺
    try:
        clear_boulder_crease(pipe_obj)
    except Exception:
        pass"""
if old_cfg in txt:
    txt = txt.replace(old_cfg, new_cfg)
    print("pipe_ops _configure fixed")
else:
    print("pipe_ops _configure not found")

# replace apply_boulder_crease_to_pipe body with clearing stub
# find full function via regex
pattern = re.compile(r'def apply_boulder_crease_to_pipe\(.*?^def move_modifier_before', re.S|re.M)
m = pattern.search(txt)
if m:
    old_func = m.group(0)
    # extract trailing def
    new_func = """def clear_boulder_crease(pipe_obj):
    \"\"\"清除所有纵向/任意边的 crease，恢复细分后的圆顺效果。\"\"\"
    if pipe_obj is None or getattr(pipe_obj, "type", None) != 'MESH':
        return
    mesh = getattr(pipe_obj, "data", None)
    if mesh is None or len(getattr(mesh, "edges", [])) == 0:
        return
    try:
        if "crease_edge" in mesh.attributes:
            try:
                attr = mesh.attributes["crease_edge"]
                vals = [0.0] * len(mesh.edges)
                try:
                    attr.data.foreach_set("value", vals)
                except Exception:
                    for i in range(len(vals)):
                        try: attr.data[i].value = 0.0
                        except: pass
            except Exception:
                pass
        for e in mesh.edges:
            try: e.crease = 0.0
            except: pass
        try: mesh.update()
        except: pass
        try: pipe_obj.update_tag()
        except: pass
    except Exception:
        pass


def apply_boulder_crease_to_pipe(pipe_obj, curve_obj=None, segments_override=None):
    \"\"\"兼容旧调用：现在一律清除折痕，不再制造棱角。\"\"\"
    clear_boulder_crease(pipe_obj)


def move_modifier_before"""
    txt = txt.replace(old_func, new_func)
    print("pipe_ops apply_boulder replaced with clear")
else:
    print("pipe_ops apply_boulder pattern NOT found")

# fix configure_pipe_object: remove apply call, replace with clear
old_conf = """    try:
        apply_boulder_crease_to_pipe(pipe_obj, curve_obj)
    except Exception:
        pass
    # 强制刷新，避免视口不更新导致看似没有细分"""
new_conf = """    # 已移除纵向折痕：确保网格无 crease，保持圆顺
    try:
        clear_boulder_crease(pipe_obj)
    except Exception:
        pass
    # 强制刷新"""
if old_conf in txt:
    txt = txt.replace(old_conf, new_conf)
    print("pipe_ops configure fixed")
else:
    print("pipe_ops configure not found")

p.write_text(txt, encoding="utf-8")

# 2) handler.py — 重建时清除折痕而非添加
h = base/"handler.py"
ht = h.read_text(encoding="utf-8")
old_h = """        try:
            from .pipe_ops import apply_boulder_crease_to_pipe
            apply_boulder_crease_to_pipe(pipe_obj, curve_obj)
        except Exception:
            pass"""
new_h = """        try:
            from .pipe_ops import clear_boulder_crease
            clear_boulder_crease(pipe_obj)
        except Exception:
            pass"""
if old_h in ht:
    ht = ht.replace(old_h, new_h)
    print("handler fixed")
else:
    # second occurrence (fallback)
    old_h2 = """        try:
            from .pipe_ops import ensure_pipe_subdivision_modifier
            if pipe_obj.modifiers.get("FiguHair Catmull-Clark") is None:
                ensure_pipe_subdivision_modifier(pipe_obj, bool(settings.default_subdiv), int(settings.subdivision_levels))
            else:
                # 同步显隐与层级
                m = pipe_obj.modifiers.get("FiguHair Catmull-Clark")
                try:
                    m.show_viewport = bool(settings.default_subdiv)
                    m.levels = int(settings.subdivision_levels)
                    m.render_levels = int(settings.subdivision_levels)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            from .pipe_ops import apply_boulder_crease_to_pipe
            apply_boulder_crease_to_pipe(pipe_obj, curve_obj)
        except Exception:
            pass"""
    if old_h2 in ht:
        ht = ht.replace(old_h2, old_h2.replace("from .pipe_ops import apply_boulder_crease_to_pipe\n            apply_boulder_crease_to_pipe(pipe_obj, curve_obj)", "from .pipe_ops import clear_boulder_crease\n            clear_boulder_crease(pipe_obj)"))
        print("handler fallback fixed")
    else:
        print("handler not found")
h.write_text(ht, encoding="utf-8")

# 3) properties.py — update_boulder_fix 改为清除折痕（避免旧值残留）
q = base/"properties.py"
qt = q.read_text(encoding="utf-8")
old_u = """def update_boulder_fix(self, context):
    owner = getattr(self, "id_data", None)
    if owner is None or getattr(owner, "type", None) != 'CURVE':
        return
    try:
        from .pipe_ops import apply_boulder_crease_to_pipe
        from .hair_lifecycle import get_pipe_object_for_curve
        pipe_obj = get_pipe_object_for_curve(owner)
        if pipe_obj is not None:
            apply_boulder_crease_to_pipe(pipe_obj, owner)
            try:
                pipe_obj.data.update_tag()
                pipe_obj.update_tag()
            except Exception:
                pass
            for area in getattr(getattr(context, 'screen', None), 'areas', ()):
                if getattr(area, 'type', None) == 'VIEW_3D':
                    area.tag_redraw()
    except Exception:
        pass"""
new_u = """def update_boulder_fix(self, context):
    # 折痕功能已移除：此回调仅清除残留 crease，避免棱角
    owner = getattr(self, "id_data", None)
    if owner is None or getattr(owner, "type", None) != 'CURVE':
        return
    try:
        from .pipe_ops import clear_boulder_crease
        from .hair_lifecycle import get_pipe_object_for_curve
        pipe_obj = get_pipe_object_for_curve(owner)
        if pipe_obj is not None:
            clear_boulder_crease(pipe_obj)
            try:
                pipe_obj.data.update_tag()
                pipe_obj.update_tag()
            except Exception:
                pass
            for area in getattr(getattr(context, 'screen', None), 'areas', ()):
                if getattr(area, 'type', None) == 'VIEW_3D':
                    area.tag_redraw()
    except Exception:
        pass"""
if old_u in qt:
    qt = qt.replace(old_u, new_u)
    print("properties update_boulder fixed")
else:
    print("properties update_boulder not found")
q.write_text(qt, encoding="utf-8")

# 4) 一次性清理场景中已有的所有 FiguHair 网格残留折痕（下次启动自动清理，此处写清理脚本供 handler 调用）
# 添加到 pipe_ops 的 clear 逻辑已足够，但额外确保 panel 不再显示相关选项（已隐藏）

print("done fix_crease")
