"""布达拉宫 P1 体量灰模生成器（阶段 2 / 专项 P1）。

生成器不保存任何几何常量：山体坡面、台地级数、梯级段数、金顶数量与
小平台房群全部来自 scene.json 中元素的 generator.parameters，经
pipeline/massing_params 展开后建出，保证“契约 → 几何”可追溯。

坐标约定：X 向东、Y 向北（白宫前立面 Y=0）、Z 向上，单位米。

运行：
  blender -b -P generators/architecture/potala_massing.py
  SCENE_DOC=/path/to/scene.json blender -b -P generators/architecture/potala_massing.py
"""

import json
import math
import os
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.massing_params import expand_boxes, expand_prisms  # noqa: E402

DEFAULT_SCENE = ROOT / "scenes" / "potala-palace-lhasa" / "scene.json"
DEFAULT_OUT = ROOT / "scenes" / "potala-palace-lhasa" / "derived"

MATERIAL_COLORS = {
    "clay": (0.72, 0.71, 0.69),
    "clay_white": (0.86, 0.85, 0.82),
    "clay_dark": (0.58, 0.57, 0.55),
    "terrain": (0.30, 0.32, 0.28),
    # 窗洞、红棕色檐带与金顶：用于在体量灰模上区分窗阵列与藏式屋顶层次
    "window_dark": (0.26, 0.25, 0.24),
    "eave_red": (0.45, 0.21, 0.17),
    "roof_gold": (0.64, 0.49, 0.17),
}


def make_material(name, color, roughness=0.95):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    return material


def mesh_object(name, verts, faces, material):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.validate()
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj


def _shear_z(item, x, z):
    """按 slopeZPerX 沿 X 方向做线性升降，使山体/白墙可连续随坡倾斜。

    契约中的 z 值对应 xRef 处；相邻分段在共享 X 边界上自动对齐，
    从而避免每 30m 出现一段垂直错台（灰模上的“肋条”）。
    """
    slope = item.get("slopeZPerX")
    if slope is None:
        return z
    x_ref = item.get("xRef", 0.0)
    return z + slope * (x - x_ref)


def box_object(box, material):
    x0, x1 = box["x0"], box["x1"]
    y0, y1 = box["y0"], box["y1"]
    z0, z1 = box["z0"], box["z1"]
    z0a, z0b = _shear_z(box, x0, z0), _shear_z(box, x1, z0)
    z1a, z1b = _shear_z(box, x0, z1), _shear_z(box, x1, z1)
    verts = [
        (x0, y0, z0a), (x1, y0, z0b), (x1, y1, z0b), (x0, y1, z0a),
        (x0, y0, z1a), (x1, y0, z1b), (x1, y1, z1b), (x0, y1, z1a),
    ]
    faces = [
        (3, 2, 1, 0), (4, 5, 6, 7),
        (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
    ]
    return mesh_object(box["name"], verts, faces, material)


def prism_object(prism, material):
    x0, x1 = prism["x0"], prism["x1"]
    profile = [(float(y), float(z)) for y, z in prism["profile"]]
    n = len(profile)
    verts = [(x0, y, _shear_z(prism, x0, z)) for y, z in profile] + [
        (x1, y, _shear_z(prism, x1, z)) for y, z in profile
    ]
    faces = [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j, n + i))
    return mesh_object(prism["name"], verts, faces, material)


def load_scene():
    path = Path(os.environ.get("SCENE_DOC", str(DEFAULT_SCENE)))
    return json.loads(path.read_text(encoding="utf-8")), path


def build_massing(scene_doc):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    materials = {
        name: make_material(f"clay_{name}", color)
        for name, color in MATERIAL_COLORS.items()
    }

    totals = {"boxes": 0, "prisms": 0}
    for element in scene_doc["elements"]:
        generator = element.get("reconstruction", {}).get("generator")
        if not generator:
            continue
        parameters = generator.get("parameters") or {}
        material = materials[parameters.get("material", "clay")]

        boxes = expand_boxes(parameters)
        prisms = expand_prisms(parameters)
        for box in boxes:
            box_object(box, material)
        for prism in prisms:
            prism_object(prism, material)
        totals["boxes"] += len(boxes)
        totals["prisms"] += len(prisms)
        print(f"[BUILD] {element['id']}: boxes={len(boxes)} prisms={len(prisms)}")

    camera_id = os.environ.get("CAMERA_ID", scene_doc["cameras"][0]["id"])
    camera_def = next((item for item in scene_doc["cameras"] if item["id"] == camera_id), None)
    if camera_def is None:
        raise SystemExit(f"[FAIL] 场景缺少相机 {camera_id}")
    build_camera(camera_def)
    build_lighting(scene_doc["environment"]["lighting"])
    return totals


def build_camera(camera_def):
    camera_data = bpy.data.cameras.new(camera_def["id"])
    camera_data.sensor_width = 36
    camera_data.sensor_height = 24
    camera_data.clip_end = 10000
    # 契约给的是垂直视场角；换算为 24mm 画幅对应的焦距。
    camera_data.lens = 12.0 / math.tan(math.radians(camera_def["fovY"]) / 2.0)

    camera = bpy.data.objects.new(camera_def["id"], camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = Vector(camera_def["position"])
    target = Vector(camera_def["target"])
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = camera
    return camera


def build_lighting(lighting):
    sun_data = bpy.data.lights.new("sun", type="SUN")
    sun_data.energy = 1.7
    sun_data.angle = math.radians(35)
    sun = bpy.data.objects.new("sun", sun_data)
    bpy.context.collection.objects.link(sun)
    sun.rotation_euler = (
        math.radians(90 - lighting["sunElevation"]),
        0,
        math.radians(lighting["sunAzimuth"]),
    )

    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    background = world.node_tree.nodes["Background"]
    background.inputs["Color"].default_value = (0.58, 0.61, 0.65, 1.0)
    background.inputs["Strength"].default_value = 1.05
    bpy.context.scene.world = world


def render(out_dir):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 40
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 1200
    scene.render.resolution_y = 800
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(out_dir / os.environ.get("RENDER_NAME", "p1-massing-main.png"))
    bpy.ops.render.render(write_still=True)


def main():
    scene_doc, scene_path = load_scene()
    out_dir = Path(os.environ.get("OUT_DIR", str(DEFAULT_OUT)))
    out_dir.mkdir(parents=True, exist_ok=True)
    totals = build_massing(scene_doc)
    render(out_dir)
    print(f"[OK] scene={scene_path}")
    print(f"[OK] boxes={totals['boxes']} prisms={totals['prisms']}")
    print(f"[OK] {out_dir / 'p1-massing-main.png'}")


if __name__ == "__main__":
    main()
