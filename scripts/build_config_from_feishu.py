#!/usr/bin/env python3
"""Build a small monitor config from the Feishu input tables."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


DEFAULT_BASE_TOKEN = os.getenv("CBM_FEISHU_BASE_TOKEN", "")
DEFAULT_KEYWORD_TABLE = os.getenv("CBM_FEISHU_KEYWORD_TABLE_ID", "")
DEFAULT_ACCOUNT_TABLE = os.getenv("CBM_FEISHU_ACCOUNT_TABLE_ID", "")
KEYWORD_FIELDS = ["关键词", "监控平台", "状态", "扫描频率"]
ACCOUNT_FIELDS = ["账号名称", "平台", "主页链接", "平台账号ID", "状态", "扫描频率"]
DISABLED_VALUES = {"停用", "暂停"}


def scalar(value: Any) -> str:
    """Convert common Base cell shapes to a compact string."""
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        markdown_link = re.fullmatch(r"\[[^\]]*\]\((https?://.+)\)", text)
        return markdown_link.group(1) if markdown_link else text
    if isinstance(value, (int, float, bool)):
        return str(value).strip()
    if isinstance(value, list):
        return ",".join(part for item in value if (part := scalar(item)))
    if isinstance(value, dict):
        for key in ("link", "url", "text", "name", "value"):
            if key in value and (part := scalar(value[key])):
                return part
        return ""
    return str(value).strip()


def selections(value: Any) -> list[str]:
    if isinstance(value, list):
        return [part for item in value if (part := scalar(item))]
    text = scalar(value)
    return [part.strip() for part in re.split(r"[,，、/|]", text) if part.strip()]


def platform_name(value: Any) -> str | None:
    text = scalar(value).lower()
    if "小红书" in text or "xiaohongshu" in text or "xhs" == text:
        return "xiaohongshu"
    if "抖音" in text or "douyin" in text:
        return "douyin"
    return None


def keyword_platforms(value: Any) -> list[str]:
    found: list[str] = []
    for item in selections(value):
        name = platform_name(item)
        if name and name not in found:
            found.append(name)
    return found or ["xiaohongshu", "douyin"]


def infer_platform(platform_value: Any, homepage: str) -> str | None:
    explicit = platform_name(platform_value)
    if explicit:
        return explicit
    host = urlparse(homepage).netloc.lower()
    if "xiaohongshu.com" in host:
        return "xiaohongshu"
    if "douyin.com" in host or "iesdouyin.com" in host:
        return "douyin"
    return None


def douyin_sec_uid(account_id: str, homepage: str) -> str | None:
    if account_id and not account_id.startswith(("http://", "https://")):
        return account_id
    candidate = homepage or account_id
    if not candidate:
        return None
    match = re.search(r"/(?:user|share/user)/([^/?#]+)", candidate)
    return unquote(match.group(1)) if match else None


def run_record_list(base_token: str, table_id: str, fields: list[str]) -> list[dict[str, Any]]:
    if not shutil.which("lark-cli"):
        raise RuntimeError("未找到 lark-cli，请先完成飞书授权配置")

    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        command = [
            "lark-cli", "base", "+record-list", "--as", "user",
            "--base-token", base_token, "--table-id", table_id,
        ]
        for field in fields:
            command.extend(["--field-id", field])
        command.extend(["--offset", str(offset), "--limit", "200", "--format", "json"])
        env = os.environ.copy()
        env["LARK_CLI_DISABLE_UPDATE_CHECK"] = "1"
        result = subprocess.run(command, check=False, capture_output=True, text=True, env=env)
        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"读取飞书表 {table_id} 失败：{detail}")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"飞书返回的内容不是有效 JSON：{exc}") from exc
        if not payload.get("ok", False):
            raise RuntimeError(f"读取飞书表 {table_id} 失败：{payload}")

        data = payload.get("data", {})
        names = data.get("fields") or fields
        page_rows = data.get("data") or []
        record_ids = data.get("record_id_list") or []
        for index, row in enumerate(page_rows):
            if isinstance(row, dict):
                mapped = dict(row)
            else:
                mapped = dict(zip(names, row))
            if index < len(record_ids):
                mapped["_record_id"] = record_ids[index]
            rows.append(mapped)
        if not data.get("has_more") or not page_rows:
            break
        offset += len(page_rows)
    return rows


def is_enabled(row: dict[str, Any]) -> bool:
    return scalar(row.get("状态")) not in DISABLED_VALUES and scalar(row.get("扫描频率")) not in DISABLED_VALUES


def build_config(
    keyword_rows: list[dict[str, Any]],
    account_rows: list[dict[str, Any]],
    direction: str,
    max_keywords: int,
    max_accounts_per_platform: int,
    max_results_per_task: int,
    max_pages: int,
) -> tuple[dict[str, Any], list[str]]:
    notices: list[str] = []
    keywords: list[dict[str, Any]] = []
    seen_terms: set[str] = set()
    for row in keyword_rows:
        term = scalar(row.get("关键词"))
        key = term.casefold()
        if not term or not is_enabled(row) or key in seen_terms:
            continue
        seen_terms.add(key)
        keywords.append({"term": term, "platforms": keyword_platforms(row.get("监控平台"))})
    if len(keywords) > max_keywords:
        notices.append(f"关键词共有 {len(keywords)} 个，本次试跑只取前 {max_keywords} 个。")
        keywords = keywords[:max_keywords]

    accounts: list[dict[str, Any]] = []
    platform_counts = {"xiaohongshu": 0, "douyin": 0}
    seen_accounts: set[tuple[str, str]] = set()
    for row in account_rows:
        if not is_enabled(row):
            continue
        name = scalar(row.get("账号名称"))
        homepage = scalar(row.get("主页链接"))
        account_id = scalar(row.get("平台账号ID"))
        platform = infer_platform(row.get("平台"), homepage or account_id)
        label = name or homepage or account_id or scalar(row.get("_record_id")) or "未命名账号"
        if not platform:
            if homepage or account_id or name:
                notices.append(f"跳过“{label}”：无法判断是小红书还是抖音，请使用平台主页链接。")
            continue
        if platform == "douyin":
            identifier = douyin_sec_uid(account_id, homepage)
            if not identifier:
                notices.append(f"跳过“{label}”：抖音链接里没有可识别的 secUid，请粘贴完整账号主页链接。")
                continue
        else:
            identifier = account_id or homepage
            if not identifier:
                notices.append(f"跳过“{label}”：缺少小红书主页链接。")
                continue
        identity = (platform, identifier)
        if identity in seen_accounts:
            continue
        if platform_counts[platform] >= max_accounts_per_platform:
            notices.append(f"{platform} 对标账号超过试跑上限 {max_accounts_per_platform} 个，已跳过“{label}”。")
            continue
        seen_accounts.add(identity)
        platform_counts[platform] += 1
        account = {"platform": platform, "id_or_url": identifier}
        if name:
            account["name"] = name
        accounts.append(account)

    config = {
        "profile": {"direction": direction},
        "pilot": {
            "max_keywords": max_keywords,
            "max_accounts_per_platform": max_accounts_per_platform,
            "max_results_per_task": max_results_per_task,
            "max_pages": max_pages,
        },
        "keywords": keywords,
        "accounts": accounts,
    }
    return config, notices


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从飞书监控表生成试跑配置")
    parser.add_argument("--output", required=True, help="生成的 JSON 配置路径")
    parser.add_argument("--base-token", default=DEFAULT_BASE_TOKEN, help="飞书 Base token；也可用 CBM_FEISHU_BASE_TOKEN")
    parser.add_argument("--keyword-table", default=DEFAULT_KEYWORD_TABLE, help="关键词表 ID；也可用 CBM_FEISHU_KEYWORD_TABLE_ID")
    parser.add_argument("--account-table", default=DEFAULT_ACCOUNT_TABLE, help="账号表 ID；也可用 CBM_FEISHU_ACCOUNT_TABLE_ID")
    parser.add_argument("--direction", default="待确认的内容方向")
    parser.add_argument("--max-keywords", type=int, default=3)
    parser.add_argument("--max-accounts-per-platform", type=int, default=2)
    parser.add_argument("--max-results-per-task", type=int, default=8)
    parser.add_argument("--max-pages", type=int, default=1)
    args = parser.parse_args()
    missing = [
        name for name, value in (
            ("base token", args.base_token),
            ("keyword table ID", args.keyword_table),
            ("account table ID", args.account_table),
        ) if not value
    ]
    if missing:
        parser.error("缺少 " + "、".join(missing) + "；请传入参数或设置 CBM_FEISHU_* 环境变量")
    return args


def main() -> int:
    args = parse_args()
    try:
        keyword_rows = run_record_list(args.base_token, args.keyword_table, KEYWORD_FIELDS)
        account_rows = run_record_list(args.base_token, args.account_table, ACCOUNT_FIELDS)
        config, notices = build_config(
            keyword_rows, account_rows, args.direction,
            args.max_keywords, args.max_accounts_per_platform,
            args.max_results_per_task, args.max_pages,
        )
        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    for notice in notices:
        print(f"提示：{notice}", file=sys.stderr)
    print(f"已生成 {output}：{len(config['keywords'])} 个关键词，{len(config['accounts'])} 个对标账号")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
