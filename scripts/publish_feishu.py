#!/usr/bin/env python3
"""Preview or publish normalized content-monitor rows to the configured Feishu Base."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_BASE_TOKEN = os.getenv("CBM_FEISHU_BASE_TOKEN", "")
DEFAULT_TABLE_ID = os.getenv("CBM_FEISHU_CONTENT_TABLE_ID", "")
FIELD_ORDER = [
    "标题", "平台", "作品类型", "作品ID", "作品链接", "作者", "作者ID", "发布时间",
    "发现方式", "命中关键词", "点赞数", "收藏数", "评论数", "分享数", "播放量",
    "互动值", "相对表现R", "监控等级", "增长状态", "AI摘要", "爆款因素", "可复用选题",
    "分析置信度", "首次发现时间", "最后采集时间", "处理状态", "数据备注",
]


def cli(args: list[str]) -> dict[str, Any]:
    env_prefix = ["env", "LARKSUITE_CLI_NO_UPDATE_NOTIFIER=1", "LARKSUITE_CLI_NO_SKILLS_NOTIFIER=1"]
    completed = subprocess.run(env_prefix + ["lark-cli", *args], text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(message[:1000])
    return json.loads(completed.stdout)


def scalar_cell(value: Any) -> str:
    """Flatten common Base cell shapes used by text and select fields."""
    if value is None:
        return ""
    if isinstance(value, list):
        return scalar_cell(value[0]) if value else ""
    if isinstance(value, dict):
        for key in ("name", "text", "value", "url", "link"):
            if key in value:
                flattened = scalar_cell(value[key])
                if flattened:
                    return flattened
        return ""
    return str(value).strip()


def existing_records(base_token: str, table_id: str) -> dict[str, str]:
    found: dict[str, str] = {}
    offset = 0
    while True:
        result = cli([
            "base", "+record-list", "--as", "user", "--base-token", base_token,
            "--table-id", table_id, "--field-id", "作品ID", "--field-id", "平台",
            "--offset", str(offset), "--limit", "200", "--format", "json",
        ])
        payload = result.get("data", {})
        fields = payload.get("fields", [])
        rows = payload.get("data", [])
        record_ids = payload.get("record_id_list", [])
        for record_id, row in zip(record_ids, rows):
            mapped = dict(zip(fields, row)) if isinstance(row, list) else row
            post_id = scalar_cell(mapped.get("作品ID"))
            platform = scalar_cell(mapped.get("平台"))
            if post_id and platform:
                # Preserve the oldest record if historical duplicates already exist.
                found.setdefault(f"{platform}:{post_id}", record_id)
        if not payload.get("has_more"):
            break
        offset += len(rows)
        if not rows:
            break
    return found


def clean_row(row: dict[str, Any]) -> dict[str, Any]:
    return {field: row[field] for field in FIELD_ORDER if field in row and row[field] is not None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--base-token", default=DEFAULT_BASE_TOKEN, help="飞书 Base token；也可用 CBM_FEISHU_BASE_TOKEN")
    parser.add_argument("--table-id", default=DEFAULT_TABLE_ID, help="内容作品表 ID；也可用 CBM_FEISHU_CONTENT_TABLE_ID")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if not args.base_token or not args.table_id:
        parser.error("缺少 Base token 或内容表 ID；请传入参数或设置 CBM_FEISHU_* 环境变量")

    rows = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise SystemExit("Input must be a JSON array")
    valid = [clean_row(row) for row in rows if row.get("作品ID") and row.get("平台")]
    skipped = len(rows) - len(valid)
    if not args.write:
        print(json.dumps({"mode": "preview", "valid_rows": len(valid), "skipped": skipped, "base_token": args.base_token, "table_id": args.table_id}, ensure_ascii=False))
        return 0
    if not shutil.which("lark-cli"):
        raise SystemExit("lark-cli is required for --write")

    existing = existing_records(args.base_token, args.table_id)
    creates: list[dict[str, Any]] = []
    updates: list[tuple[str, dict[str, Any]]] = []
    for row in valid:
        key = f"{row['平台']}:{row['作品ID']}"
        if key in existing:
            updates.append((existing[key], row))
        else:
            creates.append(row)

    for record_id, row in updates:
        cli([
            "base", "+record-upsert", "--as", "user", "--base-token", args.base_token,
            "--table-id", args.table_id, "--record-id", record_id,
            "--json", json.dumps(row, ensure_ascii=False),
        ])

    for start in range(0, len(creates), 200):
        batch = creates[start : start + 200]
        fields = [field for field in FIELD_ORDER if any(field in row for row in batch)]
        payload = {"fields": fields, "rows": [[row.get(field) for field in fields] for row in batch]}
        cli([
            "base", "+record-batch-create", "--as", "user", "--base-token", args.base_token,
            "--table-id", args.table_id, "--json", json.dumps(payload, ensure_ascii=False),
        ])

    print(json.dumps({"created": len(creates), "updated": len(updates), "skipped": skipped}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Feishu publish failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
