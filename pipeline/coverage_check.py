#!/usr/bin/env python3
"""覆盖门禁：照片区域清单 -> 结构类别 -> 场景元素。

背景：
    schema 校验与单元测试只能证明“文档自身自洽”，无法回答
    “照片里明明看得到的结构，场景里到底建没建”。这个缺口导致
    只能靠人眼逐块比对，红框前景的台地/挡墙/梯级/僧舍就是这样漏掉的。

本模块把漏项变成可执行门禁，做三方对账：
    survey.regions[].structureClasses  照片区域承诺要建什么
    scene.elements[].structureClasses  场景实际建了什么
    scene.elements[].photoRegions      建在哪个区域的对应位置

判定规则：
    1. 任一区域声明的结构类别，若没有任何元素“同时”声明该类别并引用该区域，
       即为缺口；有缺口则退出码 1（除非该区域显式写明 waiver.reason）。
    2. 元素引用的区域 ID 必须在 survey.regions 中存在，否则视为契约漂移。
    3. 勘察未定义区域清单时门禁无法执行，默认按失败处理，
       避免“没有清单所以全部通过”的静默放行。

用法：
    python3 pipeline/coverage_check.py \
        --survey examples/potala-survey.json \
        --scene scenes/potala-palace-lhasa/scene.json

    # 报告默认写到场景目录下的 derived/coverage-report.json
    python3 pipeline/coverage_check.py --survey ... --scene ... --out /tmp/c.json

退出码：0 通过，1 存在缺口或契约漂移，2 输入/环境错误。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

STRUCTURE_CLASSES = (
    "terrain", "massing_volume", "white_wall", "window_band", "eave_band",
    "terrace", "retaining_wall", "stairs", "building_cluster", "roof_cluster",
    "vegetation", "road", "water", "prop", "other",
)

STRUCTURE_CLASS_LABELS = {
    "terrain": "地形",
    "massing_volume": "体量",
    "white_wall": "白墙",
    "window_band": "窗带/窗洞",
    "eave_band": "檐带/窗楣带",
    "terrace": "台地",
    "retaining_wall": "挡墙",
    "stairs": "梯级",
    "building_cluster": "房群",
    "roof_cluster": "屋顶群",
    "vegetation": "植被",
    "road": "道路",
    "water": "水面",
    "prop": "道具",
    "other": "其他",
}


def load_json(path):
    """读取 JSON，失败时抛出可读异常。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_coverage(survey, scene, allow_empty_regions=False):
    """执行覆盖对账，返回 (errors, report)。

    errors 为人类可读的缺口/漂移列表，空列表表示通过；
    report 为写入 coverage-report.json 的机读结果。
    """
    errors = []
    regions = survey.get("regions") or []
    elements = scene.get("elements") or []

    if not regions and not allow_empty_regions:
        errors.append(
            "勘察缺少 regions 区域清单：覆盖门禁无法执行；"
            "请先在 survey.json 中声明照片区域与结构类别（或用 --allow-empty-regions 显式跳过）。"
        )

    region_ids = {}
    for index, region in enumerate(regions):
        region_id = region.get("id")
        if region_id in region_ids:
            errors.append(f"区域 ID 重复：{region_id}（regions.{region_ids[region_id]} 与 regions.{index}）")
        else:
            region_ids[region_id] = index
        unknown = [c for c in region.get("structureClasses") or [] if c not in STRUCTURE_CLASSES]
        if unknown:
            errors.append(f"区域 {region_id} 声明了未知结构类别：{', '.join(unknown)}")

    # 元素侧：类别合法性 + 区域引用是否存在
    unknown_region_refs = []
    for element in elements:
        element_id = element.get("id", "<unknown>")
        unknown = [c for c in element.get("structureClasses") or [] if c not in STRUCTURE_CLASSES]
        if unknown:
            errors.append(f"元素 {element_id} 声明了未知结构类别：{', '.join(unknown)}")
        for region_id in element.get("photoRegions") or []:
            if region_id not in region_ids:
                unknown_region_refs.append({"elementId": element_id, "regionId": region_id})
                errors.append(f"元素 {element_id} 引用了不存在的区域：{region_id}")

    region_reports = []
    declared_pairs = covered_pairs = missing_pairs = waived_regions = 0

    for region in regions:
        region_id = region.get("id")
        waiver = region.get("waiver")
        waived = bool(waiver and waiver.get("reason"))
        if waived:
            waived_regions += 1

        referenced = [e for e in elements if region_id in (e.get("photoRegions") or [])]
        coverage = {}
        missing = []
        for structure_class in region.get("structureClasses") or []:
            declared_pairs += 1
            covering = [
                e.get("id") for e in referenced
                if structure_class in (e.get("structureClasses") or [])
            ]
            coverage[structure_class] = covering
            if covering:
                covered_pairs += 1
            else:
                missing.append(structure_class)
                missing_pairs += 1
                if not waived:
                    label = STRUCTURE_CLASS_LABELS.get(structure_class, structure_class)
                    errors.append(
                        f"区域 {region_id}（{region.get('label', '')}）缺少结构类别 {structure_class}"
                        f"（{label}）：没有任何声明该类别且引用该区域的元素"
                    )

        if not referenced and not waived:
            errors.append(f"区域 {region_id} 没有任何场景元素引用，区域未被承接")

        region_reports.append(
            {
                "id": region_id,
                "label": region.get("label"),
                "requiredStage": region.get("requiredStage"),
                "bbox": region.get("bbox"),
                "structureClasses": region.get("structureClasses") or [],
                "coverage": coverage,
                "missingClasses": missing,
                "waived": waived,
                "waiverReason": (waiver or {}).get("reason"),
                "referencedElementCount": len(referenced),
            }
        )

    report = {
        "ok": not errors,
        "summary": {
            "regionCount": len(regions),
            "elementCount": len(elements),
            "declaredPairs": declared_pairs,
            "coveredPairs": covered_pairs,
            "missingPairs": missing_pairs,
            "waivedRegionCount": waived_regions,
        },
        "regions": region_reports,
        "unknownRegionRefs": unknown_region_refs,
        "errors": errors,
    }
    return errors, report


def default_report_path(scene_path):
    """报告默认写到场景目录下的 derived/，与既有派生产物同处。"""
    return Path(scene_path).resolve().parent / "derived" / "coverage-report.json"


def write_report(report, path):
    """写机读报告，自动创建父目录。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def format_summary(report, errors):
    """把门禁结果渲染成终端可读文本。"""
    summary = report["summary"]
    if not errors:
        return (
            f"[OK]   覆盖门禁通过：区域 {summary['regionCount']} 个，"
            f"结构类别对账 {summary['coveredPairs']}/{summary['declaredPairs']}"
        )
    lines = [
        f"[FAIL] 覆盖门禁未通过：区域 {summary['regionCount']} 个，"
        f"结构类别对账 {summary['coveredPairs']}/{summary['declaredPairs']}"
    ]
    lines += [f"  - {error}" for error in errors]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="照片区域 -> 结构类别的覆盖门禁")
    parser.add_argument("--survey", required=True, help="survey.json 路径")
    parser.add_argument("--scene", required=True, help="scene.json 路径")
    parser.add_argument("--out", help="coverage-report.json 输出路径；省略时写到场景目录的 derived/")
    parser.add_argument(
        "--allow-empty-regions",
        action="store_true",
        help="允许勘察未定义区域清单（此时门禁不产生约束，仅用于最小示例）",
    )
    args = parser.parse_args(argv)

    try:
        survey = load_json(args.survey)
        scene = load_json(args.scene)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[FAIL] 读取输入失败：{exc}", file=sys.stderr)
        return 2

    errors, report = check_coverage(
        survey, scene, allow_empty_regions=args.allow_empty_regions
    )
    out = Path(args.out) if args.out else default_report_path(args.scene)
    try:
        write_report(report, out)
    except OSError as exc:
        print(f"[FAIL] 写入报告失败：{exc}", file=sys.stderr)
        return 2

    print(format_summary(report, errors))
    print(f"       报告：{out}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
