"""把 survey.json 渲染为人读 Markdown 勘察报告。

勘察报告的唯一数据源是 survey.json；本模块只负责渲染，不引入
任何手工维护的结论，确保机读数据与人读报告始终一致。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.schema_validate import validate_document  # noqa: E402

STATUS_LABELS = {
    "ready": "可进入重建",
    "blocked": "存在阻塞项",
    "awaiting_user": "等待用户确认",
}

INTENT_LABELS = {
    "geolocation_first": ("真实地点优先", "以真实地理数据为准，照片只作为参考与校验。"),
    "photo_composition_first": ("照片构图优先", "以照片呈现的构图和透视关系为准，不追求真实地点还原。"),
    "style_reference": ("风格参考", "照片只提供风格与配色参考，几何按通用先验生成。"),
}

LOCATION_LABELS = {
    "confirmed": "已确认",
    "inferred": "推断",
    "unknown": "未识别",
    "not_applicable": "不适用",
    "notApplicable": "不适用",
}

CATEGORY_LABELS = {
    "building": "建筑",
    "building_cluster": "建筑群",
    "terrace": "台地",
    "stairs": "梯级",
    "retaining_wall": "挡墙",
    "terrain": "地形",
    "vegetation": "植被",
    "water": "水面",
    "sky": "天空",
    "road": "道路",
    "prop": "道具",
    "other": "其他",
}

LAYER_LABELS = {
    "near": "近景",
    "mid": "中景",
    "far": "远景",
    "dynamic": "动态",
}

METHOD_LABELS = {
    "photogrammetry": "摄影测量",
    "ai_3d": "AI 单物体生成",
    "parametric": "参数化建模",
    "geodata": "地理数据",
    "template": "模板匹配",
    "procedural": "程序化生成",
}

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

DECISION_LABELS = {
    "pending": "待确认",
    "confirmed": "已确认",
    "modify": "需修改",
    "reject": "已拒绝",
}

SEVERITY_LABELS = {
    "info": "提示",
    "warning": "警告",
    "blocking": "阻塞",
}

COVERAGE_MODE_LABELS = {
    "single_image": "单图",
    "multi_image": "多图",
}

OVERLAP_LABELS = {
    "unknown": "未知",
    "insufficient": "不足",
    "adequate": "足够",
    "excellent": "充分",
}

SERVICE_TYPE_LABELS = {
    "visual_model": "视觉模型",
    "ai_3d": "AI 3D 服务",
    "geodata": "地理数据",
    "reference": "参考资料",
}

# 计划书第 10 节的验收关卡，勘察报告必须把门槛提前摆给用户。
ACCEPTANCE_GATES = [
    "勘察确认：地点、元素、外部服务、隐私和重建意图。",
    "拆解确认：来源、置信度、假设、补全策略。",
    "灰模布局：比例、朝向、岸线、相机和元素关系。",
    "重点区域：用户指定高精度区域与可简化区域。",
    "原图对照：按形、位、色、缺四类反馈，每轮最多选 1~3 个优先项。",
    "降级验收：确定网页默认档、移动档和动态效果开关。",
]


def format_confidence(value):
    """置信度统一按百分比展示，保留一位小数。"""
    return f"{value * 100:.1f}%"


def _cell(value):
    """转义表格单元格：竖线、换行和反斜杠会破坏 Markdown 表格结构。"""
    text = "" if value is None else str(value)
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


def _table(headers, rows):
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_cell(cell) for cell in row) + " |")
    return "\n".join(lines)


def _bullets(items, empty="未提供。"):
    if not items:
        return f"- {empty}"
    return "\n".join(f"- {_cell(item)}" for item in items)


def _label(mapping, key, fallback=None):
    return mapping.get(key, fallback or key)


def _header(survey):
    return "\n".join(
        [
            f"# 勘察报告：{survey['surveyId']}",
            "",
            f"- 场景：{survey['sceneId']}",
            f"- 状态：{_label(STATUS_LABELS, survey['status'])}",
            f"- 生成时间：{survey['createdAt']}",
            f"- 契约版本：{survey['schemaVersion']}",
            "",
            survey["summary"],
        ]
    )


def _section_inputs(survey):
    inputs = survey["inputs"]
    lines = [
        "## 1. 输入清单与隐私检查",
        "",
        f"- 照片数量：{inputs['photoCount']}（可用 {inputs['usablePhotoCount']}）",
        f"- 多视角输入：{'是' if inputs['multiView'] else '否'}",
        "",
        "### 照片质量问题",
        "",
        _bullets(inputs["qualityIssues"], "未发现明显质量问题。"),
        "",
        "### 隐私提示",
        "",
        _bullets(inputs["privacyNotes"], "未记录隐私风险。"),
    ]
    return "\n".join(lines)


def _section_location(survey):
    location = survey["location"]
    name = location["name"] or "未提供"
    lines = [
        "## 2. 地点识别与用户确认",
        "",
        f"- 识别模式：{_label(LOCATION_LABELS, location['mode'])}",
        f"- 地点名称：{name}",
        f"- 置信度：{format_confidence(location['confidence'])}",
        f"- 用户已确认：{'是' if location['userConfirmed'] else '否'}",
        "",
        "### 识别证据",
        "",
        _bullets(location["evidence"], "无证据，按未知地点处理。"),
    ]
    if location["mode"] != "confirmed":
        lines += ["", "> 地点未经用户确认时，不得把推断地点写入公开数据或地理检索结果。"]
    return "\n".join(lines)


def _section_intent(survey):
    intent_name, intent_note = INTENT_LABELS[survey["intent"]]
    return "\n".join(
        [
            "## 3. 重建意图",
            "",
            f"- 意图：{intent_name}（{survey['intent']}）",
            f"- 含义：{intent_note}",
        ]
    )


def _section_elements(survey):
    rows = [
        [
            element["name"],
            element["id"],
            _label(CATEGORY_LABELS, element["category"]),
            _label(LAYER_LABELS, element["layer"]),
            _label(METHOD_LABELS, element["proposedMethod"]),
            format_confidence(element["confidence"]),
            "、".join(element["sourceRefs"]),
            _label(DECISION_LABELS, element["userDecision"]),
        ]
        for element in survey["elements"]
    ]
    return "\n".join(
        [
            "## 4. 场景元素拆解与空间层级",
            "",
            _table(["元素", "标识", "类别", "层级", "建议方法", "置信度", "来源", "用户决策"], rows),
        ]
    )


def _has_structure(element):
    """是否需要展示结构层级与测量依据。"""
    return any(
        key in element
        for key in ("parentId", "orderIndex", "measurements", "repetition")
    )


def _section_measurements(survey):
    """结构与测量章节：仅当勘察数据记录了层级、重复数量或测量依据时输出。"""
    rows = []
    for element in survey["elements"]:
        if not _has_structure(element):
            continue
        repetition = element.get("repetition")
        repetition_text = ""
        if repetition:
            repetition_text = f"{repetition['count']} 个"
            if repetition.get("spacingMeters"):
                repetition_text += f"，间距约 {repetition['spacingMeters']} 米"
            repetition_text += f"（{repetition['note']}）"
        measurements = element.get("measurements") or []
        measurement_text = "；".join(
            f"{item['label']} {item['value']}{item['unit']}"
            f"（{item['source']}{'，' + item['note'] if item.get('note') else ''}）"
            for item in measurements
        )
        rows.append(
            [
                element["name"],
                element.get("parentId", "—"),
                element.get("orderIndex", "—"),
                repetition_text or "—",
                measurement_text or "—",
            ]
        )

    if not rows:
        return ""
    return "\n".join(
        [
            "## 4.1 结构层级、重复数量与测量依据",
            "",
            _table(["元素", "父级", "序号", "重复数量", "测量依据"], rows),
        ]
    )


def _section_regions(survey):
    """区域与结构覆盖清单：覆盖门禁的输入，缺省时整节省略。"""
    regions = survey.get("regions") or []
    if not regions:
        return ""

    rows = []
    for region in regions:
        bbox = region["bbox"]
        bbox_text = (
            f"{bbox['x']},{bbox['y']},{bbox['width']},{bbox['height']}"
        )
        classes = "、".join(
            _label(STRUCTURE_CLASS_LABELS, item) + f"（{item}）"
            for item in region["structureClasses"]
        )
        note = region.get("note", "")
        waiver = region.get("waiver")
        if waiver:
            note = (note + " " if note else "") + f"已豁免：{waiver['reason']}"
        rows.append(
            [
                region["label"],
                region["id"],
                region["requiredStage"],
                bbox_text,
                classes,
                note or "—",
            ]
        )

    return "\n".join(
        [
            "## 4.2 照片区域与结构覆盖清单",
            "",
            "区域清单是覆盖门禁的输入：每个区域声明的结构类别，都必须在场景中有元素承接。",
            "",
            _table(["区域", "标识", "必需阶段", "区域框 (x,y,w,h)", "结构类别", "备注"], rows),
            "",
            "> 运行 `pipeline/coverage_check.py` 按本清单逐项对账；缺项即阻塞，不允许“看漏了”静默通过。",
        ]
    )


def _section_sources(survey):
    lines = ["## 5. 照片与外部数据的用途及覆盖范围", "", "### 照片用途", ""]
    usage = survey["inputs"].get("photoUsage") or []
    if usage:
        lines.append(
            _table(
                ["照片", "用途", "覆盖范围"],
                [[item["photoRef"], item["purpose"], item.get("coverageNote", "")] for item in usage],
            )
        )
    else:
        lines.append("未记录逐张照片用途，按统一参考图处理。")

    lines += ["", "### 外部数据用途", ""]
    if survey["externalServices"]:
        lines.append(
            _table(
                ["服务", "类型", "提供方", "用途"],
                [
                    [
                        service["id"],
                        _label(SERVICE_TYPE_LABELS, service["type"]),
                        service["provider"],
                        service["purpose"],
                    ]
                    for service in survey["externalServices"]
                ],
            )
        )
    else:
        lines.append("未使用外部数据服务。")
    return "\n".join(lines)


def _section_coverage(survey):
    coverage = survey["coverage"]
    lines = [
        "## 6. 角度覆盖、缺失方向与补拍建议",
        "",
        f"- 覆盖模式：{_label(COVERAGE_MODE_LABELS, coverage['mode'])}",
        f"- 估计覆盖角度：{coverage['estimatedDegrees']}°",
        f"- 重叠评估：{_label(OVERLAP_LABELS, coverage['overlapAssessment'])}",
        "",
        "### 已覆盖方向",
        "",
        _bullets(coverage["coveredSectors"], "未记录。"),
        "",
        "### 缺失方向",
        "",
        _bullets(coverage["missingSectors"], "未发现缺失方向。"),
        "",
        "### 补拍建议",
        "",
        _bullets(coverage["reshootInstructions"], "无需补拍。"),
    ]
    return "\n".join(lines)


def _section_assumptions(survey):
    lines = ["## 7. 不可见区域、遮挡与结构补全假设", "", "### 缺失方向", ""]
    coverage = survey["coverage"]
    lines.append(_bullets(coverage["missingSectors"], "未发现缺失方向。"))
    lines += ["", "### 结构补全假设", ""]

    has_assumptions = False
    for element in survey["elements"]:
        for assumption in element["assumptions"]:
            has_assumptions = True
            lines.append(f"- **{_cell(element['name'])}**：{_cell(assumption)}")
    if not has_assumptions:
        lines.append("- 未记录补全假设。")
    return "\n".join(lines)


def _section_services(survey):
    lines = ["## 8. 外部服务、数据许可与上传提示", ""]
    if not survey["externalServices"]:
        lines.append("本次勘察未规划外部服务，所有处理均可本地完成。")
        return "\n".join(lines)

    rows = []
    for service in survey["externalServices"]:
        upload = "上传用户照片（需当次明确授权）" if service["uploadsUserPhotos"] else "不上传用户照片"
        rows.append(
            [
                service["id"],
                _label(SERVICE_TYPE_LABELS, service["type"]),
                service["provider"],
                upload,
                "已授权" if service["authorized"] else "未授权",
                service["purpose"],
                service["licenseNotes"] or "未记录许可说明",
            ]
        )
    lines.append(
        _table(["服务", "类型", "提供方", "照片上传", "授权", "用途", "许可说明"], rows)
    )
    if any(service["uploadsUserPhotos"] and not service["authorized"] for service in survey["externalServices"]):
        lines += ["", "> 存在会上传用户照片但尚未授权的服务，必须获得用户当次同意后才能调用。"]
    return "\n".join(lines)


def _section_recommendations(survey):
    lines = [
        "## 9. 推荐重建路线、重点区域与验收门槛",
        "",
        "### 推荐路线",
        "",
        _bullets(survey["recommendations"], "未提供推荐路线。"),
        "",
        "### 重点区域",
        "",
        "由用户在灰模确认阶段指定高精度区域与可简化区域，勘察阶段不预设。",
        "",
        "### 验收门槛",
        "",
    ]
    lines += [f"{index}. {gate}" for index, gate in enumerate(ACCEPTANCE_GATES, start=1)]
    return "\n".join(lines)


def _section_blockers(survey):
    lines = ["## 10. 阻塞项与待确认决策", ""]
    if survey["blockers"]:
        lines.append(
            _table(
                ["标识", "级别", "说明", "需要用户动作"],
                [
                    [
                        blocker["id"],
                        _label(SEVERITY_LABELS, blocker["severity"]),
                        blocker["message"],
                        blocker["userAction"],
                    ]
                    for blocker in survey["blockers"]
                ],
            )
        )
    else:
        lines.append("无阻塞项。")

    lines += ["", "### 需要用户确认的问题", ""]
    lines.append(_bullets(survey["userQuestions"], "本轮无需用户决策。"))
    lines += ["", "## 下一步", "", survey["nextStep"]]
    return "\n".join(lines)


def render_survey(survey, validate=True):
    """把勘察数据渲染为 Markdown 文本；默认先校验契约。"""
    if validate:
        errors = validate_document("survey", survey)
        if errors:
            raise ValueError("勘察数据不符合 survey.schema.json：\n" + "\n".join(f"- {e}" for e in errors))

    sections = [
        _header(survey),
        _section_inputs(survey),
        _section_location(survey),
        _section_intent(survey),
        _section_elements(survey),
        _section_measurements(survey),
        _section_regions(survey),
        _section_sources(survey),
        _section_coverage(survey),
        _section_assumptions(survey),
        _section_services(survey),
        _section_recommendations(survey),
        _section_blockers(survey),
    ]
    return "\n\n".join(section for section in sections if section).rstrip() + "\n"


def render_survey_file(path):
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    return render_survey(document)


def main(argv=None):
    parser = argparse.ArgumentParser(description="把 survey.json 渲染为 Markdown 勘察报告")
    parser.add_argument("survey", help="survey.json 路径")
    parser.add_argument("--out", help="输出 Markdown 路径；省略时打印到标准输出")
    args = parser.parse_args(argv)

    try:
        report = render_survey_file(args.survey)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[FAIL] {args.survey}: {exc}", file=sys.stderr)
        return 1

    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"[OK]   {args.out}")
    else:
        sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
