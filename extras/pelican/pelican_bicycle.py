"""Procedurally build, animate and render a pelican riding a bicycle at golden hour.

Run:  /Applications/Blender.app/Contents/MacOS/Blender -b -P pelican_bicycle.py
Env:  MODE=still (default)  Cycles still of frame 1        -> pelican_bicycle.png
      MODE=anim             EEVEE animation, 8 s loop      -> frames/ + pelican_ride.mp4
      MODE=check FRAMES=1,60 EEVEE test stills of frames   -> check_0001.png ...
      PREVIEW=1             lighter grass/flowers, lower resolution
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

# ---- animation timing: one lap of the road = one seamless loop
FPS, N = 24, 192                 # 8 second loop
WR = 0.35                        # wheel radius
LANE_NEAR, TURN_R = -0.35, 0.5   # outbound lane y, U-turn radius
X_RIGHT, X_LEFT = 5.0, -5.5      # where the U-turns happen
LAP = (X_RIGHT - 0) + math.pi * TURN_R + (X_RIGHT - X_LEFT) + math.pi * TURN_R + (0 - X_LEFT)
SPEED = LAP / N                  # metres per frame (~3 m/s)
WHEEL_RATE = SPEED / WR          # radians per frame: wheels roll without slipping
CRANK_RATE = 6 * 2 * math.pi / N  # six pedal revolutions per loop -> seamless


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


def coord(mat, kind="Object", axis=None, tex=None, **tex_props):
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
        out = t.outputs["Fac"]
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


def fish(center, direction, length, body_mat, fin_mat):
    d = Vector(direction).normalized()
    side = d.orthogonal().normalized()
    ellipsoid(center, (length * 0.2, length * 0.12, length * 0.5), body_mat, direction=d)
    tail = center + d * length * 0.48
    for tw in (-1, 1):
        fd = (d + side * 0.8 * tw).normalized()
        ellipsoid(tail + fd * length * 0.13, (length * 0.1, length * 0.015, length * 0.16), fin_mat, direction=fd)
    ball(center - d * length * 0.32 + side * length * 0.08 + d.cross(side) * length * 0.1, length * 0.035, M_EYE)


def new_objects(since):
    return [o for o in scene.objects if o not in since]


# ================================================================ palette
# golden-hour: warm key light, teal/magenta accents against oranges & violets
M_FRAME = material("Frame_Teal", (0.0, 0.5, 0.55), rough=0.2, metal=0.3, coat=1.0)
M_TIRE = material("Tire", (0.025, 0.022, 0.02), rough=0.85)
M_CHROME = material("Chrome", (0.9, 0.9, 0.92), rough=0.12, metal=1.0)
M_GOLD = material("Rim_Gold", (1.0, 0.72, 0.3), rough=0.2, metal=1.0)
M_LEATHER = material("Leather", (0.35, 0.16, 0.06), rough=0.55, coat=0.3)
M_CREAM = material("Fender_Cream", (0.95, 0.88, 0.7), rough=0.3, coat=0.8)

M_FEATHER = material("Feather", (0.97, 0.93, 0.87), rough=0.75, sss=0.08, sheen=0.4)
add_bump(M_FEATHER, 180, 0.08)
M_PRIMARY = material("Primaries", (0.04, 0.04, 0.05), rough=0.45, sheen=0.3)
M_BEAK = material("Beak", (1.0, 0.6, 0.1), rough=0.3, sss=0.1, coat=0.4)
add_ramp(M_BEAK, coord(M_BEAK, "Generated", "Z"),
         [(0.0, (0.95, 0.45, 0.5)), (0.45, (1.0, 0.55, 0.12)), (1.0, (1.0, 0.82, 0.2))])
M_POUCH = material("Pouch", (1.0, 0.6, 0.18), rough=0.35, sss=0.25)
M_LEG = material("Leg", (1.0, 0.5, 0.12), rough=0.45, sss=0.1)
M_EYE = material("Eye", (0.01, 0.01, 0.01), rough=0.05)
M_CREST = material("Crest", (1.0, 0.85, 0.35), rough=0.7, sheen=0.5)

M_HELMET = material("Helmet_Magenta", (0.85, 0.03, 0.4), rough=0.15, coat=1.0)
M_STRIPE = material("Stripe_Yellow", (1.0, 0.8, 0.05), rough=0.3, coat=0.5)
M_SHADES = material("Shades_Mirror", (0.1, 0.35, 1.0), rough=0.03, metal=1.0)
M_SCARF = material("Scarf", (0.85, 0.05, 0.1), rough=0.7, sheen=0.6)
add_ramp(M_SCARF, coord(M_SCARF, "Object", tex="ShaderNodeTexWave", Scale=3.0, Distortion=0.0,
                        wave_type="BANDS", bands_direction="X"),
         [(0.0, (0.85, 0.04, 0.1)), (0.55, (1.0, 0.9, 0.75))], interp="CONSTANT")
M_FISH_BLUE = material("Fish_Blue", (0.3, 0.6, 0.95), rough=0.2, metal=0.4)
M_FISH_GOLD = material("Fish_Gold", (1.0, 0.45, 0.05), rough=0.25, metal=0.2)
M_FISH_PINK = material("Fish_Pink", (0.95, 0.5, 0.6), rough=0.25, metal=0.3)
M_FIN = material("Fin", (1.0, 0.75, 0.3), rough=0.4, sss=0.3)
M_FLAG = material("Pennant", (1.0, 0.4, 0.0), rough=0.5, sss=0.2)
M_SPEED = material("SpeedLine", (1.0, 0.95, 0.85), emit=2.5)
M_WICKER = material("Wicker", (0.55, 0.35, 0.15), rough=0.8)
add_ramp(M_WICKER, coord(M_WICKER, "Object", tex="ShaderNodeTexWave", Scale=40.0, Distortion=2.0,
                         wave_type="BANDS", bands_direction="Z"),
         [(0.0, (0.35, 0.2, 0.07)), (1.0, (0.75, 0.52, 0.25))])

# ================================================================ rig roots
# Rider follows the road loop; Lean banks into turns; Torso bobs with pedalling.
RIDER = empty("Rider", size=0.5)
LEAN = empty("Lean", size=0.4)
TORSO = empty("Torso", size=0.3)
LEAN.parent, TORSO.parent = RIDER, LEAN
rigged = set(scene.objects)

# ================================================================ bicycle
REAR, FRONT = Vector((-0.55, 0, WR)), Vector((0.55, 0, WR))
BB = Vector((-0.05, 0, 0.30))
SEAT = Vector((-0.20, 0, 0.84))
HEAD_TOP, HEAD_BOT = Vector((0.42, 0, 0.86)), Vector((0.47, 0, 0.68))
BAR = Vector((0.38, 0, 1.00))

child_of = {}  # object -> (parent, bone) for everything that is not a plain rig child

for c, label in ((REAR, "Rear"), (FRONT, "Front")):
    hub = empty(f"Wheel_{label}", c, 0.4)
    before = set(scene.objects)
    ring(c, WR, 0.03, M_TIRE)
    ring(c, WR - 0.032, 0.012, M_GOLD)
    rod(c + Vector((0, -0.045, 0)), c + Vector((0, 0.045, 0)), 0.022, M_CHROME)
    for i in range(24):
        a = 2 * math.pi * i / 24
        side = 0.035 if i % 2 else -0.035
        tip = c + Vector((math.cos(a), 0, math.sin(a))) * (WR - 0.04)
        rod(c + Vector((0, side, 0)), tip, 0.0028, M_CHROME, verts=6)
    for part in new_objects(before):
        child_of[part] = (hub, None)
    # rolling toward +X = positive rotation about +Y; tied to distance travelled
    drive(hub, "rotation_euler", 1, f"{WHEEL_RATE:.5f}*(frame-1)")

    # cream fender: upper arc of a flattened torus
    bpy.ops.mesh.primitive_torus_add(major_radius=WR + 0.04, minor_radius=0.018,
                                     major_segments=72, minor_segments=10, location=c)
    fender = bpy.context.object
    bm = bmesh.new()
    bm.from_mesh(fender.data)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.y < 0.12], context="VERTS")
    bm.to_mesh(fender.data)
    bm.free()
    fender.data.transform(Matrix.Diagonal((1, 1, 1.8, 1)))
    fender.rotation_euler = (math.radians(90), math.radians(-12 if label == "Rear" else 8), 0)
    finish(fender, M_CREAM)

T = 0.022
rod(BB, SEAT, T, M_FRAME)
rod(BB, HEAD_BOT, T * 1.15, M_FRAME)
rod(SEAT + Vector((0.02, 0, -0.04)), HEAD_TOP, T, M_FRAME)
rod(HEAD_BOT, HEAD_TOP, T * 1.25, M_FRAME)
for s in (-0.05, 0.05):
    rod(BB + Vector((0, s * 0.6, 0)), REAR + Vector((0, s, 0)), T * 0.7, M_FRAME)
    rod(SEAT + Vector((0, 0, -0.04)), REAR + Vector((0, s, 0)), T * 0.7, M_FRAME)
    rod(HEAD_BOT, FRONT + Vector((0, s, 0)), T * 0.8, M_CHROME)
rod(SEAT, SEAT + Vector((-0.02, 0, 0.08)), 0.014, M_CHROME)
rod(HEAD_TOP, BAR, 0.016, M_CHROME)
rod(BAR + Vector((0, -0.26, 0)), BAR + Vector((0, 0.26, 0)), 0.014, M_CHROME)
for s in (-1, 1):
    rod(BAR + Vector((0, s * 0.18, 0)), BAR + Vector((0, s * 0.28, 0)), 0.024, M_LEATHER)
ellipsoid(SEAT + Vector((-0.02, 0, 0.1)), (0.08, 0.035, 0.15), M_LEATHER, direction=(1, 0, 0))
ball(BAR + Vector((0, -0.13, 0.03)), 0.026, M_GOLD)  # bell
ring(REAR + Vector((0, -0.06, 0)), 0.045, 0.006, M_CHROME)
for dz in (0.1, -0.1):
    rod(BB + Vector((0, -0.06, dz)), REAR + Vector((0, -0.06, dz * 0.45)), 0.005, M_TIRE, verts=6)

# crank spins with the pedalling; pedals stay level (they only translate)
CRANK = 0.17
THETA0 = math.radians(-35)
crank = empty("Crank", BB, 0.25)
child_of[ring(BB + Vector((0, -0.06, 0)), 0.1, 0.008, M_CHROME)] = (crank, None)
drive(crank, "rotation_euler", 1, f"{CRANK_RATE:.5f}*(frame-1)")
pedals, foot_targets = {}, {}
for side, ang in ((-1, THETA0), (1, THETA0 + math.pi)):
    p = BB + Vector((CRANK * math.cos(ang), side * 0.12, CRANK * math.sin(ang)))
    child_of[rod(BB + Vector((0, side * 0.08, 0)), p, 0.012, M_CHROME)] = (crank, None)
    ped = empty(f"Pedal_{'R' if side < 0 else 'L'}", p, 0.08)
    angle = f"({ang:.5f}-{CRANK_RATE:.5f}*(frame-1))"
    drive(ped, "location", 0, f"{BB.x:.4f}+{CRANK}*cos{angle}")
    drive(ped, "location", 2, f"{BB.z:.4f}+{CRANK}*sin{angle}")
    bpy.ops.mesh.primitive_cube_add(size=1, location=p + Vector((0, side * 0.03, 0)))
    block = bpy.context.object
    block.scale = (0.09, 0.07, 0.015)
    child_of[finish(block, M_TIRE, smooth=False)] = (ped, None)
    foot = p + Vector((0, side * 0.03, 0.04))
    ft = empty(f"FootTarget_{'R' if side < 0 else 'L'}", foot, 0.05)
    child_of[ft] = (ped, None)
    pedals[side], foot_targets[side] = p, ft

# wicker basket on the front, full of fish
BASKET = Vector((0.6, 0, 0.86))
bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.14, depth=0.17, location=BASKET)
basket = bpy.context.object
bm = bmesh.new()
bm.from_mesh(basket.data)
bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.normal.z > 0.9], context="FACES")
bm.to_mesh(basket.data)
bm.free()
basket.modifiers.new("Wall", "SOLIDIFY").thickness = 0.01
finish(basket, M_WICKER)
bpy.ops.mesh.primitive_torus_add(major_radius=0.14, minor_radius=0.012, location=BASKET + Vector((0, 0, 0.085)))
finish(bpy.context.object, M_WICKER)
rod(BASKET + Vector((-0.14, 0, 0.05)), HEAD_TOP + Vector((0.01, 0, 0.06)), 0.008, M_CHROME)
for (dx, dy, tilt), fm in zip(((-0.04, -0.05, (0.3, -0.4, 1)), (0.05, 0.03, (0.2, 0.3, 1)),
                              (0.0, 0.07, (-0.35, 0.1, 1))), (M_FISH_GOLD, M_FISH_BLUE, M_FISH_PINK)):
    fish(BASKET + Vector((dx, dy, 0.06)), tilt, 0.2, fm, M_FIN)

# pennant on a whippy pole; origin at the pole top so it can flutter
pole_top = REAR + Vector((-0.14, 0.07, 1.65))
rod(REAR + Vector((-0.02, 0.07, 0)), pole_top, 0.006, M_CHROME)
flag_mesh = bpy.data.meshes.new("Pennant")
flag_mesh.from_pydata([(0, 0, 0), (-0.02, 0, -0.26), (-0.42, 0.03, -0.08)], [], [(0, 1, 2)])
flag_mesh.materials.append(M_FLAG)
pennant = bpy.data.objects.new("Pennant", flag_mesh)
pennant.location = pole_top
scene.collection.objects.link(pennant)
drive(pennant, "rotation_euler", 2, "0.35*sin(frame*0.7)")
drive(pennant, "rotation_euler", 0, "0.15*sin(frame*1.3)")

random.seed(3)
for _ in range(10):  # cartoon speed lines trail the bike
    z = random.uniform(0.3, 1.45)
    x0 = random.uniform(-0.95, -1.4)
    rod((x0, random.uniform(-0.3, 0.2), z), (x0 - random.uniform(0.4, 1.0), 0, z), 0.005, M_SPEED, verts=6)

bike_objs = new_objects(rigged)
rigged |= set(bike_objs)

# ================================================================ pelican
BODY = Vector((-0.12, 0, 1.17))
HEAD = Vector((0.12, 0, 1.80))
K = 1 / 0.575  # metaball surface sits at 0.575 x the element size (measured)

mb = bpy.data.metaballs.new("Pelican")
mb.resolution = 0.02
mb.render_resolution = 0.008
mb.threshold = 0.6


def mb_ellipsoid(co, half, direction=(1, 0, 0)):
    e = mb.elements.new()
    e.type = "ELLIPSOID"
    e.co = co
    e.radius = 1.0
    e.size_x, e.size_y, e.size_z = (h * K for h in half)
    e.rotation = aim_quat(direction, axis="X")


def mb_capsule(p1, p2, r):
    p1, p2 = Vector(p1), Vector(p2)
    e = mb.elements.new()
    e.type = "CAPSULE"
    e.co = (p1 + p2) / 2
    e.radius = r * K
    e.size_x = (p2 - p1).length / 2
    e.rotation = aim_quat(p2 - p1, axis="X")


mb_ellipsoid(BODY, (0.31, 0.17, 0.19), (1, 0, 0.45))                       # body
mb_ellipsoid(BODY + Vector((0.13, 0, 0.07)), (0.13, 0.14, 0.15))            # chest
mb_ellipsoid(BODY + Vector((-0.36, 0, -0.02)), (0.14, 0.1, 0.035), (-1, 0, -0.25))  # tail
neck = [((0.05, 0, 1.30), 0.085), ((0.0, 0, 1.46), 0.062), ((0.06, 0, 1.61), 0.052), ((0.11, 0, 1.74), 0.058)]
for (a, ra), (b, rb) in zip(neck, neck[1:]):
    mb_capsule(a, b, (ra + rb) / 2)
mb_ellipsoid(HEAD, (0.12, 0.08, 0.085), (1, 0, 0.1))                        # head

# wings reach forward to the grips (fused into the body blob)
grips = {}
for s in (-1, 1):
    shoulder = BODY + Vector((0.12, s * 0.17, 0.08))
    grip = BAR + Vector((0, s * 0.23, 0.02))
    elbow = shoulder.lerp(grip, 0.5) + Vector((-0.04, s * 0.08, 0.08))
    mb_ellipsoid(shoulder.lerp(elbow, 0.5), ((elbow - shoulder).length * 0.6, 0.06, 0.05), elbow - shoulder)
    mb_ellipsoid(elbow.lerp(grip, 0.5), ((grip - elbow).length * 0.58, 0.045, 0.04), grip - elbow)
    grips[s] = (shoulder, elbow, grip)

pelican = bpy.data.objects.new("Pelican", mb)
scene.collection.objects.link(pelican)
mb.materials.append(M_FEATHER)
# bake the blob to a fixed mesh: metaballs re-tessellate every frame, which
# breaks motion-blur vectors (vertex counts change) and costs time per frame
mb.resolution = mb.render_resolution
bpy.ops.object.select_all(action="DESELECT")
pelican.select_set(True)
bpy.context.view_layer.objects.active = pelican
bpy.ops.object.convert(target="MESH")
pelican = bpy.context.object
pelican.name = "Pelican"
for poly in pelican.data.polygons:
    poly.use_smooth = True

for s in (-1, 1):
    shoulder, elbow, grip = grips[s]
    # black flight feathers hanging from the forearm like a sleeve
    for k in range(6):
        t = 0.1 + k * 0.15
        root = elbow.lerp(grip, t) if k > 1 else shoulder.lerp(elbow, 0.5 + t)
        fd = Vector((-0.6 - k * 0.05, s * 0.25, -1.0))
        ellipsoid(root + fd.normalized() * 0.07, (0.03, 0.008, 0.1 - k * 0.006), M_PRIMARY, direction=fd)
    for off in (-0.03, 0.0, 0.03):  # feather "fingers" wrapped over the grip
        tip = grip + Vector((0.06, s * 0.02, off))
        ellipsoid(grip.lerp(tip, 0.3), (0.02, 0.012, 0.09), M_PRIMARY, direction=tip - grip)
    ellipsoid(BODY + Vector((-0.28, s * 0.17, 0.02)), (0.045, 0.02, 0.22), M_PRIMARY, direction=(-1, 0, -0.35))

# legs: mesh pieces that get bound to an IK armature further down
legs, leg_parts = {}, {}
for s in (-1, 1):
    hip = BODY + Vector((0.02, s * 0.12, -0.15))
    foot = foot_targets[s].location.copy()
    kn = knee(hip, foot, 0.46, 0.42, forward=Vector((1, 0, 0.3)))
    thigh = [ellipsoid(hip.lerp(kn, 0.35), (0.06, 0.055, 0.16), M_FEATHER, direction=kn - hip),
             rod(hip.lerp(kn, 0.5), kn, 0.022, M_LEG), ball(kn, 0.028, M_LEG)]
    shin = [rod(kn, foot, 0.02, M_LEG)]
    toes = [rod(foot, foot + Vector((0.1 * math.cos(a), 0.1 * math.sin(a), -0.01)), 0.012, M_LEG, verts=8)
            for a in (math.radians(-25), 0, math.radians(25))]
    toes.append(ellipsoid(foot + Vector((0.05, 0, -0.01)), (0.08, 0.05, 0.006), M_LEG))
    legs[s] = (hip, kn, foot)
    leg_parts[s] = (thigh, shin, toes)
    for o in toes:
        child_of[o] = (foot_targets[s], None)

ellipsoid(HEAD + Vector((-0.1, 0, 0.05)), (0.03, 0.025, 0.09), M_CREST, direction=(-1, 0, 0.5))

# beak + pouch
beak_start = HEAD + Vector((0.08, 0, -0.02))
beak_tip = Vector((0.72, 0, 1.58))
beak_dir = beak_tip - beak_start
L = beak_dir.length
zb = beak_dir.normalized()
xb = Vector((0, 0, 1)).cross(zb).normalized()
basis = Matrix((xb, zb.cross(xb), zb)).transposed().to_quaternion()
bpy.ops.mesh.primitive_cone_add(vertices=32, radius1=1, radius2=0.35, depth=1, location=(beak_start + beak_tip) / 2)
beak = bpy.context.object
beak.data.transform(Matrix.Diagonal((0.035, 0.045, L, 1)))
beak.rotation_mode = "QUATERNION"
beak.rotation_quaternion = basis
finish(beak, M_BEAK)
ball(beak_tip + Vector((0.005, 0, -0.012)), 0.02, M_LEG)
pouch_c = beak_start.lerp(beak_tip, 0.5) + Vector((0, 0, -0.075))
bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=1, location=pouch_c)
pouch = bpy.context.object
pouch.data.transform(Matrix.Diagonal((0.08, 0.042, L * 0.5, 1)))
pouch.rotation_mode = "QUATERNION"
pouch.rotation_quaternion = basis
finish(pouch, M_POUCH)
fish(pouch_c + Vector((0.06, -0.1, 0.03)), (-0.1, -1, 0.35), 0.22, M_FISH_BLUE, M_FIN)

# helmet, shades, scarf
bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=1, location=HEAD + Vector((-0.015, 0, 0.03)))
helmet = bpy.context.object
bm = bmesh.new()
bm.from_mesh(helmet.data)
bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < -0.1], context="VERTS")
bm.to_mesh(helmet.data)
bm.free()
helmet.data.transform(Matrix.Diagonal((0.15, 0.105, 0.11, 1)))
helmet.rotation_euler = (0, math.radians(12), 0)
finish(helmet, M_HELMET)
helmet.modifiers.new("Solid", "SOLIDIFY").thickness = 0.01
ellipsoid(HEAD + Vector((-0.02, 0, 0.055)), (0.155, 0.022, 0.1), M_STRIPE)
for s in (-1, 1):
    rod(HEAD + Vector((0.0, s * 0.1, 0.0)), HEAD + Vector((0.06, s * 0.05, -0.1)), 0.006, M_TIRE)
    eye = HEAD + Vector((0.045, s * 0.085, 0.03))
    rod(eye, eye + Vector((0, s * 0.012, 0)), 0.046, M_SHADES, verts=24)
    rod(eye + Vector((-0.03, 0, 0.01)), eye + Vector((-0.12, -s * 0.01, 0.02)), 0.005, M_TIRE)
rod(HEAD + Vector((0.08, -0.09, 0.05)), HEAD + Vector((0.08, 0.09, 0.05)), 0.006, M_TIRE)

bpy.ops.mesh.primitive_torus_add(major_radius=0.085, minor_radius=0.035, location=(0.01, 0, 1.42))
collar = bpy.context.object
collar.rotation_euler = (0, math.radians(-15), 0)
finish(collar, M_SCARF)
sc = bpy.data.curves.new("ScarfTail", "CURVE")
sc.dimensions = "3D"
sc.bevel_depth = 0.02
sc.extrude = 0.05
sc.resolution_u = 24
sp = sc.splines.new("BEZIER")
tail_pts = [(-0.06, -0.04, 1.42), (-0.35, -0.10, 1.50), (-0.65, -0.05, 1.40), (-0.95, -0.14, 1.52), (-1.25, -0.08, 1.43)]
sp.bezier_points.add(len(tail_pts) - 1)
for i, (bp, co) in enumerate(zip(sp.bezier_points, tail_pts)):
    bp.co = co
    bp.handle_left_type = bp.handle_right_type = "AUTO"
    if i:  # a travelling wave, growing toward the free end
        drive(sc, f"splines[0].bezier_points[{i}].co", 2, f"{co[2]}+{0.025 * i:.3f}*sin(frame*0.55-{i * 1.2:.2f})")
        drive(sc, f"splines[0].bezier_points[{i}].co", 1, f"{co[1]}+{0.018 * i:.3f}*cos(frame*0.4-{i * 0.9:.2f})")
scarf = bpy.data.objects.new("ScarfTail", sc)
scene.collection.objects.link(scarf)
sc.materials.append(M_SCARF)

pelican_objs = new_objects(rigged)

# ================================================================ rig assembly
bpy.context.view_layer.update()
for o in bike_objs:
    if o not in child_of:
        child_of[o] = (LEAN, None)
for o in pelican_objs:
    if o not in child_of and not any(o in part for s in (-1, 1) for part in leg_parts[s][:2]):
        child_of[o] = (TORSO, None)
for o, (parent, bone) in child_of.items():
    attach(o, parent, bone)

# leg armature: thigh + shin per side, IK to the foot targets riding on the pedals
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
    pole.parent = LEAN
    ik = arm.pose.bones[f"shin.{S}"].constraints.new("IK")
    ik.target = foot_targets[s]
    ik.pole_target = pole
    ik.chain_count = 2
    iks.append(ik)


def knee_error():
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    ev = arm.evaluated_get(dg)
    err = sum((ev.matrix_world @ ev.pose.bones[f"thigh.{S}"].tail - legs[s][1]).length
              for s, S in ((-1, "R"), (1, "L")))
    return err


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

# ---- the lap: a stadium-shaped loop, outbound near lane, back on the far lane
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

# bank left into both U-turns (negative X rotation tips the top toward +Y)
turn1 = (X_RIGHT + math.pi * TURN_R / 2) / SPEED
turn2 = (X_RIGHT + math.pi * TURN_R + (X_RIGHT - X_LEFT) + math.pi * TURN_R / 2) / SPEED
LEAN.rotation_euler = (0, 0, 0)
lean_keys = [(1, 0.0), (N + 1, 0.0)]
for t in (turn1, turn2):
    lean_keys += [(t - 14, 0.0), (t, -0.3), (t + 14, 0.0)]
for f, v in sorted(lean_keys):
    LEAN.rotation_euler[0] = v
    LEAN.keyframe_insert("rotation_euler", index=0, frame=f + 1)
linearize(LEAN, cyclic=True)
for fc in fcurves_of(LEAN):
    for kp in fc.keyframe_points:
        kp.interpolation = "SINE"

# body bobs twice per pedal revolution, with a slight sway
drive(TORSO, "location", 2, f"0.012*sin(2*{CRANK_RATE:.5f}*(frame-1))")
drive(TORSO, "rotation_euler", 0, f"0.03*sin({CRANK_RATE:.5f}*(frame-1))")

LOOK = empty("LookAt", (-0.1, 0, 1.08), 0.2)
LOOK.parent = RIDER

# ================================================================ environment
M_GROUND = material("Meadow", (0.25, 0.45, 0.08), rough=0.95)
add_ramp(M_GROUND, coord(M_GROUND, "Object", tex="ShaderNodeTexNoise", Scale=0.25, Detail=6.0),
         [(0.35, (0.12, 0.3, 0.04)), (0.55, (0.3, 0.48, 0.08)), (0.7, (0.6, 0.55, 0.15))])
M_ROAD = material("Asphalt", (0.12, 0.12, 0.13), rough=0.8)
add_ramp(M_ROAD, coord(M_ROAD, "Object", tex="ShaderNodeTexNoise", Scale=40.0, Detail=8.0),
         [(0.3, (0.06, 0.06, 0.07)), (0.7, (0.2, 0.19, 0.2))])
add_bump(M_ROAD, 300, 0.25)
M_LINE_Y = material("Line_Yellow", (1.0, 0.75, 0.1), rough=0.6)
M_LINE_W = material("Line_White", (0.95, 0.95, 0.92), rough=0.6)
M_HILL = [material(f"Hill{i}", c, rough=0.9) for i, c in
          enumerate(((0.35, 0.5, 0.1), (0.55, 0.5, 0.12), (0.2, 0.4, 0.12)))]
M_ROCK = material("Mountain", (0.42, 0.33, 0.6), rough=0.9)
M_SNOW = material("Snow", (1.0, 0.88, 0.85), rough=0.6)
M_BARK = material("Bark", (0.25, 0.14, 0.07), rough=0.9)
add_bump(M_BARK, 30, 0.5)
M_LEAF = [material(f"Leaves{i}", c, rough=0.75, sss=0.15) for i, c in enumerate((
    (0.95, 0.38, 0.03), (0.8, 0.1, 0.04), (1.0, 0.68, 0.08), (0.25, 0.5, 0.08), (0.08, 0.33, 0.1)))]
M_CLOUD = material("Cloud", (1.0, 0.62, 0.7), rough=1.0, emit=0.5)
M_PAINT = material("Paint", (0.96, 0.95, 0.92), rough=0.45)
M_BIRD = material("Bird", (0.08, 0.04, 0.1), rough=0.8)
M_SIGN = material("Sign_Blue", (0.03, 0.12, 0.45), rough=0.35, coat=0.6)
PETALS = [material(f"Petal{i}", c, rough=0.5, sss=0.3) for i, c in enumerate(
    ((1, 0.1, 0.35), (1, 0.85, 0.05), (0.55, 0.2, 1), (1, 1, 1), (1, 0.45, 0.05), (0.2, 0.5, 1)))]
M_POLLEN = material("Pollen", (0.9, 0.55, 0.05), rough=0.8)

bpy.ops.mesh.primitive_plane_add(size=400)
finish(bpy.context.object, M_GROUND, smooth=False)
bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 0, 0.002))
road = bpy.context.object
road.scale = (400, 1.7, 1)
finish(road, M_ROAD, smooth=False)
bpy.ops.mesh.primitive_plane_add(size=1)
dash = template(finish(bpy.context.object, M_LINE_Y, smooth=False))
for i in range(-40, 15):
    instance(dash, (i * 1.6, 0.15, 0.004), (0.7, 0.06, 1), name="Dash")
for y in (-0.78, 0.78):
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, y, 0.004))
    edge = bpy.context.object
    edge.scale = (400, 0.06, 1)
    finish(edge, M_LINE_W, smooth=False)

# --- grass blades scattered with geometry nodes, swaying in a noise "wind"
blade = bpy.data.meshes.new("Blade")
bv = [(-0.007, 0, 0), (0.007, 0, 0), (-0.005, 0.012, 0.07), (0.005, 0.012, 0.07), (0, 0.035, 0.14)]
blade.from_pydata(bv, [], [(0, 1, 3, 2), (2, 3, 4)])
uv = blade.uv_layers.new(name="UVMap")
for loop in blade.loops:
    uv.data[loop.index].uv = (0.5, bv[loop.vertex_index][2] / 0.14)
M_BLADE = material("GrassBlade", (0.3, 0.55, 0.1), rough=0.6, sss=0.25)
nt = M_BLADE.node_tree
uvn = nt.nodes.new("ShaderNodeUVMap")
sep = nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(uvn.outputs["UV"], sep.inputs[0])
rmp = add_ramp(M_BLADE, sep.outputs["Y"],
               [(0.0, (0.03, 0.12, 0.02)), (0.5, (0.22, 0.5, 0.06)), (1.0, (0.75, 0.75, 0.2))])
info = nt.nodes.new("ShaderNodeObjectInfo")
hsv = nt.nodes.new("ShaderNodeHueSaturation")
mh = nt.nodes.new("ShaderNodeMath")
mh.operation = "MULTIPLY_ADD"
mh.inputs[1].default_value, mh.inputs[2].default_value = 0.1, 0.45
mv = nt.nodes.new("ShaderNodeMath")
mv.operation = "MULTIPLY_ADD"
mv.inputs[1].default_value, mv.inputs[2].default_value = 0.6, 0.7
nt.links.new(info.outputs["Random"], mh.inputs[0])
nt.links.new(info.outputs["Random"], mv.inputs[0])
nt.links.new(mh.outputs[0], hsv.inputs["Hue"])
nt.links.new(mv.outputs[0], hsv.inputs["Value"])
nt.links.new(rmp.outputs["Color"], hsv.inputs["Color"])
nt.links.new(hsv.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
blade.materials.append(M_BLADE)
blade_obj = bpy.data.objects.new("GrassBlade", blade)
scene.collection.objects.link(blade_obj)
blade_obj.hide_render = True
blade_obj.hide_viewport = True


def socket(node, name, outputs=False):
    pool = node.outputs if outputs else node.inputs
    return [s for s in pool if s.name == name and s.enabled][0]


gn = bpy.data.node_groups.new("Grass", "GeometryNodeTree")
gn.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
gn.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
N_ = gn.nodes.new
L_ = gn.links.new
gin, gout = N_("NodeGroupInput"), N_("NodeGroupOutput")
dist = N_("GeometryNodeDistributePointsOnFaces")
dist.inputs["Density"].default_value = 250 if PREVIEW else 1200
oinfo = N_("GeometryNodeObjectInfo")
oinfo.inputs["Object"].default_value = blade_obj
iop = N_("GeometryNodeInstanceOnPoints")
rrot = N_("FunctionNodeRandomValue")
rrot.data_type = "FLOAT_VECTOR"
socket(rrot, "Min").default_value = (-0.35, -0.35, 0)
socket(rrot, "Max").default_value = (0.35, 0.35, 6.283)
rscl = N_("FunctionNodeRandomValue")
rscl.data_type = "FLOAT"
socket(rscl, "Min").default_value = 0.6
socket(rscl, "Max").default_value = 1.8
# wind: noise sampled at (position + drifting offset) tilts each blade
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
sway.inputs[1].default_value, sway.inputs[2].default_value = 1.2, -0.6
L_(gust.outputs["Fac"], sway.inputs[0])
tilt = N_("ShaderNodeCombineXYZ")
L_(sway.outputs[0], tilt.inputs["X"])
rot_sum = N_("ShaderNodeVectorMath")
rot_sum.operation = "ADD"
L_(socket(rrot, "Value", True), rot_sum.inputs[0])
L_(tilt.outputs[0], rot_sum.inputs[1])
joinn = N_("GeometryNodeJoinGeometry")
L_(gin.outputs[0], dist.inputs["Mesh"])
L_(dist.outputs["Points"], iop.inputs["Points"])
L_(oinfo.outputs["Geometry"], iop.inputs["Instance"])
try:
    e2r = N_("FunctionNodeEulerToRotation")
    L_(rot_sum.outputs[0], e2r.inputs[0])
    L_(e2r.outputs[0], iop.inputs["Rotation"])
except RuntimeError:
    L_(rot_sum.outputs[0], iop.inputs["Rotation"])
L_(socket(rscl, "Value", True), iop.inputs["Scale"])
L_(gin.outputs[0], joinn.inputs[0])
L_(iop.outputs["Instances"], joinn.inputs[0])
L_(joinn.outputs[0], gout.inputs[0])

for (x0, x1, y0, y1) in ((-11, 10, -4.5, -0.85), (-16, 12, 0.85, 9.0)):
    bpy.ops.mesh.primitive_plane_add(size=1, location=((x0 + x1) / 2, (y0 + y1) / 2, 0.001))
    strip = bpy.context.object
    strip.scale = (x1 - x0, y1 - y0, 1)
    bpy.ops.object.transform_apply(scale=True)
    strip.name = "Meadow"
    finish(strip, M_GROUND, smooth=False)
    strip.modifiers.new("Grass", "NODES").node_group = gn

# --- wildflowers (petal ring + pollen center) instanced in the meadow
bpy.ops.mesh.primitive_cylinder_add(vertices=5, radius=0.007, depth=0.3, location=(0, 0, 0.15))
stem = template(finish(bpy.context.object, M_BLADE))
flower_heads = []
for pm in PETALS:
    parts = []
    for k in range(6):
        a = k * math.pi / 3
        d = Vector((math.cos(a), math.sin(a), 0.25))
        parts.append(ellipsoid(d * 0.028, (0.018, 0.005, 0.03), pm, direction=d))
    parts.append(ball((0, 0, 0.004), 0.014, M_POLLEN))
    flower_heads.append(template(join(parts, "Flower")))
random.seed(9)
for _ in range(110 if PREVIEW else 550):
    fy = random.choice((random.uniform(-4.4, -0.95), random.uniform(1.6, 8.5)))
    fx = random.uniform(-14, 9)
    k = random.uniform(0.8, 1.3)
    instance(stem, (fx, fy, 0), (1, 1, k), name="Stem")
    instance(random.choice(flower_heads), (fx, fy, 0.3 * k), (1.2, 1.2, 1.2),
             (random.uniform(-0.3, 0.3), random.uniform(-0.3, 0.3), random.uniform(0, 6)), name="Bloom")

# --- hills, mountains
bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=1)
hill_mesh = [template(finish(bpy.context.object, M_HILL[0]))]
for m in M_HILL[1:]:
    hm = hill_mesh[0].copy()
    hm.materials[0] = m
    hill_mesh.append(hm)
random.seed(11)
for i in range(10):
    instance(hill_mesh[i % 3], (random.uniform(-50, 25), random.uniform(22, 50), -random.uniform(1, 3)),
             (random.uniform(10, 18), random.uniform(6, 10), random.uniform(4, 8)), name="Hill")
for i, (mx, my, h) in enumerate(((-60, 95, 26), (-25, 115, 36), (12, 100, 24), (45, 125, 32), (-90, 125, 30))):
    bpy.ops.mesh.primitive_cone_add(vertices=7, radius1=h * 1.1, depth=h, location=(mx, my, h / 2))
    finish(bpy.context.object, M_ROCK, smooth=False).rotation_euler = (0, 0, i)
    bpy.ops.mesh.primitive_cone_add(vertices=7, radius1=h * 0.33 + 0.4, depth=h * 0.3 + 0.1, location=(mx, my, h * 0.85 + 0.05))
    finish(bpy.context.object, M_SNOW, smooth=False).rotation_euler = (0, 0, i)

# --- fluffy autumn trees
bpy.ops.mesh.primitive_cone_add(vertices=10, radius1=0.16, radius2=0.08, depth=1.4, location=(0, 0, 0.7))
trunk = template(finish(bpy.context.object, M_BARK))
crowns = [template(fluffy(0.8, 0.35, m)) for m in M_LEAF]
random.seed(5)
spots = [(random.uniform(-26, 16), random.uniform(7, 26)) for _ in range(50)]
spots = [(x, y) for x, y in spots if not (-13 < x < -3 and y < 13)]
spots += [(random.uniform(-14, 10), random.uniform(-10, -6)) for _ in range(7)]
for tx, ty in spots:
    k = random.uniform(0.8, 1.7)
    instance(trunk, (tx, ty, 0), (k, k, k), name="Trunk")
    cm = random.choice(crowns + crowns[3:])  # extra greens for contrast
    for dz, s_, dx in ((1.6, 1.0, 0.0), (2.3, 0.78, 0.15), (2.9, 0.52, -0.1)):
        instance(cm, (tx + dx * k, ty, dz * k), (k * s_ * 1.05, k * s_, k * s_ * 0.95),
                 (0, 0, random.uniform(0, 6)), name="Crown")

# --- picket fence and swinging bunting
bpy.ops.mesh.primitive_cube_add(size=1)
post = template(finish(bpy.context.object, M_PAINT, smooth=False))
bpy.ops.mesh.primitive_cone_add(vertices=4, radius1=0.045, depth=0.06)
cap = template(finish(bpy.context.object, M_PAINT, smooth=False))
for i in range(-60, 45):
    x = i * 0.35
    instance(post, (x, 1.45, 0.3), (0.06, 0.04, 0.6), name="Picket")
    instance(cap, (x, 1.45, 0.63), (1, 0.7, 1), (0, 0, math.pi / 4), name="PicketCap")
for z in (0.2, 0.45):
    instance(post, (-2.8, 1.47, z), (36.5, 0.03, 0.06), name="Rail")

tri = bpy.data.meshes.new("Bunting")
tri.from_pydata([(-0.1, 0, 0), (0.1, 0, 0), (0, 0, -0.22)], [], [(0, 1, 2)])
FLAG_MATS = [M_SCARF, M_STRIPE, M_SHADES, M_LEAF[3], M_FLAG, PETALS[2], M_HELMET]
bunting = []
for m in FLAG_MATS:
    t = tri.copy()
    t.materials.clear()
    t.materials.append(m)
    bunting.append(t)
poles = [0.0, 3.0, 6.0, 9.0]
for px in poles:
    rod((px, 1.7, 0), (px, 1.7, 2.3), 0.035, M_PAINT)
    ball((px, 1.7, 2.33), 0.06, M_GOLD)
n = 0
for a, b in zip(poles, poles[1:]):
    for j in range(11):
        t = (j + 0.5) / 11
        flag = instance(bunting[n % len(bunting)], (a + (b - a) * t, 1.7, 2.2 - 1.8 * t * (1 - t)), name="Flag")
        drive(flag, "rotation_euler", 0, f"0.35*sin(frame*0.22+{n * 0.6:.2f})")
        n += 1
    pts_ = [Vector((a + (b - a) * t, 1.7, 2.2 - 1.8 * t * (1 - t))) for t in (0, 0.25, 0.5, 0.75, 1)]
    for p0, p1 in zip(pts_, pts_[1:]):
        rod(p0, p1, 0.006, M_TIRE, verts=6)

# --- drifting clouds, flapping birds
cloud = template(fluffy(1.0, 0.5, M_CLOUD, subdiv=3))
sky_drift = empty("CloudDrift", size=2)
random.seed(21)
for _ in range(10):
    cx, cy, cz = random.uniform(-70, 25), random.uniform(45, 85), random.uniform(12, 26)
    for _ in range(7):
        r = random.uniform(2.5, 5)
        instance(cloud, (cx + random.uniform(-6, 6), cy + random.uniform(-2, 2), cz + random.uniform(-1, 1.5)),
                 (r * 1.4, r, r * 0.6), (0, 0, random.uniform(0, 6)), name="Cloud").parent = sky_drift
for f, x in ((1, 0.0), (N + 1, 6.0)):
    sky_drift.location.x = x
    sky_drift.keyframe_insert("location", index=0, frame=f)
linearize(sky_drift)
for fc in fcurves_of(sky_drift):
    fc.extrapolation = "LINEAR"

bpy.context.view_layer.update()
for i, (bx, bz) in enumerate(((-6, 6.0), (-5.2, 6.5), (-4.5, 5.8), (-7, 6.8), (-3.6, 6.3))):
    b = Vector((bx, 14, bz))
    bird = empty(f"Bird{i}", b, 0.2)
    for s in (-1, 1):
        hinge = empty(f"Bird{i}_wing", b, 0.05)
        wing = rod(b, b + Vector((s * 0.35, 0, 0.14)), 0.03, M_BIRD, verts=6)
        bpy.context.view_layer.update()
        attach(wing, hinge)
        hinge.parent = bird
        hinge.location = (0, 0, 0)
        drive(hinge, "rotation_euler", 1, f"{-s}*0.6*sin(frame*0.9+{i:.1f})")
    for f, x in ((1, bx), (N + 1, bx + 14)):
        bird.location.x = x
        bird.keyframe_insert("location", index=0, frame=f)
    linearize(bird)

# --- billboard
sign_loc = Vector((-7.5, 6.5, 0))
rz = math.radians(28)
for dx in (-2.2, 2.2):
    off = Vector((dx * math.cos(rz), dx * math.sin(rz), 0))
    rod(sign_loc + off, sign_loc + off + Vector((0, 0, 3.0)), 0.08, M_BARK)
bpy.ops.mesh.primitive_cube_add(size=1, location=sign_loc + Vector((0, 0.1, 3.4)))
frame_ = bpy.context.object
frame_.scale = (5.6, 0.08, 1.6)
frame_.rotation_euler = (0, 0, rz)
finish(frame_, M_STRIPE, smooth=False)
bpy.ops.mesh.primitive_cube_add(size=1, location=sign_loc + Vector((-0.03, 0.05, 3.4)))
board = bpy.context.object
board.scale = (5.4, 0.1, 1.4)
board.rotation_euler = (0, 0, rz)
finish(board, M_SIGN, smooth=False)
bpy.ops.object.text_add(location=sign_loc + Vector((-0.02, -0.03, 3.18)))
txt = bpy.context.object
txt.data.body = "TOUR DE PELICAN"
txt.data.align_x = "CENTER"
txt.data.size = 0.62
txt.data.extrude = 0.03
txt.data.bevel_depth = 0.008
txt.rotation_euler = (math.radians(90), 0, rz)
txt.data.materials.append(M_STRIPE)

# ================================================================ sky + light
SUN_DIR = Vector((-0.7, 0.7, 0.16)).normalized()   # low sun, back-left: warm rim light

world = bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
wt = world.node_tree
wn, wl = wt.nodes, wt.links
out = wn["World Output"]
sky_bg = wn["Background"]
tc = wn.new("ShaderNodeTexCoord")
sep = wn.new("ShaderNodeSeparateXYZ")
wl.new(tc.outputs["Normal"], sep.inputs[0])
ramp = wn.new("ShaderNodeValToRGB")
els = ramp.color_ramp.elements
for _ in range(3):
    els.new(0.5)
for el, (pos_, col) in zip(els, [(0.0, (1.0, 0.6, 0.3)), (0.06, (1.0, 0.45, 0.45)),
                                 (0.16, (0.7, 0.4, 0.75)), (0.32, (0.3, 0.35, 0.8)), (0.7, (0.08, 0.15, 0.5))]):
    el.position, el.color = pos_, (*col, 1)
wl.new(sep.outputs["Z"], ramp.inputs["Fac"])
wl.new(ramp.outputs["Color"], sky_bg.inputs["Color"])
sky_bg.inputs["Strength"].default_value = 0.9

dot = wn.new("ShaderNodeVectorMath")
dot.operation = "DOT_PRODUCT"
dot.inputs[1].default_value = SUN_DIR
wl.new(tc.outputs["Normal"], dot.inputs[0])
clamp = wn.new("ShaderNodeMath")
clamp.operation = "MAXIMUM"
clamp.inputs[1].default_value = 0.0
wl.new(dot.outputs["Value"], clamp.inputs[0])
glow_pow = wn.new("ShaderNodeMath")
glow_pow.operation = "POWER"
glow_pow.inputs[1].default_value = 90.0
wl.new(clamp.outputs[0], glow_pow.inputs[0])
glow = wn.new("ShaderNodeBackground")
glow.inputs["Color"].default_value = (1.0, 0.55, 0.2, 1)
glow_amt = wn.new("ShaderNodeMath")
glow_amt.operation = "MULTIPLY"
glow_amt.inputs[1].default_value = 2.0
wl.new(glow_pow.outputs[0], glow_amt.inputs[0])
wl.new(glow_amt.outputs[0], glow.inputs["Strength"])
disc_gt = wn.new("ShaderNodeMath")
disc_gt.operation = "GREATER_THAN"
disc_gt.inputs[1].default_value = 0.99965
wl.new(dot.outputs["Value"], disc_gt.inputs[0])
disc_amt = wn.new("ShaderNodeMath")
disc_amt.operation = "MULTIPLY"
disc_amt.inputs[1].default_value = 60.0
wl.new(disc_gt.outputs[0], disc_amt.inputs[0])
disc = wn.new("ShaderNodeBackground")
disc.inputs["Color"].default_value = (1.0, 0.85, 0.6, 1)
wl.new(disc_amt.outputs[0], disc.inputs["Strength"])
add1, add2 = wn.new("ShaderNodeAddShader"), wn.new("ShaderNodeAddShader")
wl.new(sky_bg.outputs[0], add1.inputs[0])
wl.new(glow.outputs[0], add1.inputs[1])
wl.new(add1.outputs[0], add2.inputs[0])
wl.new(disc.outputs[0], add2.inputs[1])
wl.new(add2.outputs[0], out.inputs["Surface"])

sun_data = bpy.data.lights.new("Sun", "SUN")
sun_data.energy = 4.0
sun_data.color = (1.0, 0.82, 0.62)
sun_data.angle = math.radians(1.5)
sun = bpy.data.objects.new("Sun", sun_data)
sun.rotation_mode = "QUATERNION"
sun.rotation_quaternion = SUN_DIR.to_track_quat("Z", "Y")  # light travels along -Z
scene.collection.objects.link(sun)

fill_data = bpy.data.lights.new("Fill", "AREA")
fill_data.energy = 900
fill_data.size = 5
fill_data.color = (0.75, 0.82, 1.0)
fill = bpy.data.objects.new("Fill", fill_data)
fill.location = (4.5, -6.5, 3.5)
scene.collection.objects.link(fill)
fc = fill.constraints.new("TRACK_TO")
fc.target = LOOK
fc.track_axis, fc.up_axis = "TRACK_NEGATIVE_Z", "UP_Y"

# atmospheric haze (a bounded volume, so the sky itself stays clear)
bpy.ops.mesh.primitive_cube_add(size=1, location=(-10, 28, 15))
haze = bpy.context.object
haze.name = "Haze"
haze.scale = (100, 86, 30)
M_HAZE = bpy.data.materials.new("Haze")
M_HAZE.use_nodes = True
hn = M_HAZE.node_tree.nodes
hn.remove(hn["Principled BSDF"])
vol = hn.new("ShaderNodeVolumePrincipled")
vol.inputs["Color"].default_value = (0.9, 0.8, 1.0, 1)
vol.inputs["Density"].default_value = 0.002
vol.inputs["Anisotropy"].default_value = 0.6
M_HAZE.node_tree.links.new(vol.outputs[0], hn["Material Output"].inputs["Volume"])
haze.data.materials.append(M_HAZE)
haze.display_type = "BOUNDS"
haze.hide_select = True

# ================================================================ camera (tracks the rider)
cam_data = bpy.data.cameras.new("Camera")
cam_data.lens = 40
cam_data.dof.use_dof = True
cam_data.dof.focus_object = LOOK
cam_data.dof.aperture_fstop = 4.0
cam = bpy.data.objects.new("Camera", cam_data)
cam.location = (2.4, -4.6, 1.0)
scene.collection.objects.link(cam)
track = cam.constraints.new("TRACK_TO")
track.target = LOOK
track.track_axis, track.up_axis = "TRACK_NEGATIVE_Z", "UP_Y"
scene.camera = cam

# ================================================================ render settings
scene.render.fps = FPS
scene.frame_start, scene.frame_end = 1, N
scene.frame_set(1)
scene.render.use_motion_blur = True
scene.render.motion_blur_shutter = 0.5
scene.view_settings.view_transform = "Standard"
scene.view_settings.look = "Medium High Contrast"

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
    ee.taa_render_samples = 16 if PREVIEW else 64
    ee.use_raytracing = True
    ee.volumetric_end = 150
    ee.use_volumetric_shadows = True
    scene.render.resolution_x, scene.render.resolution_y = 1280, 720
scene.render.resolution_percentage = 50 if PREVIEW else 100

# open the .blend looking through the camera with materials visible
for screen in bpy.data.screens:
    for area in screen.areas:
        for space in area.spaces:
            if space.type == "VIEW_3D":
                space.shading.type = "MATERIAL"
                space.region_3d.view_perspective = "CAMERA"
                space.overlay.show_extras = False  # hide light/camera guide lines

if MODE != "check":
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT_DIR, "pelican_bicycle.blend"))


def encode_mp4(frames_dir, out_path):
    """Stitch the PNG frames into an H.264 MP4 using Blender's own sequencer."""
    files = sorted(f for f in os.listdir(frames_dir) if f.endswith(".png"))
    enc = bpy.data.scenes.new("Encode")
    seq = enc.sequence_editor_create()
    strips = seq.strips if hasattr(seq, "strips") else seq.sequences
    strip = strips.new_image("frames", os.path.join(frames_dir, files[0]), 1, 1)
    for f in files[1:]:
        strip.elements.append(f)
    enc.frame_start, enc.frame_end = 1, len(files)
    enc.render.fps = FPS
    enc.render.resolution_x, enc.render.resolution_y = scene.render.resolution_x, scene.render.resolution_y
    enc.render.resolution_percentage = scene.render.resolution_percentage
    enc.view_settings.view_transform = "Standard"  # frames are already display-referred
    im = enc.render.image_settings
    if hasattr(im, "media_type"):
        im.media_type = "VIDEO"
    im.file_format = "FFMPEG"
    enc.render.ffmpeg.format = "MPEG4"
    enc.render.ffmpeg.codec = "H264"
    enc.render.ffmpeg.constant_rate_factor = "HIGH"
    enc.render.filepath = out_path
    bpy.ops.render.render(animation=True, scene=enc.name)


if MODE == "still":
    scene.render.filepath = os.path.join(OUT_DIR, "pelican_bicycle.png")
    bpy.ops.render.render(write_still=True)
elif MODE == "check":
    for f in [int(x) for x in os.environ.get("FRAMES", "1").split(",")]:
        scene.frame_set(f)
        scene.render.filepath = os.path.join(OUT_DIR, f"check_{f:04d}.png")
        bpy.ops.render.render(write_still=True)
elif MODE == "anim":
    frames_dir = os.path.join(OUT_DIR, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    scene.render.filepath = os.path.join(frames_dir, "frame_")
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(animation=True)
    ffmpeg = shutil.which("ffmpeg") or next(
        (p for p in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg") if os.path.exists(p)), None)
    mp4, gif = os.path.join(OUT_DIR, "pelican_ride.mp4"), os.path.join(OUT_DIR, "pelican_ride.gif")
    if ffmpeg:
        seq = os.path.join(frames_dir, "frame_%04d.png")
        subprocess.run([ffmpeg, "-y", "-framerate", str(FPS), "-i", seq, "-c:v", "libx264", "-crf", "18",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", mp4], check=True)
        # two-pass palette keeps the GIF colors clean
        subprocess.run([ffmpeg, "-y", "-framerate", str(FPS), "-i", seq, "-vf",
                        "fps=15,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=192[p];"
                        "[b][p]paletteuse=dither=sierra2_4a", "-loop", "0", gif], check=True)
    else:
        encode_mp4(frames_dir, mp4)
print("done:", MODE)
