# Parser comparison: dev (30 requests, model claude-haiku-5-5)

Columns: behaviour right / decision details right / explanation faithful.

| kind | n | regex | Claude |
|---|---|---|---|
| ambiguous | 4 | 4/4/4 | 4/4/4 |
| complete | 7 | 7/7/7 | 7/7/7 |
| constraint | 6 | 6/6/6 | 6/6/6 |
| impossible | 3 | 3/3/3 | 3/3/3 |
| ineligible | 4 | 4/4/4 | 0/0/4 |
| missing | 3 | 3/3/3 | 3/3/3 |
| unanswerable | 3 | 3/3/3 | 3/3/3 |
| TOTAL | 30 | 30/30/30 | 26/26/30 |

## Requests where the parsers differ or Claude fails

### R03 [ambiguous] want clarify: regex clarify ok, Claude clarify ok

> R03 [08:03] Priya: Can we get the TrendCart order moving? They are chasing.

- **regex**: `{"order_id": null, "pieces": null, "due": null, "suggested": null, "missing": ["order"], "question": null, "constraints": [], "candidates": 6}`
- **claude**: `{"order_id": null, "pieces": null, "due": null, "suggested": null, "missing": ["pieces", "due_date", "order"], "question": null, "constraints": [], "candidates": 6}`

### R08 [ineligible] want refuse: regex refuse ok, Claude clarify FAIL

> R08 [08:29] Priya: Send ORD-073 (400 hoodies) to FreshStart, their quote was good.

- **regex**: `{"order_id": "ORD-073", "pieces": 400, "due": "2026-04-20", "suggested": "W8", "missing": [], "question": null, "constraints": [], "candidates": 0}`
- **claude**: `{"order_id": "ORD-073", "pieces": 400, "due": null, "suggested": "W8", "missing": ["due_date"], "question": null, "constraints": [], "candidates": 0}` — wrong behaviour: clarify

### R11 [ineligible] want refuse: regex refuse ok, Claude clarify FAIL

> R11 [08:44] Chen: OldMill is free right now — give them ORD-008.

- **regex**: `{"order_id": "ORD-008", "pieces": 600, "due": "2026-04-09", "suggested": "W7", "missing": [], "question": null, "constraints": [], "candidates": 0}`
- **claude**: `{"order_id": "ORD-008", "pieces": null, "due": null, "suggested": "W7", "missing": ["pieces", "due_date"], "question": null, "constraints": [], "candidates": 0}` — wrong behaviour: clarify

### R14 [ineligible] want refuse: regex refuse ok, Claude clarify FAIL

> R14 [08:59] Boss: QuickStitch for the scarves on ORD-103?

- **regex**: `{"order_id": "ORD-103", "pieces": 2000, "due": "2026-04-04", "suggested": "W1", "missing": [], "question": null, "constraints": [], "candidates": 0}`
- **claude**: `{"order_id": "ORD-103", "pieces": null, "due": null, "suggested": "W1", "missing": ["pieces", "due_date"], "question": null, "constraints": [], "candidates": 0}` — wrong behaviour: clarify

### R15 [ambiguous] want clarify: regex clarify ok, Claude clarify ok

> R15 [09:03] Mei: Boss wants the Loom & Leaf stuff outside asap.

- **regex**: `{"order_id": null, "pieces": null, "due": null, "suggested": null, "missing": ["order"], "question": null, "constraints": [], "candidates": 6}`
- **claude**: `{"order_id": null, "pieces": null, "due": null, "suggested": null, "missing": ["pieces", "due_date", "order"], "question": null, "constraints": [], "candidates": 6}`

### R19 [ambiguous] want clarify: regex clarify ok, Claude clarify ok

> R19 [09:23] Boss: That big reorder from last week — send it to whoever is quickest.

- **regex**: `{"order_id": null, "pieces": null, "due": null, "suggested": null, "missing": ["order"], "question": null, "constraints": ["fastest:@Boss"], "candidates": 0}`
- **claude**: `{"order_id": null, "pieces": null, "due": null, "suggested": null, "missing": ["pieces", "due_date", "order"], "question": null, "constraints": ["fastest:@Boss"], "candidates": 0}`

### R23 [constraint] want allocate: regex allocate ok, Claude allocate ok

> R23 [09:44] Priya: ORD-005 — 500 scarves for TrendCart, due Apr 20. Split it across two shops if that gets it back faster.

- **regex**: `{"order_id": "ORD-005", "pieces": 500, "due": "2026-04-20", "suggested": null, "missing": [], "question": null, "constraints": ["split_allowed:@Priya"], "candidates": 0}`
- **claude**: `{"order_id": "ORD-005", "pieces": 500, "due": "2026-04-20", "suggested": null, "missing": [], "question": null, "constraints": ["split_allowed:@Priya", "fastest:@Priya"], "candidates": 0}`

### R24 [ineligible] want refuse: regex refuse ok, Claude clarify FAIL

> R24 [09:48] Boss: Little Loom does lovely work — ORD-015 to them?

- **regex**: `{"order_id": "ORD-015", "pieces": 300, "due": "2026-04-16", "suggested": "W4", "missing": [], "question": null, "constraints": [], "candidates": 0}`
- **claude**: `{"order_id": "ORD-015", "pieces": null, "due": null, "suggested": "W4", "missing": ["pieces", "due_date"], "question": null, "constraints": [], "candidates": 0}` — wrong behaviour: clarify

### R29 [ambiguous] want clarify: regex clarify ok, Claude clarify ok

> R29 [10:14] Boss: The vests need to go out this week — who takes them?

- **regex**: `{"order_id": null, "pieces": null, "due": null, "suggested": null, "missing": ["order"], "question": null, "constraints": [], "candidates": 6}`
- **claude**: `{"order_id": null, "pieces": null, "due": null, "suggested": null, "missing": ["pieces", "due_date", "order"], "question": null, "constraints": [], "candidates": 6}`


Tokens for the Claude calls in this run (from the cache): 62,359 input, 2,834 output.