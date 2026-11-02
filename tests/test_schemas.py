"""scene.json / survey.json 契约测试：最小示例通过，非法文档必须被拒绝。"""

import contextlib
import copy
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.schema_validate import SCHEMA_PATHS, main, validate_document, validate_file  # noqa: E402


def load_example(name):
    return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))


class SchemaExampleTest(unittest.TestCase):
    """最小完整示例必须通过校验。"""

    def test_minimal_scene_is_valid(self):
        self.assertEqual(validate_document("scene", load_example("minimal-scene.json")), [])

    def test_minimal_survey_is_valid(self):
        self.assertEqual(validate_document("survey", load_example("minimal-survey.json")), [])


class SceneNegativeTest(unittest.TestCase):
    """场景文档的负向用例。"""

    def setUp(self):
        self.scene = load_example("minimal-scene.json")

    def assert_rejected(self, document, expected_path):
        errors = validate_document("scene", document)
        self.assertTrue(errors, "非法文档不应通过校验")
        self.assertTrue(
            any(error.startswith(expected_path) for error in errors),
            f"期望在 {expected_path} 报错，实际：{errors}",
        )

    def test_missing_required_field(self):
        scene = copy.deepcopy(self.scene)
        del scene["revision"]
        self.assert_rejected(scene, "<root>")

    def test_confidence_out_of_range(self):
        scene = copy.deepcopy(self.scene)
        scene["elements"][0]["confidence"] = 1.5
        self.assert_rejected(scene, "elements.0.confidence")

    def test_invalid_status_enum(self):
        scene = copy.deepcopy(self.scene)
        scene["status"] = "done"
        self.assert_rejected(scene, "status")

    def test_invalid_sha256(self):
        scene = copy.deepcopy(self.scene)
        scene["inputs"]["photos"][0]["sha256"] = "abc"
        self.assert_rejected(scene, "inputs.photos.0.sha256")

    def test_invalid_datetime(self):
        scene = copy.deepcopy(self.scene)
        scene["revision"]["createdAt"] = "not-a-date"
        self.assert_rejected(scene, "revision.createdAt")

    def test_unknown_field_rejected(self):
        scene = copy.deepcopy(self.scene)
        scene["unexpected"] = True
        self.assert_rejected(scene, "<root>")

    def test_scene_id_pattern(self):
        scene = copy.deepcopy(self.scene)
        scene["sceneId"] = "Example_Garden"
        self.assert_rejected(scene, "sceneId")

    def test_confirmed_location_requires_name_and_confirmation(self):
        scene = copy.deepcopy(self.scene)
        scene["location"] = {
            "mode": "confirmed",
            "confidence": 0.9,
            "userConfirmed": False,
            "sourceRefs": ["photo_01"],
        }
        self.assert_rejected(scene, "location")

    def test_asset_license_required(self):
        scene = copy.deepcopy(self.scene)
        scene["assets"] = [
            {
                "id": "master_glb",
                "kind": "glb",
                "uri": "scenes/example-garden-pavilion/master.glb",
                "role": "master",
                "sourceRefs": ["photo_01"],
            }
        ]
        self.assert_rejected(scene, "assets.0")


class SurveyNegativeTest(unittest.TestCase):
    """勘察文档的负向用例。"""

    def setUp(self):
        self.survey = load_example("minimal-survey.json")

    def assert_rejected(self, document, expected_path):
        errors = validate_document("survey", document)
        self.assertTrue(errors, "非法文档不应通过校验")
        self.assertTrue(
            any(error.startswith(expected_path) for error in errors),
            f"期望在 {expected_path} 报错，实际：{errors}",
        )

    def test_missing_element(self):
        survey = copy.deepcopy(self.survey)
        survey["elements"] = []
        self.assert_rejected(survey, "elements")

    def test_invalid_element_method(self):
        survey = copy.deepcopy(self.survey)
        survey["elements"][0]["proposedMethod"] = "magic"
        self.assert_rejected(survey, "elements.0.proposedMethod")

    def test_too_many_user_questions(self):
        survey = copy.deepcopy(self.survey)
        survey["userQuestions"] = ["q1", "q2", "q3", "q4"]
        self.assert_rejected(survey, "userQuestions")

    def test_invalid_blocker_severity(self):
        survey = copy.deepcopy(self.survey)
        survey["blockers"][0]["severity"] = "critical"
        self.assert_rejected(survey, "blockers.0.severity")


class FileAndCliTest(unittest.TestCase):
    """文件读取与命令行入口。"""

    def test_broken_json_reported(self):
        broken = ROOT / "tests" / "__broken__.json"
        broken.write_text("{", encoding="utf-8")
        try:
            errors = validate_file("scene", broken)
            self.assertEqual(len(errors), 1)
            self.assertIn("JSON 解析失败", errors[0])
        finally:
            broken.unlink()

    def test_cli_passes_examples(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["scene", str(ROOT / "examples" / "minimal-scene.json")]), 0)
            self.assertEqual(main(["survey", str(ROOT / "examples" / "minimal-survey.json")]), 0)

    def test_cli_fails_invalid_document(self):
        bad = ROOT / "tests" / "__invalid__.json"
        bad.write_text(json.dumps({"schemaVersion": "1.0.0"}), encoding="utf-8")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["scene", str(bad)]), 1)
        finally:
            bad.unlink()


class SchemaIntegrityTest(unittest.TestCase):
    """Schema 自身结构完整性。"""

    def test_every_ref_resolves(self):
        import re

        for kind, path in SCHEMA_PATHS.items():
            text = path.read_text(encoding="utf-8")
            schema = json.loads(text)
            defs = set(schema.get("$defs", {}))
            refs = set(re.findall(r"#/\$defs/([A-Za-z0-9_]+)", text))
            self.assertEqual(refs - defs, set(), f"{kind} 存在无法解析的 $ref")

    def test_declares_2020_12(self):
        for path in SCHEMA_PATHS.values():
            schema = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")


if __name__ == "__main__":
    unittest.main()
