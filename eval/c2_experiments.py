"""
c2_experiments.py — C2: try to beat the earliest-finish rule (owner: C).

    python -m eval.c2_experiments                 # normal + shock, 10 seeds
    python -m eval.c2_experiments --seeds 3       # quicker

Two candidate policies, run through the shared simulator next to the simple rule and
the shipped lateness objective:

    defect_tiebreak   lexicographic: lateness days first (0 when on time), then lower
                      defect rate, then earlier ETA. (Unconditional, unlike the next.)
    defect_tiebreak_eta  the rule's finish-time key, with the defect rate breaking only
                      exact finish-time ties.
    reserve_fast      keep the two fast shops (W1 QuickStitch, W6 Nimble Needle) spare
                      for urgent orders: comfortable orders are routed to the remaining
                      shops; urgent = due within 5 days, or the fastest shop would
                      finish with at most 3 days of slack.

Writes eval/results_c2.csv in the same schema as results_sim.csv.
"""
from __future__ import annotations

import argparse
import csv

from desk.allocator import earliest_finish_rule, load_objective, make_policy
from desk.data import ROOT
from desk.tools import evaluate_all, rank_candidates
from simulate import average_over_seeds, eligible_workshops

FAST = {"W1", "W6"}          # lead_days == 1: QuickStitch, Nimble Needle
URGENT_HORIZON = 5           # days from sent date to due date
URGENT_SLACK = 3             # fastest achievable slack that still counts as urgent


def _eligible_pool(batch, queues):
    return [c for c in evaluate_all(batch["category"], batch["pieces"],
                                    batch["sent_date"], batch["due_date"], queues)
            if c.eligible]


def defect_tiebreak(batch, workshops, queues):
    """Lateness first (0 if on time), then lower defect rate, then earlier ETA."""
    pool = _eligible_pool(batch, queues)
    pool.sort(key=lambda c: (max(0.0, -(c.slack_days or 0)), c.defect_rate,
                             c.eta_days, c.workshop_id))
    return pool[0].workshop_id


def defect_tiebreak_eta(batch, workshops, queues):
    """The earliest-finish rule, with the defect rate breaking exact finish ties."""
    ok = eligible_workshops(batch, workshops)

    def finish(w):
        return queues[w.workshop_id] + batch["pieces"] / w.capacity + w.lead_days

    return min(ok, key=lambda w: (finish(w), w.defect_rate, w.workshop_id)).workshop_id


def reserve_fast(batch, workshops, queues):
    """Non-urgent orders avoid the fast shops, leaving them free for urgent ones."""
    pool = _eligible_pool(batch, queues)
    horizon = (batch["due_date"] - batch["sent_date"]).days
    fastest_slack = min(c.slack_days or 0 for c in pool)
    urgent = horizon <= URGENT_HORIZON or fastest_slack <= URGENT_SLACK
    if not urgent:
        kept = [c for c in pool if c.workshop_id not in FAST]
        if kept:
            pool = kept
    ranked = rank_candidates(pool, load_objective())
    return ranked[0].workshop_id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=10)
    args = ap.parse_args()
    seeds = range(5105, 5105 + args.seeds)

    pols = {
        "rule_earliest": earliest_finish_rule,
        "desk_lateness": make_policy("lateness"),
        "defect_tiebreak": defect_tiebreak,
        "defect_tiebreak_eta": defect_tiebreak_eta,
        "reserve_fast": reserve_fast,
    }
    rows = []
    for shock in (False, True):
        res = average_over_seeds(pols, seeds, shock=shock)
        mode = "shock" if shock else "normal"
        print(f"\n{'SHOCK' if shock else 'NORMAL'} — mean over seeds {seeds.start}..{seeds.stop - 1}")
        from simulate import print_table
        print_table(res)
        rows += [{"mode": mode, "policy": p, **m} for p, m in res.items()]
    out = ROOT / "eval" / "results_c2.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
