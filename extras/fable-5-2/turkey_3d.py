"""Ocellated turkey riding a Yucatecan triciclo -- Blender 5.1, run with:
    blender -b -P turkey_triciclo.py
Renders turkey_triciclo.png next to this script.
"""
import bpy
import bmesh
import os
import math
import random
from mathutils import Vector, Matrix

random.seed(7)

try:
    OUT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    OUT_DIR = os.getcwd()

# ----------------------------------------------------------------- clean scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
scene = bpy.context.scene
col = scene.collection


# ------------------------------------------------------------------- materials
def _new_mat(name):
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    b = nt.nodes.new('ShaderNodeBsdfPrincipled')
    nt.links.new(b.outputs['BSDF'], out.inputs['Surface'])
    return m, nt, b


def _set(b, key, val):
    if key in b.inputs:
        try:
            b.inputs[key].default_value = val
        except Exception:
            pass


def mat(name, color, metallic=0.0, rough=0.5):
    m, nt, b = _new_mat(name)
    c = (color[0], color[1], color[2], 1.0)
    _set(b, 'Base Color', c)
    _set(b, 'Metallic', metallic)
    _set(b, 'Roughness', rough)
    m.diffuse_color = c
    return m


def irid(name, c_face, c_edge, metallic=0.55, rough=0.35):
    """Iridescent feather: colour shifts with viewing angle."""
    m, nt, b = _new_mat(name)
    _set(b, 'Metallic', metallic)
    _set(b, 'Roughness', rough)
    _set(b, 'Base Color', (c_face[0], c_face[1], c_face[2], 1.0))
    try:
        lw = nt.nodes.new('ShaderNodeLayerWeight')
        lw.inputs['Blend'].default_value = 0.45
        ramp = nt.nodes.new('ShaderNodeValToRGB')
        els = ramp.color_ramp.elements
        els[0].position = 0.0
        els[0].color = (c_face[0], c_face[1], c_face[2], 1.0)
        els[1].position = 1.0
        els[1].color = (c_edge[0], c_edge[1], c_edge[2], 1.0)
        nt.links.new(lw.outputs['Facing'], ramp.inputs['Fac'])
        nt.links.new(ramp.outputs['Color'], b.inputs['Base Color'])
    except Exception:
        pass
    m.diffuse_color = (c_face[0], c_face[1], c_face[2], 1.0)
    return m


# turkey
m_dark = mat("body_dark", (0.015, 0.03, 0.02), 0.3, 0.45)
m_green = irid("f_green", (0.04, 0.30, 0.10), (0.65, 0.40, 0.05))
m_bronze = irid("f_bronze", (0.50, 0.25, 0.04), (0.10, 0.45, 0.15))
m_blue = irid("f_blue", (0.03, 0.18, 0.55), (0.05, 0.55, 0.35))
m_copper = irid("f_copper", (0.80, 0.30, 0.04), (0.95, 0.65, 0.12), 0.7, 0.3)
m_white = mat("f_white", (0.92, 0.90, 0.84), 0.0, 0.6)
m_tail = mat("tail_grey", (0.28, 0.36, 0.50), 0.25, 0.45)
m_quill = mat("quill", (0.85, 0.85, 0.80), 0.0, 0.5)
m_ocel = irid("ocellus", (0.0, 0.22, 0.95), (0.0, 0.75, 0.60), 0.6, 0.25)
m_black = mat("black", (0.01, 0.01, 0.012), 0.0, 0.35)
m_gold = mat("gold_tip", (1.0, 0.58, 0.07), 0.85, 0.3)
m_head = mat("head_blue", (0.10, 0.40, 0.95), 0.0, 0.45)
m_nodule = mat("nodule", (1.0, 0.28, 0.02), 0.0, 0.4)
m_eyering = mat("eye_ring", (0.85, 0.04, 0.04), 0.0, 0.4)
m_eye = mat("eye", (0.005, 0.005, 0.005), 0.0, 0.05)
m_beak = mat("beak", (0.80, 0.68, 0.40), 0.0, 0.4)
m_leg = mat("leg_red", (0.85, 0.09, 0.11), 0.0, 0.45)
# triciclo
m_rubber = mat("rubber", (0.02, 0.02, 0.02), 0.0, 0.75)
m_chrome = mat("chrome", (0.80, 0.80, 0.82), 1.0, 0.22)
m_frame = mat("frame_turq", (0.0, 0.55, 0.60), 0.2, 0.35)
m_panel = mat("panel_pink", (0.90, 0.05, 0.38), 0.1, 0.4)
m_seat = mat("seat_red", (0.75, 0.04, 0.04), 0.0, 0.35)
m_wood = mat("wood", (0.45, 0.27, 0.12), 0.0, 0.7)
m_can_a = mat("canopy_turq", (0.0, 0.62, 0.68), 0.0, 0.7)
m_can_b = mat("canopy_white", (0.95, 0.94, 0.90), 0.0, 0.7)
m_straw = mat("straw", (0.78, 0.60, 0.30), 0.0, 0.8)
m_orange = mat("orange", (1.0, 0.42, 0.02), 0.0, 0.5)
m_melon = mat("melon", (0.05, 0.30, 0.07), 0.0, 0.35)
m_lime = mat("lime", (0.35, 0.70, 0.08), 0.0, 0.45)
m_sack = mat("sack", (0.62, 0.50, 0.33), 0.0, 0.9)
# set
m_ground = mat("street", (0.42, 0.39, 0.36), 0.0, 0.9)
m_walk = mat("sidewalk", (0.68, 0.65, 0.60), 0.0, 0.85)
m_wall = mat("wall_yellow", (0.95, 0.58, 0.06), 0.0, 0.85)
m_trim = mat("wall_trim", (0.93, 0.91, 0.85), 0.0, 0.8)
m_door = mat("door_teal", (0.02, 0.30, 0.33), 0.0, 0.55)
m_terra = mat("terracotta", (0.62, 0.27, 0.13), 0.0, 0.8)
m_agave = mat("henequen", (0.30, 0.48, 0.38), 0.0, 0.55)


# --------------------------------------------------------------- mesh helpers
_meshes = {}


def unit_mesh(kind, m):
    key = (kind, m.name)
    if key in _meshes:
        return _meshes[key]
    bm = bmesh.new()
    if kind == 'sphere':
        bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=14, radius=1.0)
    elif kind == 'cyl':
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=20,
                              radius1=1.0, radius2=1.0, depth=1.0)
    elif kind == 'cone':
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=20,
                              radius1=1.0, radius2=0.02, depth=1.0)
    else:
        bmesh.ops.create_cube(bm, size=1.0)
    me = bpy.data.meshes.new(kind + "_" + m.name)
    bm.to_mesh(me)
    bm.free()
    if kind != 'cube':
        for p in me.polygons:
            p.use_smooth = len(p.vertices) <= 4
    me.materials.append(m)
    _meshes[key] = me
    return me


I4 = Matrix.Identity(4)


def _vec3(s):
    if isinstance(s, (int, float)):
        return Vector((s, s, s))
    return Vector(s)


def add(kind, m, M):
    ob = bpy.data.objects.new(kind, unit_mesh(kind, m))
    col.objects.link(ob)
    ob.matrix_world = M
    return ob


def sphere(m, loc, scale, quat=None, P=I4):
    return add('sphere', m, P @ Matrix.LocRotScale(Vector(loc), quat, _vec3(scale)))


def box(m, loc, size, quat=None, P=I4):
    return add('cube', m, P @ Matrix.LocRotScale(Vector(loc), quat, _vec3(size)))


def tube(m, p1, p2, r, P=I4, kind='cyl'):
    p1 = Vector(p1)
    p2 = Vector(p2)
    d = p2 - p1
    q = d.to_track_quat('Z', 'Y')
    return add(kind, m, P @ Matrix.LocRotScale((p1 + p2) / 2, q,
                                               Vector((r, r, d.length))))


def ellip(m, p1, p2, rx, ry, ext=1.0, P=I4):
    p1 = Vector(p1)
    p2 = Vector(p2)
    d = p2 - p1
    q = d.to_track_quat('Z', 'Y')
    return add('sphere', m, P @ Matrix.LocRotScale((p1 + p2) / 2, q,
                                                   Vector((rx, ry, d.length / 2 * ext))))


def torus(m, center, R, r, nu=48, nv=12):
    key = ('torus', round(R, 4), round(r, 4), m.name)
    if key not in _meshes:
        verts = []
        faces = []
        for i in range(nu):
            a = 2 * math.pi * i / nu
            for j in range(nv):
                b = 2 * math.pi * j / nv
                rr = R + r * math.cos(b)
                verts.append((rr * math.cos(a), r * math.sin(b), rr * math.sin(a)))
        for i in range(nu):
            for j in range(nv):
                i2 = (i + 1) % nu
                j2 = (j + 1) % nv
                faces.append((i * nv + j, i2 * nv + j, i2 * nv + j2, i * nv + j2))
        me = bpy.data.meshes.new("torus_" + m.name)
        me.from_pydata(verts, [], faces)
        me.update()
        for p in me.polygons:
            p.use_smooth = True
        me.materials.append(m)
        _meshes[key] = me
    ob = bpy.data.objects.new("torus", _meshes[key])
    col.objects.link(ob)
    ob.location = Vector(center)
    return ob


# ======================================================================== SET
box(m_ground, (0, 0, -0.05), (60, 60, 0.1))
box(m_walk, (0, 2.75, 0.07), (60, 1.3, 0.14))
box(m_wall, (0, 3.6, 2.5), (60, 0.4, 5.0))
box(m_trim, (0, 3.385, 0.64), (60, 0.06, 1.0))
# door (right side, partly framed)
box(m_trim, (1.75, 3.385, 1.45), (1.7, 0.08, 2.75))
box(m_door, (1.75, 3.36, 1.34), (1.25, 0.1, 2.4))
box(m_wood, (1.75, 3.33, 1.34), (0.04, 0.06, 2.4))
sphere(m_chrome, (1.62, 3.29, 1.25), 0.04)
# henequen (agave) in a clay pot on the left
hx, hy = -4.7, 2.7
tube(m_terra, (hx, hy, 0.14), (hx, hy, 0.52), 0.24)
torus(m_terra, (hx, hy, 0.52), 0.24, 0.03).rotation_euler = (math.pi / 2, 0, 0)
for k in range(16):
    az = 2 * math.pi * k / 16 + random.uniform(-0.15, 0.15)
    el = math.radians(random.choice((28, 45, 62, 78)))
    L = random.uniform(0.55, 0.8)
    d = Vector((math.cos(az) * math.cos(el), math.sin(az) * math.cos(el), math.sin(el)))
    base = Vector((hx, hy, 0.5))
    tube(m_agave, base, base + d * L, 0.05, kind='cone')

# =================================================================== TRICICLO
WR = 0.34  # hub height


def wheel(c):
    c = Vector(c)
    torus(m_rubber, c, 0.30, 0.04)
    torus(m_chrome, c, 0.262, 0.016)
    tube(m_chrome, c + Vector((0, -0.05, 0)), c + Vector((0, 0.05, 0)), 0.03)
    n = 14
    for k in range(n):
        a = 2 * math.pi * k / n
        side = 0.035 if k % 2 else -0.035
        tube(m_chrome, c + Vector((0, side, 0)),
             c + Vector((0.26 * math.cos(a), 0, 0.26 * math.sin(a))), 0.004)


FX = 0.8
wheel((FX, -0.64, WR))
wheel((FX, 0.64, WR))
REAR = Vector((-1.08, 0, WR))
wheel(REAR)

# front axle + supports
tube(m_chrome, (FX, -0.64, WR), (FX, 0.64, WR), 0.018)
for s in (-1, 1):
    tube(m_frame, (FX, s * 0.4, WR), (FX, s * 0.4, 0.44), 0.02)
    tube(m_frame, (FX, s * 0.4, WR), (FX - 0.35, s * 0.4, 0.43), 0.014)
    tube(m_frame, (FX, s * 0.4, WR), (FX + 0.35, s * 0.4, 0.43), 0.014)

# cargo / passenger box
box(m_wood, (0.8, 0, 0.45), (1.0, 0.96, 0.04))
for s in (-1, 1):
    box(m_panel, (0.8, s * 0.48, 0.62), (1.0, 0.02, 0.32))
    tube(m_frame, (0.3, s * 0.48, 0.43), (1.3, s * 0.48, 0.43), 0.02)
    tube(m_frame, (0.3, s * 0.48, 0.79), (1.3, s * 0.48, 0.79), 0.018)
    # little painted diamond on the side panel
    box(m_can_b, (0.8, s * 0.492, 0.62), (0.16, 0.006, 0.16),
        quat=Matrix.Rotation(math.radians(45), 4, 'Y').to_quaternion())
box(m_panel, (1.3, 0, 0.56), (0.02, 0.96, 0.2))
box(m_panel, (0.3, 0, 0.70), (0.02, 0.96, 0.5))
tube(m_frame, (1.3, -0.48, 0.67), (1.3, 0.48, 0.67), 0.018)
tube(m_frame, (1.3, -0.48, 0.43), (1.3, 0.48, 0.43), 0.02)
# bench
box(m_seat, (0.53, 0, 0.74), (0.40, 0.9, 0.07))
box(m_seat, (0.335, 0, 0.98), (0.05, 0.9, 0.36))

# canopy (toldo)
for px in (0.33, 1.3):
    for s in (-1, 1):
        tube(m_frame, (px, s * 0.46, 0.45), (px, s * 0.46, 1.87), 0.015)
for i in range(8):
    y = -0.52 + 0.065 + i * 0.13
    box(m_can_a if i % 2 == 0 else m_can_b, (0.85, y, 1.885), (1.1, 0.13, 0.03))
for i in range(10):
    x = 0.3 + 0.055 + i * 0.11
    mm = m_panel if i % 2 == 0 else m_can_b
    for s in (-1, 1):
        sphere(mm, (x, s * 0.52, 1.865), (0.055, 0.008, 0.075))
for i in range(8):
    y = -0.52 + 0.065 + i * 0.13
    mm = m_panel if i % 2 == 0 else m_can_b
    for px in (0.3, 1.4):
        sphere(mm, (px, y, 1.865), (0.008, 0.065, 0.075))

# handlebar (behind the bench)
HBX, HBZ = 0.16, 1.10
for s in (-1, 1):
    tube(m_chrome, (0.33, s * 0.46, 0.98), (HBX, s * 0.46, HBZ), 0.014)
    tube(m_rubber, (HBX, s * 0.40, HBZ), (HBX, s * 0.52, HBZ), 0.023)
tube(m_chrome, (HBX, -0.5, HBZ), (HBX, 0.5, HBZ), 0.015)
sphere(m_chrome, (HBX, 0.12, HBZ + 0.035), 0.035)  # bell

# rear frame
BB = Vector((-0.42, 0, 0.32))
tube(m_frame, BB, (-0.64, 0, 0.92), 0.022)            # seat tube
tube(m_frame, (-0.62, 0, 0.86), (0.28, 0, 0.80), 0.022)  # top tube
tube(m_frame, BB, (0.28, 0, 0.47), 0.024)             # down tube
tube(m_frame, (0.28, 0, 0.40), (0.28, 0, 0.86), 0.032)   # head tube
for s in (-1, 1):
    tube(m_frame, (BB.x, s * 0.06, BB.z), (REAR.x, s * 0.07, REAR.z), 0.014)
    tube(m_frame, (-0.63, s * 0.03, 0.88), (REAR.x, s * 0.07, REAR.z), 0.012)
# rear mudguard hint
tube(m_chrome, (-0.63, 0, 0.88), (-0.66, 0, 0.93), 0.014)
# saddle
sphere(m_black, (-0.66, 0, 0.97), (0.17, 0.11, 0.04))
sphere(m_black, (-0.54, 0, 0.965), (0.10, 0.05, 0.03))

# drivetrain
CR = 0.17
ang = math.radians(-35)
PED_R = BB + Vector((CR * math.cos(ang), -0.17, CR * math.sin(ang)))
PED_L = BB + Vector((-CR * math.cos(ang), 0.17, -CR * math.sin(ang)))
tube(m_chrome, (BB.x, -0.12, BB.z), (BB.x, 0.12, BB.z), 0.02)
tube(m_chrome, (BB.x, -0.07, BB.z), (BB.x, -0.082, BB.z), 0.10)   # chainring
tube(m_chrome, (REAR.x, -0.07, REAR.z), (REAR.x, -0.082, REAR.z), 0.045)
tube(m_black, (BB.x, -0.076, BB.z + 0.10), (REAR.x, -0.076, REAR.z + 0.045), 0.006)
tube(m_black, (BB.x, -0.076, BB.z - 0.10), (REAR.x, -0.076, REAR.z - 0.045), 0.006)
tube(m_chrome, (BB.x, -0.11, BB.z), (PED_R.x, -0.11, PED_R.z), 0.012)
tube(m_chrome, (BB.x, 0.11, BB.z), (PED_L.x, 0.11, PED_L.z), 0.012)
for P_ in (PED_R, PED_L):
    s = -1 if P_.y < 0 else 1
    tube(m_chrome, (P_.x, s * 0.10, P_.z), (P_.x, s * 0.21, P_.z), 0.008)
    box(m_black, P_, (0.11, 0.09, 0.025))

# cargo on the bench and floor
bx, by = 0.54, 0.20
tube(m_straw, (bx, by, 0.775), (bx, by, 0.95), 0.17)
torus(m_straw, (bx, by, 0.95), 0.17, 0.018).rotation_euler = (math.pi / 2, 0, 0)
for k in range(14):
    a = random.uniform(0, 2 * math.pi)
    r = random.uniform(0.0, 0.12)
    sphere(m_orange, (bx + r * math.cos(a), by + r * math.sin(a),
                      0.97 + random.uniform(0, 0.05) + (0.12 - r) * 0.5), 0.045)
sphere(m_melon, (0.53, -0.22, 0.90), (0.13, 0.19, 0.13))
sphere(m_sack, (1.05, 0.16, 0.63), (0.19, 0.24, 0.17))
box(m_wood, (1.02, -0.24, 0.57), (0.36, 0.36, 0.2))
for k in range(12):
    sphere(m_lime, (1.02 + random.uniform(-0.13, 0.13),
                    -0.24 + random.uniform(-0.13, 0.13),
                    0.69 + random.uniform(0, 0.03)), 0.035)

# ===================================================================== TURKEY
BC = Vector((-0.60, 0, 1.32))
A, Bw, C = 0.42, 0.30, 0.32
TILT = math.radians(-15)  # breast up, rump down
BODY = Matrix.Translation(BC) @ Matrix.Rotation(TILT, 4, 'Y')

sphere(m_dark, (0, 0, 0), (A * 0.985, Bw * 0.985, C * 0.985), P=BODY)

# scalloped iridescent body feathers
NR = 13
for i in range(NR):
    t = -0.92 + i * (1.84 / (NR - 1))
    s = math.sqrt(max(0.0, 1 - t * t))
    n = max(6, int(22 * s))
    for j in range(n):
        lam = 2 * math.pi * (j + 0.5 * (i % 2)) / n
        p = Vector((A * t, Bw * s * math.cos(lam), C * s * math.sin(lam)))
        nrm = Vector((p.x / (A * A), p.y / (Bw * Bw), p.z / (C * C))).normalized()
        if t < -0.35:
            mm = (m_blue, m_bronze, m_copper)[(i + j) % 3]
        elif t < 0.3:
            mm = (m_green, m_bronze)[(i + j) % 2]
        else:
            mm = (m_green, m_green, m_bronze)[(i + j) % 3]
        sphere(mm, p, (0.07, 0.07, 0.017), quat=nrm.to_track_quat('Z', 'Y'), P=BODY)

# neck (bezier of spheres) and head
HC = Vector((-0.20, 0, 2.00))
P0 = Vector((-0.34, 0, 1.47))
P1 = Vector((0.0, 0, 1.68))
P2 = HC + Vector((0, 0, -0.04))
NN = 13
for i in range(NN):
    t = i / (NN - 1)
    c = (1 - t) ** 2 * P0 + 2 * t * (1 - t) * P1 + t * t * P2
    r = 0.15 + (0.058 - 0.15) * t
    if t < 0.42:
        sphere((m_green, m_bronze)[i % 2], c, r)
    else:
        sphere(m_head, c, r)
        if i % 2 == 0 and t < 0.95:
            for sgn in (-1, 1):
                sphere(m_nodule, c + Vector((-0.35 * r, sgn * 0.9 * r, 0.2 * r)), 0.012)

HS = Vector((0.10, 0.08, 0.085))
sphere(m_head, HC, HS)
bdir = Vector((1, 0, -0.28)).normalized()
tube(m_beak, HC + bdir * 0.07, HC + bdir * 0.20, 0.034, kind='cone')
for sgn in (-1, 1):
    sphere(m_eyering, HC + Vector((0.045, sgn * 0.062, 0.02)), (0.03, 0.012, 0.03))
    sphere(m_eye, HC + Vector((0.047, sgn * 0.068, 0.02)), 0.019)
    sphere(m_quill, HC + Vector((0.055, sgn * 0.083, 0.028)), 0.005)
# crown knob
sphere(m_head, HC + Vector((-0.01, 0, 0.095)), (0.04, 0.035, 0.045))
for k in range(5):
    a = 2 * math.pi * k / 5
    sphere(m_nodule, HC + Vector((-0.01 + 0.025 * math.cos(a), 0.022 * math.sin(a), 0.132)), 0.012)
sphere(m_nodule, HC + Vector((-0.01, 0, 0.145)), 0.013)
# orange nodules scattered on the bare blue head
cnt = 0
tries = 0
while cnt < 18 and tries < 400:
    tries += 1
    v = Vector((random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(-1, 1)))
    if v.length < 0.2:
        continue
    v.normalize()
    if not (v.z > 0.3 or v.x < -0.35):
        continue
    if v.x > 0.45 and v.z < 0.6:
        continue
    sphere(m_nodule, HC + Vector((v.x * HS.x, v.y * HS.y, v.z * HS.z)),
           random.uniform(0.010, 0.016))
    cnt += 1

# wings reaching forward to grip the handlebar
for sgn in (-1, 1):
    sh = Vector((-0.50, sgn * 0.27, 1.42))
    hand = Vector((HBX - 0.02, sgn * 0.33, HBZ + 0.02))
    ellip(m_copper, sh, hand, 0.045, 0.14)
    ellip(m_white, (-0.42, sgn * 0.30, 1.30), (0.08, sgn * 0.335, 1.06), 0.032, 0.09)
    ellip(m_green, sh + Vector((-0.08, sgn * 0.01, 0.05)),
          sh + Vector((0.22, sgn * 0.03, -0.06)), 0.05, 0.11)
    # dark barring on the white secondaries
    for k in range(5):
        f = 0.2 + k * 0.15
        c = Vector((-0.42, sgn * 0.30, 1.30)).lerp(Vector((0.08, sgn * 0.335, 1.06)), f)
        sphere(m_black, c + Vector((0, sgn * 0.022, -0.02)), (0.012, 0.012, 0.06))
    # wingtip "fingers" wrapped around the bar
    sphere(m_bronze, (HBX, sgn * 0.33, HBZ), (0.055, 0.06, 0.055))
    for k in (-1, 0, 1):
        tube(m_dark, (HBX - 0.03, sgn * 0.33 + k * 0.035, HBZ + 0.04),
             (HBX + 0.06, sgn * 0.33 + k * 0.035, HBZ - 0.03), 0.014)

# legs pedalling
legs = (
    (Vector((-0.45, -0.16, 1.10)), Vector((-0.16, -0.18, 0.78)), PED_R),
    (Vector((-0.45, 0.16, 1.10)), Vector((-0.22, 0.18, 0.86)), PED_L),
)
for hip, knee, ped in legs:
    F = ped + Vector((0, 0, 0.022))
    ellip(m_dark, hip, knee, 0.09, 0.09, ext=1.15)
    ellip(m_bronze, hip + Vector((0, 0, 0.02)), hip.lerp(knee, 0.6), 0.10, 0.10)
    sphere(m_leg, knee, 0.03)
    ankle = F + Vector((-0.02, 0, 0.015))
    tube(m_leg, knee, ankle, 0.021)
    sphere(m_leg, ankle, 0.026)
    for dy in (-0.045, 0.0, 0.045):
        tip = F + Vector((0.10, dy, -0.004))
        tube(m_leg, ankle, tip, 0.012)
        sphere(m_black, tip, 0.012)
    tube(m_leg, ankle, F + Vector((-0.07, 0, -0.004)), 0.011)

# tail: the signature fan with blue ocelli and golden tips
def tail_feather(M, L, w):
    sphere(m_tail, (0, 0, L * 0.52), (0.012, w, L * 0.5), P=M)
    tube(m_quill, (0, 0, 0), (0, 0, L * 0.6), 0.0135, P=M)
    sphere(m_black, (0, 0, L * 0.78), (0.016, w * 0.92, w * 0.92), P=M)
    sphere(m_ocel, (0, 0, L * 0.78), (0.021, w * 0.62, w * 0.62), P=M)
    sphere(m_gold, (0, 0, L * 0.95), (0.016, w * 1.0, w * 0.5), P=M)


def fan(base, tilt_deg, spread_deg, n, L, w):
    T = Matrix.Translation(Vector(base)) @ Matrix.Rotation(math.radians(tilt_deg), 4, 'Y')
    for i in range(n):
        phi = math.radians(-spread_deg + 2 * spread_deg * i / (n - 1))
        M = T @ Matrix.Rotation(phi, 4, 'X') @ Matrix.Translation(((i % 2) * 0.014, 0, 0))
        tail_feather(M, L, w)


RUMP = (-0.93, 0, 1.25)
fan(RUMP, -20, 76, 13, 0.86, 0.088)
fan((-0.89, 0, 1.27), -34, 60, 9, 0.47, 0.062)   # upper tail coverts
sphere(m_bronze, RUMP, (0.14, 0.16, 0.14))
sphere(m_blue, (-0.86, 0, 1.33), (0.14, 0.15, 0.10))

# ============================================================ LIGHT / CAMERA
world = bpy.data.worlds.new("Sky")
scene.world = world
try:
    world.use_nodes = True
except Exception:
    pass
try:
    wnt = world.node_tree
    wnt.nodes.clear()
    bg = wnt.nodes.new('ShaderNodeBackground')
    wout = wnt.nodes.new('ShaderNodeOutputWorld')
    bg.inputs['Color'].default_value = (0.50, 0.70, 1.0, 1.0)
    bg.inputs['Strength'].default_value = 1.0
    wnt.links.new(bg.outputs['Background'], wout.inputs['Surface'])
except Exception:
    pass

sun_data = bpy.data.lights.new("Sun", 'SUN')
sun_data.energy = 3.6
try:
    sun_data.angle = math.radians(2.5)
    sun_data.color = (1.0, 0.95, 0.86)
except Exception:
    pass
sun = bpy.data.objects.new("Sun", sun_data)
col.objects.link(sun)
sun.rotation_euler = Vector((-0.35, 0.55, -0.76)).to_track_quat('-Z', 'Y').to_euler()

cam_data = bpy.data.cameras.new("Cam")
cam_data.lens = 60
cam = bpy.data.objects.new("Cam", cam_data)
col.objects.link(cam)
cam_loc = Vector((3.2, -6.8, 1.9))
target = Vector((0.0, 0.0, 1.05))
cam.location = cam_loc
cam.rotation_euler = (target - cam_loc).to_track_quat('-Z', 'Y').to_euler()
scene.camera = cam

# ===================================================================== RENDER
r = scene.render
r.engine = 'CYCLES'
try:
    scene.cycles.samples = 96
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 6
except Exception:
    pass
r.resolution_x = 1440
r.resolution_y = 810
r.resolution_percentage = 100
try:
    r.image_settings.file_format = 'PNG'
except Exception:
    pass
try:
    scene.view_settings.view_transform = 'AgX'
except Exception:
    pass
for look in ('AgX - Punchy', 'AgX - Medium High Contrast', 'Medium High Contrast'):
    try:
        scene.view_settings.look = look
        break
    except Exception:
        continue
r.filepath = os.path.join(OUT_DIR, "turkey_triciclo.png")
bpy.ops.render.render(write_still=True)
