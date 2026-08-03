---
name: content-boom-monitor
description: Search Xiaohongshu (小红书) and Douyin (抖音) keywords for high-engagement posts and monitor competitor accounts for account-relative anomalies through Just One API, then normalize, deduplicate, rank, analyze, and publish selected results to Feishu Base. Use when the user asks to 搜关键词找爆款笔记或视频、建立或运行关键词爆款监控、对标账号监控、爆款雷达、竞品内容监控、异常作品检测、内容库更新、飞书内容监控日报, or calibrate these monitoring rules.
---

# Content Boom Monitor

Run a small, evidence-based content-monitoring pipeline for Xiaohongshu and Douyin. Keep human input limited to seed keywords, account links/IDs, and final relevance feedback.

## Operating principles

- Use pilot mode only for an unvalidated first run. After the pilot succeeds, use production mode: read every enabled Feishu keyword and account, while keeping each task bounded to 5 keyword results, 8 account works, and 1 page by default.
- Treat keyword monitoring and account monitoring as separate detection engines.
- Use keyword monitoring to answer “which high-engagement posts match this keyword?” Request platform popularity/like sorting, then rank the returned batch by available interaction value. Call the results `关键词爆款候选`, not new-topic or trend signals.
- Use competitor-account monitoring to answer “which recent work is unusually strong relative to this account's own baseline?” Apply account-relative R only to this engine.
- Preserve raw API responses. Never invent missing fields or convert missing metrics to factual zeros.
- Use account-relative performance only when at least 5 usable historical works are available.
- Do not claim that one search proves platform-wide virality. Report keyword-search boom candidates, observed account anomalies, and evidence quality.
- Keep API tokens in `JUSTONE_API_TOKEN`; never write tokens into this skill, reports, logs, or Feishu.
- Keep Feishu identifiers in `CBM_FEISHU_BASE_TOKEN`, `CBM_FEISHU_KEYWORD_TABLE_ID`, `CBM_FEISHU_ACCOUNT_TABLE_ID`, and `CBM_FEISHU_CONTENT_TABLE_ID`, or pass their matching CLI flags. Do not hard-code a user's Base or table IDs.
- Before writing to Feishu, read and follow the `lark-base` skill. Only pass `--write` when the user has authorized the write or an existing scheduled workflow explicitly covers it.

## Workflow

### 1. Collect minimal input

Accept any of these:

- One sentence describing the user's content direction.
- Seed keywords; production mode reads every enabled row.
- Competitor accounts; production mode reads every enabled row.
- Xiaohongshu profile URLs or user IDs.
- Douyin `secUid` values. If only a name is available, use the Just One API user-search endpoint and require an exact or user-confirmed match.

Do not ask the user to fill analytics fields. Platform, account name, IDs, metrics, baseline, grade, and scan status are automation outputs.

For the current Feishu library, the normal human input is even smaller:

- Add one row with `关键词` and optional `监控平台` in the `监控关键词 / 快速录入` view. A blank platform means both platforms.
- Paste an account homepage into `主页链接` in the `对标账号 / 快速录入` view. `账号名称` and `平台` are optional because the platform can be inferred from the link.

### 2. Prepare the run config

Use the configured Feishu Base as the default input source. First set the Base and table identifiers:

```bash
export CBM_FEISHU_BASE_TOKEN="<base-token>"
export CBM_FEISHU_KEYWORD_TABLE_ID="<keyword-table-id>"
export CBM_FEISHU_ACCOUNT_TABLE_ID="<account-table-id>"
export CBM_FEISHU_CONTENT_TABLE_ID="<content-table-id>"
```

Generate a production config directly from its keyword and account tables:

```bash
python3 scripts/build_config_from_feishu.py \
  --mode production \
  --direction "<内容方向>" \
  --output <run-config.json>
```

The reader is read-only. It skips disabled/paused rows, removes duplicates, infers platform from account URLs, and includes all enabled targets in production mode. Keep `--mode pilot` for an unvalidated first run; it applies the small pilot caps. If Feishu is unavailable or the user supplies inputs outside this Base, create a JSON file manually using [references/pilot-config.md](references/pilot-config.md).

### 3. Run collection

```bash
source ~/.zprofile
python3 scripts/pilot_monitor.py \
  --config <run-config.json> \
  --output-dir <output-directory>
```

The script reads `JUSTONE_API_TOKEN`, calls only the bounded endpoints configured for the run, and writes:

- `raw/`: redacted raw responses for mapping and debugging.
- `normalized.json`: deduplicated cross-platform posts.
- `scored.json`: account-relative scoring results.
- `analysis_candidates.json`: facts-only shortlist and the required AI output schema.
- `feishu_rows.json`: rows mapped to the current content library.
- `report.md`: decision-ready scan brief with per-keyword boom-candidate rankings, account anomalies, Top 10 items, data-quality notes, and evidence-bounded next steps.

Use `--fixtures-dir` for offline validation without network access or a token.

### 4. Review collection quality

Check `report.md` and `feishu_rows.json` for:

- Incorrect author or post IDs.
- Missing engagement fields.
- API pages that returned no recognizable post list.
- Douyin accounts whose latest works may be inaccessible.
- Scores based on fewer than 5 usable historical works.

If the API response shape changed, update only the normalizer in `pilot_monitor.py`; do not change scoring or Feishu fields until the raw sample proves it is necessary.

### 5. Apply AI analysis automatically

After every successful collection, continue automatically; do not stop at the metrics-only report. Read `analysis_candidates.json`, select up to its `max_items` entries that clearly match the user's direction, and create `analysis.json` with exactly these fields for every selected item:

```json
{
  "analyses": [
    {
      "platform": "xiaohongshu",
      "post_id": "source post ID",
      "fact_evidence": "only facts present in the candidate",
      "inferred_structure": "clearly labeled inference about hook and structure",
      "boom_factors": ["evidence-backed factor"],
      "reusable_elements": ["transferable element"],
      "non_reusable_context": ["author/account-specific context"],
      "reusable_topic": "one adapted topic for the user's direction",
      "confidence": 0.8,
      "missing_evidence": ["body text unavailable"]
    }
  ]
}
```

Do not invent post body, audience, claims, or causal explanations. Facts and inference must remain separate. Skip off-topic candidates instead of forcing the quota. Production defaults to at most 10 analyzed items; pilot defaults to 5.

Merge the analysis into the Feishu rows and report:

```bash
python3 scripts/apply_analysis.py \
  --candidates <output-directory>/analysis_candidates.json \
  --analysis <output-directory>/analysis.json \
  --rows <output-directory>/feishu_rows.json \
  --report <output-directory>/report.md
```

This step fills `AI摘要`, `爆款因素`, `可复用选题`, and `分析置信度`, and appends the evidence-bounded breakdown to the report. Codex performs the semantic analysis; the Python script validates and merges it deterministically, so no separate LLM API token is required when the Skill runs in Codex.

### 6. Preview and publish to Feishu

Preview first:

```bash
python3 scripts/publish_feishu.py --input <output-directory>/feishu_rows.json
```

After write authorization:

```bash
python3 scripts/publish_feishu.py \
  --input <output-directory>/feishu_rows.json \
  --write
```

The publisher deduplicates by `平台 + 作品ID`, updates existing rows individually, and batch-creates new rows. It requires the configured Base token and content table ID; preview and write use the same target.

### 7. Ask for lightweight feedback

Ask the user to mark only one status per reviewed item: `值得跟进`, `继续观察`, `不相关`, or `已采用`. Use this feedback to tune keywords and account priority before increasing scan volume.

## Scaling gate

Do not switch from pilot to production until one pilot run has:

- Successful API responses from both platforms.
- Correct ID and metric mapping from real samples.
- Deduplication verified in Feishu.
- At least one human relevance review.
- A known daily call-cost estimate from the Just One API console.

After those checks, production mode may include all enabled keywords and accounts. Keep per-task result and page limits bounded; increase pages or detail/comment calls only after reviewing cost and data quality.

## References

- [references/justoneapi.md](references/justoneapi.md): endpoint selection, paging, errors, and security.
- [references/scoring.md](references/scoring.md): interaction values and account-relative grades.
- [references/pilot-config.md](references/pilot-config.md): configuration schema and minimal example.
- [references/feishu-schema.md](references/feishu-schema.md): current Base, table IDs, and field ownership.
