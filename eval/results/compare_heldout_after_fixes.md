# Parser comparison: heldout_after_fixes (30 requests, model claude-haiku-5-5)

Columns: behaviour right / decision details right / explanation faithful.

| kind | n | regex | Claude |
|---|---|---|---|
| ambiguous | 4 | 4/4/4 | 4/4/4 |
| complete | 7 | 7/7/7 | 7/7/7 |
| constraint | 6 | 6/6/6 | 6/6/6 |
| impossible | 3 | 3/3/3 | 3/3/3 |
| ineligible | 4 | 4/4/4 | 4/4/4 |
| missing | 3 | 3/3/3 | 3/3/3 |
| unanswerable | 3 | 3/3/3 | 3/3/3 |
| TOTAL | 30 | 30/30/30 | 30/30/30 |

## Requests where the parsers differ or Claude fails

### R46 [ineligible] want refuse: regex refuse ok, Claude refuse ok

> R46 [11:09] Chen: Would Little Loom take ORD-107? Their quality is great.

- **regex**: `{"order_id": "ORD-107", "pieces": 2000, "due": "2026-03-16", "suggested": "W4", "missing": [], "question": null, "constraints": [], "candidates": 0}`
- **claude**: `{"order_id": "ORD-107", "pieces": 2000, "due": "2026-03-16", "suggested": "W4", "missing": [], "question": null, "constraints": ["prefer_workshop:W4@Chen"], "candidates": 0}`


Tokens for the Claude calls in this run (from the cache): 67,089 input, 2,775 output.