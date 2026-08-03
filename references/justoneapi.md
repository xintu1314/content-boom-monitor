# Just One API integration

## Base URL and authentication

- Use `https://api.justoneapi.com`.
- Read the token from `JUSTONE_API_TOKEN`.
- Authentication is a `token` query parameter. Redact it from logs and saved requests.
- Use a 120-second request timeout.

## Pilot endpoints

| Purpose | Platform | Endpoint | Pilot parameters |
|---|---|---|---|
| Keyword boom search | Xiaohongshu | `/api/xiaohongshu/search-note/v4` | `sortType=popularity_descending`, `timeFilter=ONE_WEEK`, page 1 |
| Keyword boom search | Douyin | `/api/douyin/search-video/v4` | `sortType=_1` (likes most), `publishTime=_7`, page 1 |
| Account works | Xiaohongshu | `/api/xiaohongshu/get-user-note-list/v4` | `userId`, first cursor only |
| Account works | Douyin | `/api/douyin/get-user-video-list/v3` | `secUid`, `maxCursor=0` |

Use user-search V2 only to resolve an account name. Do not guess a creator when results are ambiguous.

Keyword monitoring searches for high-engagement posts matching the user's term. Keep the platform popularity/like ordering request, then rank normalized results by the available interaction value. Do not describe this path as new-topic discovery or trend detection.

## Business response handling

HTTP success is insufficient; require response `code == 0`.

| Code | Action |
|---|---|
| 0 | Process and persist |
| 100 | Stop; token invalid |
| 301 | Retry at most twice with backoff |
| 302 | Back off and retry later |
| 303 | Stop that endpoint for the day |
| 400 | Fix parameters; do not retry |
| 500 | Retry at most twice |
| 600 | Stop; permission missing |
| 601 | Stop; account balance insufficient |
| 602 | Stop; token spending limit reached |

Only `code == 0` requests are billed according to the public usage guide. Exact endpoint prices require the signed-in console.

## Response-schema limitation

The public OpenAPI files leave `data` untyped. Keep raw responses and use tolerant field extraction. Confirm real response samples before relying on any nested path.
