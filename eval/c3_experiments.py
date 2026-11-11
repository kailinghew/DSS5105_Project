"""
c3_experiments.py — C3: justify the hybrid weights (owner: C).

    python -m eval.c3_experiments

1. Runs the shipped hybrid (50/30/20) next to an alternative weighting (40/40/20),
   normal + shock, 10 seeds -> eval/results_c3.csv.
2. Replays the same 120 orders under lateness, fair, hybrid and the alternative on
   one seed and writes the per-workshop allocation shares -> eval/allocations_c3.csv.
"""
from __future__ import annotations

import csv
from collections import defaultdict

from desk.allocator import Policy, load_objective
from desk.data import ROOT
from desk.schemas import Objective
from simulate import Simulator, average_over_seeds

ALT = Objective("hybrid_40_40_20", w_late=0.4, w_defect=0.4, w_cost=0.2)


def main():
    seeds = range(5105, 5115)

    pols = {
        "desk_hybrid": Policy(load_objective("hybrid")),
        "hybrid_40_40_20": Policy(ALT),
    }
    rows = []
    for shock in (False, True):
        res = average_over_seeds(pols, seeds, shock=shock)
        from simulate import print_table
        print(f"\n{'SHOCK' if shock else 'NORMAL'} — mean over 10 seeds")
        print_table(res)
        rows += [{"mode": "shock" if shock else "normal", "policy": p, **m}
                 for p, m in res.items()]
    out = ROOT / "eval" / "results_c3.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out}")

    # allocation comparison on one deterministic replay (normal, seed 5105)
    compare = {
        "lateness": Policy(load_objective("lateness")),
        "fair": Policy(load_objective("fair")),
        "hybrid": Policy(load_objective("hybrid")),
        "hybrid_40_40_20": Policy(ALT),
    }
    sim = Simulator(seed=5105)
    for name, policy in compare.items():
        sim.run(policy, name)

    order_ids = sorted({w.workshop_id for w in sim.workshops.values()})
    alloc_rows = []
    for name in compare:
        by_w = defaultdict(int)
        for o in sim.results[name]:
            by_w[o["workshop"]] += o["pieces"]
        total = sum(by_w.values())
        alloc_rows.append({"policy": name,
                           **{w: by_w.get(w, 0) for w in order_ids},
                           "total": total})
    aout = ROOT / "eval" / "allocations_c3.csv"
    with open(aout, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["policy", *order_ids, "total"])
        w.writeheader()
        w.writerows(alloc_rows)
    print(f"wrote {aout}")


if __name__ == "__main__":
    main()
