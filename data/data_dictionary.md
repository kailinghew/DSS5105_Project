# Data Dictionary — Track 2 (The Quick-Response Subcontracting Desk)

Two small, clean CSV files plus the chat inbox. The CSVs have no missing values and no
traps — every number can be taken at face value, and the only join is `order_id` (a chat
request names an order; the rest of its details are in `orders.csv`). The chat inbox is
deliberately *not* clean: it is the input your system must handle.

"Today" in the dataset is **2026-04-01**. Garments move through four stages:
**KNITTING → ASSEMBLY → WASHING → PACKING**.

| File | Rows | One row is |
|---|---|---|
| `orders.csv` | 120 | One customer order |
| `workshops.csv` | 8 | One outside workshop's profile card |
| `dispatch_requests.txt` | 30 | One allocation request, exactly as typed in the group chat |
| `orders_stages.csv`, `workshops_stages.csv` | 120 / 8 | **Optional** stage extension — the same rows plus one column each (see the end) |

## `orders.csv`

| Column | Meaning |
|---|---|
| `order_id` | `ORD-001` … |
| `customer`, `product` | Who ordered it and what it is |
| `category` | `TOPS` (sweaters, hoodies, …) or `ACCESSORIES` (beanies, scarves) |
| `pieces` | How many garments |
| `order_date`, `due_date` | When it was placed and when it is due |
| `status` | `COMPLETE` or `IN_PROGRESS` |
| `current_stage` | `KNITTING` / `ASSEMBLY` / `WASHING` / `PACKING` / `COMPLETE` |
| `last_activity_date` | The last day any work was recorded on this order |
| `completed_date` | When it finished (blank if still in progress) |
| `days_late` | `completed_date − due_date`; negative means early; blank if in progress |

`status`, `current_stage`, `last_activity_date`, `completed_date` and `days_late` describe
what happened **inside the factory**. The chat inbox is about the orders that are still
`IN_PROGRESS` on 1 April. The **simulator ignores these columns**: it is a
"what if every one of these 120 orders had gone outside on its `order_date`?" replay.
Promised windows in this dataset run from 14 to 35 days.

## `workshops.csv`

The eight outside workshops that batches can be sent to. This file **is** the simulator's
model of each workshop — what you see is what you get. It answers the dispatcher's three
questions: *can they make it* (`makes`), *can they take it now* (`capacity_pieces_per_day`,
`current_queue_days`), and *are they allowed to* (`status`, `max_batch_pieces`).

| Column | Meaning |
|---|---|
| `workshop_id`, `name` | `W1` … `W8` and a memorable name |
| `capacity_pieces_per_day` | How much it can process per day; work beyond this queues |
| `pickup_lead_days` | Fixed transport overhead per batch |
| `defect_rate` | Chance a batch comes back defective and is partly redone |
| `cost_per_piece` | What it charges |
| `makes` | `TOPS`, `ACCESSORIES`, or `TOPS+ACCESSORIES` — what it is equipped for |
| `status` | `ACTIVE`, or `SUSPENDED` (failed a quality audit — may not take new work) |
| `max_batch_pieces` | Per-batch cap (workshops on trial); blank means no cap |
| `current_queue_days` | Days of work it is already holding on the morning of **2026-04-01** ("today") — see the note below |
| `notes` | The one-line reputation a human dispatcher would give it |

> **One column, two dates.** For the **chat inbox**, read `current_queue_days` as the
> queue on the morning of **2026-04-01** — the same morning as the inbox. The
> **simulator** reuses the same numbers as its starting queue on **2026-01-01**, so that
> every team starts from the same place. Treat the two separately; don't work out one
> from the other.

## `dispatch_requests.txt`

Thirty allocation requests from the morning's group chat, one per line, written the way
people actually type: `R07 [08:23] Ravi: ORD-063 — 100 cardigans. No special requirements,
just make Apr 29.` Your system's behaviour on every one of them is part of the Track 2
evaluation — see the track description. The mix, so you can check your own labelling
(which request is which kind is for you to work out):

| Kind | How many | The right behaviour |
|---|---|---|
| Complete and meetable | 7 | Extract, allocate, explain |
| Complete but **impossible** | 3 | No workshop can make the date (one order is already overdue). Say so with the numbers, give the earliest achievable date and the options — do not silently allocate |
| Carries a constraint | 6 | Honour it ("keep it away from BudgetWorks", "cheapest that still makes the date") and record who imposed it |
| Ambiguous | 4 | Several orders match — ask, do not guess |
| Missing a number or date | 3 | Ask for it |
| Suggests a workshop that cannot take it | 4 | Refuse with the reason, offer an alternative |
| Unanswerable from this data | 3 | Say so, do not invent |

Dates in the inbox are relative to **2026-04-01**, and the queues to use are the
`current_queue_days` in `workshops.csv` (see the note above).

## Optional: the stage extension (`orders_stages.csv`, `workshops_stages.csv`)

Nothing in the default track needs these two files. They exist for teams who want the
workshops to differ in *which stages* they can do, and they are used only when you run
`simulate.py --stages`. Each is the original file, row for row, plus one column:

| File | Extra column | Meaning |
|---|---|---|
| `orders_stages.csv` | `dispatch_stage` | The stage the order is at when it goes outside. For in-progress orders it equals `current_stage`; for completed orders it is synthetic |
| `workshops_stages.csv` | `stages` | The stages the workshop is equipped for, e.g. `WASHING+PACKING` for a finishing house |

> **One column, two dates — again.** For the **chat inbox** (1 April), `dispatch_stage`
> is simply where the order stands that morning: for every in-progress order it equals
> `current_stage`, so the inbox and the stage files agree. The **simulator** replays each
> order on its `order_date` (January to March) and reuses the same column as "the stage
> from which the workshop takes this batch over" — it does not claim the order had already
> reached that stage on its order date. Same convention as `current_queue_days`: treat the
> two readings separately.

The rule is a fourth eligibility question: a workshop can take a batch only if it covers
**every stage from `dispatch_stage` through PACKING**. One batch still goes to one
workshop, and the work is still `pieces / capacity` whatever the stage — a deliberate
simplification. If you use the extension, say so in your report: your numbers are then
comparable with other `--stages` teams, not with the default run.
