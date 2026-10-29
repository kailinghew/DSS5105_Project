# Tool Specification: Deterministic Tool Layer

*No LLM in here, ever. Every number the agent says comes from one of these functions.*

All functions live in `desk/tools.py`. The same core (`allocate`, which calls `evaluate_all` + `rank_candidates`) is used by the chat agent (1 April view) and by the simulator policy in `desk/allocator.py` (1 Jan–Mar replay), so offline results describe the live policy. `?` marks an optional argument.

| Tool Name | Input | Output | Purpose | Non-goals | Failure Mode |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `get_order` | `order_id` | `order dict \| None` | Look up one order. | Fuzzy matching. | Unknown id -> `None` (agent must DECLINE). |
| `find_orders` | `customer?`, `product?`, `category?`, `in_progress_only` | `list of orders` | Resolve vague references ("the TrendCart order"). | Choosing one. | >1 match -> agent CLARIFIES. |
| `register_lookup` | `category`, `pieces` | `8 Candidates` (eligibility only) | Who can make it / is allowed / within cap, with reasons. | Dates. | None eligible -> IMPOSSIBLE/escalate. |
| `queue_check` | `workshop_id`, `queues?` | `days held` | Current backlog. | Forecasting future queue. | - |
| `estimate_eta` | `workshop_id`, `pieces`, `sent`, `due`, `queues?` | `Candidate` | Queue + work + expected rework + transport -> date, cost. | Stage-level timing. | Card values wrong. |
| `evaluate_all` | `category`, `pieces`, `sent`, `due`, `queues?` | `8 Candidates` | Eligibility + ETA for every shop in one call (UI table). | - | - |
| `overload_probe` | `workshop_id`, `pieces`, `queues?` | `dict` | Days this batch adds to the shop's queue = delay for the next batch sent there. | Re-planning other orders. | - |
| `rank_candidates` | `cands`, `objective`, `loaded?`, `total?`, `pieces?` | `ranked Candidates` | Score eligible shops under the configured objective. | - | - |
| `allocate` | `category`, `pieces`, `sent`, `due`, `queues`, `objective`, `constraints`, `loaded?`, `total?`, `eligible_ids?` | `(chosen id, all Candidates with scores)` | Apply constraints, then rank. | Deciding to ask/refuse (agent's job). | None eligible -> `(None, candidates)`; "cheapest/lowest-defect on time" with nobody on time -> picks earliest. |
| `earliest_possible` | `category`, `pieces`, `sent`, `due`, `queues?` | `Candidate \| None` | Earliest any eligible shop can deliver (IMPOSSIBLE replies). | - | None eligible -> `None`. |
| `split_options` | `category`, `pieces`, `sent`, `due`, `queues?` | `dict \| None` | Best two-shop split, sized by capacity. | Chat layer only — the simulator never splits. | Fewer than two eligible -> `None`. |