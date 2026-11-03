"""勘察报告渲染测试：人读 Markdown 必须完全由 survey.json 生成。"""

import contextlib
import copy
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.render_survey import main, render_survey, render_survey_file  # noqa: E402
from pipeline.schema_validate import validate_document  # noqa: E402

REPORT_PATH = ROOT / "templates" / "survey-report.md"

# 计划书第 8 节要求勘察报告覆盖的 10 项内容，对应渲染出的 10 个章节。
REQUIRED_SECTIONS = [
    "## 1. 输入清单与隐私检查",
    "## 2. 地点识别与用户确认",
    "## 3. 重建意图",
    "## 4. 场景元素拆解与空间层级",
    "## 5. 照片与外部数据的用途及覆盖范围",
    "## 6. 角度覆盖、缺失方向与补拍建议",
    "## 7. 不可见区域、遮挡与结构补全假设",
    "## 8. 外部服务、数据许可与上传提示",
    "## 9. 推荐重建路线、重点区域与验收门槛",
    "## 10. 阻塞项与待确认决策",
]


def load_survey():
    return json.loads((ROOT / "examples" / "minimal-survey.json").read_text(encoding="utf-8"))


class ReportCoverageTest(unittest.TestCase):
    """报告必须覆盖计划书第 8 节全部内容。"""

    def setUp(self):
        self.survey = load_survey()
        self.report = render_survey(self.survey)

    def test_all_required_sections_present(self):
        for section in REQUIRED_SECTIONS:
            self.assertIn(section, self.report)

    def test_next_step_present(self):
        self.assertIn("## 下一步", self.report)
        self.assertIn(self.survey["nextStep"], self.report)

    def test_summary_and_identity_present(self):
        self.assertIn("# 勘察报告：survey-example-001", self.report)
        self.assertIn(self.survey["summary"], self.report)
        self.assertIn("契约版本：1.0.0", self.report)

    def test_acceptance_gates_listed(self):
        for gate in [
            "灰模布局",
            "重点区域",
            "原图对照",
            "降级验收",
        ]:
            self.assertIn(gate, self.report)

    def test_blockers_and_questions_listed(self):
        blocker = self.survey["blockers"][0]
        self.assertIn(blocker["message"], self.report)
        self.assertIn(blocker["userAction"], self.report)
        self.assertIn(self.survey["userQuestions"][0], self.report)


class ReportSingleSourceTest(unittest.TestCase):
    """报告模板必须等于渲染结果，避免人读与机读两份结论手工维护。"""

    def test_example_report_matches_renderer_output(self):
        expected = render_survey_file(ROOT / "examples" / "minimal-survey.json")
        self.assertEqual(REPORT_PATH.read_text(encoding="utf-8"), expected)

    def test_render_is_deterministic(self):
        survey = load_survey()
        self.assertEqual(render_survey(survey), render_survey(copy.deepcopy(survey)))


class ReportBehaviourTest(unittest.TestCase):
    """渲染细节：置信度精度、表格转义、可选字段与授权提示。"""

    def test_confidence_has_one_decimal_place(self):
        survey = load_survey()
        survey["elements"][0]["confidence"] = 0.667
        self.assertIn("66.7%", render_survey(survey))

    def test_table_pipe_and_newline_are_escaped(self):
        survey = load_survey()
        survey["elements"][0]["name"] = "亭子|主体\n两层"
        report = render_survey(survey)
        self.assertIn("亭子\\|主体<br>两层", report)

    def test_photo_usage_is_optional(self):
        survey = load_survey()
        del survey["inputs"]["photoUsage"]
        report = render_survey(survey)
        self.assertIn("未记录逐张照片用途", report)

    def test_unauthorized_upload_is_flagged(self):
        survey = load_survey()
        survey["externalServices"] = [
            {
                "id": "svc_vlm",
                "type": "visual_model",
                "provider": "example-vlm",
                "uploadsUserPhotos": True,
                "authorized": False,
                "purpose": "识别建筑元素与材质。",
                "licenseNotes": "仅限本次勘察使用。",
            }
        ]
        report = render_survey(survey)
        self.assertIn("上传用户照片（需当次明确授权）", report)
        self.assertIn("存在会上传用户照片但尚未授权的服务", report)

    def test_invalid_survey_is_rejected(self):
        survey = load_survey()
        survey["elements"] = []
        with self.assertRaises(ValueError) as ctx:
            render_survey(survey)
        self.assertIn("survey.schema.json", str(ctx.exception))


class RegionSectionTest(unittest.TestCase):
    """区域清单章节：有 regions 时渲染，缺省时整节省略。"""

    def test_region_section_rendered(self):
        report = render_survey_file(ROOT / "examples" / "potala-survey.json")
        self.assertIn("## 4.2 照片区域与结构覆盖清单", report)
        self.assertIn("potala_lower_front", report)
        self.assertIn("挡墙（retaining_wall）", report)
        self.assertIn("coverage_check.py", report)

    def test_region_section_omitted_without_regions(self):
        report = render_survey(load_survey())
        self.assertNotIn("4.2 照片区域", report)

    def test_waiver_reason_rendered(self):
        survey = json.loads((ROOT / "examples" / "potala-survey.json").read_text(encoding="utf-8"))
        survey["regions"][1]["waiver"] = {"reason": "被树木遮挡"}
        self.assertIn("已豁免：被树木遮挡", render_survey(survey))


class ReportCliTest(unittest.TestCase):
    """命令行入口：输出文件、标准输出与失败返回码。"""

    def test_cli_writes_file(self):
        out = ROOT / "tests" / "__report__.md"
        try:
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(main([str(ROOT / "examples" / "minimal-survey.json"), "--out", str(out)]), 0)
            self.assertIn("[OK]", stdout.getvalue())
            self.assertEqual(out.read_text(encoding="utf-8"), REPORT_PATH.read_text(encoding="utf-8"))
        finally:
            out.unlink(missing_ok=True)

    def test_cli_prints_report_to_stdout(self):
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(main([str(ROOT / "examples" / "minimal-survey.json")]), 0)
        self.assertIn("# 勘察报告", stdout.getvalue())

    def test_cli_fails_invalid_document(self):
        bad = ROOT / "tests" / "__invalid_survey__.json"
        bad.write_text(json.dumps({"schemaVersion": "1.0.0"}, ensure_ascii=False), encoding="utf-8")
        try:
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(main([str(bad)]), 1)
            self.assertIn("[FAIL]", stderr.getvalue())
        finally:
            bad.unlink()


class PhotoUsageContractTest(unittest.TestCase):
    """photoUsage 字段的契约约束。"""

    def test_valid_photo_usage_passes(self):
        self.assertEqual(validate_document("survey", load_survey()), [])

    def test_photo_usage_requires_purpose(self):
        survey = load_survey()
        survey["inputs"]["photoUsage"] = [{"photoRef": "photo_01"}]
        errors = validate_document("survey", survey)
        self.assertTrue(any(error.startswith("inputs.photoUsage.0") for error in errors), errors)

    def test_photo_usage_rejects_unknown_field(self):
        survey = load_survey()
        survey["inputs"]["photoUsage"] = [{"photoRef": "photo_01", "purpose": "主视图", "purposeX": "额外"}]
        errors = validate_document("survey", survey)
        self.assertTrue(any(error.startswith("inputs.photoUsage.0") for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
