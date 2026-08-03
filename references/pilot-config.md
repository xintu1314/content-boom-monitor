# Run configuration

Normally generate this UTF-8 JSON from Feishu with `scripts/build_config_from_feishu.py`. Use the manual form below only as a fallback. Use `pilot` for the first validation and `production` after the pipeline has passed its scaling gate.

```json
{
  "mode": "production",
  "profile": {
    "direction": "面向创业者分享 AI 编程、AI 视频和自动化工具"
  },
  "limits": {
    "max_keywords": 20,
    "max_accounts_per_platform": 20,
    "max_results_per_task": 8,
    "max_pages": 1
  },
  "analysis": {
    "max_items": 10
  },
  "keywords": [
    {
      "term": "AI创业",
      "platforms": ["xiaohongshu", "douyin"]
    }
  ],
  "accounts": [
    {
      "platform": "xiaohongshu",
      "name": "示例账号",
      "id_or_url": "https://www.xiaohongshu.com/user/profile/..."
    },
    {
      "platform": "douyin",
      "name": "示例账号",
      "id_or_url": "MS4wLjAB..."
    }
  ]
}
```

## Rules

- `platforms` values: `xiaohongshu`, `douyin`.
- A keyword without `platforms` runs on both platforms.
- Xiaohongshu account identifiers may be a user ID or `/user/profile/` URL.
- Douyin account identifiers must be `secUid`. Resolve names with user search before the scan.
- `production` reads all enabled targets emitted by the Feishu config builder. `max_keywords` and `max_accounts_per_platform` document the generated scope; per-task result and page limits remain enforced.
- `pilot` truncates values above its caps and reports the truncation; it does not silently expand.
- Keyword tasks retain at most 5 results even when `max_results_per_task` is higher. Account tasks may retain up to 8 so five comparison works remain available.
- `analysis.max_items` defaults to 5 in pilot and 10 in production. It limits semantic analysis, not collection.
