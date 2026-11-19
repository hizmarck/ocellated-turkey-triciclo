import bpy, bmesh, os, math, random
from mathutils import Vector, Matrix
from math import sin, cos, pi

random.seed(7)
HERE = os.path.dirname(os.path.abspath(__file__))
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
scene = bpy.context.scene
col = scene.collection

# ---------------------------------------------------------------- materials
def principled(m):
    try:
        m.use_nodes = True
    except Exception:
        pass
    nt = m.node_tree
    b = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if b is None:
        nt.nodes.clear()
        b = nt.nodes.new('ShaderNodeBsdfPrincipled')
        o = nt.nodes.new('ShaderNodeOutputMaterial')
        nt.links.new(b.outputs[0], o.inputs[0])
    return nt, b

def mat(name, c, metal=0.0, rough=0.6):
    m = bpy.data.materials.new(name)
    nt, b = principled(m)
    b.inputs['Base Color'].default_value = (c[0], c[1], c[2], 1)
    b.inputs['Metallic'].default_value = metal
    b.inputs['Roughness'].default_value = rough
    m.diffuse_color = (c[0], c[1], c[2], 1)
    return m

def tex_mat(name, kind, stops, scale, metal=0.0, rough=0.5, const=False):
    m = bpy.data.materials.new(name)
    nt, b = principled(m)
    b.inputs['Metallic'].default_value = metal
    b.inputs['Roughness'].default_value = rough
    t = nt.nodes.new(kind)
    t.inputs['Scale'].default_value = scale
    if kind == 'ShaderNodeTexWave':
        try:
            t.bands_direction = 'Z'
        except Exception:
            pass
    r = nt.nodes.new('ShaderNodeValToRGB')
    cr = r.color_ramp
    if const:
        cr.interpolation = 'CONSTANT'
    cr.elements[0].color = (*stops[0][1], 1)
    cr.elements[len(cr.elements) - 1].color = (*stops[-1][1], 1)
    for p, c in stops[1:-1]:
        e = cr.elements.new(p)
        e.color = (*c, 1)
    nt.links.new(t.outputs[0], r.inputs[0])
    nt.links.new(r.outputs[0], b.inputs['Base Color'])
    return m

FEATH = tex_mat('feath', 'ShaderNodeTexNoise',
                [(0, (0.02, 0.25, 0.12)), (0.42, (0.05, 0.45, 0.2)), (0.55, (0.55, 0.33, 0.08)),
                 (0.68, (0.05, 0.3, 0.55)), (1, (0.03, 0.2, 0.4))], 9.0, 0.65, 0.35)
BAR = tex_mat('bar', 'ShaderNodeTexWave', [(0, (0.03, 0.03, 0.03)), (0.5, (0.95, 0.95, 0.9)), (1, (0.95, 0.95, 0.9))],
              5.0, 0.0, 0.5, True)
TAILG = tex_mat('tailg', 'ShaderNodeTexWave', [(0, (0.12, 0.13, 0.14)), (0.5, (0.42, 0.44, 0.45)), (1, (0.42, 0.44, 0.45))],
                7.0, 0.2, 0.5, True)
BLUE = mat('blue', (0.1, 0.4, 0.95), 0, 0.45)
ORANGE = mat('orange', (1.0, 0.38, 0.03), 0, 0.4)
RED = mat('red', (0.85, 0.1, 0.08), 0, 0.45)
BEAK = mat('beak', (0.85, 0.75, 0.5), 0, 0.4)
EYE = mat('eye', (0.01, 0.01, 0.01), 0, 0.1)
COPPER = mat('copper', (0.85, 0.38, 0.1), 0.8, 0.3)
OCEL = mat('ocel', (0.03, 0.3, 0.95), 0.7, 0.25)
GOLD = mat('gold', (0.95, 0.65, 0.15), 0.8, 0.3)
BLACK = mat('black', (0.02, 0.02, 0.02), 0, 0.7)
STEEL = mat('steel', (0.7, 0.72, 0.75), 0.9, 0.3)
PAINT = mat('paint', (0.8, 0.08, 0.08), 0.2, 0.35)
BOXG = mat('boxg', (0.05, 0.55, 0.45), 0, 0.5)
TRIM = mat('trim', (0.98, 0.8, 0.1), 0, 0.5)
WHITE = mat('white', (0.95, 0.95, 0.92))
CAN1 = mat('can1', (0.95, 0.3, 0.1))
LIME = mat('lime', (0.35, 0.7, 0.1), 0, 0.4)
MELON = mat('melon', (0.08, 0.35, 0.1), 0, 0.35)
ROAD = mat('road', (0.2, 0.2, 0.21), 0, 0.9)
GROUND = mat('ground', (0.72, 0.62, 0.42), 0, 1.0)
WALK = mat('walk', (0.7, 0.7, 0.68), 0, 0.9)
WOOD = mat('wood', (0.3, 0.16, 0.07), 0, 0.6)
GLASS = mat('glass', (0.05, 0.12, 0.15), 0, 0.2)
TRUNK = mat('trunk', (0.4, 0.3, 0.2), 0, 0.9)
LEAF = mat('leaf', (0.1, 0.45, 0.12), 0, 0.6)
STONE = mat('stone', (0.8, 0.78, 0.72), 0, 0.9)
HOUSE_C = [(0.98, 0.75, 0.15), (0.95, 0.4, 0.5), (0.2, 0.7, 0.75)]
HOUSE = [mat('house%d' % i, c) for i, c in enumerate(HOUSE_C)]
DADO = [mat('dado%d' % i, tuple(v * 0.55 for v in c)) for i, c in enumerate(HOUSE_C)]

# ---------------------------------------------------------------- mesh helpers
def bm_mesh(fn, smooth):
    bm = bmesh.new()
    fn(bm)
    me = bpy.data.meshes.new('m')
    bm.to_mesh(me)
    bm.free()
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    return me

def torus(R, r, n=40, m=10):
    vs = [((R + r * cos(2 * pi * j / m)) * cos(2 * pi * i / n), r * sin(2 * pi * j / m),
           (R + r * cos(2 * pi * j / m)) * sin(2 * pi * i / n)) for i in range(n) for j in range(m)]
    fs = [(i * m + j, i * m + (j + 1) % m, ((i + 1) % n) * m + (j + 1) % m, ((i + 1) % n) * m + j)
          for i in range(n) for j in range(m)]
    me = bpy.data.meshes.new('t')
    me.from_pydata(vs, [], fs)
    me.update()
    for p in me.polygons:
        p.use_smooth = True
    return me

WR = 0.36  # wheel outer radius
M = {
    'sph': bm_mesh(lambda bm: bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=0.5), True),
    'cyl': bm_mesh(lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=0.5, radius2=0.5, depth=1.0), False),
    'cone': bm_mesh(lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=0.5, radius2=0.0, depth=1.0), False),
    'cube': bm_mesh(lambda bm: bmesh.ops.create_cube(bm, size=1.0), False),
    'tire': torus(WR - 0.03, 0.03),
    'rim': torus(WR - 0.065, 0.012),
}

def add(kind, loc, scale=1.0, m=None, parent=None, rot=(0, 0, 0)):
    o = bpy.data.objects.new(kind, M[kind].copy())
    col.objects.link(o)
    o.location = loc
    o.scale = scale if hasattr(scale, '__len__') else (scale, scale, scale)
    o.rotation_euler = rot
    if m:
        o.data.materials.append(m)
    o.parent = parent
    return o

def empty(loc=(0, 0, 0), parent=None):
    o = bpy.data.objects.new('e', None)
    col.objects.link(o)
    o.location = loc
    o.parent = parent
    return o

def stretch(o, p1, p2, sx, sy=None, key=None, up=None):
    p1, p2 = Vector(p1), Vector(p2)
    d = p2 - p1
    L = max(d.length, 1e-5)
    dn = d / L
    o.rotation_mode = 'QUATERNION'
    o.location = (p1 + p2) / 2
    if up is None:
        q = Vector((0, 0, 1)).rotation_difference(dn)
    else:
        u = Vector(up)
        x = u - u.dot(dn) * dn
        if x.length < 1e-4:
            x = Vector((1, 0, 0))
        x.normalize()
        y = dn.cross(x)
        q = Matrix((x, y, dn)).transposed().to_quaternion()
    o.rotation_quaternion = q
    o.scale = (sx, sy if sy is not None else sx, L)
    if key is not None:
        for ch in ('location', 'rotation_quaternion', 'scale'):
            o.keyframe_insert(ch, frame=key)
    return o

def rod(p1, p2, w, m, parent=None, kind='cyl', sy=None, up=None):
    return stretch(add(kind, (0, 0, 0), 1, m, parent), p1, p2, w, sy, None, up)

# ---------------------------------------------------------------- triciclo
def wheel(loc):
    e = empty(loc)
    add('tire', (0, 0, 0), 1, BLACK, e)
    add('rim', (0, 0, 0), 1, STEEL, e)
    add('cyl', (0, 0, 0), (0.06, 0.06, 0.1), STEEL, e, (pi / 2, 0, 0))
    for i in range(12):
        a = 2 * pi * i / 12
        s = 0.035 if i % 2 else -0.035
        rod((0, s, 0), ((WR - 0.065) * cos(a), 0, (WR - 0.065) * sin(a)), 0.008, STEEL, e)
    return e

RA = Vector((-1.0, 0, WR))
BB = Vector((-0.35, 0, 0.40))
ST = Vector((-0.6, 0, 0.97))
CR = 0.17
wheels = [wheel(RA), wheel((0.95, -0.62, WR)), wheel((0.95, 0.62, WR))]

rod(BB, ST, 0.04, PAINT)
for s in (-1, 1):
    rod((BB.x, s * 0.05, BB.z), (RA.x, s * 0.06, RA.z), 0.025, PAINT)
    rod((-0.57, s * 0.03, 0.9), (RA.x, s * 0.06, RA.z), 0.022, PAINT)
rod((-0.55, 0, 0.86), (0.4, 0, 0.62), 0.04, PAINT)
rod(BB, (0.4, 0, 0.44), 0.04, PAINT)
rod((0.95, -0.62, WR), (0.95, 0.62, WR), 0.03, STEEL)
add('sph', (-0.61, 0, 1.0), (0.32, 0.22, 0.08), BLACK)
# cargo box
add('cube', (0.95, 0, 0.5), (1.1, 0.95, 0.04), BOXG)
add('cube', (0.4, 0, 0.68), (0.04, 0.95, 0.36), BOXG)
add('cube', (1.5, 0, 0.68), (0.04, 0.95, 0.36), BOXG)
for s in (-1, 1):
    add('cube', (0.95, s * 0.475, 0.68), (1.14, 0.04, 0.36), BOXG)
    rod((0.38, s * 0.475, 0.87), (1.52, s * 0.475, 0.87), 0.04, TRIM)
    rod((0.95, s * 0.4, WR), (0.95, s * 0.4, 0.5), 0.03, PAINT)
    rod((0.4, s * 0.2, 0.86), (0.12, s * 0.2, 1.14), 0.028, PAINT)
    rod((0.12, s * 0.3, 1.14), (0.12, s * 0.46, 1.14), 0.045, BLACK)
    for x in (0.45, 1.45):
        rod((x, s * 0.46, 0.86), (x, s * 0.46, 1.78), 0.022, STEEL)
for x in (0.4, 1.5):
    rod((x, -0.475, 0.87), (x, 0.475, 0.87), 0.04, TRIM)
rod((0.12, -0.44, 1.14), (0.12, 0.44, 1.14), 0.03, STEEL)
# striped canopy
for i in range(8):
    y = -0.55 + (i + 0.5) * 1.1 / 8
    add('cube', (0.95, y, 1.8), (1.25, 1.1 / 8, 0.03), CAN1 if i % 2 else WHITE)
for x in (0.325, 1.575):
    add('cube', (x, 0, 1.75), (0.02, 1.1, 0.12), TRIM)
# fruit cargo
for i in range(70):
    dx, dy = random.uniform(-1, 1), random.uniform(-1, 1)
    z = 0.58 + 0.4 * max(0.0, 1 - 0.6 * (dx * dx + dy * dy)) * random.uniform(0.5, 1)
    add('sph', (0.95 + dx * 0.45, dy * 0.38, z), 0.12, LIME if i % 5 == 0 else ORANGE)
add('sph', (1.2, 0.12, 1.0), (0.34, 0.24, 0.24), MELON)
# chain + crank
for dz in (0.09, -0.09):
    rod((BB.x, -0.08, BB.z + dz), (RA.x, -0.08, RA.z + dz * 0.4), 0.012, BLACK)
crank = empty(BB)
add('cyl', (0, 0, 0), (0.03, 0.03, 0.3), STEEL, crank, (pi / 2, 0, 0))
add('cyl', (0, -0.08, 0), (0.2, 0.2, 0.012), STEEL, crank, (pi / 2, 0, 0))
rod((0, -0.13, 0), (CR, -0.13, 0), 0.025, STEEL, crank)
rod((0, 0.13, 0), (-CR, 0.13, 0), 0.025, STEEL, crank)

# ---------------------------------------------------------------- turkey
T = empty()
add('sph', (-0.6, 0, 1.3), (0.95, 0.62, 0.66), FEATH, T, (0, -0.25, 0))
add('sph', (-0.28, 0, 1.38), (0.5, 0.5, 0.52), FEATH, T)
add('sph', (-0.9, 0, 1.33), (0.45, 0.45, 0.4), COPPER, T)
N = empty((-0.2, 0, 1.5), T)

def neck_pt(t):
    return 0.24 * t - 0.07 * sin(pi * t), 0.5 * t, 0.24 - 0.12 * t

for i in range(8):
    t = i / 7
    x, z, d = neck_pt(t)
    add('sph', (x, 0, z), d, FEATH if t < 0.35 else BLUE, N)
HC = Vector((0.25, 0, 0.53))
add('sph', HC, (0.2, 0.16, 0.17), BLUE, N)
add('cone', (0.38, 0, 0.505), (0.07, 0.06, 0.15), BEAK, N, (0, pi / 2 + 0.2, 0))
add('sph', (0.2, 0, 0.64), (0.08, 0.07, 0.09), BLUE, N)
for s in (-1, 1):
    add('sph', (0.29, s * 0.07, 0.56), 0.045, EYE, N)
    add('sph', (0.285, s * 0.064, 0.56), (0.07, 0.03, 0.07), RED, N)
for i in range(34):
    a, b = random.uniform(0, 2 * pi), random.uniform(0.05, 1.4)
    if cos(a) > 0.45 and b > 0.6:
        continue
    add('sph', HC + Vector((0.1 * sin(b) * cos(a), 0.08 * sin(b) * sin(a), 0.085 * cos(b))), 0.028, ORANGE, N)
for i in range(5):
    a = 2 * pi * i / 5
    add('sph', (0.2 + 0.03 * cos(a), 0.025 * sin(a), 0.675), 0.024, ORANGE, N)
for i in range(12):
    x, z, d = neck_pt(random.uniform(0.5, 0.9))
    a = random.uniform(0.6, 2 * pi - 0.6)
    add('sph', (x + 0.5 * d * cos(a), 0.5 * d * sin(a), z), 0.024, ORANGE, N)
# wings reaching the handlebar
for s in (-1, 1):
    gr = Vector((0.12, s * 0.33, 1.15))
    rod((-0.52, s * 0.29, 1.5), gr, 0.09, FEATH, T, 'sph', 0.24, (0, 1, 0))
    rod((-0.45, s * 0.335, 1.44), (-0.05, s * 0.34, 1.22), 0.05, COPPER, T, 'sph', 0.15, (0, 1, 0))
    rod((-0.55, s * 0.34, 1.36), (-0.1, s * 0.345, 1.1), 0.045, BAR, T, 'sph', 0.17, (0, 1, 0))
    add('sph', gr, 0.11, FEATH, T)
# tail fan with ocelli
TL = empty((-0.98, 0, 1.36), T)
FN = Vector((0.62, 0, 0.75)).normalized()
for n, spread, L, w, off in ((11, 0.95, 0.85, 0.13, 0.0), (7, 0.6, 0.47, 0.1, 0.035)):
    for i in range(n):
        phi = (i - (n - 1) / 2) / ((n - 1) / 2) * spread
        d = Vector((-0.75 * cos(phi) - 0.1, 0.8 * sin(phi), 0.62 * cos(phi) + 0.1)).normalized()
        b0 = FN * off
        rod(b0, b0 + d * L, 0.02, TAILG, TL, 'sph', w, FN)
        rod(b0 + d * L * 0.66, b0 + d * L * 0.86, 0.03, OCEL, TL, 'sph', w * 0.8, FN)
        rod(b0 + d * L * 0.86, b0 + d * L * 1.0, 0.032, GOLD, TL, 'sph', w * 0.95, FN)

# legs (analytic 2-bone IK, keyed per frame)
legs = []
for s, ph in ((-1, 0.0), (1, pi)):
    F = empty()
    add('cube', (0, 0, 0), (0.11, 0.1, 0.025), BLACK, F)
    add('sph', (-0.02, 0, 0.05), 0.055, RED, F)
    for dy in (-0.045, 0, 0.045):
        rod((-0.02, 0, 0.04), (0.11, dy, 0.025), 0.022, RED, F)
    rod((-0.02, 0, 0.04), (-0.09, 0, 0.03), 0.022, RED, F)
    legs.append(dict(s=s, ph=ph, F=F, thigh=add('sph', (0, 0, 0), 1, FEATH),
                     shank=add('cyl', (0, 0, 0), 1, RED), knee=add('sph', (0, 0, 0), 0.07, RED)))
L1, L2 = 0.47, 0.5

# ---------------------------------------------------------------- scenery
P = 3 * 2 * pi * WR  # distance per loop = scenery period
add('cube', (0, 0, -0.05), (90, 70, 0.1), GROUND)
add('cube', (0, 0, 0), (90, 3.5, 0.02), ROAD)
add('cube', (0, 2.45, 0.06), (90, 1.4, 0.12), WALK)
add('cube', (0, 1.76, 0.06), (90, 0.06, 0.13), TRIM)
S = empty()
bits = [(random.uniform(0, P), random.uniform(-5.5, -1.95), random.uniform(0.05, 0.16), random.random()) for _ in range(14)]
for k in range(-3, 5):
    x0 = k * P
    for j in range(4):
        add('cube', (x0 + j * P / 4, 1.45, 0.012), (0.8, 0.1, 0.01), WHITE, S)
        add('cube', (x0 + j * P / 4, -1.45, 0.012), (0.8, 0.1, 0.01), WHITE, S)
    for bx, by, bs, br in bits:
        if br < 0.5:
            add('sph', (x0 + bx, by, bs * 0.3), (bs * 1.4, bs, bs * 0.7), STONE, S)
        else:
            add('cone', (x0 + bx, by, bs * 1.2), (bs * 1.5, bs * 1.5, bs * 2.4), LEAF, S)
    for i in range(3):
        w = P / 3
        x = x0 + (i + 0.5) * w
        h = (3.4, 3.0, 3.7)[i]
        add('cube', (x, 4.65, h / 2), (w - 0.02, 3.0, h), HOUSE[i], S)
        add('cube', (x, 3.12, h - 0.12), (w, 0.1, 0.24), WHITE, S)
        add('cube', (x, 3.13, 0.3), (w, 0.06, 0.6), DADO[i], S)
        add('cube', (x - 0.5, 3.13, 1.12), (0.98, 0.06, 2.25), WHITE, S)
        add('cube', (x - 0.5, 3.11, 1.05), (0.8, 0.08, 2.1), WOOD, S)
        add('cube', (x + 0.55, 3.13, 1.55), (0.78, 0.06, 1.2), WHITE, S)
        add('cube', (x + 0.55, 3.11, 1.55), (0.6, 0.08, 1.02), GLASS, S)
    px = x0 + 1.1
    top = Vector((px + 0.25, 2.35, 3.0))
    rod((px, 2.35, 0.1), top, 0.17, TRUNK, S)
    for j in range(9):
        a = 2 * pi * j / 9
        rod(top, top + Vector((1.2 * cos(a), 1.2 * sin(a), -0.45)), 0.03, LEAF, S, 'sph', 0.3, (0, 0, 1))

# ---------------------------------------------------------------- animation
NF = 72
for f in range(1, NF + 2):
    u = (f - 1) / NF
    th = 2 * pi * 2 * u
    crank.rotation_euler = (0, th, 0)
    crank.keyframe_insert('rotation_euler', frame=f)
    for wobj in wheels:
        wobj.rotation_euler = (0, 2 * pi * 3 * u, 0)
        wobj.keyframe_insert('rotation_euler', frame=f)
    S.location = (-P * u, 0, 0)
    S.keyframe_insert('location', frame=f)
    bob = 0.012 * sin(2 * th)
    T.location = (0, 0, bob)
    T.keyframe_insert('location', frame=f)
    N.rotation_euler = (0, 0.08 * sin(2 * th + 0.8), 0.05 * sin(th))
    N.keyframe_insert('rotation_euler', frame=f)
    TL.rotation_euler = (0.05 * sin(th), 0.04 * sin(2 * th), 0.06 * sin(th + 1.0))
    TL.keyframe_insert('rotation_euler', frame=f)
    for lg in legs:
        a = th + lg['ph']
        y = lg['s'] * 0.2
        ped = Vector((BB.x + CR * cos(a), y, BB.z - CR * sin(a)))
        lg['F'].location = ped
        lg['F'].keyframe_insert('location', frame=f)
        H = Vector((-0.5, y, 1.17 + bob))
        A = ped + Vector((-0.02, 0, 0.05))
        d = A - H
        dl = min(d.length, L1 + L2 - 0.002)
        un = d.normalized()
        aa = (L1 * L1 - L2 * L2 + dl * dl) / (2 * dl)
        hh = math.sqrt(max(L1 * L1 - aa * aa, 0.0))
        K = H + un * aa + Vector((-un.z, 0, un.x)) * hh
        stretch(lg['thigh'], H, K, 0.17, None, f)
        stretch(lg['shank'], K, A, 0.05, None, f)
        lg['knee'].location = K
        lg['knee'].keyframe_insert('location', frame=f)

# ---------------------------------------------------------------- camera, light, world, render
cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
col.objects.link(cam)
cam.data.lens = 40
cam.location = (3.0, -7.2, 2.0)
cam.rotation_euler = (Vector((0.05, 0, 1.2)) - cam.location).to_track_quat('-Z', 'Y').to_euler()
scene.camera = cam

sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN'))
col.objects.link(sun)
sun.data.energy = 4.0
sun.rotation_euler = (0.9, 0, 0.5)

world = scene.world or bpy.data.worlds.new('world')
scene.world = world
try:
    world.use_nodes = True
except Exception:
    pass
wn = world.node_tree
bg = next((n for n in wn.nodes if n.type == 'BACKGROUND'), None)
if bg is None:
    wn.nodes.clear()
    bg = wn.nodes.new('ShaderNodeBackground')
    wo = wn.nodes.new('ShaderNodeOutputWorld')
    wn.links.new(bg.outputs[0], wo.inputs[0])
bg.inputs[0].default_value = (0.45, 0.72, 1.0, 1)
bg.inputs[1].default_value = 1.0

for eng in ('BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT'):
    try:
        scene.render.engine = eng
        break
    except Exception:
        pass
try:
    scene.eevee.taa_render_samples = 24
except Exception:
    pass
try:
    scene.view_settings.view_transform = 'Standard'
except Exception:
    pass
r = scene.render
r.resolution_x, r.resolution_y, r.resolution_percentage = 960, 540, 100
r.fps = 30
scene.frame_start, scene.frame_end = 1, NF
out = os.path.join(HERE, 'frames')
os.makedirs(out, exist_ok=True)
try:
    r.image_settings.media_type = 'IMAGE'
except Exception:
    pass
r.image_settings.file_format = 'PNG'
r.filepath = os.path.join(out, 'frame_')
bpy.ops.render.render(animation=True)
