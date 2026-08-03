#!/usr/bin/env python3
"""Merge agent-produced AI analysis into Feishu rows and the monitoring report."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


START_MARKER = "<!-- CBM_AI_ANALYSIS_START -->"
END_MARKER = "<!-- CBM_AI_ANALYSIS_END -->"
REQUIRED_FIELDS = {
    "platform", "post_id", "fact_evidence", "inferred_structure",
    "boom_factors", "reusable_elements", "non_reusable_context",
    "reusable_topic", "confidence", "missing_evidence",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def platform_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"xiaohongshu", "小红书"}:
        return "xiaohongshu"
    if text in {"douyin", "抖音"}:
        return "douyin"
    return text


def clean_prefix(value: Any, prefixes: tuple[str, ...]) -> str:
    text = str(value or "").strip()
    for prefix in prefixes:
        if text.startswith(prefix):
            return text[len(prefix):].strip(" ：:")
    return text


def text_list(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def validate_analysis(
    payload: Any,
    allowed: set[tuple[str, str]],
    max_items: int,
) -> list[dict[str, Any]]:
    analyses = payload.get("analyses") if isinstance(payload, dict) else payload
    if not isinstance(analyses, list):
        raise ValueError("analysis JSON must be a list or an object containing analyses")
    if len(analyses) > max_items:
        raise ValueError(f"analysis contains {len(analyses)} items; max_items is {max_items}")

    valid: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(analyses, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"analysis item {index} must be an object")
        missing = REQUIRED_FIELDS - set(item)
        if missing:
            raise ValueError(f"analysis item {index} missing fields: {', '.join(sorted(missing))}")
        key = (platform_key(item["platform"]), str(item["post_id"]).strip())
        if key not in allowed:
            raise ValueError(f"analysis item {index} is not in analysis_candidates: {key}")
        if key in seen:
            raise ValueError(f"duplicate analysis item: {key}")
        confidence = float(item["confidence"])
        if not 0 <= confidence <= 1:
            raise ValueError(f"confidence must be between 0 and 1: {key}")
        item = dict(item)
        item["_key"] = key
        item["confidence"] = round(confidence, 2)
        valid.append(item)
        seen.add(key)
    return valid


def report_section(analyses: list[dict[str, Any]], candidate_map: dict[tuple[str, str], dict[str, Any]]) -> str:
    lines = [START_MARKER, "", f"## Top {len(analyses)} AI 辅助拆解", ""]
    topics: list[str] = []
    for index, item in enumerate(analyses, start=1):
        candidate = candidate_map[item["_key"]]
        title = str(candidate.get("title") or candidate.get("post_id") or "未命名作品").replace("\n", " ")
        url = candidate.get("post_url") or ""
        topics.append(str(item["reusable_topic"]).strip())
        lines.extend([
            f"### {index}. [{title}]({url})",
            "",
            f"- 事实证据：{clean_prefix(item['fact_evidence'], ('事实证据', '事实'))}",
            f"- 推断结构：{clean_prefix(item['inferred_structure'], ('推断结构', '推断'))}",
            f"- 爆款因素：{text_list(item['boom_factors'])}",
            f"- 可复用元素：{text_list(item['reusable_elements'])}",
            f"- 不可复用背景：{text_list(item['non_reusable_context'])}",
            f"- 可复用选题：{item['reusable_topic']}",
            f"- 置信度：{item['confidence']:.2f}",
            f"- 缺失证据：{text_list(item['missing_evidence'])}",
            "",
        ])
    if topics:
        lines.extend(["## 优先选题建议", ""])
        lines.extend(f"{index}. {topic}" for index, topic in enumerate(topics, start=1))
        lines.append("")
    lines.append(END_MARKER)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    candidate_payload = read_json(args.candidates)
    candidates = candidate_payload.get("candidates", [])
    max_items = int(candidate_payload.get("max_items", 5))
    candidate_map = {
        (platform_key(item.get("platform")), str(item.get("post_id", "")).strip()): item
        for item in candidates
        if item.get("post_id")
    }
    analyses = validate_analysis(read_json(args.analysis), set(candidate_map), max_items)

    rows = read_json(args.rows)
    if not isinstance(rows, list):
        raise ValueError("rows JSON must be a list")
    analysis_map = {item["_key"]: item for item in analyses}
    updated = 0
    for row in rows:
        key = (platform_key(row.get("平台")), str(row.get("作品ID", "")).strip())
        item = analysis_map.get(key)
        if not item:
            continue
        fact = clean_prefix(item["fact_evidence"], ("事实证据", "事实"))
        inference = clean_prefix(item["inferred_structure"], ("推断结构", "推断"))
        row["AI摘要"] = f"事实：{fact} 推断：{inference}"
        row["爆款因素"] = text_list(item["boom_factors"])
        row["可复用选题"] = str(item["reusable_topic"]).strip()
        row["分析置信度"] = item["confidence"]
        updated += 1
    if updated != len(analyses):
        raise ValueError(f"only matched {updated} of {len(analyses)} analyses to Feishu rows")
    write_json(args.rows, rows)

    report = args.report.read_text(encoding="utf-8")
    report = re.sub(
        re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER) + r"\n?",
        "",
        report,
        flags=re.DOTALL,
    ).rstrip() + "\n\n"
    args.report.write_text(report + report_section(analyses, candidate_map), encoding="utf-8")
    print(json.dumps({"analyzed": len(analyses), "rows_updated": updated}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

