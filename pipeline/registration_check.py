#!/usr/bin/env python3
"""配准门禁：把场景几何投影到照片上，按地标包围盒逐项比对。

背景：
    体量覆盖门禁只能拦住“整类没建”，拦不住“建了但比例/位置不对”。
    之前 compare.html 只是把照片和渲染图各自 width:100% 缩放后叠透明度，
    既没有配准，也没有任何数字判据，所以“叠加对不上”只能靠人眼发现。

本模块用 scene.json 里的相机参数（与 Blender 生成器同一套针孔模型）
把地标元素的几何投影成归一化画面坐标，与勘察实测的照片地标包围盒比对：
    - 中心偏移 dx / dy（画面宽高归一化）
    - 宽 / 高相对误差
    - 包围盒 IoU
任一指标超过该地标的 tolerance（缺省 0.05）或 IoU < 0.7 即失败。

同时输出 derived/registration-overlay.svg：照片底图 + 照片地标框（橙色虚线）
+ 场景投影框（青色实线），不依赖 Blender 渲染即可核对配准。

用法：
    python3 pipeline/registration_check.py \
        --survey examples/potala-survey.json \
        --scene scenes/potala-palace-lhasa/scene.json

退出码：0 通过，1 超差，2 输入/环境错误。
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.massing_params import expand_boxes, expand_prisms  # noqa: E402

DEFAULT_TOLERANCE = 0.05
MIN_IOU = 0.70


def _sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def _normalize(a):
    length = math.sqrt(_dot(a, a))
    return [value / length for value in a]


class Projector:
    """与 Blender 相机一致的针孔投影：fovY + 3:2 画幅 -> 归一化坐标。"""

    def __init__(self, camera, frame_width=1200, frame_height=800):
        self.position = camera["position"]
        self.forward = _normalize(_sub(camera["target"], self.position))
        self.right = _normalize(_cross(self.forward, [0, 0, 1]))
        self.up = _cross(self.right, self.forward)
        self.tan_half_y = math.tan(math.radians(camera["fovY"]) / 2.0)
        self.tan_half_x = self.tan_half_y * (frame_width / frame_height)

    def project(self, point):
        view = _sub(point, self.position)
        depth = _dot(view, self.forward)
        if depth <= 1e-6:
            return None
        x = _dot(view, self.right) / depth / self.tan_half_x
        y = _dot(view, self.up) / depth / self.tan_half_y
        return (0.5 + 0.5 * x, 0.5 - 0.5 * y)


def _shear(item, x, z):
    """与生成器一致的坡面剪切：契约 z 值对应 xRef 处。"""
    slope = item.get("slopeZPerX")
    if slope is None:
        return z
    return z + slope * (x - item.get("xRef", 0.0))


def element_points(element, include_complex=True):
    """把元素的生成参数展开为世界坐标采样点（盒体 8 角 + 棱柱顶点）。

    include_complex=False 时跳过参数里标了 scope="complex" 的子体块。
    外围延伸白墙挂在 white_palace 元素上但只在建筑群完整剪影里可见，
    palace_proper 地标若把它算进包围盒，主体宽度会被虚增。
    """
    parameters = element.get("reconstruction", {}).get("generator", {}).get("parameters") or {}
    points = []
    for box in expand_boxes(parameters):
        if not include_complex and box.get("scope") == "complex":
            continue
        xs = (box["x0"], box["x1"])
        zs = (box["z0"], box["z1"])
        for x in xs:
            for y in (box["y0"], box["y1"]):
                for z in zs:
                    points.append([x, y, _shear(box, x, z)])
    for prism in expand_prisms(parameters):
        if not include_complex and prism.get("scope") == "complex":
            continue
        for x in (prism["x0"], prism["x1"]):
            for y, z in prism["profile"]:
                points.append([x, y, _shear(prism, x, z)])
    return points


def _profile_top(profile, y):
    """多边形轮廓在 y 处的上边界 z；y 落在轮廓外返回 None。"""
    best = None
    for index in range(len(profile)):
        y1, z1 = profile[index]
        y2, z2 = profile[(index + 1) % len(profile)]
        if y1 == y2:
            continue
        if min(y1, y2) <= y <= max(y1, y2):
            ratio = (y - y1) / (y2 - y1)
            z = z1 + ratio * (z2 - z1)
            best = z if best is None else max(best, z)
    return best


def terrain_height_field(hill):
    """由山体棱柱构造粗糙地形高度场 z(x, y)。

    用途是把建筑埋在山体以下的部分从投影包围盒里剔除：
    照片看不到的墙体不能参与配准比对，否则高度会被虚增。
    """
    if hill is None:
        return None
    parameters = hill.get("reconstruction", {}).get("generator", {}).get("parameters") or {}
    shape = []

    def build(item):
        profile = item.get("profile") or []
        if len(profile) < 3:
            return
        shape.append({
            "x0": min(item["x0"], item["x1"]),
            "x1": max(item["x0"], item["x1"]),
            "profile": profile,
            "slope": item.get("slopeZPerX", 0.0),
            "xRef": item.get("xRef", 0.0),
        })

    for prism in expand_prisms(parameters):
        build(prism)

    def height(x, y):
        best = None
        for item in shape:
            if not (item["x0"] <= x <= item["x1"]):
                continue
            top = _profile_top(item["profile"], y)
            if top is None:
                continue
            value = top + item["slope"] * (x - item["xRef"])
            best = value if best is None else max(best, value)
        return best

    return height


def visible_points(element, terrain=None, include_complex=True):
    """元素投影点，剔除低于地形（照片不可见）的部分。"""
    points = element_points(element, include_complex)
    if terrain is None:
        return points
    visible = []
    for point in points:
        ground = terrain(point[0], point[1])
        if ground is None or point[2] >= ground - 0.5:
            visible.append(point)
    return visible or points


def project_points(projector, points):
    """把世界点投影并合并为归一化包围盒；无可见点时返回 None。"""
    xs, ys = [], []
    for point in points:
        projected = projector.project(point)
        if projected is None:
            continue
        xs.append(projected[0])
        ys.append(projected[1])
    if not xs:
        return None
    return {"x": min(xs), "y": min(ys), "width": max(xs) - min(xs), "height": max(ys) - min(ys)}


def project_bbox(projector, elements, terrain=None, include_complex=True):
    """把若干元素投影点合并为归一化包围盒；无可见点时返回 None。"""
    xs, ys = [], []
    for element in elements:
        for point in visible_points(element, terrain, include_complex):
            projected = projector.project(point)
            if projected is None:
                continue
            xs.append(projected[0])
            ys.append(projected[1])
    if not xs:
        return None
    return {"x": min(xs), "y": min(ys), "width": max(xs) - min(xs), "height": max(ys) - min(ys)}


def _area(box):
    return max(0.0, box["width"]) * max(0.0, box["height"])


def iou(a, b):
    left = max(a["x"], b["x"])
    top = max(a["y"], b["y"])
    right = min(a["x"] + a["width"], b["x"] + b["width"])
    bottom = min(a["y"] + a["height"], b["y"] + b["height"])
    inter = max(0.0, right - left) * max(0.0, bottom - top)
    union = _area(a) + _area(b) - inter
    return inter / union if union > 0 else 0.0


def compare_landmark(landmark, projected, tolerance):
    photo = landmark["bbox"]
    dx = (projected["x"] + projected["width"] / 2) - (photo["x"] + photo["width"] / 2)
    dy = (projected["y"] + projected["height"] / 2) - (photo["y"] + photo["height"] / 2)
    width_error = (projected["width"] - photo["width"]) / photo["width"]
    height_error = (projected["height"] - photo["height"]) / photo["height"]
    overlap = iou(photo, projected)

    reasons = []
    if abs(dx) > tolerance:
        reasons.append(f"中心水平偏移 {dx * 100:+.1f}%（容差 {tolerance * 100:.0f}%）")
    if abs(dy) > tolerance:
        reasons.append(f"中心垂直偏移 {dy * 100:+.1f}%（容差 {tolerance * 100:.0f}%）")
    if abs(width_error) > tolerance:
        reasons.append(f"宽度误差 {width_error * 100:+.1f}%（容差 {tolerance * 100:.0f}%）")
    if abs(height_error) > tolerance:
        reasons.append(f"高度误差 {height_error * 100:+.1f}%（容差 {tolerance * 100:.0f}%）")
    if overlap < MIN_IOU:
        reasons.append(f"包围盒 IoU {overlap:.2f} < {MIN_IOU}")

    return {
        "dx": round(dx, 4),
        "dy": round(dy, 4),
        "widthError": round(width_error, 4),
        "heightError": round(height_error, 4),
        "iou": round(overlap, 4),
        "passed": not reasons,
        "reasons": reasons,
    }


def check_registration(survey, scene):
    """按地标所属相机逐项比对，返回 (errors, report)。

    多视角时每个地标用 cameraId 指定相机；缺省用 cameras[0]。
    """
    errors = []
    cameras = scene.get("cameras") or []
    if not cameras:
        return ["场景缺少 cameras，配准门禁无法执行"], {"ok": False, "landmarks": [], "errors": errors}

    landmarks = survey.get("photoLandmarks") or []
    if not landmarks:
        errors.append("勘察缺少 photoLandmarks：配准门禁无法执行，先按照片量测建筑/红宫等包围盒。")
        return errors, {"ok": False, "cameraIds": [], "landmarks": [], "errors": errors}

    hill = next((element for element in scene.get("elements") or [] if element["id"] == "potala_hill"), None)
    terrain = terrain_height_field(hill)
    camera_by_id = {camera["id"]: camera for camera in cameras}
    by_id = {element["id"]: element for element in scene.get("elements") or []}
    projectors = {}
    rows = []

    for landmark in landmarks:
        camera_id = landmark.get("cameraId") or cameras[0]["id"]
        camera = camera_by_id.get(camera_id)
        if camera is None:
            errors.append(f"地标 {landmark['id']} 引用了不存在的相机：{camera_id}")
            continue
        projector = projectors.setdefault(camera_id, Projector(camera))

        missing = [item for item in landmark["elementIds"] if item not in by_id]
        if missing:
            errors.append(f"地标 {landmark['id']} 引用了不存在的元素：{', '.join(missing)}")
            continue
        elements = [by_id[item] for item in landmark["elementIds"]]
        # scope=complex 的建筑群剪影才把外围延伸白墙算进来；缺省 palace_proper。
        include_complex = landmark.get("scope", "palace_proper") == "complex"
        projected = project_bbox(projector, elements, terrain, include_complex)
        if projected is None:
            errors.append(f"地标 {landmark['id']} 的元素全部落在相机后方，无法投影")
            continue

        tolerance = landmark.get("tolerance", DEFAULT_TOLERANCE)
        result = compare_landmark(landmark, projected, tolerance)
        row = {
            "id": landmark["id"],
            "label": landmark["label"],
            "photoRef": landmark.get("photoRef"),
            "cameraId": camera_id,
            "tolerance": tolerance,
            "photoBBox": landmark["bbox"],
            "projectedBBox": {key: round(value, 4) for key, value in projected.items()},
            **result,
        }
        rows.append(row)
        for reason in result["reasons"]:
            errors.append(f"地标 {landmark['id']}（{landmark['label']}）：{reason}")

    report = {
        "ok": not errors,
        "cameraIds": sorted(projectors),
        "landmarkCount": len(landmarks),
        "passedCount": sum(1 for row in rows if row["passed"]),
        "landmarks": rows,
        "errors": errors,
    }
    return errors, report


def render_overlay_svg(rows, photo_path, out_path, width, height):
    """输出可独立打开的 SVG：照片底图 + 照片地标框 + 对应相机的投影框。"""
    photo_path = Path(photo_path)
    mime = "image/png" if photo_path.suffix.lower() == ".png" else "image/jpeg"
    if photo_path.suffix.lower() == ".webp":
        mime = "image/webp"
    payload = base64.b64encode(photo_path.read_bytes()).decode("ascii")

    def rect(box, color, dash, label):
        return (
            f'<rect x="{box["x"] * width:.1f}" y="{box["y"] * height:.1f}" '
            f'width="{box["width"] * width:.1f}" height="{box["height"] * height:.1f}" '
            f'fill="none" stroke="{color}" stroke-width="2" stroke-dasharray="{dash}" />'
            f'<text x="{box["x"] * width + 3:.1f}" y="{box["y"] * height + 13:.1f}" '
            f'fill="{color}" font-size="12" font-family="sans-serif">{label}</text>'
        )

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
        f'<image href="data:{mime};base64,{payload}" x="0" y="0" width="{width}" height="{height}" />',
    ]
    for row in rows:
        parts.append(rect(row["photoBBox"], "#ff8c00", "6 4", f'{row["id"]} 照片'))
        parts.append(rect(row["projectedBBox"], "#00e5ff", "none", f'{row["id"]} 投影'))
    parts.append(
        f'<text x="8" y="{height - 8}" fill="#00e5ff" font-size="12" font-family="sans-serif">'
        f'橙色虚线=照片地标框，青色实线=场景投影框；偏差见 registration-report.json</text>'
    )
    parts.append("</svg>")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(chr(10).join(parts), encoding="utf-8")


def resolve_photo(scene, photo_ref):
    """按勘察的 photoRef 找到场景 inputs.photos 里的本地路径。"""
    for photo in scene.get("inputs", {}).get("photos", []):
        if photo.get("id") == photo_ref:
            return Path(scene.get("_base_dir", ".")) / photo["uri"]
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description="场景投影与照片地标的配准门禁")
    parser.add_argument("--survey", required=True, help="survey.json 路径")
    parser.add_argument("--scene", required=True, help="scene.json 路径")
    parser.add_argument("--out", help="配准报告路径；省略时写到场景目录的 derived/registration-report.json")
    parser.add_argument("--svg-dir", help="叠加图输出目录；省略时写到场景目录的 derived/")
    args = parser.parse_args(argv)

    try:
        survey = json.loads(Path(args.survey).read_text(encoding="utf-8"))
        scene_path = Path(args.scene).resolve()
        scene = json.loads(scene_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[FAIL] 读取输入失败：{exc}", file=sys.stderr)
        return 2

    errors, report = check_registration(survey, scene)
    derived = scene_path.parent / "derived"
    out = Path(args.out) if args.out else derived / "registration-report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")

    svg_dir = Path(args.svg_dir) if args.svg_dir else derived
    photos = {photo.get("id"): photo for photo in scene.get("inputs", {}).get("photos", [])}
    by_photo = {}
    for row in report.get("landmarks", []):
        by_photo.setdefault(row.get("photoRef"), []).append(row)
    overlays = []
    for photo_ref, rows in by_photo.items():
        photo = photos.get(photo_ref)
        if not photo:
            continue
        photo_path = ROOT / photo["uri"]
        if not photo_path.exists():
            continue
        exif = photo.get("exif") or {}
        width = int(exif.get("width") or 800)
        height = int(exif.get("height") or 533)
        svg_path = svg_dir / f"registration-overlay-{photo_ref}.svg"
        render_overlay_svg(rows, photo_path, svg_path, width, height)
        overlays.append(svg_path)

    if errors:
        print(f"[FAIL] 配准门禁未通过：地标 {report.get('passedCount', 0)}/{report.get('landmarkCount', 0)} 通过")
        for error in errors:
            print(f"  - {error}")
    else:
        print(f"[OK]   配准门禁通过：地标 {report.get('landmarkCount')} 个全部通过")
    print(f"       报告：{out}")
    for svg_path in overlays:
        print(f"       叠加：{svg_path}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
