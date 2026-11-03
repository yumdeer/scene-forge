"""结构层级与测量字段（parentId/orderIndex/measurements/repetition）契约测试。

阶段 1 增补的结构契约必须满足两点：
1. 合法结构条目通过校验，供勘察与生成器逐级引用；
2. 非法单位、来源、重复数量、父级命名必须被拒绝，防止“数不清的台阶”再次漏检。
"""

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.schema_validate import validate_document, validate_file  # noqa: E402


def load_example(name):
    return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))


def load_scene():
    return load_example("minimal-scene.json")


class StructurePositiveTest(unittest.TestCase):
    """合法结构条目必须通过校验。"""

    def test_measurements_and_repetition_accepted(self):
        scene = load_scene()
        element = scene["elements"][0]
        element["parentId"] = "pavilion_base"
        element["orderIndex"] = 0
        element["measurements"] = [
            {
                "id": "facade_width",
                "label": "立面可见宽度",
                "value": 640,
                "unit": "px",
                "source": "measured",
                "photoRef": "photo_01",
            },
            {
                "id": "eave_height",
                "label": "檐口高度",
                "value": 2.8,
                "unit": "m",
                "source": "derived",
                "note": "按檐口线与柱高先验折算",
            },
        ]
        element["repetition"] = {
            "count": 4,
            "axis": "x",
            "spacingMeters": 2.5,
            "note": "四根檐柱沿东西向等距排布",
        }
        self.assertEqual(validate_document("scene", scene), [])

    def test_new_structure_categories_accepted(self):
        for category in ("building_cluster", "terrace", "stairs", "retaining_wall"):
            with self.subTest(category=category):
                scene = load_scene()
                scene["elements"][0]["category"] = category
                self.assertEqual(validate_document("scene", scene), [])

    def test_potala_scene_is_valid(self):
        path = ROOT / "scenes" / "potala-palace-lhasa" / "scene.json"
        if not path.exists():
            self.skipTest("布达拉宫场景文件不存在")
        self.assertEqual(validate_file("scene", path), [])


class StructureNegativeTest(unittest.TestCase):
    """非法结构条目必须被拒绝。"""

    def setUp(self):
        self.scene = load_scene()
        self.element = self.scene["elements"][0]
        self.element["measurements"] = [
            {
                "id": "facade_width",
                "label": "立面可见宽度",
                "value": 640,
                "unit": "px",
                "source": "measured",
                "photoRef": "photo_01",
            }
        ]
        self.element["repetition"] = {
            "count": 4,
            "axis": "x",
            "spacingMeters": 2.5,
            "note": "四根檐柱沿东西向等距排布",
        }

    def assert_rejected(self, document, expected_path):
        errors = validate_document("scene", document)
        self.assertTrue(errors, "非法文档不应通过校验")
        self.assertTrue(
            any(error.startswith(expected_path) for error in errors),
            f"期望在 {expected_path} 报错，实际：{errors}",
        )

    def test_measurement_unit_outside_enum(self):
        self.element["measurements"][0]["unit"] = "cm"
        self.assert_rejected(self.scene, "elements.0.measurements.0.unit")

    def test_measurement_source_outside_enum(self):
        self.element["measurements"][0]["source"] = "guess"
        self.assert_rejected(self.scene, "elements.0.measurements.0.source")

    def test_measurement_id_pattern(self):
        self.element["measurements"][0]["id"] = "Facade-Width"
        self.assert_rejected(self.scene, "elements.0.measurements.0.id")

    def test_measurement_missing_required_field(self):
        del self.element["measurements"][0]["label"]
        self.assert_rejected(self.scene, "elements.0.measurements.0")

    def test_measurement_unknown_field_rejected(self):
        self.element["measurements"][0]["confidence"] = 0.4
        self.assert_rejected(self.scene, "elements.0.measurements.0")

    def test_repetition_count_must_be_at_least_two(self):
        self.element["repetition"]["count"] = 1
        self.assert_rejected(self.scene, "elements.0.repetition.count")

    def test_repetition_axis_outside_enum(self):
        self.element["repetition"]["axis"] = "diagonal"
        self.assert_rejected(self.scene, "elements.0.repetition.axis")

    def test_repetition_missing_note(self):
        del self.element["repetition"]["note"]
        self.assert_rejected(self.scene, "elements.0.repetition")

    def test_order_index_must_be_non_negative(self):
        self.element["orderIndex"] = -1
        self.assert_rejected(self.scene, "elements.0.orderIndex")

    def test_parent_id_pattern(self):
        self.element["parentId"] = "Pavilion_Base"
        self.assert_rejected(self.scene, "elements.0.parentId")


if __name__ == "__main__":
    unittest.main()
