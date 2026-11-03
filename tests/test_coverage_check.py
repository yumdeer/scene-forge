"""覆盖门禁测试：照片区域 -> 结构类别 -> 场景元素必须逐项对账。"""

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.coverage_check import check_coverage, main  # noqa: E402
from pipeline.schema_validate import validate_document  # noqa: E402

SURVEY_PATH = ROOT / "examples" / "potala-survey.json"
SCENE_PATH = ROOT / "scenes" / "potala-palace-lhasa" / "scene.json"


def load_survey():
    return json.loads(SURVEY_PATH.read_text(encoding="utf-8"))


def load_scene():
    return json.loads(SCENE_PATH.read_text(encoding="utf-8"))


class RegionContractTest(unittest.TestCase):
    """区域清单与元素字段的契约约束。"""

    def test_potala_survey_is_valid(self):
        self.assertEqual(validate_document("survey", load_survey()), [])

    def test_potala_scene_is_valid(self):
        self.assertEqual(validate_document("scene", load_scene()), [])

    def test_region_requires_bbox(self):
        survey = load_survey()
        del survey["regions"][0]["bbox"]
        errors = validate_document("survey", survey)
        self.assertTrue(any(error.startswith("regions.0") for error in errors), errors)

    def test_region_rejects_unknown_structure_class(self):
        survey = load_survey()
        survey["regions"][0]["structureClasses"] = ["magic_wall"]
        errors = validate_document("survey", survey)
        self.assertTrue(
            any(error.startswith("regions.0.structureClasses") for error in errors), errors
        )

    def test_region_rejects_out_of_range_bbox(self):
        survey = load_survey()
        survey["regions"][0]["bbox"]["width"] = 1.5
        errors = validate_document("survey", survey)
        self.assertTrue(any(error.startswith("regions.0.bbox") for error in errors), errors)

    def test_scene_element_rejects_unknown_structure_class(self):
        scene = load_scene()
        scene["elements"][0]["structureClasses"] = ["magic_wall"]
        errors = validate_document("scene", scene)
        self.assertTrue(
            any(error.startswith("elements.0.structureClasses") for error in errors), errors
        )

    def test_scene_element_rejects_extra_photo_region_field(self):
        scene = load_scene()
        scene["elements"][0]["photoRegions"] = [1]
        errors = validate_document("scene", scene)
        self.assertTrue(any(error.startswith("elements.0.photoRegions") for error in errors), errors)


class CoverageGateTest(unittest.TestCase):
    """门禁判定：缺口、契约漂移、豁免与空清单。"""

    def setUp(self):
        self.survey = load_survey()
        self.scene = load_scene()

    def test_potala_passes(self):
        errors, report = check_coverage(self.survey, self.scene)
        self.assertEqual(errors, [])
        self.assertTrue(report["ok"])
        self.assertEqual(report["summary"]["declaredPairs"], 15)
        self.assertEqual(report["summary"]["coveredPairs"], 15)

    def test_report_lists_covering_elements(self):
        _, report = check_coverage(self.survey, self.scene)
        lower = next(r for r in report["regions"] if r["id"] == "potala_lower_front")
        self.assertEqual(lower["coverage"]["retaining_wall"], ["terrace_parapets"])
        self.assertEqual(lower["missingClasses"], [])

    def test_window_band_gap_is_reported(self):
        # 门禁按“区域 x 结构类别”判定存在性；要制造缺口，需移除该区域内所有窗带元素。
        scene = copy.deepcopy(self.scene)
        scene["elements"] = [
            element for element in scene["elements"]
            if not (
                "window_band" in element["structureClasses"]
                and "potala_lower_front" in element["photoRegions"]
            )
        ]
        errors, report = check_coverage(self.survey, scene)
        self.assertTrue(report["ok"] is False)
        self.assertTrue(
            any("potala_lower_front" in error and "window_band" in error for error in errors),
            errors,
        )

    def test_whole_category_missing_is_reported(self):
        # 复现历史漏项：台地挡墙与僧舍整类没建时，门禁必须直接失败。
        scene = copy.deepcopy(self.scene)
        scene["elements"] = [
            element for element in scene["elements"]
            if element["id"] not in ("terrace_parapets", "monk_quarters", "monk_quarters_upper")
        ]
        errors, report = check_coverage(self.survey, scene)
        self.assertTrue(report["ok"] is False)
        joined = "\n".join(errors)
        self.assertIn("retaining_wall", joined)
        self.assertIn("building_cluster", joined)

    def test_unknown_region_reference_is_reported(self):
        scene = copy.deepcopy(self.scene)
        scene["elements"][0]["photoRegions"] = ["potala_ghost_region"]
        errors, report = check_coverage(self.survey, scene)
        self.assertTrue(report["ok"] is False)
        self.assertTrue(any("potala_ghost_region" in error for error in errors), errors)
        self.assertEqual(
            report["unknownRegionRefs"],
            [{"elementId": scene["elements"][0]["id"], "regionId": "potala_ghost_region"}],
        )

    def test_waiver_exempts_region(self):
        survey = copy.deepcopy(self.survey)
        scene = copy.deepcopy(self.scene)
        survey["regions"][1]["waiver"] = {"reason": "该区域被树木遮挡，P1 只做体量推断。"}
        # 只保留同时承接全域的 white_palace，前景细节元素全部移除，
        # 让 potala_lower_front 出现真实缺口，再验证 waiver 是否放行。
        scene["elements"] = [
            element for element in scene["elements"]
            if element["id"] == "white_palace"
            or "potala_lower_front" not in (element.get("photoRegions") or [])
        ]
        errors, report = check_coverage(survey, scene)
        self.assertEqual(errors, [])
        self.assertTrue(report["regions"][1]["waived"])
        self.assertIn("window_band", report["regions"][1]["missingClasses"])

    def test_duplicate_region_id_is_reported(self):
        survey = copy.deepcopy(self.survey)
        survey["regions"][1]["id"] = survey["regions"][0]["id"]
        errors, _ = check_coverage(survey, self.scene)
        self.assertTrue(any("区域 ID 重复" in error for error in errors), errors)

    def test_missing_region_list_fails_by_default(self):
        survey = copy.deepcopy(self.survey)
        del survey["regions"]
        errors, report = check_coverage(survey, self.scene)
        self.assertTrue(report["ok"] is False)
        self.assertTrue(any("regions" in error for error in errors), errors)

    def test_missing_region_list_can_be_explicitly_skipped(self):
        survey = copy.deepcopy(self.survey)
        del survey["regions"]
        scene = copy.deepcopy(self.scene)
        for element in scene["elements"]:
            element.pop("photoRegions", None)
        errors, report = check_coverage(survey, scene, allow_empty_regions=True)
        self.assertEqual(errors, [])
        self.assertTrue(report["ok"])


class CoverageCliTest(unittest.TestCase):
    """命令行入口：报告落盘与退出码。"""

    def test_cli_writes_report_and_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "derived" / "coverage-report.json"
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = main(["--survey", str(SURVEY_PATH), "--scene", str(SCENE_PATH), "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertIn("[OK]", stdout.getvalue())
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(report["ok"])
            self.assertEqual(report["summary"]["regionCount"], 2)

    def test_cli_fails_on_gap(self):
        scene = load_scene()
        scene["elements"] = [
            element for element in scene["elements"]
            if element["id"] not in ("terrace_parapets", "front_terraces")
        ]
        with tempfile.TemporaryDirectory() as tmp:
            bad_scene = Path(tmp) / "scene.json"
            bad_scene.write_text(json.dumps(scene, ensure_ascii=False), encoding="utf-8")
            out = Path(tmp) / "coverage-report.json"
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = main(["--survey", str(SURVEY_PATH), "--scene", str(bad_scene), "--out", str(out)])
            self.assertEqual(code, 1)
            self.assertIn("[FAIL]", stdout.getvalue())
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertFalse(report["ok"])
            self.assertIn("terrace", "\n".join(report["errors"]))

    def test_cli_reports_missing_input(self):
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            code = main(["--survey", str(ROOT / "no-such-survey.json"), "--scene", str(SCENE_PATH)])
        self.assertEqual(code, 2)
        self.assertIn("[FAIL]", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
