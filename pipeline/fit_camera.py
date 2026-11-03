#!/usr/bin/env python3
"""相机拟合：用照片地标包围盒反解一台相机的位姿与视场角。

相机用“目标点 + 环绕方位/俯仰/距离 + fov”参数化（5 个自由度）：
目标点水平位置固定为场景锚点（默认原点），相机水平位置只能由方位角与
距离推出，不能独立横移。正视图可用 --lock-azimuth 把方位锁死。
地标包围盒给出 4 个约束（中心 x/y、宽、高），脚本用坐标下降最小化
“中心偏移 + 宽/高相对误差 + (1-IoU)”的加权代价。

它只能把相机摆到最贴合的位置；如果几何本身比例不对，
残差无法降到容差内——这正是配准门禁要暴露的东西。

用法：
    python3 pipeline/fit_camera.py --survey examples/potala-survey.json \
        --scene scenes/potala-palace-lhasa/scene.json \
        --photo photo_front --camera camera_front [--write]
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.registration_check import (  # noqa: E402
    Projector,
    compare_landmark,
    iou,
    project_points,
    terrain_height_field,
    visible_points,
)

DEFAULT_TOLERANCE = 0.05


def camera_from_params(params, camera_id, anchor):
    """“目标点 + 方位/俯仰/距离 + fov” 还原成 position/target/fovY。

    anchor 是目标点的水平位置 (x, y)，targetZ 由求解器给出。
    相机水平位置只能由方位角与距离推出，无法独立横移，
    从根上堵住“平移几十米去吸收几何比例误差”的退化解。
    """
    azimuth = math.radians(params["azimuth"])
    elevation = math.radians(params["elevation"])
    direction = [
        math.sin(azimuth) * math.cos(elevation),
        math.cos(azimuth) * math.cos(elevation),
        math.sin(elevation),
    ]
    target = [anchor[0], anchor[1], params["targetZ"]]
    position = [target[i] - direction[i] * params["distance"] for i in range(3)]
    return {"id": camera_id, "position": position, "target": target, "fovY": params["fovY"]}


def cost(params, camera_id, landmarks, anchor):
    camera = camera_from_params(params, camera_id, anchor)
    projector = Projector(camera)
    total = 0.0
    for landmark in landmarks:
        projected = project_points(projector, landmark["points"])
        if projected is None:
            return float("inf")
        photo = landmark["bbox"]
        dx = (projected["x"] + projected["width"] / 2) - (photo["x"] + photo["width"] / 2)
        dy = (projected["y"] + projected["height"] / 2) - (photo["y"] + photo["height"] / 2)
        dw = (projected["width"] - photo["width"]) / photo["width"]
        dh = (projected["height"] - photo["height"]) / photo["height"]
        total += dx * dx + dy * dy + dw * dw + dh * dh + (1.0 - iou(photo, projected)) * 0.25
    return total


STEPS = {
    "distance": [400.0, 200.0, 100.0, 50.0, 20.0, 10.0, 5.0, 2.0],
    "targetZ": [50.0, 20.0, 10.0, 5.0, 2.0, 1.0, 0.5],
    "azimuth": [4.0, 2.0, 1.0, 0.5, 0.2, 0.1, 0.05],
    "elevation": [4.0, 2.0, 1.0, 0.5, 0.2, 0.1, 0.05],
    "fovY": [6.0, 3.0, 1.5, 0.7, 0.3, 0.1, 0.05],
}
MAX_LEVELS = max(len(steps) for steps in STEPS.values())


def descend(params, camera_id, landmarks, anchor_xy, azimuth_limit, elevation_limit):
    """坐标下降；方位/俯仰只能在初始朝向 ±limit 内移动。

    不加约束时求解器会用“转相机/横移相机”去吸收几何比例误差：
    正视图照片会被拟合成偏转 20° 的斜视，残差看着小了，物理上却是荒谬的。
    现在水平位置已经由方位角唯一决定，--lock-azimuth 再锁死方位即可。
    """
    initial = {"azimuth": params["azimuth"], "elevation": params["elevation"]}
    best = cost(params, camera_id, landmarks, anchor_xy)
    for level in range(MAX_LEVELS):
        improved = True
        while improved:
            improved = False
            for name, steps in STEPS.items():
                value = steps[min(level, len(steps) - 1)]
                for sign in (1.0, -1.0):
                    trial = dict(params)
                    trial[name] = params[name] + sign * value
                    if name == "azimuth":
                        trial[name] = max(initial["azimuth"] - azimuth_limit, min(initial["azimuth"] + azimuth_limit, trial[name]))
                    if name == "elevation":
                        trial[name] = max(initial["elevation"] - elevation_limit, min(initial["elevation"] + elevation_limit, trial[name]))
                    if name == "distance":
                        trial[name] = max(50.0, trial[name])
                    if name == "fovY":
                        trial[name] = max(4.0, min(80.0, trial[name]))
                    trial_cost = cost(trial, camera_id, landmarks, anchor_xy)
                    if trial_cost < best - 1e-12:
                        best = trial_cost
                        params = trial
                        improved = True
    return params, best


def residuals(camera, landmarks):
    projector = Projector(camera)
    rows = []
    for landmark in landmarks:
        projected = project_points(projector, landmark["points"])
        photo = landmark["bbox"]
        tolerance = landmark.get("tolerance", DEFAULT_TOLERANCE)
        result = compare_landmark(landmark, projected, tolerance)
        rows.append({
            "id": landmark["id"],
            "tolerance": tolerance,
            "photoBBox": photo,
            "projectedBBox": {key: round(value, 4) for key, value in projected.items()},
            **result,
        })
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description="按照片地标拟合相机")
    parser.add_argument("--survey", required=True)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--photo", required=True, help="地标的 photoRef，如 photo_front")
    parser.add_argument("--camera", required=True, help="要拟合/覆盖的相机 id")
    parser.add_argument("--write", action="store_true", help="把解写回 scene.json 的相机条目")
    parser.add_argument("--out", help="拟合报告路径；缺省 derived/camera-fit-<photo>.json")
    parser.add_argument("--azimuth-limit", type=float, default=8.0, help="允许相对初始方位角的偏转（度）")
    parser.add_argument("--elevation-limit", type=float, default=8.0, help="允许相对初始俯仰角的偏转（度）")
    parser.add_argument("--lock-azimuth", action="store_true", help="方位角锁死（正视图必须开启）")
    parser.add_argument("--anchor-x", type=float, default=0.0, help="目标点水平锚点 X")
    parser.add_argument("--anchor-y", type=float, default=0.0, help="目标点水平锚点 Y")
    args = parser.parse_args(argv)
    azimuth_limit = 0.0 if args.lock_azimuth else args.azimuth_limit

    survey = json.loads(Path(args.survey).read_text(encoding="utf-8"))
    scene_path = Path(args.scene).resolve()
    scene = json.loads(scene_path.read_text(encoding="utf-8"))

    by_id = {element["id"]: element for element in scene.get("elements") or []}
    hill = next((element for element in scene.get("elements") or [] if element["id"] == "potala_hill"), None)
    terrain = terrain_height_field(hill)
    landmarks = []
    for landmark in survey.get("photoLandmarks") or []:
        if landmark.get("photoRef") != args.photo:
            continue
        missing = [item for item in landmark["elementIds"] if item not in by_id]
        if missing:
            print(f"[FAIL] 地标 {landmark['id']} 引用不存在的元素：{missing}", file=sys.stderr)
            return 2
        item = dict(landmark)
        item["elements"] = [by_id[name] for name in landmark["elementIds"]]
        points = []
        include_complex = landmark.get("scope", "palace_proper") == "complex"
        for element in item["elements"]:
            points.extend(visible_points(element, terrain, include_complex))
        item["points"] = points
        landmarks.append(item)
    if not landmarks:
        print(f"[FAIL] 没有 photoRef={args.photo} 的地标", file=sys.stderr)
        return 2

    camera_def = next((camera for camera in scene["cameras"] if camera["id"] == args.camera), None)
    if camera_def is None:
        print(f"[FAIL] 场景缺少相机 {args.camera}", file=sys.stderr)
        return 2

    position = camera_def["position"]
    target = camera_def["target"]
    delta = [target[i] - position[i] for i in range(3)]
    horizontal = math.hypot(delta[0], delta[1])
    params = {
        "targetZ": target[2],
        "distance": math.sqrt(sum(value * value for value in delta)),
        "azimuth": math.degrees(math.atan2(delta[0], delta[1])),
        "elevation": math.degrees(math.atan2(delta[2], horizontal)),
        "fovY": camera_def["fovY"],
    }
    anchor_xy = (args.anchor_x, args.anchor_y)

    solved, final_cost = descend(
        params, args.camera, landmarks, anchor_xy, azimuth_limit, args.elevation_limit
    )
    camera = camera_from_params(solved, args.camera, anchor_xy)
    rows = residuals(camera, landmarks)

    report = {
        "photo": args.photo,
        "cameraId": args.camera,
        "initial": params,
        "anchor": [args.anchor_x, args.anchor_y],
        "solved": {
            **camera,
            "position": [round(value, 2) for value in camera["position"]],
            "target": [round(value, 2) for value in camera["target"]],
            "fovY": round(camera["fovY"], 3),
            "orbit": {
                "azimuth": round(solved["azimuth"], 3),
                "elevation": round(solved["elevation"], 3),
                "distance": round(solved["distance"], 3),
                "targetZ": round(solved["targetZ"], 3),
                "azimuthLocked": args.lock_azimuth,
            },
        },
        "cost": round(final_cost, 6),
        "azimuthLimit": azimuth_limit,
        "elevationLimit": args.elevation_limit,
        "landmarks": rows,
        "ok": all(row["passed"] for row in rows),
    }

    out = Path(args.out) if args.out else scene_path.parent / "derived" / f"camera-fit-{args.photo}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")

    for row in rows:
        print(f"  {row['id']}: dx={row['dx'] * 100:+.1f}% dy={row['dy'] * 100:+.1f}% "
              f"w={row['widthError'] * 100:+.1f}% h={row['heightError'] * 100:+.1f}% iou={row['iou']:.2f} "
              f"{'PASS' if row['passed'] else 'FAIL'}")

    if args.write:
        for index, existing in enumerate(scene["cameras"]):
            if existing["id"] == args.camera:
                existing["position"] = [round(value, 2) for value in camera["position"]]
                existing["target"] = [round(value, 2) for value in camera["target"]]
                existing["fovY"] = round(camera["fovY"], 2)
                existing["confidence"] = 0.45
                existing["orbit"] = {
                    "target": [round(value, 2) for value in camera["target"]],
                    "azimuth": round(solved["azimuth"], 3),
                    "elevation": round(solved["elevation"], 3),
                    "distance": round(solved["distance"], 3),
                    "locked": ["azimuth"] if args.lock_azimuth else [],
                }
                existing["sourceRefs"] = sorted(set(existing.get("sourceRefs", []) + [args.photo]))
                scene["cameras"][index] = existing
        scene_path.write_text(json.dumps(scene, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
        print(f"[OK] 已写回 {scene_path} 的 {args.camera}")

    print(f"       报告：{out}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
