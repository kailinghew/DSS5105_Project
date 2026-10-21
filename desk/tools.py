"""
tools.py — the deterministic tool layer. No LLM in here, ever.

Every number the agent says comes from one of these functions. The same core
(`evaluate_all` + `rank_candidates`) is used by the chat agent (1 April view) and by the
simulator policy in allocator.py (1 Jan–Mar replay), so offline results describe the
live policy.

TOOL SPEC (copy into Documentation.pdf; keep in sync)
-----------------------------------------------------------------------------------------
name              input                             output                 purpose / non-goals / failure mode
get_order         order_id                          order dict | None      Look up one order. Non-goal: fuzzy matching.
                                                                           Failure: unknown id -> None (agent must DECLINE).
find_orders       customer?, product?, category?    list of orders         Resolve vague references ("the TrendCart order").
                  in_progress_only                                         Non-goal: choosing one. Failure: >1 match -> agent CLARIFIES.
register_lookup   category, pieces                  8 Candidates           Who can make it / is allowed / within cap, with reasons.
                                                    (eligibility only)     Non-goal: dates. Failure: none eligible -> IMPOSSIBLE/escalate.
queue_check       workshop_id, queues?              days held              Current backlog. Non-goal: forecasting future queue.
estimate_eta      workshop_id, pieces, sent, due,   Candidate              queue + work + expected rework + transport -> date, cost.
                  queues?                                                  Non-goal: stage-level timing. Failure: card values wrong.
evaluate_all      category, pieces, sent, due,      8 Candidates           Eligibility + ETA for every shop in one call (UI table).
                  queues?
overload_probe    workshop_id, pieces, queues?      dict                   Days this batch adds to the shop's queue = delay for the
                                                                           next batch sent there. Non-goal: re-planning other orders.
rank_candidates   candidates, objective, shares     ranked Candidates      Score eligible shops under the configured objective.
allocate          category, pieces, sent, due,      (chosen id, ranked)    Apply constraints, then rank. Non-goal: deciding to ask/refuse
                  queues, objective, constraints                           (agent's job). Failure: nothing on time -> picks earliest.
earliest_possible category, pieces, sent, due, q    Candidate              Earliest any eligible shop can deliver (IMPOSSIBLE replies).
split_options     category, pieces, sent, due, q    dict | None            Best two-shop split, sized by capacity. Chat layer only — the
                                                                           simulator never splits.
-----------------------------------------------------------------------------------------
"""
from __future__ import annotations

from datetime import date, timedelta
from itertools import combinations
from typing import Iterable, Optional

from .data import TODAY, eligible_workshops, orders, today_queues, workshops
from .schemas import Candidate, Constraint, ConstraintKind, Objective

REWORK_FACTOR = 0.5   # simulate.py: a defective batch redoes half its work


# ----------------------------------------------------------------------------- orders
def get_order(order_id: str) -> Optional[dict]:
    return orders().get(order_id.upper().strip())


def find_orders(customer: str | None = None, product: str | None = None,
                category: str | None = None, in_progress_only: bool = True) -> list[dict]:
    def match(field, want, row):
        if want is None:
            return True
        w = want.lower().rstrip("s")       # "vests" -> "vest"
        return w in row[field].lower()
    return [o for o in orders().values()
            if (not in_progress_only or o["status"] == "IN_PROGRESS")
            and match("customer", customer, o) and match("product", product, o)
            and (category is None or o["category"] == category)]


# ------------------------------------------------------------------------- workshops
def _why_not(w, category: str, pieces: int) -> list[str]:
    r = []
    if w.status != "ACTIVE":
        r.append(f"status {w.status}")
    if category not in w.makes:
        r.append(f"does not make {category} (makes {'+'.join(sorted(w.makes))})")
    if w.max_batch is not None and pieces > w.max_batch:
        r.append(f"batch of {pieces} exceeds its {w.max_batch}-piece cap")
    return r


def register_lookup(category: str, pieces: int) -> list[Candidate]:
    batch = {"category": category, "pieces": pieces}
    ok = {w.workshop_id for w in eligible_workshops(batch, workshops())}
    return [Candidate(w.workshop_id, w.name, w.workshop_id in ok, _why_not(w, category, pieces),
                      cost_per_piece=w.cost, defect_rate=w.defect_rate)
            for w in workshops().values()]


def queue_check(workshop_id: str, queues: dict | None = None) -> float:
    return (queues or today_queues())[workshop_id]


def estimate_eta(workshop_id: str, pieces: int, sent: date = TODAY, due: date | None = None,
                 queues: dict | None = None, category: str | None = None) -> Candidate:
    w = workshops()[workshop_id]
    q = queue_check(workshop_id, queues)
    work = pieces / w.capacity
    rework = work * REWORK_FACTOR * w.defect_rate
    eta = q + work + rework + w.lead_days
    eta_date = sent + timedelta(days=round(eta))
    c = Candidate(w.workshop_id, w.name, True,
                  queue_days=round(q, 2), work_days=round(work, 2), rework_days=round(rework, 2),
                  lead_days=w.lead_days, eta_days=round(eta, 2), eta_date=eta_date,
                  cost=round(pieces * w.cost, 2), cost_per_piece=w.cost, defect_rate=w.defect_rate)
    if category is not None:
        c.ineligible_reasons = _why_not(w, category, pieces)
        c.eligible = not c.ineligible_reasons
    if due is not None:
        c.slack_days = (due - eta_date).days
        c.meets_due = eta_date <= due
    return c


def evaluate_all(category: str, pieces: int, sent: date = TODAY, due: date | None = None,
                 queues: dict | None = None) -> list[Candidate]:
    return [estimate_eta(w_id, pieces, sent, due, queues, category) for w_id in workshops()]


def overload_probe(workshop_id: str, pieces: int, queues: dict | None = None) -> dict:
    w = workshops()[workshop_id]
    before = queue_check(workshop_id, queues)
    added = pieces / w.capacity
    return {"workshop_id": workshop_id, "queue_before_days": round(before, 2),
            "added_days": round(added, 2), "queue_after_days": round(before + added, 2),
            "meaning": f"the next batch sent to {w.name} would wait {round(before + added, 1)} days"}


# --------------------------------------------------------------------------- ranking
def rank_candidates(cands: list[Candidate], objective: Objective,
                    loaded: dict | None = None, total: float = 0.0,
                    pieces: int = 0) -> list[Candidate]:
    """Lower score is better. Each criterion is min-max normalised across the
    candidates so days, rates and dollars can be weighted together."""
    pool = [c for c in cands if c.eligible and c.excluded_by is None]
    if not pool:
        return []
    loaded = loaded or {}
    raw = {}
    for c in pool:
        late = max(0.0, -(c.slack_days or 0)) if c.slack_days is not None else c.eta_days
        share = (loaded.get(c.workshop_id, 0) + pieces) / (total + pieces) if pieces else 0.0
        raw[c.workshop_id] = {"late": late, "defect": c.defect_rate, "share": share,
                              "cost": c.cost_per_piece}

    def norm(k):
        vals = [v[k] for v in raw.values()]
        lo, hi = min(vals), max(vals)
        return {w: 0.0 if hi == lo else (v[k] - lo) / (hi - lo) for w, v in raw.items()}
    n = {k: norm(k) for k in ("late", "defect", "share", "cost")}
    wts = {"late": objective.w_late, "defect": objective.w_defect,
           "share": objective.w_share, "cost": objective.w_cost}
    for c in pool:
        c.score = round(sum(wts[k] * n[k][c.workshop_id] for k in wts), 4)
    pool.sort(key=lambda c: (c.score, c.eta_days, c.workshop_id))
    for i, c in enumerate(pool, 1):
        c.rank = i
    return pool


def allocate(category: str, pieces: int, sent: date, due: date, queues: dict | None,
             objective: Objective, constraints: Iterable[Constraint] = (),
             loaded: dict | None = None, total: float = 0.0,
             eligible_ids: set | None = None) -> tuple[Optional[str], list[Candidate]]:
    """Returns (chosen workshop id, all candidates with scores). Constraints win over
    the objective; the objective decides among what is left. `eligible_ids` lets the
    simulator policy pass the harness's own verdict (needed for --stages)."""
    cands = evaluate_all(category, pieces, sent, due, queues)
    if eligible_ids is not None:
        for c in cands:
            if c.eligible and c.workshop_id not in eligible_ids:
                c.eligible = False
                c.ineligible_reasons.append("does not cover the remaining stages")
    kinds = {}
    for k in constraints:
        kinds[k.kind] = k
        if k.kind == ConstraintKind.EXCLUDE_WORKSHOP:
            for c in cands:
                if c.workshop_id == k.value:
                    c.excluded_by = k.imposed_by or "unknown"
    ranked = rank_candidates(cands, objective, loaded, total, pieces)
    if not ranked:
        return None, cands
    on_time = [c for c in ranked if c.meets_due]
    if ConstraintKind.FASTEST in kinds:
        pick = min(ranked, key=lambda c: (c.eta_days, c.workshop_id))
    elif ConstraintKind.CHEAPEST_ON_TIME in kinds and on_time:
        pick = min(on_time, key=lambda c: (c.cost_per_piece, c.eta_days))
    elif ConstraintKind.LOWEST_DEFECT_ON_TIME in kinds and on_time:
        pick = min(on_time, key=lambda c: (c.defect_rate, c.eta_days))
    elif kinds.keys() & {ConstraintKind.CHEAPEST_ON_TIME, ConstraintKind.LOWEST_DEFECT_ON_TIME}:
        pick = min(ranked, key=lambda c: (c.eta_days, c.workshop_id))   # nobody on time
    else:
        pick = ranked[0]
    return pick.workshop_id, cands


def earliest_possible(category: str, pieces: int, sent: date = TODAY, due: date | None = None,
                      queues: dict | None = None) -> Optional[Candidate]:
    ok = [c for c in evaluate_all(category, pieces, sent, due, queues) if c.eligible]
    return min(ok, key=lambda c: (c.eta_days, c.workshop_id)) if ok else None


def split_options(category: str, pieces: int, sent: date = TODAY, due: date | None = None,
                  queues: dict | None = None) -> Optional[dict]:
    """Best two-shop split: pieces divided in proportion to capacity, finish = the later
    of the two. Returns None if fewer than two shops are eligible."""
    q = queues or today_queues()
    ws = workshops()
    best = None
    for a, b in combinations(ws.values(), 2):
        cap = a.capacity + b.capacity
        pa = round(pieces * a.capacity / cap)
        parts = [(a, pa), (b, pieces - pa)]
        cs = []
        for w, p in parts:
            c = estimate_eta(w.workshop_id, p, sent, due, q, category)
            if not c.eligible or p <= 0:
                break
            cs.append(c)
        else:
            finish = max(c.eta_days for c in cs)
            if best is None or finish < best["eta_days"]:
                best = {"parts": [{"workshop_id": c.workshop_id, "name": c.name,
                                   "pieces": p, "eta_date": c.eta_date.isoformat()}
                                  for c, (_, p) in zip(cs, parts)],
                        "eta_days": round(finish, 2),
                        "eta_date": (sent + timedelta(days=round(finish))).isoformat(),
                        "meets_due": None if due is None else sent + timedelta(days=round(finish)) <= due}
    return best
