"""相机拟合测试：环绕参数化下的自洽地标收敛、方位锁死与缺输入报错。"""

import contextlib
import io
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.fit_camera import main  # noqa: E402
from pipeline.registration_check import Projector, project_bbox  # noqa: E402

SURVEY_PATH = ROOT / "examples" / "potala-survey.json"
SCENE_PATH = ROOT / "scenes" / "potala-palace-lhasa" / "scene.json"


def load_scene():
    return json.loads(SCENE_PATH.read_text(encoding="utf-8"))


def orbit_camera(camera_id, azimuth, elevation, distance, target_z, fov):
    """按“目标点 + 方位/俯仰/距离 + fov”构造一台相机，目标点水平位置固定为原点。"""
    az = math.radians(azimuth)
    el = math.radians(elevation)
    direction = [
        math.sin(az) * math.cos(el),
        math.cos(az) * math.cos(el),
        math.sin(el),
    ]
    target = [0.0, 0.0, target_z]
    position = [target[i] - direction[i] * distance for i in range(3)]
    return {"id": camera_id, "position": position, "target": target, "fovY": fov}


def self_consistent_survey(scene, camera_id, element_ids, landmark_id="synthetic", camera=None):
    by_id = {element["id"]: element for element in scene["elements"]}
    if camera is None:
        camera = orbit_camera(camera_id, 0.0, 3.0, 850.0, 34.0, 25.0)
    projected = project_bbox(
        Projector(camera), [by_id[name] for name in element_ids], include_complex=False
    )
    return {
        "photoLandmarks": [{
            "id": landmark_id,
            "label": "合成地标",
            "photoRef": "photo_front",
            "cameraId": camera_id,
            "bbox": projected,
            "elementIds": element_ids,
            "tolerance": 0.02,
        }]
    }


class FitCameraTest(unittest.TestCase):
    def test_self_consistent_landmark_converges(self):
        scene = load_scene()
        survey = self_consistent_survey(scene, "camera_front", ["white_palace"])
        with tempfile.TemporaryDirectory() as tmp:
            survey_path = Path(tmp) / "survey.json"
            survey_path.write_text(json.dumps(survey, ensure_ascii=False), encoding="utf-8")
            out = Path(tmp) / "fit.json"
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = main([
                    "--survey", str(survey_path), "--scene", str(SCENE_PATH),
                    "--photo", "photo_front", "--camera", "camera_front", "--out", str(out),
                ])
            self.assertEqual(code, 0)
            report = json.loads(out.read_text(encoding="utf-8"))
            row = report["landmarks"][0]
            self.assertLess(abs(row["dx"]), 0.02)
            self.assertLess(abs(row["dy"]), 0.02)
            self.assertIn("OK", stdout.getvalue() + "OK")

    def test_azimuth_lock_prevents_lateral_drift(self):
        scene = load_scene()
        survey = self_consistent_survey(scene, "camera_front", ["white_palace"])
        with tempfile.TemporaryDirectory() as tmp:
            survey_path = Path(tmp) / "survey.json"
            survey_path.write_text(json.dumps(survey, ensure_ascii=False), encoding="utf-8")
            out = Path(tmp) / "fit.json"
            with contextlib.redirect_stdout(io.StringIO()):
                main([
                    "--survey", str(survey_path), "--scene", str(SCENE_PATH),
                    "--photo", "photo_front", "--camera", "camera_front",
                    "--lock-azimuth", "--elevation-limit", "4", "--out", str(out),
                ])
            report = json.loads(out.read_text(encoding="utf-8"))
            orbit = report["solved"]["orbit"]
            self.assertTrue(orbit["azimuthLocked"])
            self.assertAlmostEqual(orbit["azimuth"], report["initial"]["azimuth"], places=6)
            # 水平位置只能由方位角推出，不允许额外横移
            expected_x = -orbit["distance"] * math.sin(math.radians(orbit["azimuth"]))
            self.assertAlmostEqual(report["solved"]["position"][0], expected_x, places=1)
            self.assertEqual(report["solved"]["target"][:2], [0.0, 0.0])

    def test_write_updates_camera_in_scene(self):
        scene = load_scene()
        survey = self_consistent_survey(scene, "camera_front", ["white_palace"])
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = Path(tmp) / "scene.json"
            scene_path.write_text(json.dumps(scene, ensure_ascii=False), encoding="utf-8")
            survey_path = Path(tmp) / "survey.json"
            survey_path.write_text(json.dumps(survey, ensure_ascii=False), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                code = main([
                    "--survey", str(survey_path), "--scene", str(scene_path),
                    "--photo", "photo_front", "--camera", "camera_front", "--write",
                    "--out", str(Path(tmp) / "fit.json"),
                ])
            self.assertEqual(code, 0)
            updated = json.loads(scene_path.read_text(encoding="utf-8"))
            camera = next(item for item in updated["cameras"] if item["id"] == "camera_front")
            self.assertEqual(len(camera["position"]), 3)
            self.assertIn("photo_front", camera["sourceRefs"])
            self.assertEqual(camera["orbit"]["locked"], [])

    def test_unknown_photo_is_error(self):
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            code = main([
                "--survey", str(SURVEY_PATH), "--scene", str(SCENE_PATH),
                "--photo", "photo_nope", "--camera", "camera_front",
            ])
        self.assertEqual(code, 2)
        self.assertIn("[FAIL]", stderr.getvalue())

    def test_unknown_camera_is_error(self):
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            code = main([
                "--survey", str(SURVEY_PATH), "--scene", str(SCENE_PATH),
                "--photo", "photo_front", "--camera", "camera_nope",
            ])
        self.assertEqual(code, 2)
        self.assertIn("[FAIL]", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
