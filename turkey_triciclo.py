"""Procedurally build, animate and render an ocellated turkey (pavo ocelado)
riding a Yucatecan cargo triciclo down a sascab road in rural Yucatán.

Run:  /Applications/Blender.app/Contents/MacOS/Blender -b -P turkey_triciclo.py
Env:  MODE=still (default)  Cycles still of frame 1        -> turkey_triciclo.png
      MODE=anim             EEVEE animation, 8 s loop      -> frames_turkey/ + turkey_ride.mp4/.gif
      MODE=check FRAMES=1,60 EEVEE test stills of frames   -> tcheck_0001.png ...
      PREVIEW=1             lighter vegetation, lower resolution
"""
import math
import os
import random
import shutil
import subprocess

import bmesh
import bpy
from mathutils import Matrix, Vector

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
MODE = os.environ.get("MODE", "still")
PREVIEW = bool(os.environ.get("PREVIEW"))

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# ================================================================ helpers
def material(name, color, rough=0.5, metal=0.0, sss=0.0, coat=0.0, sheen=0.0, emit=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    b = mat.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1.0)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    b.inputs["Subsurface Weight"].default_value = sss
    b.inputs["Coat Weight"].default_value = coat
    b.inputs["Sheen Weight"].default_value = sheen
    if emit:
        b.inputs["Emission Color"].default_value = (*color, 1.0)
        b.inputs["Emission Strength"].default_value = emit
    return mat


def add_ramp(mat, source, stops, target="Base Color", interp="LINEAR"):
    """Drive a BSDF input from `source` (a socket) through a color ramp."""
    nt = mat.node_tree
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = interp
    els = ramp.color_ramp.elements
    while len(els) < len(stops):
        els.new(0.5)
    for el, (pos, col) in zip(els, stops):
        el.position = pos
        el.color = (*col, 1.0)
    nt.links.new(source, ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], nt.nodes["Principled BSDF"].inputs[target])
    return ramp


def coord(mat, kind="Object", axis=None, tex=None, tex_out="Fac", **tex_props):
    """Texture coordinate -> optional texture -> optional single axis."""
    nt = mat.node_tree
    tc = nt.nodes.new("ShaderNodeTexCoord")
    out = tc.outputs[kind]
    if tex:
        t = nt.nodes.new(tex)
        for k, v in tex_props.items():
            if k in t.inputs:
                t.inputs[k].default_value = v
            else:
                setattr(t, k, v)
        nt.links.new(out, t.inputs["Vector"])
        out = t.outputs[tex_out]
    if axis:
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(out, sep.inputs[0])
        out = sep.outputs[axis]
    return out


def add_bump(mat, scale, strength, detail=4.0):
    nt = mat.node_tree
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = detail
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = strength
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], nt.nodes["Principled BSDF"].inputs["Normal"])


def finish(obj, mat, smooth=True):
    obj.data.materials.append(mat)
    if smooth:
        for p in obj.data.polygons:
            p.use_smooth = True
    return obj


def aim_quat(direction, axis="Z"):
    base = Vector((0, 0, 1)) if axis == "Z" else Vector((1, 0, 0))
    return base.rotation_difference(Vector(direction).normalized())


def orient(obj, direction):
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = aim_quat(direction)


def rod(p1, p2, r, mat, verts=16):
    p1, p2 = Vector(p1), Vector(p2)
    v = p2 - p1
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=v.length, location=(p1 + p2) / 2)
    obj = bpy.context.object
    orient(obj, v)
    return finish(obj, mat)


def ball(loc, r, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=r, location=loc)
    return finish(bpy.context.object, mat)


def ellipsoid(loc, scale, mat, direction=None):
    """Sphere with scale baked into the mesh (local Z = long axis), then aimed."""
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=1, location=loc)
    obj = bpy.context.object
    obj.data.transform(Matrix.Diagonal((*scale, 1)))
    if direction is not None:
        orient(obj, direction)
    return finish(obj, mat)


def ring(loc, major, minor, mat):
    bpy.ops.mesh.primitive_torus_add(major_radius=major, minor_radius=minor,
                                     major_segments=72, minor_segments=12, location=loc)
    obj = bpy.context.object
    obj.rotation_euler = (math.radians(90), 0, 0)  # wheel plane = XZ
    return finish(obj, mat)


def empty(name, loc=(0, 0, 0), size=0.1):
    obj = bpy.data.objects.new(name, None)
    obj.location = loc
    obj.empty_display_size = size
    scene.collection.objects.link(obj)
    return obj


def attach(obj, parent, bone=None):
    """Re-parent keeping the current world transform (works for bone parents)."""
    mw = obj.matrix_world.copy()
    obj.parent = parent
    if bone:
        obj.parent_type = "BONE"
        obj.parent_bone = bone
    obj.matrix_world = mw


def drive(owner, path, index, expr):
    """Scripted driver using a 'simple expression' (runs without Python trust)."""
    fc = owner.driver_add(path, index) if index is not None else owner.driver_add(path)
    fc.driver.type = "SCRIPTED"
    fc.driver.expression = expr
    return fc


def fcurves_of(idblock):
    act = idblock.animation_data.action
    if hasattr(act, "fcurves"):
        return act.fcurves
    return act.layers[0].strips[0].channelbag(idblock.animation_data.action_slot).fcurves


def linearize(idblock, cyclic=False):
    for fc in fcurves_of(idblock):
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
        if cyclic and not any(m.type == "CYCLES" for m in fc.modifiers):
            fc.modifiers.new("CYCLES")


def instance(mesh, loc, scale=(1, 1, 1), rot=(0, 0, 0), name="Inst"):
    obj = bpy.data.objects.new(name, mesh)
    obj.location, obj.scale, obj.rotation_euler = loc, scale, rot
    scene.collection.objects.link(obj)
    return obj


def template(obj):
    mesh = obj.data
    bpy.data.objects.remove(obj)
    return mesh


def join(objs, name):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    obj = bpy.context.object
    # the joined mesh lives in the first part's local space: bake it back to world
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    obj.name = name
    return obj


FLUFF = bpy.data.textures.new("Fluff", "CLOUDS")
FLUFF.noise_scale = 0.35


def fluffy(radius, strength, mat, subdiv=3):
    """Icosphere with baked cloud displacement - for tree crowns and clouds."""
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=subdiv, radius=radius)
    obj = bpy.context.object
    mod = obj.modifiers.new("Displace", "DISPLACE")
    mod.texture = FLUFF
    mod.strength = strength
    mod.mid_level = 0.5
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)
    return finish(obj, mat)


def knee(hip, foot, l1, l2, forward):
    """Two-bone IK: knee position bending toward `forward`."""
    hip, foot, forward = Vector(hip), Vector(foot), Vector(forward)
    d_vec = foot - hip
    d = min(d_vec.length, l1 + l2 - 1e-3)
    axis = d_vec.normalized()
    a = (l1 ** 2 - l2 ** 2 + d ** 2) / (2 * d)
    h = math.sqrt(max(l1 ** 2 - a ** 2, 0))
    perp = (forward - axis * forward.dot(axis)).normalized()
    return hip + axis * a + perp * h



def new_objects(since):
    return [o for o in scene.objects if o not in since]


def socket(node, name, outputs=False):
    pool = node.outputs if outputs else node.inputs
    return [s for s in pool if s.name == name and s.enabled][0]


# ---- animation timing: one lap of the sascab road = one seamless loop
FPS, N = 30, 420                   # 14 second loop at 30 fps
R_REAR, R_FRONT = 0.33, 0.25       # 26" rear wheel, 20" front cargo wheels
LANE_NEAR, TURN_R = -0.55, 0.8     # outbound lane y, U-turn radius (trikes turn wide)
X_RIGHT, X_LEFT = 7.0, -8.0
LAP = (X_RIGHT - 0) + math.pi * TURN_R + (X_RIGHT - X_LEFT) + math.pi * TURN_R + (0 - X_LEFT)
SPEED = LAP / N
CRANK_RATE = 14 * 2 * math.pi / N  # ~1 pedal rev per second, whole number per loop -> seamless


# ================================================================ palette
M_FRAME = material("Frame_Red", (0.8, 0.07, 0.04), rough=0.25, metal=0.2, coat=1.0)
M_BOX = material("Box_Turquoise", (0.0, 0.55, 0.58), rough=0.45, coat=0.4)
add_bump(M_BOX, 60, 0.15)
M_TRIM = material("Trim_Yellow", (1.0, 0.78, 0.05), rough=0.35, coat=0.5)
M_TIRE = material("Tire", (0.025, 0.022, 0.02), rough=0.85)
M_CHROME = material("Chrome", (0.9, 0.9, 0.92), rough=0.15, metal=1.0)
M_RIM = material("Rim", (0.75, 0.76, 0.78), rough=0.25, metal=1.0)
M_SEAT = material("Seat", (0.08, 0.06, 0.05), rough=0.6)
M_ORANGE = material("Orange", (1.0, 0.42, 0.02), rough=0.45, sss=0.1)
add_bump(M_ORANGE, 120, 0.3)
M_LIME = material("Lime", (0.35, 0.65, 0.08), rough=0.4)
add_bump(M_LIME, 120, 0.3)
M_LETTER = material("Lettering", (1.0, 0.95, 0.85), rough=0.4)

# ================================================================ rig roots
# Rider follows the road loop; Steer turns the front cargo box; Torso bobs.
RIDER = empty("Rider", size=0.5)
TORSO = empty("Torso", size=0.3)
TORSO.parent = RIDER
PIVOT = Vector((0.24, 0, 0.45))
STEER = empty("Steer", PIVOT, 0.3)
STEER.parent = RIDER
rigged = set(scene.objects)
child_of = {}  # object -> (parent, bone) for everything not a plain rig child

# ================================================================ triciclo
# Yucatecan cargo triciclo: rider behind on one wheel, a turquoise cargo box
# between two front wheels, the whole box pivots to steer.
REAR = Vector((-0.55, 0, R_REAR))
BB = Vector((-0.22, 0, 0.30))
SEAT = Vector((-0.40, 0, 0.80))
HEAD_LO, HEAD_HI = Vector((0.2, 0, 0.36)), Vector((0.2, 0, 0.6))
FRONT_AX = Vector((0.62, 0, R_FRONT))
BOX_C = Vector((0.62, 0, 0.55))            # box center
BOX_HALF = Vector((0.31, 0.37, 0.15))      # half size (x, y, z)
BAR = Vector((0.2, 0, 0.98))


def wheel(center, radius, name, parent_hub_to):
    hub = empty(name, center, radius + 0.05)
    before = set(scene.objects)
    ring(center, radius, 0.028, M_TIRE)
    ring(center, radius - 0.03, 0.011, M_RIM)
    rod(center + Vector((0, -0.04, 0)), center + Vector((0, 0.04, 0)), 0.02, M_CHROME)
    n = 20 if radius > 0.3 else 16
    for i in range(n):
        a = 2 * math.pi * i / n
        tip = center + Vector((math.cos(a), 0, math.sin(a))) * (radius - 0.035)
        rod(center + Vector((0, 0.03 if i % 2 else -0.03, 0)), tip, 0.0026, M_CHROME, verts=6)
    for part in new_objects(before):
        child_of[part] = (hub, None)
    drive(hub, "rotation_euler", 1, f"{SPEED / radius:.5f}*(frame-1)")
    child_of[hub] = (parent_hub_to, None)
    return hub


wheel(REAR, R_REAR, "Wheel_Rear", RIDER)

# rear frame (rider side)
T = 0.022
rod(BB, SEAT, T, M_FRAME)
rod(BB, HEAD_LO + Vector((0, 0, 0.04)), T * 1.2, M_FRAME)
rod(SEAT + Vector((0.02, 0, -0.08)), HEAD_HI, T, M_FRAME)
rod(HEAD_LO, HEAD_HI, T * 1.4, M_FRAME)
for s in (-0.05, 0.05):
    rod(BB + Vector((0, s * 0.6, 0)), REAR + Vector((0, s, 0)), T * 0.7, M_FRAME)
    rod(SEAT + Vector((0, 0, -0.06)), REAR + Vector((0, s, 0)), T * 0.7, M_FRAME)
rod(SEAT, SEAT + Vector((-0.02, 0, 0.07)), 0.015, M_CHROME)
ellipsoid(SEAT + Vector((-0.03, 0, 0.09)), (0.1, 0.05, 0.14), M_SEAT, direction=(1, 0, 0))
ring(REAR + Vector((0, -0.06, 0)), 0.045, 0.006, M_CHROME)
for dz in (0.1, -0.1):
    rod(BB + Vector((0, -0.06, dz)), REAR + Vector((0, -0.06, dz * 0.45)), 0.005, M_TIRE, verts=6)

CRANK = 0.16
THETA0 = math.radians(-35)
crank = empty("Crank", BB, 0.25)
child_of[ring(BB + Vector((0, -0.06, 0)), 0.1, 0.008, M_CHROME)] = (crank, None)
drive(crank, "rotation_euler", 1, f"{CRANK_RATE:.5f}*(frame-1)")
foot_targets = {}
for side, ang in ((-1, THETA0), (1, THETA0 + math.pi)):
    p = BB + Vector((CRANK * math.cos(ang), side * 0.13, CRANK * math.sin(ang)))
    child_of[rod(BB + Vector((0, side * 0.08, 0)), p, 0.012, M_CHROME)] = (crank, None)
    ped = empty(f"Pedal_{'R' if side < 0 else 'L'}", p, 0.08)
    angle = f"({ang:.5f}-{CRANK_RATE:.5f}*(frame-1))"
    drive(ped, "location", 0, f"{BB.x:.4f}+{CRANK}*cos{angle}")
    drive(ped, "location", 2, f"{BB.z:.4f}+{CRANK}*sin{angle}")
    bpy.ops.mesh.primitive_cube_add(size=1, location=p + Vector((0, side * 0.03, 0)))
    block = bpy.context.object
    block.scale = (0.09, 0.07, 0.015)
    child_of[finish(block, M_TIRE, smooth=False)] = (ped, None)
    ft = empty(f"FootTarget_{'R' if side < 0 else 'L'}", p + Vector((0, side * 0.03, 0.04)), 0.05)
    child_of[ft] = (ped, None)
    foot_targets[side] = ft

# ---- front assembly (steers as one unit)
front_before = set(scene.objects)
for s in (-1, 1):
    wheel(FRONT_AX + Vector((0, s * 0.45, 0)), R_FRONT, f"Wheel_Front{'L' if s > 0 else 'R'}", STEER)
rod(FRONT_AX + Vector((0, -0.47, 0)), FRONT_AX + Vector((0, 0.47, 0)), 0.016, M_CHROME)  # axle
for s in (-1, 1):  # axle hangers up to the box floor
    rod(FRONT_AX + Vector((0, s * 0.3, 0)), BOX_C + Vector((0, s * 0.3, -BOX_HALF.z)), 0.014, M_FRAME)


def plank(center, half, mat):
    bpy.ops.mesh.primitive_cube_add(size=2, location=center)
    obj = bpy.context.object
    obj.scale = half
    bpy.ops.object.transform_apply(scale=True)
    mod = obj.modifiers.new("Bevel", "BEVEL")
    mod.width, mod.segments = 0.006, 2
    return finish(obj, mat, smooth=False)


hx, hy, hz = BOX_HALF
plank(BOX_C + Vector((0, 0, -hz)), (hx, hy, 0.015), M_BOX)                   # floor
for s in (-1, 1):
    plank(BOX_C + Vector((0, s * hy, 0)), (hx, 0.012, hz), M_BOX)            # sides
    plank(BOX_C + Vector((s * hx, 0, 0)), (0.012, hy, hz), M_BOX)            # front/back
    plank(BOX_C + Vector((0, s * hy, hz)), (hx + 0.015, 0.02, 0.012), M_TRIM)  # top rails
    plank(BOX_C + Vector((s * hx, 0, hz)), (0.02, hy + 0.015, 0.012), M_TRIM)
    for fx in (-0.18, 0.0, 0.18):                                            # painted stripes
        plank(BOX_C + Vector((fx + 0.09, s * (hy + 0.013), -0.05)), (0.035, 0.002, 0.07), M_TRIM)
for s in (-1, 1):  # cargo-box legs down to the head tube bracket
    rod(BOX_C + Vector((-hx, s * 0.12, -hz)), PIVOT + Vector((0, s * 0.03, -0.02)), 0.014, M_FRAME)

bpy.ops.object.text_add(location=BOX_C + Vector((0.0, -hy - 0.018, 0.02)))
txt = bpy.context.object
txt.data.body = "YUCATÁN"
txt.data.align_x, txt.data.align_y = "CENTER", "CENTER"
txt.data.size = 0.1
txt.data.extrude = 0.004
txt.rotation_euler = (math.radians(90), 0, 0)
txt.data.materials.append(M_LETTER)

# handlebar is bolted to the back wall of the box -> turns with it
rod(BOX_C + Vector((-hx, 0, hz)), BAR, 0.017, M_CHROME)
rod(BAR + Vector((0, -0.3, 0)), BAR + Vector((0, 0.3, 0)), 0.015, M_CHROME)
for s in (-1, 1):
    rod(BAR + Vector((0, s * 0.2, 0)), BAR + Vector((0, s * 0.3, 0)), 0.024, M_SEAT)
ball(BAR + Vector((0.02, -0.15, 0.03)), 0.025, M_CHROME)  # bell

# cargo: a mound of Oxkutzcab oranges and a few limes
bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=10, radius=0.045)
orange_mesh = template(finish(bpy.context.object, M_ORANGE))
bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8, radius=0.03)
lime_mesh = template(finish(bpy.context.object, M_LIME))
random.seed(4)
for _ in range(90 if PREVIEW else 220):
    fx, fy = random.uniform(-hx + 0.05, hx - 0.05), random.uniform(-hy + 0.05, hy - 0.05)
    mound = 0.34 * (1 - (fx / hx) ** 2) * (1 - (fy / hy) ** 2)
    z = BOX_C.z - hz + 0.05 + random.uniform(0, 1) * mound
    mesh = lime_mesh if random.random() < 0.15 else orange_mesh
    instance(mesh, BOX_C + Vector((fx, fy, z - BOX_C.z)), (1, 1, 0.95),
             (random.uniform(0, 3), random.uniform(0, 3), 0), name="Fruit")

for o in new_objects(front_before):
    child_of.setdefault(o, (STEER, None))
trike_objs = new_objects(rigged)
rigged |= set(trike_objs)

# ================================================================ ocellated turkey
# iridescent bronze-green body feathers: scalloped Voronoi bands + thin-film sheen
M_BRONZE = material("Plumage_Bronze", (0.35, 0.22, 0.06), rough=0.35, metal=0.45, coat=0.3)
add_ramp(M_BRONZE, coord(M_BRONZE, "Object", tex="ShaderNodeTexVoronoi", tex_out="Distance", Scale=22.0, feature="DISTANCE_TO_EDGE"),
         [(0.0, (0.02, 0.02, 0.02)), (0.05, (0.55, 0.32, 0.07)), (0.12, (0.1, 0.4, 0.28)), (0.3, (0.04, 0.24, 0.17))])
_b = M_BRONZE.node_tree.nodes["Principled BSDF"]
if "Thin Film Thickness" in _b.inputs:
    _b.inputs["Thin Film Thickness"].default_value = 420.0
    _b.inputs["Thin Film IOR"].default_value = 1.45
M_SKIN = material("Skin_Blue", (0.12, 0.38, 0.95), rough=0.4, sss=0.2)
M_WART = material("Warts_Orange", (1.0, 0.33, 0.06), rough=0.3, coat=0.4)
M_KNOB = material("Crown_Knobs", (1.0, 0.68, 0.08), rough=0.3, coat=0.4)
M_EYE = material("Eye", (0.02, 0.01, 0.01), rough=0.05)
M_EYERING = material("EyeRing", (0.9, 0.12, 0.08), rough=0.4)
M_BEAK = material("Beak_Horn", (0.9, 0.78, 0.55), rough=0.35)
M_LEG = material("Legs_Pink", (0.9, 0.32, 0.35), rough=0.45, sss=0.1)
M_COPPER = material("Wing_Copper", (0.75, 0.35, 0.08), rough=0.35, metal=0.6)
M_BARRED = material("Wing_Barred", (0.95, 0.93, 0.88), rough=0.6)
add_ramp(M_BARRED, coord(M_BARRED, "Object", tex="ShaderNodeTexWave", Scale=28.0, wave_type="BANDS",
                         bands_direction="Z"),
         [(0.0, (0.95, 0.93, 0.88)), (0.62, (0.08, 0.07, 0.06))], interp="CONSTANT")
M_TAIL = material("Tail_Grey", (0.36, 0.42, 0.5), rough=0.55)
add_ramp(M_TAIL, coord(M_TAIL, "Object", tex="ShaderNodeTexNoise", Scale=90.0, Detail=3.0),
         [(0.35, (0.28, 0.33, 0.4)), (0.65, (0.5, 0.52, 0.55))])
M_OCELLUS = material("Ocellus_Blue", (0.1, 0.3, 0.95), rough=0.15, metal=0.7, coat=1.0)
M_OCRING = material("Ocellus_Bronze", (0.55, 0.3, 0.08), rough=0.25, metal=0.7)
M_TIPGOLD = material("Tail_Tip_Gold", (1.0, 0.6, 0.12), rough=0.25, metal=0.8)

BODY = Vector((-0.38, 0, 1.17))
NECK = [((-0.2, 0, 1.3), 0.075), ((-0.14, 0, 1.45), 0.05), ((-0.08, 0, 1.56), 0.042)]
HEAD = Vector((-0.04, 0, 1.61))
K = 1 / 0.575  # metaball surface sits at 0.575 x the element size (measured)


def metaball(name, mat):
    mb = bpy.data.metaballs.new(name)
    mb.resolution = 0.008
    mb.threshold = 0.6
    mb.materials.append(mat)
    obj = bpy.data.objects.new(name, mb)
    scene.collection.objects.link(obj)
    return mb, obj


def mb_ellipsoid(mb, co, half, direction=(1, 0, 0)):
    e = mb.elements.new()
    e.type = "ELLIPSOID"
    e.co, e.radius = co, 1.0
    e.size_x, e.size_y, e.size_z = (h * K for h in half)
    e.rotation = aim_quat(direction, axis="X")


def mb_capsule(mb, p1, p2, r):
    p1, p2 = Vector(p1), Vector(p2)
    e = mb.elements.new()
    e.type = "CAPSULE"
    e.co, e.radius = (p1 + p2) / 2, r * K
    e.size_x = (p2 - p1).length / 2
    e.rotation = aim_quat(p2 - p1, axis="X")


def bake(obj):
    """Metaball -> fixed mesh (stable for motion blur, no per-frame remeshing)."""
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.convert(target="MESH")
    out = bpy.context.object
    for poly in out.data.polygons:
        poly.use_smooth = True
    return out


# feathered body + wings as one blended blob
mb_body, body_obj = metaball("Turkey_Body", M_BRONZE)
mb_ellipsoid(mb_body, BODY, (0.3, 0.23, 0.25), (1, 0, 0.35))
mb_ellipsoid(mb_body, BODY + Vector((0.16, 0, -0.02)), (0.17, 0.19, 0.2))           # breast
mb_ellipsoid(mb_body, BODY + Vector((-0.24, 0, -0.03)), (0.15, 0.17, 0.15))         # rump
mb_ellipsoid(mb_body, Vector(NECK[0][0]) + Vector((0, 0, -0.02)), (0.1, 0.1, 0.1))  # feather ruff
grips = {}
for s in (-1, 1):
    shoulder = BODY + Vector((0.14, s * 0.2, 0.06))
    grip = BAR + Vector((0, s * 0.25, 0.02))
    elbow = shoulder.lerp(grip, 0.5) + Vector((-0.05, s * 0.1, 0.06))
    mb_ellipsoid(mb_body, shoulder.lerp(elbow, 0.5), ((elbow - shoulder).length * 0.62, 0.07, 0.06), elbow - shoulder)
    mb_ellipsoid(mb_body, elbow.lerp(grip, 0.5), ((grip - elbow).length * 0.6, 0.05, 0.045), grip - elbow)
    grips[s] = (shoulder, elbow, grip)
body_obj = bake(body_obj)
body_obj.name = "Turkey_Body"

# bare blue head + neck as a second blob (a different material, so no blending)
mb_head, head_obj = metaball("Turkey_Head", M_SKIN)
for (a, ra), (b, rb) in zip(NECK, NECK[1:]):
    mb_capsule(mb_head, a, b, (ra + rb) / 2)
mb_ellipsoid(mb_head, HEAD, (0.075, 0.05, 0.056), (1, 0, -0.1))
mb_ellipsoid(mb_head, HEAD + Vector((0.035, 0, 0.045)), (0.022, 0.016, 0.02))       # fleshy crown
head_obj = bake(head_obj)
head_obj.name = "Turkey_Head"

# orange-red warts scattered over neck and head, golden knobs on the crown
random.seed(8)
for _ in range(34):
    (a, ra), (b, rb) = random.choice(list(zip(NECK, NECK[1:])))
    t = random.random()
    axis = (Vector(b) - Vector(a)).normalized()
    u = axis.orthogonal().normalized()
    v = axis.cross(u)
    phi = random.uniform(0, 2 * math.pi)
    p = Vector(a).lerp(Vector(b), t) + (u * math.cos(phi) + v * math.sin(phi)) * ((ra + rb) / 2) * 1.02
    ball(p, random.uniform(0.006, 0.011), M_WART)
for _ in range(14):
    d = Vector((random.uniform(-0.6, 0.4), random.choice((-1, 1)) * random.uniform(0.5, 1), random.uniform(-0.6, 0.7)))
    d.normalize()
    ball(HEAD + Vector((d.x * 0.074, d.y * 0.05, d.z * 0.055)), random.uniform(0.005, 0.009), M_WART)
for dx, dy, r in ((0.03, 0, 0.016), (0.005, 0, 0.014), (-0.02, 0, 0.012), (0.015, 0.014, 0.01), (0.015, -0.014, 0.01)):
    ball(HEAD + Vector((dx, dy, 0.066)), r, M_KNOB)
M_GLINT = material("Eye_Glint", (1, 1, 1), rough=0.1, emit=2.0)
for s in (-1, 1):  # set slightly forward, cartoon-style, so both read from the front
    eye = HEAD + Vector((0.042, s * 0.04, 0.016))
    out = Vector((0.55, s * 0.84, 0.1)).normalized()
    ball(eye, 0.019, M_EYERING)
    ball(eye + out * 0.011, 0.012, M_EYE)
    ball(eye + out * 0.019 + Vector((0.003, 0, 0.005)), 0.0035, M_GLINT)
beak_base, beak_tip = HEAD + Vector((0.068, 0, -0.012)), HEAD + Vector((0.125, 0, -0.035))
bpy.ops.mesh.primitive_cone_add(vertices=24, radius1=0.022, radius2=0.004, depth=(beak_tip - beak_base).length,
                                location=(beak_base + beak_tip) / 2)
orient(finish(bpy.context.object, M_BEAK), beak_tip - beak_base)

# wing feathers: copper secondaries and white-barred flight feathers
for s in (-1, 1):
    shoulder, elbow, grip = grips[s]
    for k in range(7):
        root = elbow.lerp(grip, 0.1 + k * 0.12) if k > 1 else shoulder.lerp(elbow, 0.55 + k * 0.25)
        fd = Vector((-0.7 - k * 0.04, s * 0.2, -1.0))
        ellipsoid(root + fd.normalized() * 0.075, (0.035, 0.008, 0.11 - k * 0.005),
                  M_COPPER if k % 2 else M_BARRED, direction=fd)
    for off in (-0.03, 0.0, 0.03):  # feather "fingers" over the grip
        tip = grip + Vector((0.06, s * 0.02, off))
        ellipsoid(grip.lerp(tip, 0.3), (0.02, 0.012, 0.09), M_BARRED, direction=tip - grip)
    ellipsoid(BODY + Vector((-0.12, s * 0.21, 0.02)), (0.05, 0.02, 0.24), M_BARRED, direction=(-1, 0, -0.3))

# the fanned tail with its famous eye-spots (ocelli) facing forward
TAIL_BASE = BODY + Vector((-0.3, 0, -0.04))
for k in range(15):
    a = math.radians(-78 + k * (156 / 14))
    d = Vector((-0.3, math.sin(a), math.cos(a))).normalized()
    length = 0.52 - 0.1 * abs(math.degrees(a)) / 78
    ellipsoid(TAIL_BASE + d * length / 2, (0.008, 0.06, length / 2), M_TAIL, direction=d)
    front = Vector((1, 0, 0)) - d * d.x
    front.normalize()
    eye_c = TAIL_BASE + d * (length - 0.075) + front * 0.012
    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.036, depth=0.006, location=eye_c)
    orient(finish(bpy.context.object, M_OCELLUS), front)
    bpy.ops.mesh.primitive_torus_add(major_radius=0.038, minor_radius=0.007, location=eye_c - front * 0.002)
    orient(finish(bpy.context.object, M_OCRING), front)
    ellipsoid(TAIL_BASE + d * (length - 0.018) + front * 0.006, (0.009, 0.055, 0.02), M_TIPGOLD, direction=d)
for k in range(9):  # bronze coverts hide the fan's base
    a = math.radians(-70 + k * 17.5)
    d = Vector((-0.2, math.sin(a) * 0.9, math.cos(a))).normalized()
    ellipsoid(TAIL_BASE + d * 0.1 + Vector((0.03, 0, 0)), (0.012, 0.06, 0.12), M_BRONZE, direction=d)

# legs: bound to an IK armature later; feet ride on the pedals
legs, leg_parts = {}, {}
for s in (-1, 1):
    hip = BODY + Vector((0.05, s * 0.12, -0.17))
    foot = foot_targets[s].location.copy()
    kn = knee(hip, foot, 0.46, 0.44, forward=Vector((1, 0, 0.3)))
    thigh = [ellipsoid(hip.lerp(kn, 0.3), (0.075, 0.07, 0.16), M_BRONZE, direction=kn - hip),
             rod(hip.lerp(kn, 0.45), kn, 0.022, M_LEG), ball(kn, 0.028, M_LEG)]
    shin = [rod(kn, foot, 0.02, M_LEG)]
    toes = [rod(foot, foot + Vector((0.1 * math.cos(a), 0.1 * math.sin(a), -0.01)), 0.011, M_LEG, verts=8)
            for a in (math.radians(-28), 0, math.radians(28))]
    toes.append(rod(foot, foot + Vector((-0.06, 0, -0.01)), 0.01, M_LEG, verts=8))  # hind toe
    legs[s] = (hip, kn, foot)
    leg_parts[s] = (thigh, shin, toes)
    for o in toes:
        child_of[o] = (foot_targets[s], None)

turkey_objs = new_objects(rigged)

# ================================================================ rig assembly
bpy.context.view_layer.update()
leg_bound = {o for s in (-1, 1) for part in leg_parts[s][:2] for o in part}
for o in trike_objs:
    child_of.setdefault(o, (RIDER, None))
for o in turkey_objs:
    if o not in leg_bound:
        child_of.setdefault(o, (TORSO, None))
for o, (parent, bone) in child_of.items():
    attach(o, parent, bone)

arm_data = bpy.data.armatures.new("Legs")
arm = bpy.data.objects.new("Legs", arm_data)
scene.collection.objects.link(arm)
arm.parent = TORSO
arm.show_in_front = True
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
for s, S in ((-1, "R"), (1, "L")):
    hip, kn, foot = legs[s]
    tb = arm_data.edit_bones.new(f"thigh.{S}")
    tb.head, tb.tail = hip, kn
    sb = arm_data.edit_bones.new(f"shin.{S}")
    sb.head, sb.tail = kn, foot
    sb.parent, sb.use_connect = tb, True
bpy.ops.object.mode_set(mode="OBJECT")
iks = []
for s, S in ((-1, "R"), (1, "L")):
    pole = empty(f"KneePole_{S}", legs[s][1] + Vector((0.6, s * 0.05, 0.2)), 0.05)
    pole.parent = RIDER
    ik = arm.pose.bones[f"shin.{S}"].constraints.new("IK")
    ik.target, ik.pole_target, ik.chain_count = foot_targets[s], pole, 2
    iks.append(ik)


def knee_error():
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    ev = arm.evaluated_get(dg)
    return sum((ev.matrix_world @ ev.pose.bones[f"thigh.{S}"].tail - legs[s][1]).length
               for s, S in ((-1, "R"), (1, "L")))


best = min((math.radians(d) for d in range(-180, 180, 5)),
           key=lambda a: [setattr(ik, "pole_angle", a) for ik in iks] and knee_error())
for ik in iks:
    ik.pole_angle = best
print(f"IK pole angle {math.degrees(best):.0f} deg, knee error {knee_error():.4f} m")
for s, S in ((-1, "R"), (1, "L")):
    thigh, shin, _ = leg_parts[s]
    for o in thigh:
        attach(o, arm, f"thigh.{S}")
    for o in shin:
        attach(o, arm, f"shin.{S}")

# ---- the lap: out along the near lane, wide U-turn, back along the far lane
pts = []


def seg(a, b, step=0.1):
    n = max(2, int((b - a).length / step))
    pts.extend(a.lerp(b, i / n) for i in range(n))


def arc(center, a0, a1, step=0.05):
    n = max(8, int(abs(a1 - a0) * TURN_R / step))
    pts.extend(center + Vector((math.cos(a0 + (a1 - a0) * i / n), math.sin(a0 + (a1 - a0) * i / n), 0)) * TURN_R
               for i in range(n))


y0, y1 = LANE_NEAR, LANE_NEAR + 2 * TURN_R
seg(Vector((0, y0, 0)), Vector((X_RIGHT, y0, 0)))
arc(Vector((X_RIGHT, y0 + TURN_R, 0)), -math.pi / 2, math.pi / 2)
seg(Vector((X_RIGHT, y1, 0)), Vector((X_LEFT, y1, 0)))
arc(Vector((X_LEFT, y0 + TURN_R, 0)), math.pi / 2, 3 * math.pi / 2)
seg(Vector((X_LEFT, y0, 0)), Vector((0, y0, 0)))
path_data = bpy.data.curves.new("Lap", "CURVE")
path_data.dimensions = "3D"
spl = path_data.splines.new("POLY")
spl.points.add(len(pts) - 1)
for p, co in zip(spl.points, pts):
    p.co = (*co, 1)
spl.use_cyclic_u = True
path_data.use_path = True
lap = bpy.data.objects.new("Lap", path_data)
scene.collection.objects.link(lap)
lap.hide_render = True

follow = RIDER.constraints.new("FOLLOW_PATH")
follow.name = "Follow Path"
follow.target = lap
follow.use_curve_follow = True
follow.use_fixed_location = True
follow.forward_axis, follow.up_axis = "FORWARD_X", "UP_Z"
for f, v in ((1, 0.0), (N + 1, 1.0)):
    follow.offset_factor = v
    RIDER.keyframe_insert('constraints["Follow Path"].offset_factor', frame=f)
linearize(RIDER, cyclic=True)

# steer the cargo box left through both U-turns (trikes don't lean)
turn_len = math.pi * TURN_R
turns = ((X_RIGHT + turn_len / 2) / SPEED,
         (X_RIGHT + turn_len + (X_RIGHT - X_LEFT) + turn_len / 2) / SPEED)
half = turn_len / 2 / SPEED
steer_keys = [(1, 0.0), (N + 1, 0.0)]
for t in turns:
    steer_keys += [(t - half - 6, 0.0), (t - half + 4, 0.5), (t + half - 4, 0.5), (t + half + 6, 0.0)]
for f, v in sorted(steer_keys):
    STEER.rotation_euler[2] = v
    STEER.keyframe_insert("rotation_euler", index=2, frame=f)
linearize(STEER, cyclic=True)
for fc in fcurves_of(STEER):
    for kp in fc.keyframe_points:
        kp.interpolation = "SINE"

# a plump bob with each pedal stroke, plus the classic turkey head-bob
drive(TORSO, "location", 2, f"0.014*sin(2*{CRANK_RATE:.5f}*(frame-1))")
drive(TORSO, "rotation_euler", 0, f"0.035*sin({CRANK_RATE:.5f}*(frame-1))")
# ---- neck rig: 3 bones so the neck bends instead of sliding as a rigid piece.
# The base bone sits inside the feather ruff and barely moves -> stays joined.
CHAIN = [Vector(NECK[0][0]), Vector(NECK[1][0]), Vector(NECK[2][0]), HEAD + Vector((0.07, 0, -0.01))]
NECK_BONES = ["neck.1", "neck.2", "head"]
neck_data = bpy.data.armatures.new("NeckRig")
neck_arm = bpy.data.objects.new("NeckRig", neck_data)
scene.collection.objects.link(neck_arm)
neck_arm.parent = TORSO
neck_arm.show_in_front = True
bpy.context.view_layer.objects.active = neck_arm
bpy.ops.object.mode_set(mode="EDIT")
prev = None
for name, h, t in zip(NECK_BONES, CHAIN, CHAIN[1:]):
    eb = neck_data.edit_bones.new(name)
    eb.head, eb.tail = h, t
    if prev:
        eb.parent, eb.use_connect = prev, True
    prev = eb
bpy.ops.object.mode_set(mode="OBJECT")


def closest_bone(p):
    """(bone index, t along it) of the chain segment nearest to p."""
    best = None
    for i, (a_, b_) in enumerate(zip(CHAIN, CHAIN[1:])):
        ab = b_ - a_
        t = max(0.0, min(1.0, (p - a_).dot(ab) / ab.length_squared))
        d = (a_ + ab * t - p).length
        if best is None or d < best[0]:
            best = (d, i, t)
    return best[1], best[2]


# skin the head/neck mesh with smooth blends across each joint
head_obj.parent = neck_arm
head_obj.matrix_parent_inverse = Matrix.Identity(4)
groups = [head_obj.vertex_groups.new(name=n) for n in NECK_BONES]
BLEND = 0.25
for v in head_obj.data.vertices:
    i, t = closest_bone(v.co)
    w = {i: 1.0}
    if t > 1 - BLEND and i + 1 < len(NECK_BONES):
        w[i] = 1 - 0.5 * (t - (1 - BLEND)) / BLEND
        w[i + 1] = 1 - w[i]
    elif t < BLEND and i > 0:
        w[i] = 0.5 + 0.5 * t / BLEND
        w[i - 1] = 1 - w[i]
    for gi, wt in w.items():
        groups[gi].add([v.index], wt, "REPLACE")
head_obj.modifiers.new("Neck", "ARMATURE").object = neck_arm

# warts, crown knobs, eyes and beak ride on their nearest bone
bpy.context.view_layer.update()
for o in turkey_objs:
    if o.parent != TORSO or o is head_obj:
        continue
    p = o.matrix_local.translation
    i, t = closest_bone(p)
    seg_pt = CHAIN[i].lerp(CHAIN[i + 1], t)
    if (p - seg_pt).length < 0.12 or (p - HEAD).length < 0.16:
        attach(o, neck_arm, NECK_BONES[i])

LOOK = empty("LookAt", (-0.15, LANE_NEAR, 1.0), 0.2)  # keyed with a smoothed path below

# ================================================================ rural Yucatán
M_SASCAB = material("Sascab_Road", (0.88, 0.84, 0.74), rough=0.9)
add_ramp(M_SASCAB, coord(M_SASCAB, "Object", tex="ShaderNodeTexNoise", Scale=6.0, Detail=8.0),
         [(0.3, (0.55, 0.49, 0.4)), (0.55, (0.72, 0.67, 0.57)), (0.75, (0.8, 0.76, 0.66))])
add_bump(M_SASCAB, 80, 0.35)
M_SOIL = material("Kankab_Soil", (0.55, 0.22, 0.1), rough=0.95)
add_ramp(M_SOIL, coord(M_SOIL, "Object", tex="ShaderNodeTexNoise", Scale=0.35, Detail=6.0),
         [(0.35, (0.5, 0.2, 0.08)), (0.5, (0.45, 0.42, 0.15)), (0.65, (0.22, 0.4, 0.08))])
M_LIMESTONE = material("Limestone", (0.8, 0.77, 0.7), rough=0.85)
add_ramp(M_LIMESTONE, coord(M_LIMESTONE, "Object", tex="ShaderNodeTexNoise", Scale=4.0, Detail=6.0),
         [(0.35, (0.32, 0.3, 0.27)), (0.6, (0.6, 0.57, 0.5)), (0.8, (0.74, 0.71, 0.64))])
add_bump(M_LIMESTONE, 25, 0.6)
M_AGAVE = material("Henequen", (0.33, 0.5, 0.44), rough=0.55)
M_BARK = material("Bark", (0.45, 0.42, 0.38), rough=0.9)
add_bump(M_BARK, 20, 0.5)
M_LEAVES = [material(f"Selva{i}", c, rough=0.75, sss=0.15) for i, c in enumerate((
    (0.12, 0.42, 0.08), (0.2, 0.5, 0.1), (0.08, 0.32, 0.1), (0.3, 0.52, 0.12), (0.95, 0.3, 0.05)))]
M_LIMEWASH = material("Limewash", (0.96, 0.94, 0.9), rough=0.8)
M_THATCH = material("Huano_Thatch", (0.62, 0.5, 0.28), rough=0.9)
add_ramp(M_THATCH, coord(M_THATCH, "Object", tex="ShaderNodeTexWave", Scale=18.0, Distortion=6.0,
                         wave_type="BANDS", bands_direction="Z"),
         [(0.0, (0.28, 0.18, 0.07)), (1.0, (0.55, 0.4, 0.16))])
add_bump(M_THATCH, 60, 0.6)
M_WOOD = material("Wood", (0.3, 0.17, 0.08), rough=0.7)
M_HAMMOCK = material("Hammock", (1, 0.2, 0.4), rough=0.8, sheen=0.6)
add_ramp(M_HAMMOCK, coord(M_HAMMOCK, "Object", tex="ShaderNodeTexWave", Scale=5.0, wave_type="BANDS",
                          bands_direction="X"),
         [(0.0, (1.0, 0.15, 0.4)), (0.2, (1.0, 0.8, 0.05)), (0.4, (0.0, 0.6, 0.65)),
          (0.6, (1.0, 0.45, 0.05)), (0.8, (0.5, 0.15, 0.7))], interp="CONSTANT")
M_PYRAMID = material("Pyramid_Stone", (0.55, 0.5, 0.42), rough=0.9)
add_bump(M_PYRAMID, 8, 0.4)
M_CLOUD = material("Cloud", (1, 1, 1), rough=1.0, emit=0.35)
M_TOH_BODY = material("Toh_Green", (0.3, 0.5, 0.22), rough=0.5)
M_TOH_RUST = material("Toh_Rust", (0.7, 0.32, 0.12), rough=0.5)
M_TOH_BLUE = material("Toh_Turquoise", (0.0, 0.7, 0.85), rough=0.3, coat=0.5)

bpy.ops.mesh.primitive_plane_add(size=400)
finish(bpy.context.object, M_SOIL, smooth=False)
bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 0, 0.002))
road = bpy.context.object
road.scale = (400, 3.4, 1)
finish(road, M_SASCAB, smooth=False)

# --- sparse, sun-dried grass (geometry nodes, swaying)
blade = bpy.data.meshes.new("Blade")
bv = [(-0.007, 0, 0), (0.007, 0, 0), (-0.005, 0.012, 0.07), (0.005, 0.012, 0.07), (0, 0.035, 0.14)]
blade.from_pydata(bv, [], [(0, 1, 3, 2), (2, 3, 4)])
uv = blade.uv_layers.new(name="UVMap")
for loop in blade.loops:
    uv.data[loop.index].uv = (0.5, bv[loop.vertex_index][2] / 0.14)
M_BLADE = material("GrassBlade", (0.4, 0.5, 0.15), rough=0.6, sss=0.25)
nt = M_BLADE.node_tree
uvn = nt.nodes.new("ShaderNodeUVMap")
sep = nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(uvn.outputs["UV"], sep.inputs[0])
add_ramp(M_BLADE, sep.outputs["Y"], [(0.0, (0.1, 0.18, 0.03)), (0.5, (0.35, 0.5, 0.1)), (1.0, (0.85, 0.75, 0.35))])
blade.materials.append(M_BLADE)
blade_obj = bpy.data.objects.new("GrassBlade", blade)
scene.collection.objects.link(blade_obj)
blade_obj.hide_render = blade_obj.hide_viewport = True

gn = bpy.data.node_groups.new("Grass", "GeometryNodeTree")
gn.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
gn.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
N_, L_ = gn.nodes.new, gn.links.new
gin, gout = N_("NodeGroupInput"), N_("NodeGroupOutput")
dist = N_("GeometryNodeDistributePointsOnFaces")
dist.inputs["Density"].default_value = 150 if PREVIEW else 700
oinfo = N_("GeometryNodeObjectInfo")
oinfo.inputs["Object"].default_value = blade_obj
iop = N_("GeometryNodeInstanceOnPoints")
rrot = N_("FunctionNodeRandomValue")
rrot.data_type = "FLOAT_VECTOR"
socket(rrot, "Min").default_value = (-0.4, -0.4, 0)
socket(rrot, "Max").default_value = (0.4, 0.4, 6.283)
rscl = N_("FunctionNodeRandomValue")
rscl.data_type = "FLOAT"
socket(rscl, "Min").default_value, socket(rscl, "Max").default_value = 0.5, 1.6
pos, clock = N_("GeometryNodeInputPosition"), N_("GeometryNodeInputSceneTime")
drift = N_("ShaderNodeVectorMath")
drift.operation = "SCALE"
drift.inputs[0].default_value = (0.9, 0.35, 0)
L_(clock.outputs["Seconds"], drift.inputs["Scale"])
moved = N_("ShaderNodeVectorMath")
moved.operation = "ADD"
L_(pos.outputs[0], moved.inputs[0])
L_(drift.outputs[0], moved.inputs[1])
gust = N_("ShaderNodeTexNoise")
gust.inputs["Scale"].default_value = 0.5
L_(moved.outputs[0], gust.inputs["Vector"])
sway = N_("ShaderNodeMath")
sway.operation = "MULTIPLY_ADD"
sway.inputs[1].default_value, sway.inputs[2].default_value = 1.0, -0.5
L_(gust.outputs["Fac"], sway.inputs[0])
tilt = N_("ShaderNodeCombineXYZ")
L_(sway.outputs[0], tilt.inputs["X"])
rot_sum = N_("ShaderNodeVectorMath")
rot_sum.operation = "ADD"
L_(socket(rrot, "Value", True), rot_sum.inputs[0])
L_(tilt.outputs[0], rot_sum.inputs[1])
e2r = N_("FunctionNodeEulerToRotation")
L_(rot_sum.outputs[0], e2r.inputs[0])
joinn = N_("GeometryNodeJoinGeometry")
L_(gin.outputs[0], dist.inputs["Mesh"])
L_(dist.outputs["Points"], iop.inputs["Points"])
L_(oinfo.outputs["Geometry"], iop.inputs["Instance"])
L_(e2r.outputs[0], iop.inputs["Rotation"])
L_(socket(rscl, "Value", True), iop.inputs["Scale"])
L_(gin.outputs[0], joinn.inputs[0])
L_(iop.outputs["Instances"], joinn.inputs[0])
L_(joinn.outputs[0], gout.inputs[0])
for (x0, x1, y0, y1) in ((-15, 15, -4.5, -1.75), (-20, 18, 2.2, 12)):
    bpy.ops.mesh.primitive_plane_add(size=1, location=((x0 + x1) / 2, (y0 + y1) / 2, 0.001))
    strip = bpy.context.object
    strip.scale = (x1 - x0, y1 - y0, 1)
    bpy.ops.object.transform_apply(scale=True)
    strip.name = "Grass"
    finish(strip, M_SOIL, smooth=False)
    strip.modifiers.new("Grass", "NODES").node_group = gn

# --- albarrada: the dry-stacked limestone wall that lines every Yucatecan road
rocks = [template(fluffy(0.14, 0.16, M_LIMESTONE, subdiv=1)) for _ in range(3)]
for r_ in rocks:
    for p_ in r_.polygons:
        p_.use_smooth = False
random.seed(12)
x = -26.0
while x < 22:
    for layer in range(3):
        if layer == 2 and random.random() < 0.3:
            continue
        s_ = random.uniform(0.8, 1.35)
        instance(random.choice(rocks), (x + random.uniform(-0.06, 0.06), 1.95 + random.uniform(-0.07, 0.07),
                                        0.12 + layer * 0.2 + random.uniform(-0.03, 0.03)),
                 (s_ * random.uniform(0.9, 1.3), s_, s_ * random.uniform(0.7, 1.0)),
                 (random.uniform(0, 6), random.uniform(0, 6), random.uniform(0, 6)), name="Albarrada")
    x += random.uniform(0.18, 0.24)

# --- henequén (agave) field in rows behind the wall
leaves = []
random.seed(13)
for i in range(18):
    az = i * 2.39996
    el = math.radians(20 + 55 * (i / 17))
    d = Vector((math.cos(az) * math.cos(el), math.sin(az) * math.cos(el), math.sin(el)))
    bpy.ops.mesh.primitive_cone_add(vertices=4, radius1=0.055, radius2=0.0, depth=1.0, location=d * 0.48)
    leaf = bpy.context.object
    leaf.data.transform(Matrix.Diagonal((1.0, 0.35, 1.0, 1)))
    orient(leaf, d)
    leaves.append(finish(leaf, M_AGAVE, smooth=False))
agave = template(join(leaves, "Agave"))
bpy.ops.object.select_all(action="DESELECT")
for row in range(9 if not PREVIEW else 5):
    for col in range(40):
        ax, ay = -24 + col * 1.15 + random.uniform(-0.15, 0.15), 3.2 + row * 1.25 + random.uniform(-0.1, 0.1)
        if (-8.6 < ax < -2.6 and ay < 8.6) or (-4.3 < ax < -0.5 and ay < 5.2):  # house + hammock yard
            continue  # clearing for the casa maya and ceiba
        k = random.uniform(0.75, 1.2)
        instance(agave, (ax, ay, 0), (k, k, k), (0, 0, random.uniform(0, 6)), name="Henequen")

PYR = Vector((-42, 115, 0))
# --- low selva trees, a flowering flamboyán, and the sacred ceiba
bpy.ops.mesh.primitive_cone_add(vertices=8, radius1=0.12, radius2=0.06, depth=2.0, location=(0, 0, 1.0))
bpy.ops.object.transform_apply(location=True)
trunk = template(finish(bpy.context.object, M_BARK))
crowns = [template(fluffy(0.9, 0.4, m)) for m in M_LEAVES]
random.seed(14)
for _ in range(70):
    tx, ty = random.uniform(-40, 30), random.uniform(15, 38)
    if abs(math.atan2(tx - 2.6, ty + 4.6) - math.atan2(PYR.x - 2.6, PYR.y + 4.6)) < 0.13:
        continue
    k = random.uniform(0.9, 1.8)
    instance(trunk, (tx, ty, 0), (k, k, k), name="Trunk")
    cm = crowns[4] if random.random() < 0.12 else random.choice(crowns[:4])
    for dz, s_ in ((2.1, 1.0), (2.8, 0.7)):
        instance(cm, (tx, ty, dz * k), (k * s_ * 1.3, k * s_ * 1.2, k * s_ * 0.8), (0, 0, random.uniform(0, 6)),
                 name="Crown")

CEIBA = Vector((-15.0, 21.0, 0))
bpy.ops.mesh.primitive_cone_add(vertices=16, radius1=0.6, radius2=0.35, depth=7.0, location=CEIBA + Vector((0, 0, 3.5)))
finish(bpy.context.object, M_BARK)
for i in range(5):  # buttress roots
    a = i * 2 * math.pi / 5
    d = Vector((math.cos(a), math.sin(a), 0))
    ellipsoid(CEIBA + d * 0.6 + Vector((0, 0, 0.5)), (0.12, 0.6, 0.9), M_BARK, direction=d + Vector((0, 0, 1.2)))
for i in range(6):  # horizontal branches, the ceiba's signature layering
    a = i * math.pi / 3 + 0.3
    tip = CEIBA + Vector((math.cos(a) * 3.2, math.sin(a) * 3.2, 7.4 + (i % 2) * 0.6))
    rod(CEIBA + Vector((0, 0, 6.6 + (i % 2) * 0.5)), tip, 0.14, M_BARK, verts=8)
    instance(crowns[0], tip + Vector((0, 0, 0.4)), (2.2, 2.2, 0.75), (0, 0, a), name="CeibaCrown")
instance(crowns[1], CEIBA + Vector((0, 0, 8.2)), (2.6, 2.6, 0.9), name="CeibaCrown")

# --- casas mayas: oval limewashed walls under steep huano palm thatch
def casa_maya(loc, rot):
    before = set(scene.objects)
    bpy.ops.mesh.primitive_cylinder_add(vertices=40, radius=1.0, depth=1.7, location=(0, 0, 0.85))
    wall = bpy.context.object
    wall.scale = (2.1, 1.25, 1)
    finish(wall, M_LIMEWASH)
    bpy.ops.mesh.primitive_cone_add(vertices=40, radius1=1.0, depth=2.2, location=(0, 0, 1.7 + 1.0))
    roof = bpy.context.object
    roof.scale = (2.4, 1.55, 1)
    finish(roof, M_THATCH)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, -1.24, 0.6))
    door = bpy.context.object
    door.scale = (0.7, 0.08, 1.2)
    finish(door, M_WOOD, smooth=False)
    holder = empty("CasaMaya", (0, 0, 0))
    for o in new_objects(before):
        if o is not holder:
            o.parent = holder
    holder.location, holder.rotation_euler = loc, (0, 0, rot)


casa_maya((-5.6, 6.2, 0), math.radians(-8))
casa_maya((-13.5, 11.0, 0), math.radians(15))

# --- a striped Yucatecan hammock slung between two posts by the house
A, B = Vector((-3.6, 4.2, 1.45)), Vector((-1.2, 4.0, 1.45))
for p in (A, B):
    rod((p.x, p.y, 0), (p.x, p.y, 1.8), 0.07, M_WOOD)
nu, nv = 36, 8
verts, faces = [], []
for i in range(nu + 1):
    t = i / nu
    base = A.lerp(B, t)
    for j in range(nv + 1):
        w = j / nv - 0.5
        spread = math.sin(math.pi * t)  # fabric fans out in the middle
        verts.append(base + Vector((0, w * 0.9 * spread, -0.75 * 4 * t * (1 - t) + 0.5 * (w * spread) ** 2)))
for i in range(nu):
    for j in range(nv):
        a = i * (nv + 1) + j
        faces.append((a, a + 1, a + nv + 2, a + nv + 1))
hm = bpy.data.meshes.new("Hammock")
hm.from_pydata(verts, [], faces)
hm.materials.append(M_HAMMOCK)
hammock = bpy.data.objects.new("Hammock", hm)
scene.collection.objects.link(hammock)
hammock.modifiers.new("Thick", "SOLIDIFY").thickness = 0.01
for p in hm.polygons:
    p.use_smooth = True

# --- El Castillo (Chichén Itzá) on the horizon
for i in range(9):
    s_ = 20 - i * 1.8
    bpy.ops.mesh.primitive_cube_add(size=1, location=PYR + Vector((0, 0, 0.8 + i * 1.6)))
    step = bpy.context.object
    step.scale = (s_, s_, 1.6)
    finish(step, M_PYRAMID, smooth=False)
base_half, top_half, height = 10.0, (20 - 8 * 1.8) / 2, 9 * 1.6
slope = math.atan2(height, base_half - top_half)
run = math.hypot(height, base_half - top_half)
for d in (Vector((0, -1, 0)), Vector((1, 0, 0))):  # the two stairways facing us
    bpy.ops.mesh.primitive_cube_add(size=1, location=PYR + d * (base_half + top_half) / 2 + Vector((0, 0, height / 2)))
    stair = bpy.context.object
    if d.x == 0:
        stair.scale, stair.rotation_euler = (3.8, run, 0.9), (slope, 0, 0)
    else:
        stair.scale, stair.rotation_euler = (run, 3.8, 0.9), (0, slope, 0)
    finish(stair, M_PYRAMID, smooth=False)
bpy.ops.mesh.primitive_cube_add(size=1, location=PYR + Vector((0, 0, 16.3)))
temple = bpy.context.object
temple.scale = (5.6, 5.6, 3.6)
finish(temple, M_PYRAMID, smooth=False)

# --- cumulus clouds (drifting) and a toh bird perched on the albarrada
cloud = template(fluffy(1.0, 0.5, M_CLOUD))
sky_drift = empty("CloudDrift", size=2)
random.seed(21)
for _ in range(12):
    cx, cy, cz = random.uniform(-80, 40), random.uniform(50, 95), random.uniform(16, 32)
    for _ in range(8):
        r = random.uniform(2.5, 5.5)
        instance(cloud, (cx + random.uniform(-7, 7), cy + random.uniform(-2, 2), cz + random.uniform(-1, 2.5)),
                 (r * 1.4, r, r * 0.75), (0, 0, random.uniform(0, 6)), name="Cloud").parent = sky_drift
for f, xv in ((1, 0.0), (N + 1, 6.0)):
    sky_drift.location.x = xv
    sky_drift.keyframe_insert("location", index=0, frame=f)
linearize(sky_drift)

TOH = Vector((1.3, 1.95, 0.86))
toh_before = set(scene.objects)
ellipsoid(TOH + Vector((0, 0, 0.07)), (0.045, 0.04, 0.08), M_TOH_BODY, direction=(0.3, -0.2, 1))
ellipsoid(TOH + Vector((0.02, -0.01, 0.06)), (0.035, 0.03, 0.05), M_TOH_RUST, direction=(0.3, -0.2, 1))
ball(TOH + Vector((0.03, -0.02, 0.16)), 0.035, M_TOH_BODY)
for s in (-1, 1):
    ellipsoid(TOH + Vector((0.035, -0.02 + s * 0.028, 0.175)), (0.012, 0.004, 0.022), M_TOH_BLUE, direction=(1, 0, 0))
ball(TOH + Vector((0.055, -0.045, 0.165)), 0.009, M_EYE)
bpy.ops.mesh.primitive_cone_add(vertices=12, radius1=0.012, radius2=0.002, depth=0.06,
                                location=TOH + Vector((0.08, -0.03, 0.155)))
orient(finish(bpy.context.object, M_TIPGOLD), (1, -0.3, -0.2))
tail_root = TOH + Vector((-0.04, 0.01, 0.02))
tail_tip = tail_root + Vector((-0.05, 0.02, -0.26))
for s in (-1, 1):  # two bare shafts ending in turquoise "rackets"
    shaft_tip = tail_tip + Vector((0, s * 0.012, 0))
    rod(tail_root, shaft_tip, 0.003, M_TIRE, verts=6)
    ellipsoid(shaft_tip + Vector((0, 0, 0.025)), (0.016, 0.004, 0.03), M_TOH_BLUE, direction=(0, 0, 1))
toh_pivot = empty("Toh", TOH, 0.1)
bpy.context.view_layer.update()
for o in new_objects(toh_before):
    if o is not toh_pivot:
        attach(o, toh_pivot)
drive(toh_pivot, "rotation_euler", 2, "0.4*sin(frame*0.12)")  # glances around

# ================================================================ sky + light (hot Yucatecan afternoon)
SUN_DIR = Vector((-0.35, -0.75, 0.75)).normalized()  # from the camera side, shadows fall behind

world = bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
wn, wl = world.node_tree.nodes, world.node_tree.links
sky_bg = wn["Background"]
tc = wn.new("ShaderNodeTexCoord")
sep = wn.new("ShaderNodeSeparateXYZ")
wl.new(tc.outputs["Normal"], sep.inputs[0])
ramp = wn.new("ShaderNodeValToRGB")
els = ramp.color_ramp.elements
for _ in range(2):
    els.new(0.5)
for el, (p_, col) in zip(els, [(0.0, (0.7, 0.8, 0.93)), (0.1, (0.42, 0.62, 0.92)),
                               (0.45, (0.18, 0.42, 0.9)), (1.0, (0.08, 0.26, 0.78))]):
    el.position, el.color = p_, (*col, 1)
wl.new(sep.outputs["Z"], ramp.inputs["Fac"])
wl.new(ramp.outputs["Color"], sky_bg.inputs["Color"])
sky_bg.inputs["Strength"].default_value = 0.85

sun_data = bpy.data.lights.new("Sun", "SUN")
sun_data.energy = 3.8
sun_data.color = (1.0, 0.95, 0.86)
sun_data.angle = math.radians(1.0)
sun = bpy.data.objects.new("Sun", sun_data)
sun.rotation_mode = "QUATERNION"
sun.rotation_quaternion = SUN_DIR.to_track_quat("Z", "Y")
scene.collection.objects.link(sun)

bpy.ops.mesh.primitive_cube_add(size=1, location=(-10, 32, 15))
haze = bpy.context.object
haze.name = "Haze"
haze.scale = (110, 90, 30)
M_HAZE = bpy.data.materials.new("Haze")
M_HAZE.use_nodes = True
hn = M_HAZE.node_tree.nodes
hn.remove(hn["Principled BSDF"])
vol = hn.new("ShaderNodeVolumePrincipled")
vol.inputs["Color"].default_value = (0.8, 0.88, 1.0, 1)
vol.inputs["Density"].default_value = 0.0008
vol.inputs["Anisotropy"].default_value = 0.4
M_HAZE.node_tree.links.new(vol.outputs[0], hn["Material Output"].inputs["Volume"])
haze.data.materials.append(M_HAZE)
haze.display_type = "BOUNDS"
haze.hide_select = True

# ================================================================ camera (tracks the rider)
cam_data = bpy.data.cameras.new("Camera")
cam_data.lens = 38
cam_data.dof.use_dof = True
cam_data.dof.focus_object = LOOK
cam_data.dof.aperture_fstop = 5.6
cam = bpy.data.objects.new("Camera", cam_data)
cam.location = (2.6, -4.6, 1.15)
scene.collection.objects.link(cam)
track = cam.constraints.new("TRACK_TO")
track.target = LOOK
track.track_axis, track.up_axis = "TRACK_NEGATIVE_Z", "UP_Y"
scene.camera = cam

# A camera glued to the rider whips around in the U-turns. Instead, sample the
# rider's path, average it over ~1 s, and key LookAt + a sideways camera slide.
seg_len = [(pts[(i + 1) % len(pts)] - pts[i]).length for i in range(len(pts))]
total = sum(seg_len)


def rider_pos(frame):
    d = ((frame - 1) / N % 1.0) * total
    for i, L_ in enumerate(seg_len):
        if d <= L_:
            return pts[i].lerp(pts[(i + 1) % len(pts)], d / L_ if L_ else 0)
        d -= L_
    return pts[0].copy()


WINDOW = FPS  # average over one second either side


def smooth_pos(f):
    return sum((rider_pos(f + k) for k in range(-WINDOW, WINDOW + 1, 2)), Vector()) / (WINDOW + 1)


def cam_at(f):
    avg = smooth_pos(f)
    return Vector((2.6 + 0.6 * avg.x, -4.6 + 0.25 * (avg.y - LANE_NEAR), 1.15))


for f in range(1, N + 2, 3):
    avg = smooth_pos(f)
    LOOK.location = (avg.x - 0.1, avg.y, 1.0)
    LOOK.keyframe_insert("location", frame=f)
    cam.location = cam_at(f)
    cam.keyframe_insert("location", frame=f)
for ob in (LOOK, cam):
    for fc in fcurves_of(ob):
        fc.modifiers.new("CYCLES")

# ---- the turkey turns its neck to look into the camera.
# Pre-computed (not a live constraint) so it never snaps when the camera passes
# behind: the turn is capped at ~100 deg and eases back to forward as the
# camera approaches dead-behind, then the curve is smoothed over time.
MAX_TURN = math.radians(100)


def heading(f):
    d = rider_pos(f + 1) - rider_pos(f - 1)
    return math.atan2(d.y, d.x)


raw = []
for f in range(1, N + 1):
    h = heading(f)
    head_w = rider_pos(f) + Vector((math.cos(h), math.sin(h), 0)) * HEAD.x
    c = cam_at(f)
    rel = (math.atan2(c.y - head_w.y, c.x - head_w.x) - h + math.pi) % (2 * math.pi) - math.pi
    t = max(0.0, (abs(rel) - MAX_TURN) / (math.pi - MAX_TURN))
    raw.append(max(-MAX_TURN, min(MAX_TURN, rel)) * (1 - (3 * t * t - 2 * t ** 3)))
SMOOTH = 6
# yaw split along the chain (base barely turns); the head-bob is a thrust:
# mid-neck pitches forward while the head counter-pitches to stay level
YAW_SHARE = (0.2, 0.35, 0.45)
BOB = 0.16
for pb in neck_arm.pose.bones:
    pb.rotation_mode = "QUATERNION"
rest = {n: neck_data.bones[n].matrix_local.to_3x3() for n in NECK_BONES}
for f in range(1, N + 2, 2):
    i = f - 1
    yaw = sum(raw[(i + k) % N] for k in range(-SMOOTH, SMOOTH + 1)) / (2 * SMOOTH + 1)
    thrust = BOB * math.sin(2 * CRANK_RATE * (f - 1))
    pitch = {"neck.1": 0.0, "neck.2": thrust, "head": -1.1 * thrust}
    for n, share in zip(NECK_BONES, YAW_SHARE):
        r = (Matrix.Rotation(yaw * share, 3, "Z") @ Matrix.Rotation(pitch[n], 3, "Y"))
        pb = neck_arm.pose.bones[n]
        pb.rotation_quaternion = (rest[n].inverted() @ r @ rest[n]).to_quaternion()
        pb.keyframe_insert("rotation_quaternion", frame=f)
for fc in fcurves_of(neck_arm):
    fc.modifiers.new("CYCLES")
print(f"head turn range: {math.degrees(min(raw)):.0f}..{math.degrees(max(raw)):.0f} deg")

# ================================================================ render settings
scene.render.fps = FPS
scene.frame_start, scene.frame_end = 1, N
scene.frame_set(1)
scene.render.use_motion_blur = True
scene.render.motion_blur_shutter = 0.5 if MODE == "anim" else 0.2
scene.view_settings.view_transform = "Standard"
scene.view_settings.look = "High Contrast"
scene.view_settings.exposure = -0.45

if MODE == "still":
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 48 if PREVIEW else 256
    scene.cycles.adaptive_threshold = 0.02
    scene.cycles.use_denoising = True
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = "METAL"
        prefs.get_devices()
        for d in prefs.devices:
            d.use = True
        scene.cycles.device = "GPU"
    except Exception as e:
        print("GPU unavailable, using CPU:", e)
    scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
else:
    scene.render.engine = "BLENDER_EEVEE"
    ee = scene.eevee
    ee.taa_render_samples = 16 if PREVIEW else 48
    ee.use_raytracing = True
    ee.volumetric_end = 150
    scene.render.resolution_x, scene.render.resolution_y = 1280, 720
scene.render.resolution_percentage = 50 if PREVIEW else 100

for screen in bpy.data.screens:
    for area in screen.areas:
        for space in area.spaces:
            if space.type == "VIEW_3D":
                space.shading.type = "MATERIAL"
                space.region_3d.view_perspective = "CAMERA"
                space.overlay.show_extras = False

if MODE != "check":
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT_DIR, "turkey_triciclo.blend"))

if MODE == "still":
    scene.render.filepath = os.path.join(OUT_DIR, "turkey_triciclo.png")
    bpy.ops.render.render(write_still=True)
elif MODE == "check":
    for f in [int(x) for x in os.environ.get("FRAMES", "1").split(",")]:
        scene.frame_set(f)
        scene.render.filepath = os.path.join(OUT_DIR, f"tcheck_{f:04d}.png")
        bpy.ops.render.render(write_still=True)
elif MODE == "anim":
    frames_dir = os.path.join(OUT_DIR, "frames_turkey")
    os.makedirs(frames_dir, exist_ok=True)
    scene.render.filepath = os.path.join(frames_dir, "frame_")
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(animation=True)
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    seq = os.path.join(frames_dir, "frame_%04d.png")
    subprocess.run([ffmpeg, "-y", "-framerate", str(FPS), "-i", seq, "-c:v", "libx264", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    os.path.join(OUT_DIR, "turkey_ride.mp4")], check=True)
    subprocess.run([ffmpeg, "-y", "-framerate", str(FPS), "-i", seq, "-vf",
                    "fps=15,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=192[p];"
                    "[b][p]paletteuse=dither=sierra2_4a", "-loop", "0",
                    os.path.join(OUT_DIR, "turkey_ride.gif")], check=True)
print("done:", MODE)
