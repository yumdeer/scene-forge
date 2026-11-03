"""配准门禁测试：场景投影必须落在照片地标包围盒的容差内。"""

import contextlib
import copy
import io
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.registration_check import (  # noqa: E402
    Projector,
    check_registration,
    element_points,
    iou,
    main,
    project_bbox,
)

SURVEY_PATH = ROOT / "examples" / "potala-survey.json"
SCENE_PATH = ROOT / "scenes" / "potala-palace-lhasa" / "scene.json"


def load_survey():
    return json.loads(SURVEY_PATH.read_text(encoding="utf-8"))


def load_scene():
    return json.loads(SCENE_PATH.read_text(encoding="utf-8"))


class ProjectorTest(unittest.TestCase):
    """投影几何：正视相机中心点落在画面中心，横向偏移符合 fov。"""

    def test_center_point_maps_to_center(self):
        camera = {"position": [0, -100, 0], "target": [0, 0, 0], "fovY": 90}
        x, y = Projector(camera).project([0, 0, 0])
        self.assertAlmostEqual(x, 0.5, places=6)
        self.assertAlmostEqual(y, 0.5, places=6)

    def test_horizontal_offset_uses_aspect(self):
        camera = {"position": [0, -100, 0], "target": [0, 0, 0], "fovY": 90}
        # fovY=90 -> tan=1；3:2 画幅 -> tanX=1.5；x=10m、depth=100m。
        x, _ = Projector(camera).project([10, 0, 0])
        self.assertAlmostEqual(x, 0.5 + 0.5 * (10 / 100 / 1.5), places=6)

    def test_point_behind_camera_is_ignored(self):
        camera = {"position": [0, -100, 0], "target": [0, 0, 0], "fovY": 90}
        self.assertIsNone(Projector(camera).project([0, -200, 0]))


class ScopeFilterTest(unittest.TestCase):
    """外围延伸白墙只计入 complex 剪影，palace_proper 必须剔除。"""

    def setUp(self):
        self.scene = load_scene()
        self.by_id = {element["id"]: element for element in self.scene["elements"]}

    def test_palace_proper_excludes_outer_extension(self):
        element = self.by_id["white_palace"]
        proper = element_points(element, include_complex=False)
        full = element_points(element, include_complex=True)
        self.assertGreater(len(full), len(proper))
        self.assertGreater(min(point[0] for point in proper), -181)
        self.assertLessEqual(min(point[0] for point in full), -200)

    def test_complex_scope_widens_front_bbox(self):
        projector = Projector(next(camera for camera in self.scene["cameras"] if camera["id"] == "camera_front"))
        elements = [self.by_id["white_palace"]]
        proper = project_bbox(projector, elements, include_complex=False)
        full = project_bbox(projector, elements, include_complex=True)
        self.assertGreater(full["width"], proper["width"])


class IoUTest(unittest.TestCase):
    def test_identical_boxes(self):
        box = {"x": 0.2, "y": 0.2, "width": 0.4, "height": 0.4}
        self.assertAlmostEqual(iou(box, dict(box)), 1.0)

    def test_disjoint_boxes(self):
        a = {"x": 0.0, "y": 0.0, "width": 0.1, "height": 0.1}
        b = {"x": 0.5, "y": 0.5, "width": 0.1, "height": 0.1}
        self.assertEqual(iou(a, b), 0.0)


class RegistrationGateTest(unittest.TestCase):
    """门禁判定：自洽地标通过，偏移/尺寸/引用错误必须失败。"""

    def setUp(self):
        self.survey = load_survey()
        self.scene = load_scene()

    def _projected(self, element_ids):
        by_id = {element["id"]: element for element in self.scene["elements"]}
        projector = Projector(self.scene["cameras"][0])
        # 与门禁缺省 scope=palace_proper 一致：合成地标只含宫殿主体。
        return project_bbox(projector, [by_id[item] for item in element_ids], include_complex=False)

    def _survey_with(self, landmarks):
        survey = copy.deepcopy(self.survey)
        survey["photoLandmarks"] = landmarks
        return survey

    def test_self_consistent_landmark_passes(self):
        projected = self._projected(["white_palace", "red_palace", "golden_roofs"])
        landmark = {
            "id": "building_main",
            "label": "建筑整体",
            "photoRef": "photo_01",
            "bbox": projected,
            "elementIds": ["white_palace", "red_palace", "golden_roofs"],
        }
        errors, report = check_registration(self._survey_with([landmark]), self.scene)
        self.assertEqual(errors, [])
        self.assertTrue(report["ok"])
        self.assertEqual(report["passedCount"], 1)

    def test_shifted_landmark_fails(self):
        projected = self._projected(["white_palace"])
        shifted = dict(projected)
        shifted["x"] = projected["x"] + 0.1
        landmark = {
            "id": "building_main",
            "label": "建筑整体",
            "photoRef": "photo_01",
            "bbox": shifted,
            "elementIds": ["white_palace"],
        }
        errors, report = check_registration(self._survey_with([landmark]), self.scene)
        self.assertFalse(report["ok"])
        self.assertTrue(any("中心水平偏移" in error for error in errors), errors)

    def test_unknown_element_is_reported(self):
        landmark = copy.deepcopy(self.survey["photoLandmarks"][0])
        landmark["elementIds"] = ["ghost_element"]
        errors, report = check_registration(self._survey_with([landmark]), self.scene)
        self.assertFalse(report["ok"])
        self.assertTrue(any("ghost_element" in error for error in errors), errors)

    def test_missing_landmarks_fails(self):
        survey = copy.deepcopy(self.survey)
        del survey["photoLandmarks"]
        errors, report = check_registration(survey, self.scene)
        self.assertFalse(report["ok"])
        self.assertTrue(any("photoLandmarks" in error for error in errors), errors)

    def test_missing_camera_fails(self):
        scene = copy.deepcopy(self.scene)
        scene["cameras"] = []
        errors, report = check_registration(self.survey, scene)
        self.assertFalse(report["ok"])
        self.assertTrue(any("cameras" in error for error in errors), errors)

    def test_element_points_follow_shear(self):
        element = next(item for item in self.scene["elements"] if item["id"] == "white_palace")
        points = element_points(element)
        self.assertTrue(points)
        # 带 slopeZPerX 的盒子两端 z 必须不同，否则坡面剪切没生效。
        zs = [point[2] for point in points]
        self.assertGreater(max(zs) - min(zs), 90)


class RegistrationCliTest(unittest.TestCase):
    """命令行入口：报告、叠加图与退出码。"""

    def test_cli_reports_failure_for_current_scene(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "registration-report.json"
            svg = Path(tmp) / "registration-overlay-photo_01.svg"
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = main([
                    "--survey", str(SURVEY_PATH), "--scene", str(SCENE_PATH),
                    "--out", str(out), "--svg-dir", str(Path(tmp)),
                ])
            self.assertEqual(code, 1)
            self.assertIn("[FAIL]", stdout.getvalue())
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertFalse(report["ok"])
            self.assertTrue(svg.exists(), list(Path(tmp).iterdir()))
            self.assertIn("<svg", svg.read_text(encoding="utf-8"))

    def test_cli_passes_with_self_consistent_landmark(self):
        scene = load_scene()
        by_id = {element["id"]: element for element in scene["elements"]}
        projector = Projector(scene["cameras"][0])
        projected = project_bbox(projector, [by_id["white_palace"]], include_complex=False)
        survey = load_survey()
        survey["photoLandmarks"] = [{
            "id": "building_main",
            "label": "建筑整体",
            "photoRef": "photo_01",
            "bbox": projected,
            "elementIds": ["white_palace"],
        }]
        with tempfile.TemporaryDirectory() as tmp:
            survey_path = Path(tmp) / "survey.json"
            survey_path.write_text(json.dumps(survey, ensure_ascii=False), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = main([
                    "--survey", str(survey_path), "--scene", str(SCENE_PATH),
                    "--out", str(Path(tmp) / "report.json"), "--svg-dir", str(Path(tmp)),
                ])
            self.assertEqual(code, 0)
            self.assertIn("[OK]", stdout.getvalue())

    def test_cli_reports_missing_input(self):
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            code = main(["--survey", str(ROOT / "no-such.json"), "--scene", str(SCENE_PATH)])
        self.assertEqual(code, 2)
        self.assertIn("[FAIL]", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
