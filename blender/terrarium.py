# Renders the static terrarium set as layers for static/terrarium/set/.
#
#   blender -b -P blender/terrarium.py -- [--scale 0.4] [--samples 32] [--only back,id] [--portrait]
#
# --portrait renders a taller jar with more soil for phones, like the page's
# procedural layout does. scripts/render-set.sh renders everything the site uses.
#
# Units: the jar's glass is 2 units wide (x -1..1) and sits on z=0, looking
# down +y with an orthographic camera, so 1 unit = jarWidthPx / 2 in the page.
# Layers:
#   back   everything but the glass (live mycelium is drawn over this)
#   front  moss, litter and the twig only, drawn over the mycelium
#   glass  reflections and condensation only, drawn over everything
#   id     flat colors: red = soil, green = wood, black = everything else
#   grow   a strip of growth frames per mushroom species, in mush/, with
#          mush.json (run on its own)
# set.json records the frame so the page can line the layers up.
import bpy, bmesh, json, math, os, random, sys
from mathutils import Vector, noise

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def arg(name, default, cast=str):
    return cast(argv[argv.index(name) + 1]) if name in argv else default
SCALE = arg("--scale", 1.0, float)
SAMPLES = arg("--samples", 128, int)
ONLY = arg("--only", "back,front,glass,id").split(",")
STRIPS = arg("--strips", "")  # grow: just these strips, kept alongside the rest
BRACKET_PPU = arg("--bracket-ppu", 100, int)
OUT = arg("--out", os.path.join(os.path.dirname(bpy.data.filepath) or os.getcwd(), "static/terrarium/set"))

PORTRAIT = "--portrait" in argv
PPU = 390  # px per unit at scale 1: a 780px jar
# matches the page layout: jh = 1.05 jw (1.5 jw on phones), domeH = .3 jw
JAR_H, DOME_H = (3.0, 0.6) if PORTRAIT else (2.1, 0.6)
WALL_TOP = JAR_H - DOME_H
GROUND = JAR_H * (0.4 if PORTRAIT else 0.34)  # soil surface
GRAVEL = 0.12
SOIL_R = 0.975
LOG_R, LOG_LEN = 0.17, 0.86
FRAME = dict(x0=-1.13, x1=1.13, z0=-0.16, z1=JAR_H + 0.1)

rng = random.Random(7)
def rnd(a, b): return rng.uniform(a, b)

# ---------- scene ----------
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "GPU"
prefs = bpy.context.preferences.addons["cycles"].preferences
prefs.compute_device_type = "METAL"
prefs.get_devices()
for d in prefs.devices:
    d.use = True
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
scene.render.film_transparent = True
scene.view_settings.view_transform = "AgX"
scene.render.resolution_percentage = 100
scene.render.resolution_x = round((FRAME["x1"] - FRAME["x0"]) * PPU * SCALE)
scene.render.resolution_y = round((FRAME["z1"] - FRAME["z0"]) * PPU * SCALE)

world = bpy.data.worlds.new("world")
scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs["Color"].default_value = (0.02, 0.035, 0.025, 1)
bg.inputs["Strength"].default_value = 0.35

cam_data = bpy.data.cameras.new("cam")
cam_data.type = "ORTHO"
cam_data.sensor_fit = "VERTICAL"
cam_data.ortho_scale = FRAME["z1"] - FRAME["z0"]
cam = bpy.data.objects.new("cam", cam_data)
cam.location = ((FRAME["x0"] + FRAME["x1"]) / 2, -10, (FRAME["z0"] + FRAME["z1"]) / 2)
cam.rotation_euler = (math.pi / 2, 0, 0)
scene.collection.objects.link(cam)
scene.camera = cam

def light(name, kind, loc, energy, color, size=1.0, rot=None):
    ld = bpy.data.lights.new(name, kind)
    ld.energy, ld.color = energy, color
    if kind == "AREA":
        ld.size = size
    o = bpy.data.objects.new(name, ld)
    o.location = loc
    if rot:
        o.rotation_euler = rot
    else:
        d = Vector((0, 0, 1.0)) - Vector(loc)
        o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(o)
    return o

# the studio lights stay out of the glass's reflections...
for l in (light("key", "AREA", (-3.6, -1.6, 2.6), 170, (1.0, 0.9, 0.78), 2.5),
          light("fill", "AREA", (3.0, -2.5, 1.4), 30, (0.7, 0.85, 1.0), 3),
          light("rim", "AREA", (0.6, 3.0, 2.6), 120, (0.85, 1.0, 0.85), 2)):
    l.visible_glossy = False
# ...except a tall narrow "window", which is the highlight on the glass
win = light("window", "AREA", (-1.7, -2.4, 1.5), 40, (0.95, 1.0, 0.97))
win.data.shape, win.data.size, win.data.size_y = "RECTANGLE", 0.22, 2.2

# ---------- materials ----------
def mat(name, color, rough=0.6, **kw):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (*color, 1)
    p.inputs["Roughness"].default_value = rough
    for k, v in kw.items():
        p.inputs[k].default_value = v
    return m

def sock(sockets, name, kind=None):
    return next(s for s in sockets if s.name == name and (kind is None or s.type == kind))

def textured(name, ramp, scale, rough=0.85, bump=0.4, voronoi=None, stretch=(1, 1, 1), random_tint=0.0):
    """Principled material colored by a noise-driven ramp, with bump."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    N, L = nt.nodes, nt.links
    p = N["Principled BSDF"]
    p.inputs["Roughness"].default_value = rough
    tc = N.new("ShaderNodeTexCoord")
    mp = N.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = stretch
    L.new(tc.outputs["Object"], mp.inputs["Vector"])
    nz = N.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = scale
    nz.inputs["Detail"].default_value = 8
    nz.inputs["Roughness"].default_value = 0.6
    L.new(mp.outputs["Vector"], nz.inputs["Vector"])
    cr = N.new("ShaderNodeValToRGB")
    els = cr.color_ramp.elements
    els[0].position, els[0].color = ramp[0][0], (*ramp[0][1], 1)
    els[1].position, els[1].color = ramp[-1][0], (*ramp[-1][1], 1)
    for pos, col in ramp[1:-1]:
        e = els.new(pos)
        e.color = (*col, 1)
    fac = nz.outputs["Fac"]
    if voronoi:
        vo = N.new("ShaderNodeTexVoronoi")
        vo.inputs["Scale"].default_value = voronoi
        L.new(mp.outputs["Vector"], vo.inputs["Vector"])
        mx = N.new("ShaderNodeMath")
        mx.operation = "MULTIPLY_ADD"
        mx.inputs[1].default_value = 0.35
        L.new(vo.outputs["Distance"], mx.inputs[0])
        L.new(nz.outputs["Fac"], mx.inputs[2])
        fac = mx.outputs[0]
    L.new(fac, cr.inputs["Fac"])
    col = cr.outputs["Color"]
    if random_tint:
        oi = N.new("ShaderNodeObjectInfo")
        hsv = N.new("ShaderNodeHueSaturation")
        L.new(col, hsv.inputs["Color"])
        mr = N.new("ShaderNodeMapRange")
        mr.inputs["To Min"].default_value = 1 - random_tint
        mr.inputs["To Max"].default_value = 1 + random_tint
        L.new(oi.outputs["Random"], mr.inputs["Value"])
        L.new(mr.outputs["Result"], hsv.inputs["Value"])
        col = hsv.outputs["Color"]
    L.new(col, p.inputs["Base Color"])
    b = N.new("ShaderNodeBump")
    b.inputs["Strength"].default_value = bump
    L.new(fac, b.inputs["Height"])
    L.new(b.outputs["Normal"], p.inputs["Normal"])
    return m

RIVER = [(0.22, 0.2, 0.18), (0.32, 0.28, 0.23), (0.1, 0.095, 0.09), (0.4, 0.38, 0.35),
         (0.2, 0.15, 0.11), (0.27, 0.26, 0.25), (0.45, 0.43, 0.39), (0.15, 0.14, 0.13)]

def river_stone():
    """Rounded river pebbles: each its own color from RIVER, finely speckled,
    with a little sheen."""
    m = bpy.data.materials.new("river-stone")
    m.use_nodes = True
    N, L = m.node_tree.nodes, m.node_tree.links
    p = N["Principled BSDF"]
    p.inputs["Roughness"].default_value = 0.38
    oi = N.new("ShaderNodeObjectInfo")
    pick = N.new("ShaderNodeValToRGB")
    pick.color_ramp.interpolation = "CONSTANT"
    e = pick.color_ramp.elements
    e[0].position, e[0].color = 0.0, (*RIVER[0], 1)
    e[1].position, e[1].color = 1.0, (*RIVER[-1], 1)
    for k, c in enumerate(RIVER[1:-1], 1):
        e.new(k / len(RIVER)).color = (*c, 1)
    L.new(oi.outputs["Random"], pick.inputs["Fac"])
    tc = N.new("ShaderNodeTexCoord")
    sp = N.new("ShaderNodeTexNoise")
    sp.inputs["Scale"].default_value = 160
    sp.inputs["Detail"].default_value = 4
    L.new(tc.outputs["Object"], sp.inputs["Vector"])
    fleck = N.new("ShaderNodeMapRange")
    fleck.inputs["To Min"].default_value, fleck.inputs["To Max"].default_value = 0.7, 1.25
    L.new(sp.outputs["Fac"], fleck.inputs["Value"])
    mul = N.new("ShaderNodeMix")
    mul.data_type, mul.blend_type = "RGBA", "MULTIPLY"
    mul.inputs["Factor"].default_value = 1
    L.new(pick.outputs["Color"], sock(mul.inputs, "A", "RGBA"))
    gc = N.new("ShaderNodeCombineColor")
    for i in range(3):
        L.new(fleck.outputs["Result"], gc.inputs[i])
    L.new(gc.outputs[0], sock(mul.inputs, "B", "RGBA"))
    L.new(sock(mul.outputs, "Result", "RGBA"), p.inputs["Base Color"])
    b = N.new("ShaderNodeBump")
    b.inputs["Strength"].default_value = 0.08
    L.new(sp.outputs["Fac"], b.inputs["Height"])
    L.new(b.outputs["Normal"], p.inputs["Normal"])
    return m

def soil_material():
    m = bpy.data.materials.new("soil")
    m.use_nodes = True
    N, L = m.node_tree.nodes, m.node_tree.links
    p = N["Principled BSDF"]
    p.inputs["Roughness"].default_value = 0.95
    tc = N.new("ShaderNodeTexCoord")
    nz = N.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 14
    nz.inputs["Detail"].default_value = 12
    nz.inputs["Roughness"].default_value = 0.7
    L.new(tc.outputs["Object"], nz.inputs["Vector"])
    crumbs = N.new("ShaderNodeTexVoronoi")
    crumbs.inputs["Scale"].default_value = 160
    crumbs.inputs["Randomness"].default_value = 1
    L.new(tc.outputs["Object"], crumbs.inputs["Vector"])
    clods = N.new("ShaderNodeTexVoronoi")
    clods.inputs["Scale"].default_value = 38
    L.new(tc.outputs["Object"], clods.inputs["Vector"])
    # height in the soil: 0 at the surface, 1 at the gravel
    xyz = N.new("ShaderNodeSeparateXYZ")
    L.new(tc.outputs["Object"], xyz.inputs["Vector"])
    depth = N.new("ShaderNodeMapRange")
    depth.inputs["From Min"].default_value = GROUND
    depth.inputs["From Max"].default_value = GRAVEL
    L.new(xyz.outputs["Z"], depth.inputs["Value"])
    # wobble the humus line
    wob = N.new("ShaderNodeMath")
    wob.operation = "MULTIPLY_ADD"
    wob.inputs[1].default_value = 0.25
    L.new(nz.outputs["Fac"], wob.inputs[0])
    L.new(depth.outputs["Result"], wob.inputs[2])
    layer = N.new("ShaderNodeValToRGB")
    e = layer.color_ramp.elements
    e[0].position, e[0].color = 0.12, (0.018, 0.011, 0.007, 1)
    e[1].position, e[1].color = 0.55, (0.075, 0.05, 0.03, 1)
    e.new(1.0).color = (0.06, 0.042, 0.028, 1)
    L.new(wob.outputs[0], layer.inputs["Fac"])
    speck = N.new("ShaderNodeValToRGB")
    e = speck.color_ramp.elements
    e[0].position, e[0].color = 0.0, (1.5, 1.4, 1.3, 1)
    e[1].position, e[1].color = 0.12, (1, 1, 1, 1)
    L.new(crumbs.outputs["Distance"], speck.inputs["Fac"])
    var = N.new("ShaderNodeValToRGB")
    e = var.color_ramp.elements
    e[0].position, e[0].color = 0.3, (0.6, 0.6, 0.6, 1)
    e[1].position, e[1].color = 0.75, (1.35, 1.3, 1.25, 1)
    L.new(nz.outputs["Fac"], var.inputs["Fac"])
    m1 = N.new("ShaderNodeMix")
    m1.data_type, m1.blend_type = "RGBA", "MULTIPLY"
    m1.inputs["Factor"].default_value = 1
    L.new(layer.outputs["Color"], sock(m1.inputs, "A", "RGBA"))
    L.new(var.outputs["Color"], sock(m1.inputs, "B", "RGBA"))
    m2 = N.new("ShaderNodeMix")
    m2.data_type, m2.blend_type = "RGBA", "MULTIPLY"
    m2.inputs["Factor"].default_value = 1
    L.new(sock(m1.outputs, "Result", "RGBA"), sock(m2.inputs, "A", "RGBA"))
    L.new(speck.outputs["Color"], sock(m2.inputs, "B", "RGBA"))
    L.new(sock(m2.outputs, "Result", "RGBA"), p.inputs["Base Color"])
    h = N.new("ShaderNodeMath")
    h.operation = "MULTIPLY_ADD"
    h.inputs[1].default_value = 0.5
    L.new(clods.outputs["Distance"], h.inputs[0])
    L.new(crumbs.outputs["Distance"], h.inputs[2])
    b = N.new("ShaderNodeBump")
    b.inputs["Strength"].default_value = 0.9
    b.inputs["Distance"].default_value = 0.02
    L.new(h.outputs[0], b.inputs["Height"])
    L.new(b.outputs["Normal"], p.inputs["Normal"])
    return m

M = {
    "soil": soil_material(),
    # the gravel bed is only seen in the gaps between the stones
    "gravel": textured("gravel", [(0.0, (0.02, 0.02, 0.02)), (1.0, (0.07, 0.065, 0.06))], 40, rough=0.7, bump=0.3),
    "stone": river_stone(),
    "pebble": textured("pebble", [(0.0, (0.05, 0.04, 0.03)), (1.0, (0.16, 0.13, 0.1))], 8, rough=0.6, bump=0.2, random_tint=0.4),
    "bark": textured("bark", [(0.0, (0.012, 0.008, 0.005)), (0.45, (0.05, 0.034, 0.022)), (0.75, (0.1, 0.07, 0.048)), (1.0, (0.17, 0.13, 0.095))], 9, stretch=(0.2, 1, 1), voronoi=20, bump=1.0),
    "base": textured("base", [(0.0, (0.12, 0.07, 0.04)), (1.0, (0.3, 0.19, 0.11))], 3, stretch=(1, 1, 12), rough=0.45, bump=0.15),
    "moss": textured("moss", [(0.0, (0.06, 0.12, 0.02)), (0.6, (0.17, 0.28, 0.05)), (1.0, (0.33, 0.45, 0.1))], 60, rough=0.9, bump=0.5, random_tint=0.3),
    "leaf": textured("leaf", [(0.0, (0.2, 0.08, 0.02)), (0.5, (0.42, 0.2, 0.05)), (1.0, (0.55, 0.33, 0.1))], 9, rough=0.7, bump=0.3, random_tint=0.5),
    "twig": textured("twig", [(0.0, (0.04, 0.03, 0.02)), (1.0, (0.14, 0.1, 0.07))], 30, stretch=(1, 1, 0.2), bump=0.5),
    "lichen": mat("lichen", (0.55, 0.62, 0.48), 0.9),
    "stalk": mat("stalk", (0.45, 0.25, 0.08), 0.6),
    "capsule": mat("capsule", (0.5, 0.3, 0.1), 0.5),
    "glass": mat("glass", (0.92, 0.98, 0.95), 0.02, **{"Transmission Weight": 1.0, "IOR": 1.47}),
    # a little rough, so each drop catches the window as a soft dot, not a line
    "drop": mat("drop", (1, 1, 1), 0.2, **{"Transmission Weight": 1.0, "IOR": 1.33}),
}
def thin_glass():
    """A cloche wall is thin, so it reflects but barely refracts: transparent
    plus a Fresnel-weighted gloss composites cleanly over the page."""
    m = bpy.data.materials.new("glass")
    m.use_nodes = True
    N, L = m.node_tree.nodes, m.node_tree.links
    N.remove(N["Principled BSDF"])
    tr = N.new("ShaderNodeBsdfTransparent")
    tr.inputs["Color"].default_value = (0.96, 1.0, 0.97, 1)
    gl = N.new("ShaderNodeBsdfGlossy")
    gl.inputs["Roughness"].default_value = 0.03
    lw = N.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = 0.12
    mix = N.new("ShaderNodeMixShader")
    L.new(lw.outputs["Fresnel"], mix.inputs["Fac"])
    L.new(tr.outputs[0], mix.inputs[1])
    L.new(gl.outputs[0], mix.inputs[2])
    L.new(mix.outputs[0], N["Material Output"].inputs["Surface"])
    return m
M["glass"] = thin_glass()

def endgrain():
    """Growth rings on the log's cut ends, darkening toward the rotten bark."""
    m = bpy.data.materials.new("endgrain")
    m.use_nodes = True
    N, L = m.node_tree.nodes, m.node_tree.links
    p = N["Principled BSDF"]
    p.inputs["Roughness"].default_value = 0.85
    tc = N.new("ShaderNodeTexCoord")
    yz = N.new("ShaderNodeVectorMath")
    yz.operation = "MULTIPLY"
    yz.inputs[1].default_value = (0, 1, 1)
    L.new(tc.outputs["Object"], yz.inputs[0])
    rings = N.new("ShaderNodeTexWave")
    rings.wave_type = "RINGS"
    rings.inputs["Scale"].default_value = 9
    rings.inputs["Distortion"].default_value = 3
    rings.inputs["Detail"].default_value = 4
    L.new(yz.outputs[0], rings.inputs["Vector"])
    r = N.new("ShaderNodeVectorMath")
    r.operation = "LENGTH"
    L.new(yz.outputs[0], r.inputs[0])
    edge = N.new("ShaderNodeMapRange")
    edge.inputs["From Min"].default_value, edge.inputs["From Max"].default_value = LOG_R * 0.55, LOG_R
    L.new(r.outputs["Value"], edge.inputs["Value"])
    cr = N.new("ShaderNodeValToRGB")
    e = cr.color_ramp.elements
    e[0].position, e[0].color = 0.0, (0.2, 0.12, 0.06, 1)
    e[1].position, e[1].color = 1.0, (0.42, 0.29, 0.16, 1)
    L.new(rings.outputs["Fac"], cr.inputs["Fac"])
    rot = N.new("ShaderNodeMix")
    rot.data_type, rot.blend_type = "RGBA", "MULTIPLY"
    L.new(edge.outputs["Result"], rot.inputs["Factor"])
    L.new(cr.outputs["Color"], sock(rot.inputs, "A", "RGBA"))
    sock(rot.inputs, "B", "RGBA").default_value = (0.25, 0.18, 0.12, 1)
    L.new(sock(rot.outputs, "Result", "RGBA"), p.inputs["Base Color"])
    b = N.new("ShaderNodeBump")
    b.inputs["Strength"].default_value = 0.4
    L.new(rings.outputs["Fac"], b.inputs["Height"])
    L.new(b.outputs["Normal"], p.inputs["Normal"])
    return m
M["endgrain"] = endgrain()

for k in ("leaf", "moss"):
    p = M[k].node_tree.nodes["Principled BSDF"]
    p.inputs["Subsurface Weight"].default_value = 0.15

# ---------- geometry helpers ----------
COL = {}
def coll(name):
    c = bpy.data.collections.new(name)
    scene.collection.children.link(c)
    COL[name] = c
    return c
for name in ("set", "front", "glass"):
    coll(name)

def obj(name, mesh, material, collection="set", sub=None, smooth=True):
    o = bpy.data.objects.new(name, mesh)
    COL[collection].objects.link(o)
    if material:
        o.data.materials.append(material)
    if smooth:
        for poly in o.data.polygons:
            poly.use_smooth = True
    o["sub"] = sub or ""
    return o

def lathe(name, profile, segs, material, collection="set", close_top=False, sub=None):
    """Revolves (r, z) points around the z axis."""
    bm = bmesh.new()
    rings = []
    for r, z in profile:
        ring = [bm.verts.new((r * math.cos(2 * math.pi * i / segs), r * math.sin(2 * math.pi * i / segs), z)) for i in range(segs)]
        rings.append(ring)
    for a, b in zip(rings, rings[1:]):
        for i in range(segs):
            j = (i + 1) % segs
            bm.faces.new((a[i], a[j], b[j], b[i]))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return obj(name, me, material, collection, sub)

def blob(name, material, loc, size, rot=(0, 0, 0), subdiv=2, rough=0.25, seed=0, collection="set", sub=None):
    """A lumpy ellipsoid: an icosphere displaced by noise."""
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=1.0)
    off = Vector((seed * 3.1, seed * 1.7, seed * 2.3))
    for v in bm.verts:
        v.co *= 1 + rough * noise.noise(v.co * 1.6 + off)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = obj(name, me, material, collection, sub)
    o.location, o.scale, o.rotation_euler = loc, size, rot
    return o

def tube(name, pts, radius, material, collection="set", taper=0.4):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = radius
    cu.bevel_resolution = 3
    sp = cu.splines.new("NURBS")
    sp.points.add(len(pts) - 1)
    for p, co in zip(sp.points, pts):
        p.co = (*co, 1)
    for i, p in enumerate(sp.points):
        p.radius = 1 - taper * i / max(1, len(pts) - 1)
    sp.use_endpoint_u = True
    sp.order_u = min(4, len(pts))
    o = bpy.data.objects.new(name, cu)
    COL[collection].objects.link(o)
    o.data.materials.append(material)
    o["sub"] = ""
    return o

# ---------- the set ----------
def soil_top(x, y):
    return GROUND + 0.022 * noise.noise(Vector((x * 2.2, y * 2.2, 0.5))) + 0.012 * noise.noise(Vector((x * 9, y * 9, 1.5))) \
        + 0.005 * noise.noise(Vector((x * 30, y * 30, 2.5)))

# soil: a disc whose top follows soil_top, filling the jar down to the gravel
segs, rings_n = 160, 28
bm = bmesh.new()
center = bm.verts.new((0, 0, soil_top(0, 0)))
rings = []
for k in range(1, rings_n + 1):
    r = SOIL_R * k / rings_n
    rings.append([bm.verts.new((r * math.cos(t), r * math.sin(t), soil_top(r * math.cos(t), r * math.sin(t))))
                  for t in (2 * math.pi * i / segs for i in range(segs))])
for i in range(segs):
    bm.faces.new((center, rings[0][i], rings[0][(i + 1) % segs]))
for a, b in zip(rings, rings[1:]):
    for i in range(segs):
        j = (i + 1) % segs
        bm.faces.new((a[i], b[i], b[j], a[j]))
prev = rings[-1]
for z in (GROUND - 0.15, GROUND - 0.32, GRAVEL):
    ring = [bm.verts.new((v.co.x, v.co.y, z)) for v in rings[-1]]
    for i in range(segs):
        j = (i + 1) % segs
        bm.faces.new((prev[i], ring[i], ring[j], prev[j]))
    prev = ring
me = bpy.data.meshes.new("soil")
bm.to_mesh(me)
bm.free()
obj("soil", me, M["soil"], sub="soil")

# clods along the front rim so the soil line isn't a ruled edge
for i in range(140):
    x = rnd(-0.96, 0.96)
    y = -math.sqrt(max(0.0, SOIL_R ** 2 - x * x)) + rnd(0.005, 0.06)
    s = rnd(0.006, 0.016)
    blob(f"clod{i}", M["soil"], (x, y, soil_top(x, y) - s * 0.3), (s, s, s * 0.7), (rnd(0, 3), rnd(0, 3), rnd(0, 3)),
         subdiv=1, rough=0.4, seed=700 + i, sub="soil")

# gravel bed and stones against the glass
lathe("gravel-bed", [(SOIL_R, 0.0), (SOIL_R, GRAVEL)], 120, M["gravel"])
# river pebbles against the glass: rounded and flattish, mostly small with a
# few big ones, in two layers so the gaps show more stones rather than bed.
# They draw from their own generator; the shared one is advanced as the old
# 520-stone loop did, so everything placed after keeps its position.
srng = random.Random(11)
for _ in range(520 * 9):
    rng.random()
for i in range(1400):
    x = srng.uniform(-0.97, 0.97)
    y = -math.sqrt(max(0.0, SOIL_R ** 2 - x * x)) + (srng.uniform(0.0, 0.012) if i % 3 else srng.uniform(0.012, 0.035))
    s = 0.008 + 0.026 * srng.random() ** 2.2
    blob(f"stone{i}", M["stone"], (x, y, srng.uniform(0.004, GRAVEL - 0.003)),
         (s * srng.uniform(1.0, 1.35), s * srng.uniform(0.6, 0.9), s * srng.uniform(0.55, 0.8)),
         (srng.uniform(-0.3, 0.3), srng.uniform(-0.3, 0.3), srng.uniform(0, 3)), subdiv=3, rough=0.1, seed=i)
# a few pebbles in the soil, against the glass
for i in range(30):
    x = rnd(-0.95, 0.95)
    y = -math.sqrt(max(0.0, SOIL_R ** 2 - x * x)) + 0.008
    s = rnd(0.008, 0.022)
    blob(f"pebble{i}", M["pebble"], (x, y, rnd(GRAVEL + 0.03, GROUND - 0.04)), (s, s * 0.8, s * rnd(0.6, 0.9)),
         (rnd(0, 3), rnd(0, 3), rnd(0, 3)), subdiv=2, rough=0.3, seed=100 + i, sub="soil")

# the log: lying across the left half, sunk a little, cut end turned toward us
LOG_C = Vector((-0.2, -0.55, GROUND + LOG_R * 0.55))
bm = bmesh.new()
lsegs, lrows = 220, 110
grid = []
for k in range(lrows + 1):
    u = k / lrows
    row = []
    for i in range(lsegs):
        t = 2 * math.pi * i / lsegs
        ridge = (1 - abs(noise.noise(Vector((u * 2.2, math.cos(t) * 7, math.sin(t) * 7))))) ** 2
        d = 1 + 0.05 * noise.noise(Vector((u * 2, math.cos(t) * 1.5, math.sin(t) * 1.5))) \
              + 0.15 * (ridge - 0.6) + 0.02 * noise.noise(Vector((u * 40, math.cos(t) * 9, math.sin(t) * 9)))
        row.append(bm.verts.new(((u - 0.5) * LOG_LEN, LOG_R * d * math.cos(t), LOG_R * d * math.sin(t))))
    grid.append(row)
for a, b in zip(grid, grid[1:]):
    for i in range(lsegs):
        j = (i + 1) % lsegs
        bm.faces.new((a[i], a[j], b[j], b[i]))
ends = [[v.co.copy() for v in grid[-1]], [v.co.copy() for v in grid[0]]]
me = bpy.data.meshes.new("log")
bm.to_mesh(me)
bm.free()
log = obj("log", me, M["bark"], sub="wood")
log.location, log.rotation_euler = LOG_C, (0, 0, math.radians(-30))
for end, sign in zip(ends, (1, -1)):
    bm = bmesh.new()
    vs = [bm.verts.new(co) for co in end]
    f = bm.faces.new(vs if sign > 0 else list(reversed(vs)))
    me = bpy.data.meshes.new("end")
    bm.to_mesh(me)
    bm.free()
    e = obj("log-end", me, M["endgrain"], sub="wood")
    e.location, e.rotation_euler = LOG_C, log.rotation_euler

def log_top(x):
    """World z of the top of the log at world x (approximate), or None."""
    ca = math.cos(math.radians(-30))
    u = (x - LOG_C.x) / ca
    if abs(u) > LOG_LEN / 2 - 0.01:
        return None
    return LOG_C.z + LOG_R * 0.98

# moss: clumps of small lumps on the soil and along the log, plus sporophytes
def moss_clump(cx, cy, cz_fn, n, spread, tag):
    for k in range(n):
        x, y = cx + rnd(-spread, spread), cy + rnd(-spread * 0.6, spread * 0.6)
        z = cz_fn(x, y)
        if z is None:
            continue
        s = rnd(0.012, 0.028) * (1 - 0.55 * abs(x - cx) / spread)
        blob(f"moss{tag}-{k}", M["moss"], (x, y, z + s * 0.4), (s, s, s * rnd(0.6, 1.0)), (0, 0, rnd(0, 6)),
             subdiv=1, rough=0.35, seed=k, collection="front")
    for k in range(rng.randint(2, 6)):
        x, y = cx + rnd(-spread * 0.6, spread * 0.6), cy + rnd(-0.03, 0.03)
        z = cz_fn(x, y)
        if z is None:
            continue
        h = rnd(0.025, 0.05)
        lean = rnd(-0.008, 0.008)
        tube(f"seta{tag}-{k}", [(x, y, z), (x + lean * 0.4, y, z + h * 0.6), (x + lean, y, z + h)], 0.0012, M["stalk"], "front", taper=0.3)
        blob(f"caps{tag}-{k}", M["capsule"], (x + lean, y, z + h), (0.003, 0.003, 0.0045), (rnd(-.3, .3), 0, 0),
             subdiv=1, rough=0.1, seed=k, collection="front")

for i in range(34):
    on_log = i % 3 == 0
    if on_log:
        u = rnd(-0.4, 0.4)
        x = LOG_C.x + u * math.cos(math.radians(-30))
        moss_clump(x, rnd(-0.75, -0.45), lambda x, y: log_top(x), 90, rnd(0.06, 0.12), i)
    else:
        moss_clump(rnd(-0.95, 0.95), rnd(-0.95, -0.2), soil_top, 80, rnd(0.05, 0.11), i)

# leaf litter
for i in range(70):
    x, y = rnd(-0.96, 0.96), rnd(-0.96, 0.2)
    z = soil_top(x, y)
    s = rnd(0.025, 0.05)
    blob(f"leaf{i}", M["leaf"], (x, y, z + s * 0.25), (s, s * rnd(0.35, 0.5), 0.004), (rnd(-1.1, 1.1), rnd(-0.6, 0.6), rnd(0, 6)),
         subdiv=2, rough=0.35, seed=300 + i, collection="front")

# the twig, stuck in the soil and leaning left, with side twigs and lichen
tb = Vector((0.38, -0.45, GROUND - 0.03))
tip = tb + Vector((-0.34, 0.05, 0.86))
mid = (tb + tip) / 2 + Vector((-0.04, 0, 0))
tube("twig", [tb, tb.lerp(mid, 0.5), mid, mid.lerp(tip, 0.5), tip], 0.011, M["twig"], "front", taper=0.6)
for t, dx, l in ((0.45, -1, 0.22), (0.62, 1, 0.18), (0.8, -1, 0.12)):
    p = tb.lerp(tip, t)
    end = p + Vector((dx * l * 0.55, rnd(-0.03, 0.03), l))
    tube(f"twig-side{t}", [p, p.lerp(end, 0.5) + Vector((dx * 0.01, 0, 0)), end], 0.006, M["twig"], "front", taper=0.7)
for i in range(60):
    p = tb.lerp(tip, rnd(0.2, 0.95)) + Vector((rnd(-0.01, 0.01), -0.01, rnd(-0.01, 0.01)))
    s = rnd(0.004, 0.009)
    blob(f"lichen{i}", M["lichen"], p, (s, s * 0.5, s * 0.8), (rnd(0, 3), 0, rnd(0, 3)), subdiv=1, rough=0.4, seed=500 + i, collection="front")

# wooden base
base = lathe("base", [(0.0, -0.1), (1.09, -0.1), (1.1, -0.095), (1.1, -0.006), (1.09, 0.0), (0.0, 0.0)], 160, M["base"])

# glass cloche: straight wall, elliptical dome, knob
prof = [(1.0, 0.0), (1.0, WALL_TOP)]
for k in range(1, 25):
    t = k / 24 * math.pi / 2
    prof.append((math.cos(t) * 1.0 + 1e-4, WALL_TOP + DOME_H * math.sin(t)))
glass = lathe("glass", prof, 160, M["glass"], "glass")
sol = glass.modifiers.new("solid", "SOLIDIFY")
sol.thickness, sol.offset = 0.012, -1
lathe("lip", [(1.0, 0.0), (1.016, 0.0), (1.016, 0.03), (1.0, 0.03)], 160, M["glass"], "glass")
blob("knob", M["glass"], (0, 0, JAR_H + 0.018), (0.07, 0.07, 0.03), subdiv=3, rough=0.0, collection="glass")
# condensation on the inside of the glass, densest under the dome
for i in range(480):
    f = rng.random() ** 1.6
    z = JAR_H - f * (JAR_H - GROUND - 0.1)
    if z > WALL_TOP:
        r = math.cos(math.asin(min(1.0, (z - WALL_TOP) / DOME_H)))
    else:
        r = 1.0
    t = math.radians(rnd(200, 340))
    s = rnd(0.002, 0.008) * (1.2 - f * 0.6)
    d = blob(f"drop{i}", M["drop"], ((r - 0.014) * math.cos(t), (r - 0.014) * math.sin(t), z), (s, s, s), subdiv=2, rough=0.0,
             seed=900 + i, collection="glass")
    d.visible_glossy = False  # or the dome mirrors them into streaks near its edge

# ---------- render layers ----------
ALL = [o for o in scene.objects if o.type in ("MESH", "CURVE")]

def show(visible, holdout=()):
    for o in ALL:
        o.hide_render = o not in visible and o not in holdout
        o.is_holdout = o in holdout

def render(name, ext="WEBP"):
    os.makedirs(OUT, exist_ok=True)
    s = scene.render.image_settings
    s.file_format = ext
    s.color_mode = "RGBA" if ext != "PNG" or name != "id" else "RGB"
    if ext == "WEBP":
        s.quality = 72 if name == "glass" else 88  # the glass is all soft gradients
    scene.render.filepath = os.path.join(OUT, name)
    scene.render.use_file_extension = True
    bpy.ops.render.render(write_still=True)

in_coll = lambda c: [o for o in ALL if o.users_collection[0] is COL[c]]
set_objs, front_objs, glass_objs = in_coll("set"), in_coll("front"), in_coll("glass")

if "back" in ONLY:
    show(set_objs + front_objs)
    render("back")
if "front" in ONLY:
    show(front_objs, holdout=set_objs)
    render("front")
if "glass" in ONLY:
    show(glass_objs, holdout=set_objs + front_objs)
    scene.cycles.film_transparent_glass = True
    render("glass")
    scene.cycles.film_transparent_glass = False
# ---------- growing mushrooms ----------
# Each species renders as a strip of frames from pinhead to open cap. The stem
# elongates; the cap swells from a closed button (a narrow cone for Mycena and
# Entoloma, a "drumstick" egg for the parasol) and opens, its gills deepening.
# In the veiled species (parasol, Gymnopilus) the partial veil covers the gills,
# stretches as the cap lifts, then tears, leaving a ring on the stem and scraps
# on the cap margin; the parasol's brown skin cracks into scales as it opens.
# The fly agaric (mycomatch) also has a universal veil: its white egg tears into
# the warts on the red cap.
# Units: the mature stem is 1 long, which the page scales to the mushroom's
# height. Run on its own (--only grow); it clears the set to render quickly.
SPECIES = {
    # R: mature cap radius; r0: stem radius; closed: button half-width,
    # half-height and how far round the cap wraps (deg)
    "bluesky":  dict(shape="conic", tall=1.05, R=0.32, r0=0.03, closed=(0.07, 0.15, 165), center=(0.01, 0.03, 0.22), edge=(0.04, 0.12, 0.6), gill=(0.35, 0.4, 0.6), stem=(0.06, 0.12, 0.45), stripes=1.0, frames=24, ppu=300),
    "about":    dict(shape="dome", flat=0.62, R=0.4, r0=0.05, closed=(0.15, 0.14, 150), center=(0.3, 0.06, 0.01), edge=(0.7, 0.22, 0.03), gill=(0.55, 0.3, 0.07), stem=(0.6, 0.45, 0.28), bulb=True, veil=dict(color=(0.7, 0.42, 0.12), ring=0.6), frames=24, ppu=300),
    "colophon": dict(shape="conic", tall=1.2, R=0.29, r0=0.022, closed=(0.06, 0.13, 165), center=(0.3, 0.13, 0.01), edge=(0.8, 0.5, 0.08), gill=(0.75, 0.68, 0.5), stem=(0.7, 0.6, 0.42), stripes=0.8, sss=0.35, frames=24, ppu=300),
    "github":   dict(shape="dome", flat=0.42, R=0.38, r0=0.032, closed=(0.12, 0.17, 148), center=(0.22, 0.13, 0.07), edge=(0.85, 0.8, 0.7), gill=(0.85, 0.82, 0.74), stem=(0.75, 0.7, 0.6), umbo=True, scales=True, bulb=True, veil=dict(color=(0.85, 0.82, 0.74), ring=1.0), frames=24, ppu=300),
    "mycomatch": dict(shape="dome", flat=0.5, R=0.4, r0=0.045, closed=(0.15, 0.16, 150), center=(0.42, 0.012, 0.006), edge=(0.72, 0.05, 0.012), gill=(0.88, 0.86, 0.8), stem=(0.85, 0.83, 0.76), warts=True, bulb=True, veil=dict(color=(0.88, 0.86, 0.8), ring=0.9), frames=24, ppu=300),
    "mycena":   dict(shape="conic", tall=1.15, R=0.12, r0=0.022, closed=(0.04, 0.08, 165), center=(0.2, 0.11, 0.05), edge=(0.55, 0.38, 0.2), gill=(0.7, 0.62, 0.5), stem=(0.62, 0.52, 0.38), stripes=0.7, sss=0.3, frames=16, ppu=180),
    "mycena2":  dict(shape="conic", tall=1.05, R=0.13, r0=0.022, closed=(0.045, 0.085, 165), center=(0.25, 0.15, 0.07), edge=(0.6, 0.45, 0.28), gill=(0.7, 0.62, 0.5), stem=(0.6, 0.52, 0.4), stripes=0.6, sss=0.3, seed=2, frames=16, ppu=180),
    "brown":    dict(shape="dome", flat=0.6, R=0.22, r0=0.05, closed=(0.1, 0.1, 155), center=(0.14, 0.06, 0.02), edge=(0.38, 0.2, 0.08), gill=(0.55, 0.42, 0.28), stem=(0.65, 0.55, 0.4), bulb=True, frames=16, ppu=180),
    "brown2":   dict(shape="dome", flat=0.52, R=0.24, r0=0.05, closed=(0.11, 0.1, 155), center=(0.2, 0.09, 0.03), edge=(0.45, 0.26, 0.11), gill=(0.55, 0.42, 0.28), stem=(0.62, 0.52, 0.38), bulb=True, seed=2, frames=16, ppu=180),
}
TILT = math.radians(-9)  # as if from a little below, so gills and veil show
TEAR = 0.42  # cap openness at which the partial veil tears

def cap_material(sp, o=1.0):
    m = bpy.data.materials.new("cap")
    m.use_nodes = True
    N, L = m.node_tree.nodes, m.node_tree.links
    p = N["Principled BSDF"]
    p.inputs["Roughness"].default_value = 0.55
    p.inputs["Subsurface Weight"].default_value = sp.get("sss", 0.12)
    p.inputs["Subsurface Radius"].default_value = (0.4, 0.25, 0.15)
    tc = N.new("ShaderNodeTexCoord")
    # texture in cap radii, so every species gets the same pattern scale
    unit = N.new("ShaderNodeVectorMath")
    unit.operation = "SCALE"
    unit.inputs["Scale"].default_value = 1 / sp["R"]
    L.new(tc.outputs["Object"], unit.inputs[0])
    # distance from the cap's axis: 0 at the center, 1 at the rim
    xy = N.new("ShaderNodeVectorMath")
    xy.operation = "MULTIPLY"
    xy.inputs[1].default_value = (1, 1, 0)
    L.new(unit.outputs["Vector"], xy.inputs[0])
    rad = N.new("ShaderNodeVectorMath")
    rad.operation = "LENGTH"
    L.new(xy.outputs[0], rad.inputs[0])
    nz = N.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 6
    nz.inputs["Detail"].default_value = 6
    L.new(unit.outputs["Vector"], nz.inputs["Vector"])
    wob = N.new("ShaderNodeMath")
    wob.operation = "MULTIPLY_ADD"
    wob.inputs[1].default_value = 0.25
    L.new(nz.outputs["Fac"], wob.inputs[0])
    L.new(rad.outputs["Value"], wob.inputs[2])
    ramp = N.new("ShaderNodeValToRGB")
    e = ramp.color_ramp.elements
    e[0].position, e[0].color = 0.15, (*sp["center"], 1)
    e[1].position, e[1].color = 1.05, (*sp["edge"], 1)
    L.new(wob.outputs[0], ramp.inputs["Fac"])
    col, height = ramp.outputs["Color"], nz.outputs["Fac"]
    if sp.get("stripes"):
        # fine radial grooves, like a Mycena's striate cap
        ang = N.new("ShaderNodeTexGradient")
        ang.gradient_type = "RADIAL"
        L.new(unit.outputs["Vector"], ang.inputs["Vector"])
        k = N.new("ShaderNodeMath")
        k.operation = "MULTIPLY"
        k.inputs[1].default_value = 2 * math.pi * 46
        L.new(ang.outputs["Fac"], k.inputs[0])
        sn = N.new("ShaderNodeMath")
        sn.operation = "SINE"
        L.new(k.outputs[0], sn.inputs[0])
        g = N.new("ShaderNodeMapRange")
        g.inputs["From Min"].default_value, g.inputs["From Max"].default_value = -1, 1
        g.inputs["To Min"].default_value, g.inputs["To Max"].default_value = 1 - 0.3 * sp["stripes"], 1
        L.new(sn.outputs[0], g.inputs["Value"])
        dark = N.new("ShaderNodeMix")
        dark.data_type, dark.blend_type = "RGBA", "MULTIPLY"
        L.new(rad.outputs["Value"], dark.inputs["Factor"])
        L.new(col, sock(dark.inputs, "A", "RGBA"))
        gc = N.new("ShaderNodeCombineColor")
        for i in range(3):
            L.new(g.outputs["Result"], gc.inputs[i])
        L.new(gc.outputs[0], sock(dark.inputs, "B", "RGBA"))
        col, height = sock(dark.outputs, "Result", "RGBA"), sn.outputs[0]
    if sp.get("scales"):
        # torn brown scales, densest toward the center, like a parasol
        vo = N.new("ShaderNodeTexVoronoi")
        vo.inputs["Scale"].default_value = 7
        vo.inputs["Randomness"].default_value = 1
        L.new(unit.outputs["Vector"], vo.inputs["Vector"])
        th = N.new("ShaderNodeMath")
        th.operation = "MULTIPLY_ADD"
        th.inputs[1].default_value = -0.3
        L.new(rad.outputs["Value"], th.inputs[0])
        # the brown skin is whole on the button and cracks into scales as
        # the cap expands
        th.inputs[2].default_value = 1.3 - 0.8 * o
        lt = N.new("ShaderNodeMath")
        lt.operation = "LESS_THAN"
        L.new(vo.outputs["Distance"], lt.inputs[0])
        L.new(th.outputs[0], lt.inputs[1])
        sc = N.new("ShaderNodeMix")
        sc.data_type = "RGBA"
        L.new(lt.outputs[0], sc.inputs["Factor"])
        L.new(col, sock(sc.inputs, "A", "RGBA"))
        sock(sc.inputs, "B", "RGBA").default_value = (0.16, 0.09, 0.045, 1)
        col, height = sock(sc.outputs, "Result", "RGBA"), lt.outputs[0]
    if sp.get("warts"):
        # a fly agaric's universal veil: white over the whole egg, torn into
        # warts as the red cap swells through it
        vo = N.new("ShaderNodeTexVoronoi")
        vo.inputs["Scale"].default_value = 11
        L.new(unit.outputs["Vector"], vo.inputs["Vector"])
        lt = N.new("ShaderNodeMath")
        lt.operation = "LESS_THAN"
        L.new(vo.outputs["Distance"], lt.inputs[0])
        lt.inputs[1].default_value = max(0.24, 0.9 - 1.5 * o)
        sc = N.new("ShaderNodeMix")
        sc.data_type = "RGBA"
        L.new(lt.outputs[0], sc.inputs["Factor"])
        L.new(col, sock(sc.inputs, "A", "RGBA"))
        sock(sc.inputs, "B", "RGBA").default_value = (0.85, 0.82, 0.72, 1)
        col, height = sock(sc.outputs, "Result", "RGBA"), lt.outputs[0]
    L.new(col, p.inputs["Base Color"])
    b = N.new("ShaderNodeBump")
    b.inputs["Strength"].default_value = 0.35
    b.inputs["Distance"].default_value = 0.02
    L.new(height, b.inputs["Height"])
    L.new(b.outputs["Normal"], p.inputs["Normal"])
    return m

def stem_material(sp):
    m = textured("stem", [(0.0, tuple(c * 0.7 for c in sp["stem"])), (1.0, tuple(min(1, c * 1.15) for c in sp["stem"]))],
                 14, stretch=(1, 1, 0.08), rough=0.6, bump=0.25)
    m.node_tree.nodes["Principled BSDF"].inputs["Subsurface Weight"].default_value = 0.2
    return m

def cap_profile(sp):
    """(r, z) from the apex out over the top, round the rim, and back under."""
    pts = []
    if sp["shape"] == "conic":
        h = sp["tall"]
        for k in range(0, 41):
            t = k / 40
            pts.append((max(t, 1e-3), h * (1 - t ** 2.4)))
        pts += [(1.0, -0.04), (0.96, -0.05)]
        under = lambda t: h * 0.55 * (1 - t ** 1.5)
    else:
        h = sp["flat"]
        for k in range(0, 41):
            t = k / 40
            z = h * math.sqrt(max(0.0, 1 - t ** 2.2))
            if sp.get("umbo"):
                z += h * 0.16 * math.exp(-(t / 0.13) ** 2)
            pts.append((max(t, 1e-3), z))
        pts += [(1.0, -0.02), (0.97, -0.05)]
        under = lambda t: h * 0.18 * (1 - t)
    for k in range(1, 13):
        t = 0.96 - k / 12 * 0.84
        pts.append((t, under(t)))
    return pts, under

def ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)

def stage(t):
    """Stem length, cap openness and button size at growth t in [0, 1]."""
    return 0.1 + 0.9 * ease(t / 0.85), ease((t - 0.3) / 0.7), 0.4 + 0.6 * ease(t / 0.3)

def frame_times(sp, n):
    """Growth times for n frames, spaced by how much the mushroom changes
    rather than evenly, so the cap opening and the veil tear get more frames
    than the slow stem stretch."""
    M = 400
    acc, prev = [0.0], stage(0)
    for i in range(1, M + 1):
        t = i / M
        cur = stage(t)
        d = math.hypot(cur[0] - prev[0], 1.3 * (cur[1] - prev[1]), 0.5 * (cur[2] - prev[2]))
        if sp.get("veil") and TEAR - 0.12 < cur[1] < TEAR + 0.2:
            d *= 2.5
        acc.append(acc[-1] + d + 0.15 / M)
        prev = cur
    ts, j = [], 0
    for k in range(n):
        target = acc[-1] * k / (n - 1)
        while j < M and acc[j + 1] < target:
            j += 1
        span = acc[j + 1] - acc[j] if j < M else 1
        ts.append(min(1.0, (j + (target - acc[j]) / span) / M) if j < M else 1.0)
    return ts

def open_profile(sp):
    pts, _ = cap_profile(sp)
    return [(r * sp["R"], z * sp["R"]) for r, z in pts]

def closed_profile(sp):
    """Same point layout as cap_profile: 41 over the top, 2 round the rim,
    12 back under to the stem."""
    a, b, wrap = sp["closed"]
    wrap, zc, r0 = math.radians(wrap), -0.3 * b, sp["r0"]
    top = [(max(a * math.sin(wrap * k / 40), 1e-4), zc + b * math.cos(wrap * k / 40)) for k in range(41)]
    rm, zm = top[-1]
    pts = top + [(rm * 0.97, zm - 0.004), (rm * 0.9, zm)]
    for k in range(1, 13):
        u = k / 12
        pts.append((rm * 0.9 + (r0 * 1.2 - rm * 0.9) * u, zm + (zc * 0.2 - zm) * u))
    return pts

def revolve(name, prof, segs, material, wobble=0.0, seed=1, freq=(10, 10, 10)):
    """lathe() plus a little noise in the radius, at freq cycles per unit."""
    o = lathe(name, prof, segs, material, "mush")
    if wobble:
        for v in o.data.vertices:
            p = Vector((v.co.x * freq[0], v.co.y * freq[1], v.co.z * freq[2]))
            w = 1 + wobble * noise.noise(p + Vector((seed * 5.0, 0, 0)))
            v.co.x *= w
            v.co.y *= w
    return o

def build_mushroom(name, sp, t):
    """Builds the mushroom at growth t; returns (objects, stem top z, cap
    radius, cap height) in mushroom units, before the tilt."""
    hs, o, pin = stage(t)
    closed = [(r * pin, z * pin) for r, z in closed_profile(sp)]
    prof = [(c[0] + (q[0] - c[0]) * o, c[1] + (q[1] - c[1]) * o) for c, q in zip(closed, open_profile(sp))]
    rnow = max(r for r, _ in prof)
    seed = sp.get("seed", 1)
    objs = []

    f = 2.5 / sp["R"]
    cap = revolve(name + "-cap", prof, 96, cap_material(sp, o), 0.03, seed, (f, f, f))
    cap.location.z = hs
    objs.append(cap)

    # gills under the cap, deepening as it opens
    bm = bmesh.new()
    under = prof[43:]
    n = 70
    for i in range(n):
        a = 2 * math.pi * i / n
        ca, sa = math.cos(a), math.sin(a)
        row = []
        for k, (r, z) in enumerate(under):
            u = k / (len(under) - 1)
            depth = 0.09 * rnow * math.sin(math.pi * u) * (0.2 + 0.8 * o)
            row.append((bm.verts.new((r * ca, r * sa, z)), bm.verts.new((r * 0.98 * ca, r * 0.98 * sa, z - depth))))
        for (a1, b1), (a2, b2) in zip(row, row[1:]):
            bm.faces.new((a1, a2, b2, b1))
    me = bpy.data.meshes.new(name + "-gills")
    bm.to_mesh(me)
    bm.free()
    gills = obj(name + "-gills", me, mat("gill", sp["gill"], 0.7, **{"Subsurface Weight": 0.2}), "mush")
    gills.location.z = hs
    objs.append(gills)

    # the stem, thicker for its length when young
    rs = sp["r0"] * (0.8 + 0.2 * t)
    sprof = []
    for k in range(31):
        z = hs * k / 30
        rr = rs * (1.0 - 0.18 * z / hs)
        if sp.get("bulb"):
            rr *= 1 + 0.75 * math.exp(-((z - 0.04) / 0.07) ** 2)
        sprof.append((rr, z))
    f = 0.8 / sp["r0"]
    objs.append(revolve(name + "-stem", sprof, 48, stem_material(sp), 0.05, seed, (f, f, 3)))

    veil = sp.get("veil")
    if veil:
        vm = textured("veil", [(0.0, tuple(c * 0.8 for c in veil["color"])), (1.0, veil["color"])], 30, rough=0.75, bump=0.3)
        vm.node_tree.nodes["Principled BSDF"].inputs["Subsurface Weight"].default_value = 0.3
        z_att = -1.35 * sp["closed"][1]  # where the veil joins the stem, below the cap
        rm, zm = prof[42]
        if o < TEAR:
            # a skin from the cap margin to the stem, stretching as the cap lifts
            vp = []
            for k in range(7):
                u = k / 6
                vp.append((rm * 0.98 + (rs * 1.05 - rm * 0.98) * u + 0.012 * math.sin(math.pi * u),
                           zm + (z_att - zm) * u))
            v = revolve(name + "-veil", vp, 64, vm, 0.04, seed, (40, 40, 40))
            v.location.z = hs
            objs.append(v)
        else:
            # torn: a hanging ring on the stem...
            w = veil["ring"]
            rp = [(rs * 1.02, z_att + 0.012), (rs * (1.4 + 0.8 * w), z_att), (rs * (1.6 + 0.8 * w), z_att - 0.02 * (1 + w)),
                  (rs * (1.3 + 0.6 * w), z_att - 0.035 * (1 + w)), (rs * 1.02, z_att - 0.01)]
            ring = revolve(name + "-ring", rp, 64, vm, 0.08, seed, (60, 60, 60))
            ring.location.z = hs
            objs.append(ring)
            # ...and ragged scraps on the cap margin, falling away as it opens
            left = 1 - (o - TEAR) / (1 - TEAR)
            if left > 0.05:
                bm = bmesh.new()
                segs, top, bot = 96, [], []
                for i in range(segs):
                    a = 2 * math.pi * i / segs
                    ln = max(0.0, noise.noise(Vector((math.cos(a) * 3, math.sin(a) * 3, seed))) + 0.1) * 0.05 * left
                    top.append(bm.verts.new((rm * math.cos(a), rm * math.sin(a), zm)))
                    bot.append(bm.verts.new((rm * 0.97 * math.cos(a), rm * 0.97 * math.sin(a), zm - ln)))
                for i in range(segs):
                    j = (i + 1) % segs
                    bm.faces.new((top[i], top[j], bot[j], bot[i]))
                me = bpy.data.meshes.new(name + "-scraps")
                bm.to_mesh(me)
                bm.free()
                sc = obj(name + "-scraps", me, vm, "mush")
                sc.location.z = hs
                objs.append(sc)

    pivot = bpy.data.objects.new(name + "-pivot", None)
    COL["mush"].objects.link(pivot)
    pivot.rotation_euler = (TILT, 0, 0)
    for x in objs:
        x.parent = pivot
    objs.append(pivot)
    return objs, hs, rnow, prof[0][1]

# ---------- turkey tail brackets ----------
# Trametes versicolor: thin, leathery fans in overlapping tiers, zoned in
# browns, tans and blue-grays with a pale growing margin. Zones are laid down
# by distance from the wood, so new ones appear at the edge as a shelf grows.
# Units: the top shelf is 1 across at maturity, attached at the origin, seen a
# little from above like the log.
BRACKETS = {"turkey2": 2, "turkey3": 3}
BRACKET_TILT = math.radians(38)
ZONES = [(0.62, 0.5, 0.36), (0.3, 0.2, 0.12), (0.5, 0.38, 0.26), (0.06, 0.045, 0.035), (0.34, 0.39, 0.45),
         (0.22, 0.15, 0.1), (0.55, 0.48, 0.38), (0.08, 0.09, 0.11), (0.42, 0.3, 0.2)]

def bracket_material(rmax, rnow):
    m = bpy.data.materials.new("bracket")
    m.use_nodes = True
    N, L = m.node_tree.nodes, m.node_tree.links
    p = N["Principled BSDF"]
    p.inputs["Roughness"].default_value = 0.75
    p.inputs["Sheen Weight"].default_value = 0.3  # velvety zones
    tc = N.new("ShaderNodeTexCoord")
    xy = N.new("ShaderNodeVectorMath")
    xy.operation = "MULTIPLY"
    xy.inputs[1].default_value = (1, 1, 0)
    L.new(tc.outputs["Object"], xy.inputs[0])
    d = N.new("ShaderNodeVectorMath")
    d.operation = "LENGTH"
    L.new(xy.outputs[0], d.inputs[0])
    nz = N.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 9 / rmax
    nz.inputs["Detail"].default_value = 4
    L.new(tc.outputs["Object"], nz.inputs["Vector"])
    wob = N.new("ShaderNodeMath")
    wob.operation = "MULTIPLY_ADD"
    wob.inputs[1].default_value = 0.06 * rmax
    L.new(nz.outputs["Fac"], wob.inputs[0])
    L.new(d.outputs["Value"], wob.inputs[2])
    # concentric zones, outward from the wood
    zr = N.new("ShaderNodeMath")
    zr.operation = "DIVIDE"
    zr.inputs[1].default_value = rmax
    L.new(wob.outputs[0], zr.inputs[0])
    ramp = N.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "EASE"
    e = ramp.color_ramp.elements
    e[0].position, e[0].color = 0.0, (*ZONES[0], 1)
    e[1].position, e[1].color = 1.0, (*ZONES[-1], 1)
    for k, c in enumerate(ZONES[1:-1], 1):
        e.new(k / (len(ZONES) - 1)).color = (*c, 1)
    L.new(zr.outputs[0], ramp.inputs["Fac"])
    # the pale growing margin
    mg = N.new("ShaderNodeMapRange")
    mg.inputs["From Min"].default_value = rnow - 0.085 * rmax
    mg.inputs["From Max"].default_value = rnow - 0.045 * rmax
    L.new(wob.outputs[0], mg.inputs["Value"])
    col = N.new("ShaderNodeMix")
    col.data_type = "RGBA"
    L.new(mg.outputs["Result"], col.inputs["Factor"])
    L.new(ramp.outputs["Color"], sock(col.inputs, "A", "RGBA"))
    sock(col.inputs, "B", "RGBA").default_value = (0.86, 0.82, 0.7, 1)
    L.new(sock(col.outputs, "Result", "RGBA"), p.inputs["Base Color"])
    # fine ridges between zones
    rg = N.new("ShaderNodeMath")
    rg.operation = "SINE"
    k = N.new("ShaderNodeMath")
    k.operation = "MULTIPLY"
    k.inputs[1].default_value = 2 * math.pi * 14 / rmax
    L.new(wob.outputs[0], k.inputs[0])
    L.new(k.outputs[0], rg.inputs[0])
    b = N.new("ShaderNodeBump")
    b.inputs["Strength"].default_value = 0.25
    b.inputs["Distance"].default_value = 0.01
    L.new(rg.outputs[0], b.inputs["Height"])
    L.new(b.outputs["Normal"], p.inputs["Normal"])
    return m

def shelf(name, rmax, rnow, seed):
    """A fan reaching toward the camera (-y) from the origin, wavy at the
    margin and drooping a little, as a thin solid."""
    r = random.Random(seed)
    ph = [r.uniform(0, 6.3) for _ in range(4)]
    nr, na, spread = 12, 48, math.radians(100)
    bm = bmesh.new()
    grid = []
    for i in range(nr + 1):
        rho = 0.03 + 0.97 * i / nr
        row = []
        for j in range(na + 1):
            th = -spread + 2 * spread * j / na
            rm = rnow * (1 + 0.07 * math.sin(5 * th + ph[0]) + 0.035 * math.sin(11 * th + ph[1])) * (0.7 + 0.3 * math.cos(th * 0.9))
            z = rnow * (0.05 * (1 - rho) - 0.12 * rho ** 2 + 0.035 * rho ** 2 * math.sin(7 * th + ph[2]))
            row.append(bm.verts.new((rho * rm * math.sin(th), -rho * rm * math.cos(th), z)))
        grid.append(row)
    for a, b in zip(grid, grid[1:]):
        for j in range(na):
            bm.faces.new((a[j], a[j + 1], b[j + 1], b[j]))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = obj(name, me, bracket_material(rmax, rnow), "mush")
    sol = o.modifiers.new("solid", "SOLIDIFY")
    sol.thickness, sol.offset = 0.008 + 0.014 * rnow, -1
    return o

def build_bracket(name, tiers, t):
    """Shelves in tiers stepping down and sideways, each starting a little after
    the one above. Returns the objects and the top shelf's radius."""
    objs, top = [], 0
    for j in range(tiers):
        rmax = 0.5 * (1 - 0.18 * j)
        g = ease((t - 0.14 * j) / (1 - 0.14 * j))
        if g <= 0 and j:
            continue
        rnow = rmax * (0.1 + 0.9 * g)
        top = top or rnow
        o = shelf(f"{name}-{j}", rmax, rnow, seed=sum(map(ord, name)) + j)
        o.location = (j * 0.3, 0.02 * j, -j * 0.24)
        o.rotation_euler = (BRACKET_TILT, 0, math.radians(8 * (j % 2 * 2 - 1)))
        objs.append(o)
    return objs, [top]

def remove(objs):
    for x in objs:
        data = x.data
        mats = list(data.materials) if data is not None and hasattr(data, "materials") else []
        bpy.data.objects.remove(x)
        if data is not None and data.users == 0:
            (bpy.data.meshes if isinstance(data, bpy.types.Mesh) else bpy.data.curves).remove(data)
        for m in mats:
            if m and m.users == 0:
                bpy.data.materials.remove(m)

def world_bounds(objs):
    dg = bpy.context.evaluated_depsgraph_get()
    xs, zs = [], []
    for o in objs:
        if o.type != "MESH":
            continue
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        for v in me.vertices:
            w = ev.matrix_world @ v.co
            xs.append(w.x)
            zs.append(w.z)
        ev.to_mesh_clear()
    return min(xs), max(xs), min(zs), max(zs)

# ---------- the log rotting ----------
# Turkey tail is a white rot: bark sloughs off in lengthwise strips, the wood
# under it bleaches pale and soft, and black zone lines form where rival
# colonies meet. Each stage is the log alone, cropped to its box, for the page
# to fade in over back.webp as the mycelium eats the wood.
ROT_STAGES = (0.35, 0.7, 1.0)

def rotted(base, amt, end=False):
    m = base.copy()
    N, L = m.node_tree.nodes, m.node_tree.links
    p = N["Principled BSDF"]
    old_col = p.inputs["Base Color"].links[0].from_socket
    old_nrm = p.inputs["Normal"].links[0].from_socket
    tc = N.new("ShaderNodeTexCoord")
    # bark gone in patches stretched along the log (its local x)
    mp = N.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (0.35, 1, 1)
    L.new(tc.outputs["Object"], mp.inputs["Vector"])
    nz = N.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 9
    nz.inputs["Detail"].default_value = 6
    nz.inputs["Roughness"].default_value = 0.65
    L.new(mp.outputs["Vector"], nz.inputs["Vector"])
    gone = N.new("ShaderNodeMapRange")
    lo = 0.25 + 0.25 * amt
    gone.inputs["From Min"].default_value, gone.inputs["From Max"].default_value = lo, lo - 0.03
    L.new(nz.outputs["Fac"], gone.inputs["Value"])
    # bleached, stringy wood
    fib = N.new("ShaderNodeTexNoise")
    fib.inputs["Scale"].default_value = 30
    fib.inputs["Detail"].default_value = 8
    mf = N.new("ShaderNodeMapping")
    mf.inputs["Scale"].default_value = (0.08, 1, 1)
    L.new(tc.outputs["Object"], mf.inputs["Vector"])
    L.new(mf.outputs["Vector"], fib.inputs["Vector"])
    wr = N.new("ShaderNodeValToRGB")
    e = wr.color_ramp.elements
    e[0].position, e[0].color = 0.3, (0.2, 0.15, 0.09, 1)
    e[1].position, e[1].color = 0.7, (0.5, 0.42, 0.3, 1)
    L.new(fib.outputs["Fac"], wr.inputs["Fac"])
    # zone lines: meandering contours of a coarse noise
    zn = N.new("ShaderNodeTexNoise")
    zn.inputs["Scale"].default_value = 3.5
    zn.inputs["Detail"].default_value = 3
    L.new(tc.outputs["Object"], zn.inputs["Vector"])
    za = N.new("ShaderNodeMath")
    za.operation = "ABSOLUTE"
    zs = N.new("ShaderNodeMath")
    zs.operation = "SUBTRACT"
    zs.inputs[1].default_value = 0.5
    L.new(zn.outputs["Fac"], zs.inputs[0])
    L.new(zs.outputs[0], za.inputs[0])
    zl = N.new("ShaderNodeMapRange")
    zl.inputs["From Min"].default_value, zl.inputs["From Max"].default_value = 0.0, 0.008
    zl.inputs["To Min"].default_value, zl.inputs["To Max"].default_value = 0.9 * amt, 0.0
    L.new(za.outputs[0], zl.inputs["Value"])
    lines = N.new("ShaderNodeMix")
    lines.data_type = "RGBA"
    L.new(zl.outputs["Result"], lines.inputs["Factor"])
    L.new(wr.outputs["Color"], sock(lines.inputs, "A", "RGBA"))
    sock(lines.inputs, "B", "RGBA").default_value = (0.015, 0.01, 0.006, 1)
    # what bark is left goes dark and damp
    damp = N.new("ShaderNodeMix")
    damp.data_type, damp.blend_type = "RGBA", "MULTIPLY"
    damp.inputs["Factor"].default_value = 1
    L.new(old_col, sock(damp.inputs, "A", "RGBA"))
    v = 1 - (0.15 if end else 0.35) * amt
    sock(damp.inputs, "B", "RGBA").default_value = (v, v * 0.97, v * 0.9, 1)
    col = N.new("ShaderNodeMix")
    col.data_type = "RGBA"
    if end:
        # the cut end bleaches from the rim in, rings still showing
        rr = N.new("ShaderNodeVectorMath")
        rr.operation = "LENGTH"
        yz = N.new("ShaderNodeVectorMath")
        yz.operation = "MULTIPLY"
        yz.inputs[1].default_value = (0, 1, 1)
        L.new(tc.outputs["Object"], yz.inputs[0])
        L.new(yz.outputs[0], rr.inputs[0])
        rim = N.new("ShaderNodeMapRange")
        rim.inputs["From Min"].default_value = LOG_R * (1 - 0.8 * amt)
        rim.inputs["From Max"].default_value = LOG_R
        rim.inputs["To Max"].default_value = 0.65
        L.new(rr.outputs["Value"], rim.inputs["Value"])
        L.new(rim.outputs["Result"], col.inputs["Factor"])
    else:
        L.new(gone.outputs["Result"], col.inputs["Factor"])
    L.new(sock(damp.outputs, "Result", "RGBA"), sock(col.inputs, "A", "RGBA"))
    L.new(sock(lines.outputs, "Result", "RGBA"), sock(col.inputs, "B", "RGBA"))
    L.new(sock(col.outputs, "Result", "RGBA"), p.inputs["Base Color"])
    p.inputs["Roughness"].default_value = 0.95
    # bare wood sits below the bark
    h = N.new("ShaderNodeMath")
    h.operation = "MULTIPLY_ADD"
    h.inputs[1].default_value = -1
    L.new(gone.outputs["Result"], h.inputs[0])
    L.new(fib.outputs["Fac"], h.inputs[2])
    b = N.new("ShaderNodeBump")
    b.inputs["Strength"].default_value = 0.5
    b.inputs["Distance"].default_value = 0.002 if end else 0.006
    L.new(h.outputs[0], b.inputs["Height"])
    L.new(old_nrm, b.inputs["Normal"])
    L.new(b.outputs["Normal"], p.inputs["Normal"])
    return m

if "rot" in ONLY:
    logs = [o for o in ALL if o.name.startswith("log")]
    a, b, c, d = world_bounds(logs)
    resx, resy = scene.render.resolution_x, scene.render.resolution_y
    px = (FRAME["x1"] - FRAME["x0"]) / resx
    # whole pixels, with a margin for the bump
    i0, i1 = math.floor((a - FRAME["x0"]) / px) - 4, math.ceil((b - FRAME["x0"]) / px) + 4
    j0, j1 = math.floor((c - FRAME["z0"]) / px) - 4, math.ceil((d - FRAME["z0"]) / px) + 4
    scene.render.use_border, scene.render.use_crop_to_border = True, True
    scene.render.border_min_x, scene.render.border_max_x = i0 / resx, i1 / resx
    scene.render.border_min_y, scene.render.border_max_y = j0 / resy, j1 / resy
    show(logs, holdout=[o for o in set_objs + front_objs if o not in logs])
    base = {o: o.data.materials[0] for o in logs}
    for k, amt in enumerate(ROT_STAGES, 1):
        for o in logs:
            o.data.materials[0] = rotted(base[o], amt, end=o.name.startswith("log-end"))
        render(f"rot{k}")
    scene.render.use_border = False
    with open(os.path.join(OUT, "rot.json"), "w") as f:
        json.dump({"n": len(ROT_STAGES), "box": [FRAME["x0"] + i0 * px, FRAME["z0"] + j0 * px,
                                                  FRAME["x0"] + i1 * px, FRAME["z0"] + j1 * px]}, f)

# ---------- the room ----------
# The jar on a painted windowsill, the window and wall behind it out of focus,
# for the page backdrop. The jar is set in a flat orthographic view, which
# can't see the sill's top, so the room gets its own perspective camera from a
# little above, matched to the jar's scale on its plane (y = 0). The jar is
# hidden from it but still shadows the sill. Day and night versions.
ROOM = dict(x0=-6.0, x1=6.0, z0=-3.5, z1=6.5)  # what the image covers on y = 0
ROOM_PPU = 110

def box(name, x0, x1, y0, y1, z0, z1, material):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1)
    for v in bm.verts:
        v.co = Vector(((x0 + x1) / 2 + v.co.x * (x1 - x0), (y0 + y1) / 2 + v.co.y * (y1 - y0), (z0 + z1) / 2 + v.co.z * (z1 - z0)))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return obj(name, me, material, "room", smooth=False)

def outside(night):
    """Sky and blurry foliage seen through the window, as light."""
    m = bpy.data.materials.new("outside")
    m.use_nodes = True
    N, L = m.node_tree.nodes, m.node_tree.links
    N.remove(N["Principled BSDF"])
    em = N.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = 1.0 if night else 2.6
    tc = N.new("ShaderNodeTexCoord")
    nz = N.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 0.35
    nz.inputs["Detail"].default_value = 5
    L.new(tc.outputs["Object"], nz.inputs["Vector"])
    leaf = N.new("ShaderNodeValToRGB")
    e = leaf.color_ramp.elements
    sky, green = ((0.012, 0.018, 0.045), (0.002, 0.004, 0.003)) if night else ((0.62, 0.74, 0.86), (0.09, 0.2, 0.06))
    e[0].position, e[0].color = 0.48, (*sky, 1)
    e[1].position, e[1].color = 0.56, (*green, 1)
    L.new(nz.outputs["Fac"], leaf.inputs["Fac"])
    L.new(leaf.outputs["Color"], em.inputs["Color"])
    L.new(em.outputs[0], N["Material Output"].inputs["Surface"])
    return m

if "room" in ONLY:
    coll("room")
    paint = textured("sill", [(0.0, (0.5, 0.47, 0.4)), (1.0, (0.66, 0.62, 0.54))], 4, rough=0.45, bump=0.08)
    plaster = textured("plaster", [(0.0, (0.12, 0.135, 0.115)), (1.0, (0.19, 0.205, 0.175))], 6, rough=0.9, bump=0.3)
    frame_m = mat("frame", (0.72, 0.7, 0.64), 0.4)
    # wall plane; the window opening's center, half-width, bottom and top
    WY, WX, OX, OZ0, OZ1 = 3.0, -4.3, 1.4, 0.35, 3.9
    box("sill", -12, 12, -2.2, WY + 0.4, -0.35, -0.1, paint)
    box("apron", -12, 12, -1.9, -1.85, -8, -0.35, plaster)
    for args in ((-16, WX - OX, WY, WY + 0.1, -0.35, 14), (WX + OX, 16, WY, WY + 0.1, -0.35, 14),
                 (WX - OX, WX + OX, WY, WY + 0.1, OZ1, 14)):
        box("wall", *args, plaster)
    # the reveal round the opening, then the sash: frame, a mullion and a transom
    box("reveal", WX - OX - 0.02, WX - OX, WY, WY + 0.4, -0.1, OZ1, plaster)
    box("reveal", WX + OX, WX + OX + 0.02, WY, WY + 0.4, -0.1, OZ1, plaster)
    box("reveal", WX - OX, WX + OX, WY, WY + 0.4, OZ1, OZ1 + 0.02, plaster)
    FY, B = WY + 0.32, 0.12
    for args in ((WX - OX, WX - OX + B, FY, FY + 0.08, OZ0, OZ1), (WX + OX - B, WX + OX, FY, FY + 0.08, OZ0, OZ1),
                 (WX - OX, WX + OX, FY, FY + 0.08, OZ0, OZ0 + B), (WX - OX, WX + OX, FY, FY + 0.08, OZ1 - B, OZ1),
                 (WX - 0.045, WX + 0.045, FY, FY + 0.08, OZ0, OZ1), (WX - OX, WX + OX, FY, FY + 0.08, 2.5, 2.58)):
        box("sash", *args, frame_m)
    box("frame-sill", WX - OX, WX + OX, WY, FY + 0.08, -0.1, OZ0, frame_m)
    sky = box("outside", -40, 40, 16, 16.1, -10, 40, None)
    mm = bpy.data.materials.new("moonlight")
    mm.use_nodes = True
    mm.node_tree.nodes.remove(mm.node_tree.nodes["Principled BSDF"])
    glow = mm.node_tree.nodes.new("ShaderNodeEmission")
    glow.inputs["Color"].default_value, glow.inputs["Strength"].default_value = (0.9, 0.93, 1.0, 1), 8
    mm.node_tree.links.new(glow.outputs[0], mm.node_tree.nodes["Material Output"].inputs["Surface"])
    moon = blob("moon", mm, (-8.6, 15.5, 4.6), (0.32, 0.32, 0.32), rough=0, collection="room")
    # the jar only casts shadows; its glass doesn't
    for o in ALL:
        o.hide_render, o.is_holdout = False, False
        o.visible_camera = False
        if o in glass_objs:
            o.visible_shadow = False
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(-35), math.radians(35), 0)  # from outside, high, from the left
    sun.data.angle = math.radians(6)
    lamp = light("lamp", "POINT", (5.0, -4.0, 3.5), 0, (1.0, 0.62, 0.32))
    # soft light from the room, so the jar's shadow on the sill isn't black
    room_fill = light("room-fill", "AREA", (0.0, -9.0, 2.0), 0, (1.0, 0.95, 0.88), 6)
    # daylight (moonlight) from the window, raking across the wall
    spill = light("spill", "AREA", (-3.2, 2.2, 2.2), 0, (1.0, 1.0, 1.0), 1.6, rot=(math.radians(90), 0, math.radians(-118)))
    lamp.data.shadow_soft_size = 0.6
    room_cam = bpy.data.cameras.new("room-cam")
    D, zc = 14.0, (ROOM["z0"] + ROOM["z1"]) / 2
    room_cam.sensor_fit, room_cam.sensor_height = "VERTICAL", 36
    room_cam.lens = 36 * D / (ROOM["z1"] - ROOM["z0"])
    room_cam.dof.use_dof, room_cam.dof.focus_distance, room_cam.dof.aperture_fstop = True, D, 0.03
    rc = bpy.data.objects.new("room-cam", room_cam)
    rc.location, rc.rotation_euler = (0, -D, zc), (math.pi / 2, 0, 0)
    scene.collection.objects.link(rc)
    scene.camera = rc
    scene.render.resolution_x = round((ROOM["x1"] - ROOM["x0"]) * ROOM_PPU)
    scene.render.resolution_y = round((ROOM["z1"] - ROOM["z0"]) * ROOM_PPU)
    scene.render.film_transparent = False
    st = scene.render.image_settings
    for night in (False, True):
        sky.data.materials.clear()
        sky.data.materials.append(outside(night))
        moon.hide_render = not night
        sun.data.energy, sun.data.color = (0.35, (0.6, 0.7, 1.0)) if night else (4.0, (1.0, 0.9, 0.75))
        lamp.data.energy = 700 if night else 0
        room_fill.data.energy = 20 if night else 300
        spill.data.energy, spill.data.color = (90, (0.45, 0.58, 1.0)) if night else (260, (1.0, 0.96, 0.88))
        bg.inputs["Strength"].default_value = 0.25 if night else 1.1
        st.file_format, st.color_mode, st.quality = "WEBP", "RGB", 78
        scene.render.filepath = os.path.join(OUT, "room-night" if night else "room-day")
        bpy.ops.render.render(write_still=True)
    with open(os.path.join(OUT, "room.json"), "w") as f:
        json.dump({"box": [ROOM["x0"], ROOM["z0"], ROOM["x1"], ROOM["z1"]]}, f)

if "grow" in ONLY:
    import numpy as np, tempfile
    assert "id" not in ONLY, "render grow on its own"
    # the set isn't needed and slows every render down
    for o in list(scene.objects):
        if o.type in ("MESH", "CURVE"):
            bpy.data.objects.remove(o)
    COL["mush"] = coll("mush")
    bounce = light("bounce", "AREA", (0.0, -2.0, -1.4), 60, (1.0, 0.85, 0.65), 3)
    for look in ("AgX - Punchy", "Punchy"):
        try:
            scene.view_settings.look = look
            break
        except TypeError:
            pass
    tmp = tempfile.mkdtemp()
    sheet_path = os.path.join(OUT, "mush.json")
    sheet = json.load(open(sheet_path)) if STRIPS and os.path.exists(sheet_path) else {}

    def strip(name, ts, ppu, build, symmetric=True):
        """Renders build(t) -> (objs, meta) at each growth time into one strip
        of frames, origin at (ax, ay) px in every frame."""
        # one frame for the whole strip, big enough for every stage
        x0 = z0 = 1e9
        x1 = z1 = -1e9
        for t in ts:
            objs, _ = build(t)
            bpy.context.view_layer.update()
            a, b, c, d = world_bounds(objs)
            x0, x1, z0, z1 = min(x0, a), max(x1, b), min(z0, c), max(z1, d)
            remove(objs)
        if symmetric:
            x1 = max(-x0, x1)
            x0 = -x1
        x0, x1, z0, z1 = x0 - 0.02, x1 + 0.02, z0 - 0.02, z1 + 0.02
        fw, fh = math.ceil((x1 - x0) * ppu), math.ceil((z1 - z0) * ppu)
        x1, z0 = x0 + fw / ppu, z1 - fh / ppu
        scene.render.resolution_x, scene.render.resolution_y = fw, fh
        cam_data.sensor_fit = "HORIZONTAL" if fw >= fh else "VERTICAL"
        cam_data.ortho_scale = max(fw, fh) / ppu
        cam.location = ((x0 + x1) / 2, -10, (z0 + z1) / 2)
        st = scene.render.image_settings
        st.file_format, st.color_mode, st.color_depth = "PNG", "RGBA", "8"
        frames, paths = [], []
        for i, t in enumerate(ts):
            objs, meta = build(t)
            path = os.path.join(tmp, f"{name}-{i:02d}.png")
            scene.render.filepath = path
            bpy.ops.render.render(write_still=True)
            remove(objs)
            frames.append([round(v * ppu, 1) for v in meta])
            paths.append(path)
        # stitch the frames into one strip
        n = len(ts)
        atlas = np.zeros((fh, fw * n, 4), np.float32)
        for i, path in enumerate(paths):
            im = bpy.data.images.load(path)
            px = np.empty(fw * fh * 4, np.float32)
            im.pixels.foreach_get(px)
            atlas[:, i * fw:(i + 1) * fw, :] = px.reshape(fh, fw, 4)
            bpy.data.images.remove(im)
        img = bpy.data.images.new(name + "-strip", fw * n, fh, alpha=True)
        img.pixels.foreach_set(atlas.ravel())
        os.makedirs(os.path.join(OUT, "mush"), exist_ok=True)
        img.filepath_raw = os.path.join(OUT, "mush", name + ".webp")
        img.file_format = "WEBP"
        img.save()
        bpy.data.images.remove(img)
        sheet[name] = dict(n=n, fw=fw, fh=fh, ppu=ppu, ax=round(-x0 * ppu, 1), ay=round(z1 * ppu, 1),
                           t=[round(t, 4) for t in ts], f=frames)
        print("grew", name, fw, fh)

    want = lambda name: not STRIPS or name in STRIPS.split(",")
    for name, sp in SPECIES.items():
        if not want(name):
            continue
        def build(t, name=name, sp=sp):
            objs, hs, rnow, ch = build_mushroom(name, sp, t)
            # stem top (height above the base), cap radius and cap height
            return objs, [hs * math.cos(TILT), rnow, ch]
        strip(name, frame_times(sp, sp["frames"]), sp["ppu"], build)
    for name, tiers in BRACKETS.items():
        if want(name):
            strip(name, [k / 15 for k in range(16)], BRACKET_PPU, lambda t, name=name, tiers=tiers: build_bracket(name, tiers, t), symmetric=False)
    with open(sheet_path, "w") as f:
        json.dump(sheet, f)

if "id" in ONLY:
    flat = {k: bpy.data.materials.new("id-" + k) for k in ("soil", "wood", "")}
    for k, m in flat.items():
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.remove(nt.nodes["Principled BSDF"])
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = {"soil": (1, 0, 0, 1), "wood": (0, 1, 0, 1), "": (0, 0, 0, 1)}[k]
        nt.links.new(em.outputs[0], nt.nodes["Material Output"].inputs["Surface"])
    for o in ALL:
        o.data.materials.clear()
        o.data.materials.append(flat[o.get("sub", "")])
    show(set_objs + front_objs)
    scene.cycles.samples, scene.cycles.use_denoising = 1, False
    scene.cycles.filter_width = 0.01
    scene.render.dither_intensity = 0
    scene.view_settings.view_transform = "Standard"
    scene.render.film_transparent = False
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0
    render("id", "PNG")

if set(ONLY) & {"back", "front", "glass", "id"}:
  with open(os.path.join(OUT, "set.json"), "w") as f:
    json.dump({"frame": FRAME, "ppu": PPU * SCALE, "width": scene.render.resolution_x, "height": scene.render.resolution_y,
               "jar": {"h": JAR_H, "domeH": DOME_H, "ground": GROUND}}, f, indent=1)
print("done", scene.render.resolution_x, scene.render.resolution_y)
