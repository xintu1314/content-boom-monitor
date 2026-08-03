#!/usr/bin/env python3
"""Small Just One API pilot for Xiaohongshu and Douyin monitoring."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


BASE_URL = "https://api.justoneapi.com"
DEFAULT_LIMITS = {
    "max_keywords": 3,
    "max_accounts_per_platform": 2,
    "max_results_per_task": 8,
    "max_pages": 1,
}
PLATFORMS = {"xiaohongshu", "douyin"}


class ApiError(RuntimeError):
    pass


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", value).strip("_")
    return cleaned[:60] or hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def parse_count(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    multiplier = 1
    if text.endswith("万"):
        multiplier, text = 10000, text[:-1]
    elif text.lower().endswith("w"):
        multiplier, text = 10000, text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return None


def first_direct(obj: Any, aliases: Iterable[str]) -> Any:
    if not isinstance(obj, dict):
        return None
    for key in aliases:
        if key in obj and obj[key] not in (None, "", []):
            return obj[key]
    return None


def first_recursive(obj: Any, aliases: Iterable[str], depth: int = 0) -> Any:
    if depth > 5:
        return None
    direct = first_direct(obj, aliases)
    if direct is not None:
        return direct
    if isinstance(obj, dict):
        for value in obj.values():
            if isinstance(value, (dict, list)):
                found = first_recursive(value, aliases, depth + 1)
                if found is not None:
                    return found
    elif isinstance(obj, list):
        for value in obj[:20]:
            found = first_recursive(value, aliases, depth + 1)
            if found is not None:
                return found
    return None


def iter_dict_lists(obj: Any, depth: int = 0):
    if depth > 7:
        return
    if isinstance(obj, list) and obj and all(isinstance(v, dict) for v in obj):
        yield obj
    if isinstance(obj, dict):
        for value in obj.values():
            yield from iter_dict_lists(value, depth + 1)
    elif isinstance(obj, list):
        for value in obj[:30]:
            yield from iter_dict_lists(value, depth + 1)


def candidate_score(obj: dict[str, Any], platform: str) -> int:
    id_aliases = ("note_id", "noteId", "aweme_id", "awemeId", "item_id")
    score = 3 if first_recursive(obj, id_aliases) is not None else 0
    if platform == "xiaohongshu" and first_direct(obj, ("id",)) is not None:
        score += 3
    if first_recursive(obj, ("display_title", "title", "desc", "description")) is not None:
        score += 2
    if first_recursive(obj, ("liked_count", "digg_count", "like_count", "collect_count", "comment_count")) is not None:
        score += 2
    if first_recursive(obj, ("author", "user", "user_info", "nickname")) is not None:
        score += 1
    if platform == "douyin" and first_recursive(obj, ("aweme_id", "awemeId")) is not None:
        score += 2
    if platform == "xiaohongshu" and first_recursive(obj, ("note_id", "noteId")) is not None:
        score += 2
    return score


def choose_item_list(response: Any, platform: str) -> list[dict[str, Any]]:
    candidates = []
    for values in iter_dict_lists(response):
        sample = values[:10]
        scores = [candidate_score(v, platform) for v in sample]
        good = sum(1 for score in scores if score >= 4)
        candidates.append((good * 100 + sum(scores) + min(len(values), 30), values))
    if not candidates:
        return []
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    best_score, best = candidates[0]
    return best if best_score >= 100 else []


def normalize_time(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        number = int(value)
        if number > 10_000_000_000:
            number //= 1000
        try:
            return datetime.fromtimestamp(number, timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    return text[:19] if text else None


def normalize_item(item: dict[str, Any], platform: str, source: dict[str, Any], rank: int) -> dict[str, Any] | None:
    containers = [item]
    for key in ("note_card", "noteCard", "aweme_info", "awemeInfo", "item", "note"):
        value = item.get(key)
        if isinstance(value, dict):
            containers.insert(0, value)

    def pick(aliases: Iterable[str], recursive: bool = True):
        for container in containers:
            found = first_direct(container, aliases)
            if found is not None:
                return found
        return first_recursive(item, aliases) if recursive else None

    if platform == "douyin":
        post_id = pick(("aweme_id", "awemeId", "item_id", "itemId"))
    else:
        post_id = pick(("note_id", "noteId", "item_id", "itemId", "id"))
    if post_id is None:
        return None
    post_id = str(post_id)

    author_obj = pick(("author", "user", "user_info", "userInfo"))
    if not isinstance(author_obj, dict):
        author_obj = item
    author_name = first_recursive(author_obj, ("nickname", "nick_name", "name", "user_name"))
    author_id = first_recursive(author_obj, ("sec_uid", "secUid", "user_id", "userId", "userid", "id"))

    title = pick(("display_title", "displayTitle", "title", "desc", "description"))
    note_type = pick(("note_type", "noteType", "type", "aweme_type"))
    published = pick(("create_time", "createTime", "publish_time", "publishTime", "time"))
    # Store stable canonical links rather than API-provided share URLs containing
    # transient tracking and device query parameters.
    url = (
        f"https://www.douyin.com/video/{post_id}"
        if platform == "douyin"
        else f"https://www.xiaohongshu.com/explore/{post_id}"
    )

    metric_aliases = {
        "likes": ("liked_count", "likedCount", "digg_count", "diggCount", "like_count", "likes"),
        "collects": ("collected_count", "collectedCount", "collect_count", "collectCount", "favorite_count"),
        "comments": ("comment_count", "comments_count", "commentCount", "comments"),
        "shares": ("share_count", "shared_count", "shareCount", "shares"),
        "views": ("play_count", "playCount", "view_count", "viewCount", "views"),
    }
    metrics = {name: parse_count(pick(aliases)) for name, aliases in metric_aliases.items()}
    return {
        "platform": platform,
        "post_id": post_id,
        "title": str(title or "").strip(),
        "post_url": url,
        "content_type": str(note_type or "unknown"),
        "author_name": str(author_name or source.get("account_name") or "").strip(),
        "author_id": str(author_id or source.get("account_id") or "").strip(),
        "published_at": normalize_time(published),
        "likes": metrics["likes"],
        "collects": metrics["collects"],
        "comments": metrics["comments"],
        "shares": metrics["shares"],
        "views": metrics["views"],
        "monitor_sources": [source],
        "search_rank": rank if source["type"] == "keyword" else None,
        "collected_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
    }


def merge_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for record in records:
        key = f"{record['platform']}:{record['post_id']}"
        if key not in merged:
            merged[key] = record
            continue
        current = merged[key]
        known_sources = {json.dumps(v, ensure_ascii=False, sort_keys=True) for v in current["monitor_sources"]}
        for source in record["monitor_sources"]:
            encoded = json.dumps(source, ensure_ascii=False, sort_keys=True)
            if encoded not in known_sources:
                current["monitor_sources"].append(source)
                known_sources.add(encoded)
        for field in ("title", "post_url", "author_name", "author_id", "published_at", "likes", "collects", "comments", "shares", "views"):
            if current.get(field) in (None, "") and record.get(field) not in (None, ""):
                current[field] = record[field]
    return list(merged.values())


def interaction_value(record: dict[str, Any]) -> tuple[int | None, list[str]]:
    weights = {"likes": 1, "collects": 2, "comments": 2, "shares": 0}
    if record["platform"] == "douyin":
        weights = {"likes": 1, "collects": 2, "comments": 3, "shares": 4}
    available = [name for name in weights if record.get(name) is not None]
    if not available:
        return None, []
    return sum(int(record.get(name) or 0) * weights[name] for name in available), available


def score_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    account_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        value, available = interaction_value(record)
        record["interaction_value"] = value
        record["available_metrics"] = available
        for source in record["monitor_sources"]:
            if source["type"] == "account":
                account_groups[(record["platform"], source.get("account_id") or record.get("author_id") or source.get("account_name", ""))].append(record)

    for record in records:
        record["relative_r"] = None
        keyword_sources = [s for s in record["monitor_sources"] if s["type"] == "keyword"]
        record["monitor_grade"] = "关键词爆款候选" if keyword_sources else "样本不足"
        if keyword_sources:
            terms = "、".join(dict.fromkeys(str(s.get("keyword", "")).strip() for s in keyword_sources if s.get("keyword")))
            record["score_note"] = f"关键词“{terms}”热度搜索结果，按可用互动值排序" if terms else "关键词热度搜索结果，按可用互动值排序"
        else:
            record["score_note"] = "账号历史样本不足"
        account_sources = [s for s in record["monitor_sources"] if s["type"] == "account"]
        if not account_sources or record["interaction_value"] is None:
            continue
        source = account_sources[0]
        group_key = (record["platform"], source.get("account_id") or record.get("author_id") or source.get("account_name", ""))
        comparisons = [
            other["interaction_value"]
            for other in account_groups[group_key]
            if other is not record and other.get("interaction_value") is not None and other["interaction_value"] > 0
        ][:20]
        if len(comparisons) < 5:
            record["score_note"] = f"仅有 {len(comparisons)} 条可用对比作品，暂不评级"
            continue
        baseline = float(statistics.median(comparisons))
        if baseline <= 0:
            record["score_note"] = "历史互动基线为零，暂不评级"
            continue
        ratio = record["interaction_value"] / baseline
        record["relative_r"] = round(ratio, 2)
        floor = max(20, baseline * 2)
        if ratio >= 8 and record["interaction_value"] >= floor:
            grade = "T3 现象级"
        elif ratio >= 4 and record["interaction_value"] >= floor:
            grade = "T2 爆款"
        elif ratio >= 2 and record["interaction_value"] >= floor:
            grade = "T1 潜力"
        elif ratio >= 2:
            grade = "虚高"
        else:
            grade = "普通"
        record["monitor_grade"] = grade
        record["score_note"] = f"历史中位数 {baseline:.2f}，当前互动值 {record['interaction_value']}"
    return records


class ApiClient:
    def __init__(self, token: str):
        self.token = token

    def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urllib.parse.urlencode({"token": self.token, **params})
        request = urllib.request.Request(f"{BASE_URL}{path}?{query}", headers={"User-Agent": "content-boom-monitor/0.1"})
        retryable = {301, 500}
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                if attempt == 2:
                    raise ApiError(f"Request failed for {path}: {type(exc).__name__}") from exc
                time.sleep(2**attempt)
                continue
            code = payload.get("code")
            if code == 0:
                return payload
            if code in retryable and attempt < 2:
                time.sleep(2**attempt)
                continue
            raise ApiError(f"Business error for {path}: code={code}, message={payload.get('message', '')}")
        raise ApiError(f"Request failed for {path}")


def task_spec(platform: str, task_type: str, value: str) -> tuple[str, dict[str, Any]]:
    if task_type == "keyword" and platform == "xiaohongshu":
        return "/api/xiaohongshu/search-note/v4", {"keyword": value, "page": 1, "sortType": "popularity_descending", "timeFilter": "ONE_WEEK"}
    if task_type == "keyword" and platform == "douyin":
        return "/api/douyin/search-video/v4", {"keyword": value, "page": 1, "sortType": "_1", "publishTime": "_7"}
    if task_type == "account" and platform == "xiaohongshu":
        return "/api/xiaohongshu/get-user-note-list/v4", {"userId": value}
    if task_type == "account" and platform == "douyin":
        return "/api/douyin/get-user-video-list/v3", {"secUid": value, "maxCursor": 0}
    raise ValueError(f"Unsupported task: {task_type}/{platform}")


def fixture_path(fixtures_dir: Path, platform: str, task_type: str, value: str) -> Path:
    return fixtures_dir / f"{platform}_{task_type}_{safe_name(value)}.json"


def build_tasks(config: dict[str, Any], limits: dict[str, int]) -> tuple[list[dict[str, Any]], list[str]]:
    tasks: list[dict[str, Any]] = []
    notices: list[str] = []
    keywords = config.get("keywords", [])[: limits["max_keywords"]]
    if len(config.get("keywords", [])) > len(keywords):
        notices.append(f"关键词已截断为 {len(keywords)} 个")
    for keyword in keywords:
        term = str(keyword.get("term", "")).strip()
        if not term:
            continue
        platforms = keyword.get("platforms") or ["xiaohongshu", "douyin"]
        for platform in platforms:
            if platform in PLATFORMS:
                tasks.append({"type": "keyword", "platform": platform, "value": term, "keyword": term})

    counts = defaultdict(int)
    for account in config.get("accounts", []):
        platform = account.get("platform")
        value = str(account.get("id_or_url", "")).strip()
        if platform not in PLATFORMS or not value:
            continue
        if counts[platform] >= limits["max_accounts_per_platform"]:
            notices.append(f"{platform} 对标账号已截断为 {limits['max_accounts_per_platform']} 个")
            continue
        counts[platform] += 1
        tasks.append({
            "type": "account",
            "platform": platform,
            "value": value,
            "account_id": value,
            "account_name": str(account.get("name", "")).strip(),
        })
    return tasks, notices


def to_feishu_row(record: dict[str, Any]) -> dict[str, Any]:
    sources = record["monitor_sources"]
    methods = []
    keywords = []
    for source in sources:
        if source["type"] == "keyword":
            if "关键词监控" not in methods:
                methods.append("关键词监控")
            if source.get("keyword") and source["keyword"] not in keywords:
                keywords.append(source["keyword"])
        elif source["type"] == "account" and "对标账号监控" not in methods:
            methods.append("对标账号监控")
    content_type = "视频" if any(token in record["content_type"].lower() for token in ("video", "视频")) else "未知"
    if record["platform"] == "xiaohongshu" and content_type == "未知":
        content_type = "图文"
    return {
        "标题": record["title"] or f"{record['platform']} {record['post_id']}",
        "平台": "小红书" if record["platform"] == "xiaohongshu" else "抖音",
        "作品类型": content_type,
        "作品ID": record["post_id"],
        "作品链接": record["post_url"],
        "作者": record["author_name"],
        "作者ID": record["author_id"],
        "发布时间": record["published_at"],
        "发现方式": methods,
        "命中关键词": "、".join(keywords),
        "点赞数": record["likes"],
        "收藏数": record["collects"],
        "评论数": record["comments"],
        "分享数": record["shares"],
        "播放量": record["views"],
        "互动值": record["interaction_value"],
        "相对表现R": record["relative_r"],
        "监控等级": record["monitor_grade"],
        "增长状态": "首次采集",
        "首次发现时间": record["collected_at"],
        "最后采集时间": record["collected_at"],
        "处理状态": "待评估",
        "数据备注": record["score_note"],
    }


def render_report(records: list[dict[str, Any]], tasks: list[dict[str, Any]], notices: list[str], failures: list[str], mode: str) -> str:
    def md(value: Any) -> str:
        text = "—" if value in (None, "") else str(value)
        return text.replace("|", "\\|").replace("\n", " ")

    def platform_label(value: str) -> str:
        return "小红书" if value == "xiaohongshu" else "抖音"

    def source_label(record: dict[str, Any]) -> str:
        labels: list[str] = []
        for source in record.get("monitor_sources", []):
            if source.get("type") == "keyword":
                label = f"关键词：{source.get('keyword', '—')}"
            else:
                label = f"账号：{source.get('account_name') or source.get('account_id') or '—'}"
            if label not in labels:
                labels.append(label)
        return "；".join(labels) or "—"

    def ratio(value: Any) -> str:
        return "—" if value is None else f"{value:.2f}"

    grade_order = {"T3 现象级": 0, "T2 爆款": 1, "T1 潜力": 2, "关键词爆款候选": 3, "虚高": 4, "普通": 5, "样本不足": 6}
    grades: dict[str, int] = defaultdict(int)
    platforms: dict[str, int] = defaultdict(int)
    for record in records:
        grades[record["monitor_grade"]] += 1
        platforms[record["platform"]] += 1

    keyword_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    account_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        for source in record.get("monitor_sources", []):
            if source.get("type") == "keyword":
                keyword_groups[(str(source.get("keyword", "")), record["platform"])].append(record)
            elif source.get("type") == "account":
                account_name = str(source.get("account_name") or source.get("account_id") or "未命名账号")
                account_groups[(account_name, record["platform"])].append(record)

    keyword_tasks = sum(task.get("type") == "keyword" for task in tasks)
    account_tasks = sum(task.get("type") == "account" for task in tasks)
    missing_published = sum(record.get("published_at") in (None, "") for record in records)
    missing_links = sum(record.get("post_url") in (None, "") for record in records)
    missing_authors = sum(record.get("author_name") in (None, "") for record in records)
    no_interaction = sum(record.get("interaction_value") is None for record in records)
    lines = [
        "# 内容监控生产报告" if mode == "production" else "# 内容监控试运行报告",
        "",
        "## 执行摘要",
        "",
        f"- 运行模式：{mode}",
        f"- 执行任务：{len(tasks)}（关键词 {keyword_tasks}，对标账号 {account_tasks}）",
        f"- 去重后作品：{len(records)}（小红书 {platforms.get('xiaohongshu', 0)}，抖音 {platforms.get('douyin', 0)}）",
        f"- 接口失败：{len(failures)}",
        f"- 数据完整性：缺发布时间 {missing_published} 条，缺链接 {missing_links} 条，缺作者 {missing_authors} 条，无法计算互动值 {no_interaction} 条",
        "",
        "## 等级分布",
        "",
        "| 等级 | 数量 | 含义 |",
        "|---|---:|---|",
    ]
    if grades:
        meanings = {
            "T3 现象级": "账号内相对表现 R≥8，且达到互动证据门槛",
            "T2 爆款": "账号内相对表现 R≥4，且达到互动证据门槛",
            "T1 潜力": "账号内相对表现 R≥2，且达到互动证据门槛",
            "虚高": "相对比值较高，但绝对互动证据不足",
            "普通": "已有账号基线，R<2",
            "关键词爆款候选": "关键词热度搜索结果，按可用互动值优先审阅",
            "样本不足": "对标账号可用作品不足，暂不做相对评级",
        }
        for grade, count in sorted(grades.items(), key=lambda item: grade_order.get(item[0], 99)):
            lines.append(f"| {md(grade)} | {count} | {meanings.get(grade, '—')} |")
    else:
        lines.append("| 暂无可识别作品 | 0 | — |")

    lines.extend(["", "## 关键词爆款结果", ""])
    if keyword_groups:
        for (keyword, platform), items in sorted(keyword_groups.items()):
            values = [item["interaction_value"] for item in items if item.get("interaction_value") is not None]
            median_value = round(statistics.median(values), 1) if values else "—"
            ranked_items = sorted(items, key=lambda item: (-(item.get("interaction_value") or -1), item.get("search_rank") or 999))
            lines.extend([
                f"### {md(keyword)}（{platform_label(platform)}）",
                "",
                f"- 返回 {len(items)} 条爆款候选；互动值中位数：{median_value}",
                "",
                "| 排名 | 互动值 | 点赞 | 收藏 | 评论 | 分享 | 标题 | 作者 |",
                "|---:|---:|---:|---:|---:|---:|---|---|",
            ])
            for index, item in enumerate(ranked_items, start=1):
                title = md(item.get("title") or item.get("post_id"))
                lines.append(
                    f"| {index} | {md(item.get('interaction_value'))} | {md(item.get('likes'))} | {md(item.get('collects'))} | "
                    f"{md(item.get('comments'))} | {md(item.get('shares'))} | [{title}]({item.get('post_url', '')}) | {md(item.get('author_name'))} |"
                )
            lines.append("")
    else:
        lines.append("- 本次没有关键词监控结果。")

    lines.extend(["", "## 对标账号异常", ""])
    if account_groups:
        for (account_name, platform), items in sorted(account_groups.items()):
            values = [item["interaction_value"] for item in items if item.get("interaction_value") is not None]
            baseline = round(statistics.median(values), 1) if values else "—"
            lines.extend([
                f"### {md(account_name)}（{platform_label(platform)}）",
                "",
                f"- 本次作品：{len(items)}；本批互动值中位数：{baseline}",
                "",
                "| 等级 | R | 互动值 | 标题 | 作者 |",
                "|---|---:|---:|---|---|",
            ])
            for item in sorted(items, key=lambda value: (grade_order.get(value["monitor_grade"], 99), -(value.get("relative_r") or 0), -(value.get("interaction_value") or 0))):
                title = md(item.get("title") or item.get("post_id"))
                lines.append(
                    f"| {md(item['monitor_grade'])} | {ratio(item.get('relative_r'))} | {md(item.get('interaction_value'))} | [{title}]({item.get('post_url', '')}) | {md(item.get('author_name'))} |"
                )
    else:
        lines.append("- 本次没有对标账号结果。")

    ranked = sorted(
        records,
        key=lambda item: (grade_order.get(item["monitor_grade"], 99), -(item.get("relative_r") or 0), -(item.get("interaction_value") or 0)),
    )[:10]
    lines.extend([
        "",
        "## 重点内容 Top 10",
        "",
        "| # | 平台 | 等级 | R | 互动值 | 标题 | 作者 | 来源 |",
        "|---:|---|---|---:|---:|---|---|---|",
    ])
    for index, item in enumerate(ranked, start=1):
        title = md(item.get("title") or item.get("post_id"))
        lines.append(
            f"| {index} | {platform_label(item['platform'])} | {md(item['monitor_grade'])} | {ratio(item.get('relative_r'))} | {md(item.get('interaction_value'))} | [{title}]({item.get('post_url', '')}) | {md(item.get('author_name'))} | {md(source_label(item))} |"
        )

    lines.extend(["", "## 事实观察与下一步", ""])
    anomaly_items = [item for item in records if item["monitor_grade"] in {"T3 现象级", "T2 爆款", "T1 潜力"}]
    if anomaly_items:
        strongest = sorted(anomaly_items, key=lambda item: item.get("relative_r") or 0, reverse=True)[0]
        lines.append(
            f"- 优先复盘：[{md(strongest.get('title') or strongest.get('post_id'))}]({strongest.get('post_url', '')})，"
            f"账号相对表现为 {ratio(strongest.get('relative_r'))}，等级为 {md(strongest['monitor_grade'])}。"
        )
    else:
        lines.append("- 本次没有达到 T1/T2/T3 的账号相对异常作品。")
    if keyword_groups:
        best_group = max(
            keyword_groups.items(),
            key=lambda pair: max((item.get("interaction_value") or 0) for item in pair[1]),
        )
        (keyword, platform), items = best_group
        best = max(items, key=lambda item: item.get("interaction_value") or 0)
        lines.append(
            f"- 关键词爆款候选：`{md(keyword)}` 在{platform_label(platform)}中的最高互动作品为"
            f"[{md(best.get('title') or best.get('post_id'))}]({best.get('post_url', '')})，互动值 {md(best.get('interaction_value'))}。"
        )
    lines.append("- 建议只对 Top 5 做正文级 AI 拆解；当前报告只依据标题、作者和公开互动字段，不推断未获取的正文、受众或爆款原因。")

    lines.extend([
        "",
        "## 数据质量与口径",
        "",
        f"- {missing_published} 条作品缺少发布时间；保持为空，不按采集时间替代。",
        f"- {missing_links} 条缺作品链接，{missing_authors} 条缺作者，{no_interaction} 条无法计算互动值。",
        "- 小红书互动值 = 点赞 + 2×收藏 + 2×评论；抖音互动值 = 点赞 + 2×收藏 + 3×评论 + 4×分享。",
        "- 关键词监控调用平台热度/点赞排序，再按本批可用互动值排序；返回的是该关键词搜索范围内的爆款候选，不代表全网爆款认证。",
        "- R 仅用于对标账号：当前作品互动值 ÷ 同账号其他可用作品互动值中位数；至少需要 5 条对比作品。",
        "- `样本不足` 只用于缺少可用历史基线的对标账号作品，不用于关键词搜索结果。",
    ])
    if notices:
        lines.extend(["", "## 小样本限制", "", *[f"- {notice}" for notice in notices]])
    if failures:
        lines.extend(["", "## 失败与缺口", "", *[f"- {failure}" for failure in failures]])
    return "\n".join(lines) + "\n"


def prepare_analysis_candidates(records: list[dict[str, Any]], direction: str, max_items: int) -> dict[str, Any]:
    """Build a larger evidence pool so the agent can select relevant items automatically."""
    grade_order = {"T3 现象级": 0, "T2 爆款": 1, "T1 潜力": 2, "关键词爆款候选": 3}
    eligible = [
        record for record in records
        if record.get("monitor_grade") in grade_order
        or len(record.get("monitor_sources", [])) > 1
    ]
    eligible.sort(key=lambda item: (
        grade_order.get(item.get("monitor_grade", ""), 4),
        -(item.get("relative_r") or 0),
        -(item.get("interaction_value") or 0),
    ))
    pool_limit = max(max_items, max_items * 3)
    candidates = []
    for record in eligible[:pool_limit]:
        candidates.append({
            "platform": record.get("platform"),
            "post_id": record.get("post_id"),
            "title": record.get("title"),
            "post_url": record.get("post_url"),
            "author_name": record.get("author_name"),
            "published_at": record.get("published_at"),
            "likes": record.get("likes"),
            "collects": record.get("collects"),
            "comments": record.get("comments"),
            "shares": record.get("shares"),
            "views": record.get("views"),
            "interaction_value": record.get("interaction_value"),
            "relative_r": record.get("relative_r"),
            "monitor_grade": record.get("monitor_grade"),
            "monitor_sources": record.get("monitor_sources", []),
        })
    return {
        "direction": direction,
        "max_items": max_items,
        "selection_rule": "Select the most relevant items first; prefer keyword boom candidates, T1/T2/T3 anomalies, cross-source hits, recent posts, and complete evidence. Skip off-topic items.",
        "required_output_fields": [
            "platform", "post_id", "fact_evidence", "inferred_structure",
            "boom_factors", "reusable_elements", "non_reusable_context",
            "reusable_topic", "confidence", "missing_evidence",
        ],
        "candidates": candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fixtures-dir", type=Path)
    args = parser.parse_args()

    config = read_json(args.config)
    mode = str(config.get("mode", "pilot")).strip().lower()
    if mode not in {"pilot", "production"}:
        raise SystemExit("config.mode must be pilot or production")
    configured_limits = config.get("limits") or config.get("pilot", {})
    limits = DEFAULT_LIMITS | {k: int(v) for k, v in configured_limits.items() if k in DEFAULT_LIMITS}
    if mode == "pilot":
        limits = {key: min(value, DEFAULT_LIMITS[key]) for key, value in limits.items()}
    else:
        limits = {key: max(0, value) for key, value in limits.items()}
    tasks, notices = build_tasks(config, limits)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = args.output_dir / "raw"
    raw_dir.mkdir(exist_ok=True)

    token = os.getenv("JUSTONE_API_TOKEN", "")
    if not args.fixtures_dir and not token:
        print("JUSTONE_API_TOKEN is required unless --fixtures-dir is used", file=sys.stderr)
        return 2
    client = ApiClient(token) if token else None
    all_records: list[dict[str, Any]] = []
    failures: list[str] = []

    for task in tasks:
        platform, task_type, value = task["platform"], task["type"], task["value"]
        try:
            if args.fixtures_dir:
                source_file = fixture_path(args.fixtures_dir, platform, task_type, value)
                response = read_json(source_file)
            else:
                path, params = task_spec(platform, task_type, value)
                response = client.get(path, params)  # type: ignore[union-attr]
            raw_file = raw_dir / f"{platform}_{task_type}_{safe_name(value)}.json"
            write_json(raw_file, response)
            items = choose_item_list(response.get("data", response), platform)
            if not items:
                failures.append(f"{platform}/{task_type}/{value}: 未识别到作品列表")
                continue
            source = {key: task[key] for key in ("type", "keyword", "account_id", "account_name") if key in task}
            task_limit = 5 if task_type == "keyword" else limits["max_results_per_task"]
            for rank, item in enumerate(items[:task_limit], start=1):
                normalized = normalize_item(item, platform, source, rank)
                if normalized:
                    all_records.append(normalized)
        except (ApiError, FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
            failures.append(f"{platform}/{task_type}/{value}: {exc}")

    normalized = merge_records(all_records)
    scored = score_records(normalized)
    feishu_rows = [to_feishu_row(record) for record in scored if record.get("post_id")]
    direction = str(config.get("profile", {}).get("direction", "")).strip()
    default_analysis_max = 10 if mode == "production" else 5
    analysis_max = max(1, min(50, int(config.get("analysis", {}).get("max_items", default_analysis_max))))
    analysis_candidates = prepare_analysis_candidates(scored, direction, analysis_max)
    write_json(args.output_dir / "normalized.json", normalized)
    write_json(args.output_dir / "scored.json", scored)
    write_json(args.output_dir / "feishu_rows.json", feishu_rows)
    write_json(args.output_dir / "analysis_candidates.json", analysis_candidates)
    (args.output_dir / "report.md").write_text(render_report(scored, tasks, notices, failures, mode), encoding="utf-8")
    print(json.dumps({"mode": mode, "tasks": len(tasks), "records": len(scored), "analysis_candidates": len(analysis_candidates["candidates"]), "failures": len(failures), "output_dir": str(args.output_dir)}, ensure_ascii=False))
    return 0 if scored else 1


if __name__ == "__main__":
    raise SystemExit(main())
