# Parser comparison: dev_v2 (30 requests, model claude-haiku-5-5)

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

### R23 [constraint] want allocate: regex allocate ok, Claude allocate ok

> R23 [09:44] Priya: ORD-005 — 500 scarves for TrendCart, due Apr 20. Split it across two shops if that gets it back faster.

- **regex**: `{"order_id": "ORD-005", "pieces": 500, "due": "2026-04-20", "suggested": null, "missing": [], "question": null, "constraints": ["split_allowed:@Priya"], "candidates": 0}`
- **claude**: `{"order_id": "ORD-005", "pieces": 500, "due": "2026-04-20", "suggested": null, "missing": [], "question": null, "constraints": ["split_allowed:@Priya", "fastest:@Priya"], "candidates": 0}`


Tokens for the Claude calls in this run (from the cache): 67,219 input, 2,824 output.