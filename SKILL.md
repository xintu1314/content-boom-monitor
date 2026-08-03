---
name: content-boom-monitor
description: Monitor Xiaohongshu (小红书) and Douyin (抖音) keywords and competitor accounts through Just One API, normalize and deduplicate posts, detect unusual performance, prepare AI-assisted content insights, and publish a compact content radar into Feishu Base. Use when the user asks to 建立或运行关键词监控、对标账号监控、爆款雷达、竞品内容监控、热门选题发现、异常作品检测、内容库更新、飞书内容监控日报, or calibrate these monitoring rules.
---

# Content Boom Monitor

Run a small, evidence-based content-monitoring pipeline for Xiaohongshu and Douyin. Keep human input limited to seed keywords, account links/IDs, and final relevance feedback.

## Operating principles

- Start in pilot mode. Default to at most 3 keywords, 2 accounts per platform, and 1 page per request. Keep at most 5 keyword results and 8 account works per task so account scoring has enough history.
- Treat keyword monitoring and account monitoring as separate detection engines.
- Preserve raw API responses. Never invent missing fields or convert missing metrics to factual zeros.
- Use account-relative performance only when at least 5 usable historical works are available.
- Do not claim to predict virality. Report observed anomalies, growth signals, and evidence quality.
- Keep API tokens in `JUSTONE_API_TOKEN`; never write tokens into this skill, reports, logs, or Feishu.
- Keep Feishu identifiers in `CBM_FEISHU_BASE_TOKEN`, `CBM_FEISHU_KEYWORD_TABLE_ID`, `CBM_FEISHU_ACCOUNT_TABLE_ID`, and `CBM_FEISHU_CONTENT_TABLE_ID`, or pass their matching CLI flags. Do not hard-code a user's Base or table IDs.
- Before writing to Feishu, read and follow the `lark-base` skill. Only pass `--write` when the user has authorized the write or an existing scheduled workflow explicitly covers it.

## Workflow

### 1. Collect minimal input

Accept any of these:

- One sentence describing the user's content direction.
- 1-3 seed keywords; expand only when the user asks or after the pilot succeeds.
- Up to 2 competitor accounts per platform for the first run.
- Xiaohongshu profile URLs or user IDs.
- Douyin `secUid` values. If only a name is available, use the Just One API user-search endpoint and require an exact or user-confirmed match.

Do not ask the user to fill analytics fields. Platform, account name, IDs, metrics, baseline, grade, and scan status are automation outputs.

For the current Feishu library, the normal human input is even smaller:

- Add one row with `关键词` and optional `监控平台` in the `监控关键词 / 快速录入` view. A blank platform means both platforms.
- Paste an account homepage into `主页链接` in the `对标账号 / 快速录入` view. `账号名称` and `平台` are optional because the platform can be inferred from the link.

### 2. Prepare the pilot config

Use the configured Feishu Base as the default input source. First set the Base and table identifiers:

```bash
export CBM_FEISHU_BASE_TOKEN="<base-token>"
export CBM_FEISHU_KEYWORD_TABLE_ID="<keyword-table-id>"
export CBM_FEISHU_ACCOUNT_TABLE_ID="<account-table-id>"
export CBM_FEISHU_CONTENT_TABLE_ID="<content-table-id>"
```

Generate the pilot config directly from its keyword and account tables:

```bash
python3 scripts/build_config_from_feishu.py \
  --direction "<内容方向>" \
  --output <pilot-config.json>
```

The reader is read-only. It skips disabled/paused rows, removes duplicates, infers platform from account URLs, and applies the small pilot caps. If Feishu is unavailable or the user supplies inputs outside this Base, create a JSON file manually using [references/pilot-config.md](references/pilot-config.md).

### 3. Run collection

```bash
source ~/.zprofile
python3 scripts/pilot_monitor.py \
  --config <pilot-config.json> \
  --output-dir <output-directory>
```

The script reads `JUSTONE_API_TOKEN`, calls only the limited pilot endpoints, and writes:

- `raw/`: redacted raw responses for mapping and debugging.
- `normalized.json`: deduplicated cross-platform posts.
- `scored.json`: account-relative scoring results.
- `feishu_rows.json`: rows mapped to the current content library.
- `report.md`: decision-ready scan brief with scope, platform/source statistics, keyword performance, account anomalies, Top 10 items, data-quality notes, and evidence-bounded next steps.

Use `--fixtures-dir` for offline validation without network access or a token.

### 4. Review before publishing

Check `report.md` and `feishu_rows.json` for:

- Incorrect author or post IDs.
- Missing engagement fields.
- API pages that returned no recognizable post list.
- Douyin accounts whose latest works may be inaccessible.
- Scores based on fewer than 5 usable historical works.

If the API response shape changed, update only the normalizer in `pilot_monitor.py`; do not change scoring or Feishu fields until the raw sample proves it is necessary.

### 5. Publish to Feishu

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

### 6. Apply AI analysis selectively

Analyze no more than the top 5 pilot items. Prefer items that are:

- T2/T3 account anomalies.
- Discovered by both keyword and account monitoring.
- Recent and supported by multiple engagement fields.
- Clearly relevant to the user's stated direction.

Separate facts from inference. Output a concise summary, hook, topic, audience, up to 4 evidence-backed factors, reusable elements, non-reusable context, adapted ideas, confidence, and missing evidence. Write only verified source data and clearly labeled AI analysis to Feishu.

Append this analysis to `report.md` under `Top 5 AI 辅助拆解`, followed by 2-4 prioritized adapted topic ideas. Each item must label factual evidence, inferred structure, reusable elements, non-reusable context, confidence, and missing evidence. Do not leave the report as a metrics-only run log.

### 7. Ask for lightweight feedback

Ask the user to mark only one status per reviewed item: `值得跟进`, `继续观察`, `不相关`, or `已采用`. Use this feedback to tune keywords and account priority before increasing scan volume.

## Scaling gate

Do not increase volume until one pilot run has:

- Successful API responses from both platforms.
- Correct ID and metric mapping from real samples.
- Deduplication verified in Feishu.
- At least one human relevance review.
- A known daily call-cost estimate from the Just One API console.

After those checks, increase one dimension at a time: keywords, accounts, pages, then detail/comment calls.

## References

- [references/justoneapi.md](references/justoneapi.md): endpoint selection, paging, errors, and security.
- [references/scoring.md](references/scoring.md): interaction values and account-relative grades.
- [references/pilot-config.md](references/pilot-config.md): configuration schema and minimal example.
- [references/feishu-schema.md](references/feishu-schema.md): current Base, table IDs, and field ownership.
