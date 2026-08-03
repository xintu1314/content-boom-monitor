# Feishu content library

## Configuration

Create or choose a Feishu Base, then configure its identifiers outside the skill:

```bash
export CBM_FEISHU_BASE_TOKEN="<base-token>"
export CBM_FEISHU_KEYWORD_TABLE_ID="<keyword-table-id>"
export CBM_FEISHU_ACCOUNT_TABLE_ID="<account-table-id>"
export CBM_FEISHU_CONTENT_TABLE_ID="<content-table-id>"
```

The scripts also accept matching command-line flags. Never commit a real Base token or table ID to a public skill repository.

## Tables

| Table | ID | Ownership |
|---|---|---|
| 内容作品库 | `CBM_FEISHU_CONTENT_TABLE_ID` | Automation writes; user reviews `处理状态` |
| 监控关键词 | `CBM_FEISHU_KEYWORD_TABLE_ID` | User enters `关键词` and optional platform |
| 对标账号 | `CBM_FEISHU_ACCOUNT_TABLE_ID` | User pastes `主页链接`; name and platform are optional |

## Views and daily input

| Table | Daily view | Human-visible input |
|---|---|---|
| 内容作品库 | `重点内容` | Review evidence and update `处理状态` |
| 监控关键词 | `快速录入` | `关键词` and optional `监控平台`; blank means both platforms |
| 对标账号 | `快速录入` | `账号名称` (optional), `平台` (optional), and `主页链接` |

Each table also has a `系统数据` view containing all fields. Keep those fields for automation and debugging; do not require the user to fill them.

Generate the monitoring config from these two input tables with `scripts/build_config_from_feishu.py`. Manual JSON configuration is a fallback, not the default workflow.

## Content deduplication key

Use `平台 + 作品ID`. When `作品ID` is absent, do not write automatically until a stable canonical URL is available.

## Human-owned fields

- `处理状态`: `待评估`, `值得跟进`, `继续观察`, `不相关`, `已采用`.
- Optional seed input: keyword text or account homepage link.

All metrics, scan times, IDs, scores, AI summaries, and scan results are automation-owned.
