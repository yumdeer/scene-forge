"""体量参数展开测试：repeat 的数量、坐标与命名必须可从契约定量核对。

生成器不再保存几何常量，因此“契约里写了 5 级台地”必须等价于
“实际生成 5 个台阶体块”，这正是本轮修复灰模漏掉台阶的关键。
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.massing_params import expand_boxes, expand_prisms  # noqa: E402

BOX = {"x0": -1, "x1": 1, "y0": -2, "y1": 2, "z0": 0, "z1": 4}


def scene_document():
    return json.loads(
        (ROOT / "scenes" / "potala-palace-lhasa" / "scene.json").read_text(encoding="utf-8")
    )


class ExpandBoxesTest(unittest.TestCase):
    """boxes 原样返回，repeat 逐份展开。"""

    def test_plain_boxes_passthrough(self):
        parameters = {"boxes": [{"name": "main", **BOX}]}
        boxes = expand_boxes(parameters)
        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0]["name"], "main")
        for key, value in BOX.items():
            self.assertEqual(boxes[0][key], value)

    def test_repeat_expands_count_names_and_coordinates(self):
        parameters = {
            "repeat": [
                {
                    "namePattern": "terrace_{i:02d}",
                    "box": dict(BOX),
                    "count": 3,
                    "step": {"x": -10, "y": -18, "z": -11.1},
                }
            ]
        }
        boxes = expand_boxes(parameters)
        self.assertEqual(len(boxes), 3)
        self.assertEqual([box["name"] for box in boxes], ["terrace_01", "terrace_02", "terrace_03"])
        for offset, box in enumerate(boxes):
            self.assertEqual(box["x0"], BOX["x0"] - 10 * offset)
            self.assertEqual(box["x1"], BOX["x1"] - 10 * offset)
            self.assertEqual(box["y0"], BOX["y0"] - 18 * offset)
            self.assertEqual(box["y1"], BOX["y1"] - 18 * offset)
            self.assertAlmostEqual(box["z0"], BOX["z0"] - 11.1 * offset)
            self.assertAlmostEqual(box["z1"], BOX["z1"] - 11.1 * offset)

    def test_repeat_preserves_shear_parameters(self):
        parameters = {
            "repeat": [
                {
                    "namePattern": "window_{i:02d}",
                    "box": {**BOX, "slopeZPerX": -0.1, "xRef": 12.0},
                    "count": 2,
                    "step": {"x": 6.0},
                }
            ]
        }
        boxes = expand_boxes(parameters)
        for box in boxes:
            self.assertEqual(box["slopeZPerX"], -0.1)
            self.assertEqual(box["xRef"], 12.0)

    def test_repeat_without_step_keeps_same_coordinates(self):
        parameters = {
            "repeat": [{"namePattern": "roof_{i:02d}", "box": dict(BOX), "count": 2}]
        }
        boxes = expand_boxes(parameters)
        self.assertEqual(len(boxes), 2)
        self.assertEqual([box["name"] for box in boxes], ["roof_01", "roof_02"])
        for box in boxes:
            for key, value in BOX.items():
                self.assertEqual(box[key], value)

    def test_boxes_and_repeat_are_merged_in_order(self):
        parameters = {
            "boxes": [{"name": "base", **BOX}],
            "repeat": [{"namePattern": "step_{i:02d}", "box": dict(BOX), "count": 2}],
        }
        names = [box["name"] for box in expand_boxes(parameters)]
        self.assertEqual(names, ["base", "step_01", "step_02"])

    def test_missing_boxes_and_repeat_returns_empty(self):
        self.assertEqual(expand_boxes({}), [])

    def test_missing_name_pattern_rejected(self):
        with self.assertRaises(ValueError):
            expand_boxes({"repeat": [{"box": dict(BOX), "count": 2}]})

    def test_repeat_count_must_be_positive_integer(self):
        for bad_count in (0, -1, 1.5, "3"):
            with self.subTest(count=bad_count):
                with self.assertRaises(ValueError):
                    expand_boxes(
                        {
                            "repeat": [
                                {"namePattern": "item_{i:02d}", "box": dict(BOX), "count": bad_count}
                            ]
                        }
                    )

    def test_repeat_missing_geometry_key(self):
        box = dict(BOX)
        del box["z1"]
        with self.assertRaises(ValueError):
            expand_boxes({"repeat": [{"namePattern": "item_{i:02d}", "box": box, "count": 2}]})

    def test_repeat_unknown_step_axis(self):
        with self.assertRaises(ValueError):
            expand_boxes(
                {
                    "repeat": [
                        {
                            "namePattern": "item_{i:02d}",
                            "box": dict(BOX),
                            "count": 2,
                            "step": {"w": 3},
                        }
                    ]
                }
            )


class ExpandPrismsTest(unittest.TestCase):
    """坡面棱柱：profile 为 YZ 多边形，沿 X 拉伸。"""

    def test_prism_passthrough(self):
        prism = {
            "name": "hill_front_slope",
            "x0": -260,
            "x1": 330,
            "profile": [[-165, -110], [-55, -42], [-55, -110]],
        }
        prisms = expand_prisms({"prisms": [prism]})
        self.assertEqual(len(prisms), 1)
        self.assertEqual(prisms[0]["name"], "hill_front_slope")
        self.assertEqual(prisms[0]["profile"], prism["profile"])

    def test_prism_missing_name_rejected(self):
        with self.assertRaises(ValueError):
            expand_prisms({"prisms": [{"x0": 0, "x1": 1, "profile": [[0, 0], [0, 1], [1, 1]]}]})

    def test_prism_profile_needs_three_points(self):
        with self.assertRaises(ValueError):
            expand_prisms({"prisms": [{"name": "bad", "x0": 0, "x1": 1, "profile": [[0, 0], [1, 1]]}]})


class PotalaSceneParameterTest(unittest.TestCase):
    """布达拉宫场景的参数展开结果必须与勘察中的结构数量一致。"""

    def test_potala_scene_expands_to_recorded_counts(self):
        doc = scene_document()
        boxes_count = {}
        prisms_count = {}
        for element in doc["elements"]:
            generator = element.get("reconstruction", {}).get("generator")
            if not generator:
                continue
            parameters = generator.get("parameters") or {}
            boxes_count[element["id"]] = len(expand_boxes(parameters))
            prisms_count[element["id"]] = len(expand_prisms(parameters))

        # 山坡按 30m 分段细分（22 段），保证东西向 10% 坡度不出现大台阶
        self.assertEqual(prisms_count["potala_hill"], 22)
        self.assertEqual(boxes_count["potala_terraces"], 5)
        self.assertEqual(boxes_count["stair_path"], 3)
        self.assertEqual(boxes_count["ancillary_compound"], 6)
        # 金顶改为三棱柱坡屋顶，不再用盒子
        self.assertEqual(prisms_count["golden_roofs"], 7)
        self.assertEqual(boxes_count["golden_roofs"], 0)
        # 白宫：四段收分白墙棱柱 + 五段上部体块 + 西塔
        self.assertEqual(prisms_count["white_palace"], 6)
        self.assertEqual(boxes_count["white_palace"], 6)
        # 檐口棕色横带：四段白墙顶 + 六段白宫檐口（西塔处断开）+ 红宫顶 + 西塔顶
        self.assertEqual(boxes_count["potala_eaves"], 12)
        self.assertEqual(boxes_count["red_palace"], 1)

        # 白墙细节：四段 × 四排 × 14 孔窗洞，每排上方一道窗楣带
        self.assertEqual(boxes_count["white_palace_windows"], 224)
        self.assertEqual(boxes_count["white_palace_window_bands"], 16)
        # 白宫上部五段体块各两排窗洞 + 对应窗楣带
        self.assertEqual(boxes_count["white_palace_upper_windows"], 74)
        self.assertEqual(boxes_count["white_palace_upper_bands"], 10)
        # 前坡台地、之字台阶、坡下僧舍房群
        self.assertEqual(boxes_count["front_terraces"], 4)
        self.assertEqual(boxes_count["terrace_parapets"], 4)
        self.assertEqual(boxes_count["grand_stair"], 18)
        self.assertEqual(boxes_count["stair_rails"], 18)
        self.assertEqual(boxes_count["monk_quarters"], 8)
        self.assertEqual(boxes_count["monk_quarter_eaves"], 8)
        self.assertEqual(boxes_count["monk_quarter_windows"], 8)
        self.assertEqual(boxes_count["monk_quarter_roofs"], 4)
        # 中层僧舍房群
        self.assertEqual(boxes_count["monk_quarters_upper"], 5)
        self.assertEqual(boxes_count["monk_upper_eaves"], 5)
        self.assertEqual(boxes_count["monk_upper_windows"], 5)
        self.assertEqual(boxes_count["monk_upper_roofs"], 3)


if __name__ == "__main__":
    unittest.main()
