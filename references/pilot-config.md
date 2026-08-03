# Pilot configuration

Normally generate this UTF-8 JSON from Feishu with `scripts/build_config_from_feishu.py`. Use the manual form below only as a fallback. Keep the first run deliberately small.

```json
{
  "profile": {
    "direction": "面向创业者分享 AI 编程、AI 视频和自动化工具"
  },
  "pilot": {
    "max_keywords": 3,
    "max_accounts_per_platform": 2,
    "max_results_per_task": 8,
    "max_pages": 1
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
- Douyin account identifiers must be `secUid` in the pilot. Resolve names with user search before the scan.
- Values above the pilot caps are truncated and reported; they are not silently expanded.
- Keyword tasks retain at most 5 results even when `max_results_per_task` is higher. Account tasks may retain up to 8 so five comparison works remain available.
