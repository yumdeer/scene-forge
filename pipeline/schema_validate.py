#!/usr/bin/env python3
"""校验 SceneForge 场景工程（scene）与勘察结果（survey）文档。

用法：
    python3 pipeline/schema_validate.py scene examples/minimal-scene.json
    python3 pipeline/schema_validate.py survey examples/minimal-survey.json

退出码：0 表示全部通过，1 表示存在校验错误，2 表示输入或环境错误。
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]

SCHEMA_PATHS = {
    "scene": ROOT / "schemas" / "scene.schema.json",
    "survey": ROOT / "schemas" / "survey.schema.json",
}


def load_schema(kind):
    """读取并解析指定类型的 Schema。"""
    path = SCHEMA_PATHS[kind]
    return json.loads(path.read_text(encoding="utf-8"))


def build_format_checker():
    """构造格式校验器，显式校验 RFC3339 date-time。

    jsonschema 的 date-time 检查依赖可选的 rfc3339-validator；缺省时不生效，
    因此这里注册一个最小实现，保证契约不因环境差异而放松。
    """
    checker = FormatChecker()

    @checker.checks("date-time", raises=(ValueError,))
    def is_rfc3339_datetime(value):
        if not isinstance(value, str):
            return True
        if "T" not in value:
            raise ValueError("date-time 缺少时间部分")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("date-time 缺少时区")
        return True

    return checker


def format_path(error):
    """把校验错误的路径转成可读形式。"""
    path = ".".join(str(part) for part in error.absolute_path)
    return path or "<root>"


def validate_document(kind, document):
    """校验文档，返回按路径排序的错误信息列表；空列表表示通过。"""
    validator = Draft202012Validator(load_schema(kind), format_checker=build_format_checker())
    errors = sorted(validator.iter_errors(document), key=lambda e: (list(e.absolute_path), e.message))
    return [f"{format_path(error)}: {error.message}" for error in errors]


def validate_file(kind, path):
    """读取并校验单个文件，返回错误信息列表。"""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"<file>: JSON 解析失败：{exc}"]
    except OSError as exc:
        return [f"<file>: 读取失败：{exc}"]
    return validate_document(kind, document)


def main(argv=None):
    parser = argparse.ArgumentParser(description="校验 SceneForge 的 scene / survey 文档")
    parser.add_argument("kind", choices=sorted(SCHEMA_PATHS), help="文档类型")
    parser.add_argument("files", nargs="+", help="待校验的 JSON 文件")
    args = parser.parse_args(argv)

    failed = False
    for file in args.files:
        errors = validate_file(args.kind, file)
        if errors:
            failed = True
            print(f"[FAIL] {file}")
            for message in errors:
                print(f"  - {message}")
        else:
            print(f"[OK]   {file}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
