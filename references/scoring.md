# Scoring rules

## Interaction value

Use only metrics present in the response. Record which metrics were available.

Xiaohongshu:

```text
interaction = likes + 2 × collects + 2 × comments
```

Douyin:

```text
interaction = likes + 2 × collects + 3 × comments + 4 × shares
```

Do not treat an unavailable metric as observed zero.

## Account-relative ratio

For account-monitor results only:

```text
R = current interaction / median(other usable works from the same account)
```

- Use at most 20 comparison works.
- Require at least 5 usable comparison works.
- If the baseline is missing or zero, leave R blank and mark low confidence.
- Keyword-search results do not receive an account-relative grade unless account history is also present.

## Grades

Use a minimum evidence floor of `max(20, baseline × 2)`.

| Grade | Rule |
|---|---|
| T3 现象级 | `R >= 8` and evidence floor met |
| T2 爆款 | `R >= 4` and evidence floor met |
| T1 潜力 | `R >= 2` and evidence floor met |
| 虚高 | `R >= 2` but evidence floor not met |
| 普通 | usable baseline exists and `R < 2` |
| 新发现 | keyword result or insufficient history |

These labels prioritize review; they are not probabilities or guarantees.
