"""
satisfy.py - turn ANY 3D model into a satisfying looping video (MP4).

Run:
  blender -b -P satisfy.py -- --model apple.glb --style drop --vertical
No --model? A demo object is used.

Styles: turntable | drop | rain
"""
import argparse
import math
import os
import random
import sys

import bpy
from mathutils import Vector


# ---------------------------------------------------------------- args
def get_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(description="Satisfying video maker")
    p.add_argument("--model", default="", help=".glb .gltf .obj .fbx .stl .ply")
    p.add_argument("--style", default="drop", choices=["turntable", "drop", "rain"])
    p.add_argument("--out", default="out/satisfy.mp4")
    p.add_argument("--seconds", type=float, default=0, help="0 = style default")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--vertical", action="store_true", help="1080x1920 for Reels/Shorts")
    p.add_argument("--engine", default="eevee", choices=["eevee", "cycles"])
    p.add_argument("--samples", type=int, default=64)
    p.add_argument("--bg", default="#14142b", help="background hex")
    p.add_argument("--floor", default="#2a2a4a", help="floor hex")
    p.add_argument("--color", default="#ff4d6d", help="demo/untextured object hex")
    p.add_argument("--size", type=float, default=2.0, help="object size in Blender units")
    p.add_argument("--count", type=int, default=60, help="copies for rain style")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--preview", action="store_true", help="fast low-quality test render")
    return p.parse_args(argv)


def hex_rgba(h):
    h = h.lstrip("#")
    r, g, b = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return (lin(r), lin(g), lin(b), 1.0)


# ---------------------------------------------------------------- model
def import_model(path):
    before = set(bpy.data.objects)
    ext = os.path.splitext(path)[1].lower()
    ops = bpy.ops
    if ext in (".glb", ".gltf"):
        ops.import_scene.gltf(filepath=path)
    elif ext == ".obj":
        (ops.wm.obj_import if hasattr(ops.wm, "obj_import") else ops.import_scene.obj)(filepath=path)
    elif ext == ".fbx":
        ops.import_scene.fbx(filepath=path)
    elif ext == ".stl":
        (ops.wm.stl_import if hasattr(ops.wm, "stl_import") else ops.import_mesh.stl)(filepath=path)
    elif ext == ".ply":
        (ops.wm.ply_import if hasattr(ops.wm, "ply_import") else ops.import_mesh.ply)(filepath=path)
    else:
        sys.exit(f"Unsupported format: {ext}")
    return [o for o in bpy.data.objects if o not in before]


def make_demo():
    bpy.ops.mesh.primitive_monkey_add(size=2)
    o = bpy.context.active_object
    bpy.ops.object.modifier_add(type="SUBSURF")
    o.modifiers["Subdivision"].levels = 2
    bpy.ops.object.modifier_apply(modifier="Subdivision")
    bpy.ops.object.shade_smooth()
    return [o]


def prepare_object(objs, size, color):
    """Merge meshes into one object, scale to `size`, sit it on the floor."""
    meshes = [o for o in objs if o.type == "MESH"]
    if not meshes:
        sys.exit("No mesh found in model.")
    for o in objs:  # flatten hierarchy, keep world transform
        if o.parent:
            mw = o.matrix_world.copy()
            o.parent = None
            o.matrix_world = mw
    for o in objs:
        if o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    bpy.ops.object.select_all(action="DESELECT")
    for m in meshes:
        m.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
    s = size / max(obj.dimensions)
    obj.scale = (s, s, s)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.location = (0, 0, obj.dimensions.z / 2)

    if not any(slot.material for slot in obj.material_slots):
        mat = bpy.data.materials.new("Obj")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = hex_rgba(color)
        bsdf.inputs["Roughness"].default_value = 0.25
        obj.data.materials.append(mat)
    obj.name = "Hero"
    return obj


# ---------------------------------------------------------------- scene
def aim(obj, target):
    c = obj.constraints.new("TRACK_TO")
    c.target = target
    c.track_axis = "TRACK_NEGATIVE_Z"
    c.up_axis = "UP_Y"


def build_scene(scene, a, cam_loc, cam_target):
    col = scene.collection
    # world
    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = hex_rgba(a.bg)
    bg.inputs["Strength"].default_value = 0.8
    scene.world = world

    # floor
    bpy.ops.mesh.primitive_plane_add(size=80, location=(0, 0, 0))
    floor = bpy.context.active_object
    floor.name = "Floor"
    m = bpy.data.materials.new("Floor")
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = hex_rgba(a.floor)
    b.inputs["Roughness"].default_value = 0.55
    floor.data.materials.append(m)

    # target + camera
    tgt = bpy.data.objects.new("Target", None)
    tgt.location = cam_target
    col.objects.link(tgt)
    cd = bpy.data.cameras.new("Cam")
    cd.lens = 50
    cam = bpy.data.objects.new("Cam", cd)
    cam.location = cam_loc
    col.objects.link(cam)
    aim(cam, tgt)
    scene.camera = cam

    # 3-point lights
    for name, loc, energy, size in (
        ("Key", (4, -3, 7), 900, 6),
        ("Fill", (-6, -3, 4), 350, 8),
        ("Rim", (0, 6, 5), 600, 5),
    ):
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy, ld.size = energy, size
        lo = bpy.data.objects.new(name, ld)
        lo.location = loc
        col.objects.link(lo)
        aim(lo, tgt)
    return floor


def add_rigid(obj, passive=False, restitution=0.55, friction=0.6):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.rigidbody.object_add()
    rb = obj.rigid_body
    rb.type = "PASSIVE" if passive else "ACTIVE"
    rb.collision_shape = "MESH" if passive else "CONVEX_HULL"
    rb.restitution = restitution
    rb.friction = friction


def setup_physics(scene, frame_end, time_scale):
    rw = scene.rigidbody_world
    rw.time_scale = time_scale
    rw.substeps_per_frame = 10
    rw.solver_iterations = 20
    rw.point_cache.frame_start = 1
    rw.point_cache.frame_end = frame_end


# ---------------------------------------------------------------- styles
def style_turntable(scene, obj, frames):
    bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"
    obj.rotation_euler = (0, 0, 0)
    obj.keyframe_insert("rotation_euler", index=2, frame=1)
    obj.rotation_euler[2] = math.tau
    obj.keyframe_insert("rotation_euler", index=2, frame=frames + 1)  # seamless loop


def style_drop(scene, obj, floor, frames, rng):
    add_rigid(floor, passive=True)
    obj.location.z += 6
    obj.rotation_euler = (rng.uniform(-.5, .5), rng.uniform(-.5, .5), rng.uniform(0, 6))
    add_rigid(obj, restitution=0.6)
    setup_physics(scene, frames, time_scale=0.6)  # slow motion


def style_rain(scene, obj, floor, frames, rng, count):
    add_rigid(floor, passive=True, restitution=0.4)
    items = [obj]
    for _ in range(count - 1):
        c = obj.copy()  # shares mesh data = light on memory
        scene.collection.objects.link(c)
        items.append(c)
    for i, o in enumerate(items):
        r = rng.uniform(0, 2.2)
        t = rng.uniform(0, math.tau)
        o.location = (r * math.cos(t), r * math.sin(t), 3 + i * 0.35)  # staggered
        o.rotation_euler = (rng.uniform(0, 6), rng.uniform(0, 6), rng.uniform(0, 6))
        add_rigid(o, restitution=0.35, friction=0.7)
    setup_physics(scene, frames, time_scale=0.8)


# ---------------------------------------------------------------- render
def set_engine(scene, a):
    samples = 16 if a.preview else a.samples
    if a.engine == "cycles":
        scene.render.engine = "CYCLES"
        scene.cycles.samples = samples
        scene.cycles.use_denoising = False
        scene.cycles.use_denoising = False
        scene.view_layers[0].cycles.use_denoising = False
    else:
        for name in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
            try:
                scene.render.engine = name
                break
            except TypeError:
                continue
        for attr, val in (("taa_render_samples", samples), ("use_gtao", True), ("use_soft_shadows", True)):
            try:
                setattr(scene.eevee, attr, val)
            except Exception:
                pass
    try:
        scene.view_settings.view_transform = "Standard"
    except Exception:
        pass


def main():
    a = get_args()
    rng = random.Random(a.seed)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    objs = import_model(os.path.abspath(a.model)) if a.model else make_demo()
    hero = prepare_object(objs, a.size, a.color)

    default_secs = {"turntable": 6, "drop": 5, "rain": 10}[a.style]
    secs = a.seconds or default_secs
    frames = int(secs * a.fps)
    if a.preview:
        frames = min(frames, 60)
    scene.frame_start, scene.frame_end = 1, frames
    scene.render.fps = a.fps

    if a.style == "rain":
        cam_loc, cam_tgt = (9, -9, 6), (0, 0, 1.2)
    else:
        cam_loc, cam_tgt = (5, -5, 3.2), (0, 0, 1.0)
    if a.vertical:  # pull back a little for tall frame
        cam_loc = tuple(v * 1.25 for v in cam_loc)

    floor = build_scene(scene, a, cam_loc, cam_tgt)

    if a.style == "turntable":
        style_turntable(scene, hero, frames)
    elif a.style == "drop":
        style_drop(scene, hero, floor, frames, rng)
    else:
        style_rain(scene, hero, floor, frames, rng, a.count)

    set_engine(scene, a)
    w, h = (1080, 1920) if a.vertical else (1920, 1080)
    scene.render.resolution_x, scene.render.resolution_y = w, h
    scene.render.resolution_percentage = 40 if a.preview else 100

    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    scene.render.filepath = out
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "HIGH"

    bpy.ops.render.render(animation=True)
    print(f"DONE -> {out}")


if __name__ == "__main__":
    main()
