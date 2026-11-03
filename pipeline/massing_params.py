"""体量参数展开：把契约中的 boxes / prisms / repeat 展开成几何指令。

本模块不依赖 bpy，Blender 生成器与单元测试共用同一套展开逻辑，
保证“契约里的结构参数”与“实际生成的体块数量”不会脱节。
"""

from __future__ import annotations

GEOMETRY_KEYS = ("x0", "x1", "y0", "y1", "z0", "z1")
BOX_KEYS = ("name",) + GEOMETRY_KEYS
STEP_KEYS = ("x", "y", "z")


def _check_box(box, context, require_name=True):
    keys = BOX_KEYS if require_name else GEOMETRY_KEYS
    missing = [key for key in keys if key not in box]
    if missing:
        raise ValueError(f"{context} 缺少字段：{', '.join(missing)}")


def _expand_repeat(repeat, index):
    pattern = repeat.get("namePattern")
    if not pattern:
        raise ValueError(f"repeat[{index}] 缺少 namePattern")
    count = repeat.get("count")
    if not isinstance(count, int) or count < 1:
        raise ValueError(f"repeat[{index}] 的 count 必须是正整数")
    box = repeat.get("box")
    if not isinstance(box, dict):
        raise ValueError(f"repeat[{index}] 缺少 box")
    _check_box(box, f"repeat[{index}].box", require_name=False)
    step = repeat.get("step") or {}
    unknown = [key for key in step if key not in STEP_KEYS]
    if unknown:
        raise ValueError(f"repeat[{index}] 的 step 含未知维度：{', '.join(unknown)}")

    # 除几何键外的附加参数（slopeZPerX / xRef 等）必须随 repeat 一起复制，
    # 否则窗洞、檐带等阵列会脱离随坡剪切的墙面，出现漂浮或穿插。
    extras = {key: value for key, value in box.items() if key not in GEOMETRY_KEYS}

    boxes = []
    for offset in range(count):
        dx = step.get("x", 0) * offset
        dy = step.get("y", 0) * offset
        dz = step.get("z", 0) * offset
        boxes.append(
            {
                "name": pattern.format(i=offset + 1),
                "x0": box["x0"] + dx,
                "x1": box["x1"] + dx,
                "y0": box["y0"] + dy,
                "y1": box["y1"] + dy,
                "z0": box["z0"] + dz,
                "z1": box["z1"] + dz,
                **extras,
            }
        )
    return boxes


def expand_boxes(parameters):
    """返回展开后的 box 列表；repeat 按 step 逐份复制。"""
    boxes = []
    for index, box in enumerate(parameters.get("boxes") or []):
        _check_box(box, f"boxes[{index}]")
        boxes.append(dict(box))
    for index, repeat in enumerate(parameters.get("repeat") or []):
        boxes.extend(_expand_repeat(repeat, index))
    return boxes


def expand_prisms(parameters):
    """返回 prism 列表；profile 为 YZ 平面多边形，沿 X 拉伸。"""
    prisms = []
    for index, prism in enumerate(parameters.get("prisms") or []):
        for key in ("name", "x0", "x1", "profile"):
            if key not in prism:
                raise ValueError(f"prisms[{index}] 缺少字段：{key}")
        profile = prism["profile"]
        if len(profile) < 3:
            raise ValueError(f"prisms[{index}] 的 profile 至少需要 3 个点")
        prisms.append(dict(prism))
    return prisms
