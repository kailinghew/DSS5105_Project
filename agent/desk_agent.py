"""
desk_agent.py — ParsedRequest -> Decision. Deterministic routing over the tools.

The LLM parses (agent/parse.py) and may later rephrase the explanation, but the
behaviour, the candidates and every number come from here and the tools.

    from agent.desk_agent import handle_line
    decision = handle_line("R07 [08:23] Ravi: ORD-063 — 100 cardigans. ...")
"""
from __future__ import annotations

from datetime import date
from typing import Callable

from desk.allocator import load_objective
from desk.data import TODAY, workshops
from desk.explain import fmt_date
from desk.schemas import Behaviour, ConstraintKind, Decision, Objective, ParsedRequest
from desk.tools import (allocate, earliest_possible, estimate_eta, get_order, overload_probe,
                        split_options)

from .parse import parse_baseline


def handle_line(line: str, parser: Callable[[str], ParsedRequest] = parse_baseline,
                objective: Objective | None = None) -> Decision:
    return handle(parser(line), objective)


def handle(req: ParsedRequest, objective: Objective | None = None) -> Decision:
    obj = objective or load_objective()
    dec = Decision(req.request_id, Behaviour.DECLINE, req, obj.name)

    # 1. unanswerable from this data -------------------------------------------------
    if req.question_type:
        why = {"history": "this system holds no record of past allocations",
               "price": "this system holds no quotes or customer prices, only workshop cost per piece",
               "unknown_order": f"{req.order_id} is not in the order register"}[req.question_type]
        dec.explanation = f"I can't answer that: {why}."
        return dec

    # 2. ambiguous or incomplete -> ask ---------------------------------------------------
    if req.missing or not req.order_id:
        dec.behaviour = Behaviour.CLARIFY
        need = {"pieces": "the quantity", "due_date": "the confirmed due date",
                "order": "which order this is"}
        asks = [need[m] for m in req.missing if not (m == "order" and req.candidate_orders)]
        parts = []
        if req.candidate_orders:
            dec.facts = {"matches": req.candidate_orders, "n_matches": len(req.candidate_orders)}
            parts.append(f"{len(req.candidate_orders)} open orders match "
                         f"({', '.join(req.candidate_orders)}): which one do you mean?")
        if asks:
            parts.append("Please confirm " + " and ".join(asks) + ".")
        dec.question = " ".join(parts) + " I won't allocate until then."
        dec.explanation = dec.question
        return dec

    order = get_order(req.order_id)
    cat, pieces, due = order["category"], req.pieces, req.due_date
    dec.facts = {"order_id": order["order_id"], "pieces": pieces, "due": due,
                 "order_pieces": order["pieces"], "today": TODAY}

    chosen, cands = allocate(cat, pieces, TODAY, due, None, obj, req.constraints)
    dec.candidates = cands
    dec.facts["candidates"] = {c.workshop_id: {"eta": c.eta_date, "eta_days": c.eta_days,
                                               "cost": c.cost, "cost_per_piece": c.cost_per_piece,
                                               "defect_rate": c.defect_rate,
                                               "defect_pct": round(100 * c.defect_rate),
                                               "queue_days": c.queue_days, "slack": c.slack_days}
                               for c in cands if c.eligible}
    best = next((c for c in cands if c.workshop_id == chosen), None)

    # 3. suggested workshop that can't take it -> refuse ----------------------------------
    if req.suggested_workshop:
        s = next(c for c in cands if c.workshop_id == req.suggested_workshop)
        if not s.eligible:
            dec.behaviour = Behaviour.REFUSE
            dec.alternative = chosen
            dec.facts["refused"] = {"workshop": s.workshop_id, "reasons": s.ineligible_reasons}
            why = f"{s.name} can't take {order['order_id']}: {'; '.join(s.ineligible_reasons)}."
            if best is None:
                dec.explanation = why + " No other workshop can take it either."
            elif best.meets_due:
                dec.explanation = (why + f" Instead I suggest {best.name}: ready about {fmt_date(best.eta_date)}"
                                   f" (on time for {fmt_date(due)}), ${best.cost:,.0f}.")
            else:
                # the alternative is late too: say so, with the same options as an impossible date
                early = _late_options(dec, cat, pieces, due)
                dec.alternative = early.workshop_id
                dec.explanation = (why + f" No other workshop can make {fmt_date(due)} either:"
                                   f" the earliest single workshop is {early.name}, about {fmt_date(early.eta_date)}."
                                   f" Options: " + "; ".join(dec.options) + ".")
            return dec
        if s.excluded_by is None:          # eligible suggestion: honour it
            best, chosen = s, s.workshop_id

    if best is None:
        dec.behaviour = Behaviour.IMPOSSIBLE
        dec.options = ["escalate to a human"]
        dec.explanation = f"No eligible workshop can take {pieces} pcs of {order['product'].lower()}."
        return dec

    # 4. nobody can make the date -> impossible, with numbers and options ------------------
    split = split_options(cat, pieces, TODAY, due) if not best.meets_due or any(
        k.kind == ConstraintKind.SPLIT_ALLOWED for k in req.constraints) else None
    if not best.meets_due and not (split and split["meets_due"]):
        early = _late_options(dec, cat, pieces, due, split)
        dec.behaviour = Behaviour.IMPOSSIBLE
        dec.alternative = early.workshop_id
        overdue = " It is already overdue." if due < TODAY else ""
        dec.explanation = (f"No workshop can deliver {order['order_id']} by {fmt_date(due)}.{overdue}"
                           f" The earliest single workshop is {early.name}, about {fmt_date(early.eta_date)}."
                           f" Options: " + "; ".join(dec.options) + ".")
        return dec

    # 5. allocate ------------------------------------------------------------------------
    dec.behaviour = Behaviour.ALLOCATE
    dec.chosen = chosen
    if split and split["meets_due"] and split["eta_days"] < best.eta_days and any(
            k.kind == ConstraintKind.SPLIT_ALLOWED for k in req.constraints):
        dec.split = split["parts"]
        dec.facts["split"] = split
    probe = overload_probe(chosen, pieces)
    dec.facts["probe"] = probe
    eligible = [c for c in cands if c.eligible]
    dec.facts["n_eligible"], dec.facts["n_workshops"] = len(eligible), len(cands)
    constraint_txt = "".join(
        f" Honoured {k.imposed_by}'s instruction ({k.source_text.strip()})." for k in req.constraints)
    excluded = [c for c in cands if c.excluded_by]
    if dec.split:
        dec.explanation = (
            f"Split {order['order_id']} ({pieces} pcs, {order['product'].lower()}): "
            + " + ".join(f"{p['pieces']} to {p['name']}" for p in dec.split)
            + f", all back by about {fmt_date(date.fromisoformat(split['eta_date']))} vs due {fmt_date(due)}"
            f" (one shop alone, {best.name}: {fmt_date(best.eta_date)})."
            + constraint_txt)
        return dec
    dec.explanation = (
        f"Send {order['order_id']} ({pieces} pcs, {order['product'].lower()}) to {best.name}:"
        f" ready about {fmt_date(best.eta_date)} vs due {fmt_date(due)},"
        f" ${best.cost:,.0f} at ${best.cost_per_piece:.2f}/pc, defect rate {round(100 * best.defect_rate)}%."
        f" {len(eligible)} of {len(cands)} workshops were eligible"
        + (f"; excluded {', '.join(c.name for c in excluded)}" if excluded else "") + "."
        + constraint_txt)
    return dec


def _late_options(dec: Decision, cat: str, pieces: int, due: date, split: dict | None = None):
    """When no single workshop can make the date: record the earliest achievable date and
    the three options (accept lateness, split, escalate) in dec.facts / dec.options.
    Returns the earliest candidate."""
    early = earliest_possible(cat, pieces, TODAY, due)
    if split is None:
        split = split_options(cat, pieces, TODAY, due)
    dec.facts["earliest"] = {"workshop": early.workshop_id, "eta": early.eta_date,
                             "days_late": -early.slack_days}
    dec.facts["split"] = split
    dec.options = [f"accept lateness: {early.name} by {fmt_date(early.eta_date)}"
                   f" ({-early.slack_days} days late)",
                   *([f"split {' + '.join(str(p['pieces']) + ' to ' + p['name'] for p in split['parts'])},"
                      f" done by {fmt_date(date.fromisoformat(split['eta_date']))}"
                      f"{'' if split['meets_due'] else ' (still late)'}"]
                     if split else []),
                   "escalate: renegotiate the date with the customer"]
    return early
