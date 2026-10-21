"""
run_sim.py — every policy through the shared simulator, normal and --shock, 10 seeds.

    python -m eval.run_sim                  # all objectives + baselines + the rule
    python -m eval.run_sim --seeds 3        # quicker
    python -m eval.run_sim --stages         # optional extension (report separately!)

Writes eval/results_sim.csv for the report.
"""
from __future__ import annotations

import argparse
import csv
import json

from desk.allocator import CONFIG, earliest_finish_rule, make_policy
from desk.data import ROOT
from simulate import average_over_seeds, cheapest, greedy_biggest, print_table, random_choice


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--stages", action="store_true")
    args = ap.parse_args()
    seeds = range(5105, 5105 + args.seeds)

    pols = {"random": random_choice, "greedy_biggest": greedy_biggest, "cheapest": cheapest,
            "rule_earliest": earliest_finish_rule}
    for name in json.loads(CONFIG.read_text())["objectives"]:
        pols[f"desk_{name}"] = make_policy(name)

    rows = []
    for shock in (False, True):
        print(f"\n{'SHOCK' if shock else 'NORMAL'} — mean over seeds {seeds.start}..{seeds.stop - 1}")
        res = average_over_seeds(pols, seeds, shock=shock, stages=args.stages)
        print_table(res)
        rows += [{"mode": "shock" if shock else "normal", "policy": p, **m} for p, m in res.items()]
    out = ROOT / "eval" / ("results_sim_stages.csv" if args.stages else "results_sim.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
