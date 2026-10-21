"""
run_inbox.py — score the desk on the 30 chat requests.

    python -m eval.run_inbox                 # baseline (regex) parser
    python -m eval.run_inbox --parser llm    # once parse_llm exists
    python -m eval.run_inbox --show          # print every reply

Scores, per request: behaviour correct? decision details correct (the 'expect' block)?
explanation faithful (no number that a tool did not produce)? Reported by kind.
Judge the decision and the explanation separately, as the brief requires.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from agent.desk_agent import handle_line
from agent.parse import parse_baseline, parse_llm
from desk.data import DATA, ROOT
from desk.explain import untraced_numbers

GOLD = json.loads((ROOT / "eval" / "gold_labels.json").read_text())


def check_details(dec, exp) -> list[str]:
    errs = []
    if "order_id" in exp and dec.request.order_id != exp["order_id"]:
        errs.append(f"order {dec.request.order_id} != {exp['order_id']}")
    if "chosen" in exp and dec.chosen != exp["chosen"]:
        errs.append(f"chose {dec.chosen}, expected {exp['chosen']}")
    if "not_chosen" in exp and dec.chosen == exp["not_chosen"]:
        errs.append(f"chose excluded {exp['not_chosen']}")
    if "on_time" in exp and dec.chosen:
        c = next(c for c in dec.candidates if c.workshop_id == dec.chosen)
        if bool(c.meets_due) != exp["on_time"]:
            errs.append("on-time mismatch")
    if "constraint" in exp and exp["constraint"] not in {k.kind.value for k in dec.request.constraints}:
        errs.append(f"missed constraint {exp['constraint']}")
    if "imposed_by" in exp and not any(k.imposed_by == exp["imposed_by"] for k in dec.request.constraints):
        errs.append(f"constraint not attributed to {exp['imposed_by']}")
    if "refused" in exp and (dec.facts.get("refused", {}).get("workshop") != exp["refused"]):
        errs.append(f"did not refuse {exp['refused']}")
    if "reason" in exp and exp["reason"] not in json.dumps(dec.facts, default=str) + (dec.request.question_type or ""):
        errs.append(f"reason '{exp['reason']}' not given")
    if "matches" in exp and len(dec.facts.get("matches", [])) != exp["matches"]:
        errs.append(f"{len(dec.facts.get('matches', []))} matches, expected {exp['matches']}")
    if "missing" in exp and exp["missing"] not in dec.request.missing:
        errs.append(f"did not flag missing {exp['missing']}")
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parser", choices=["baseline", "llm"], default="baseline")
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()
    parser = parse_llm if args.parser == "llm" else parse_baseline

    lines = [l for l in (DATA / "dispatch_requests.txt").read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#")]
    by_kind = defaultdict(lambda: [0, 0, 0, 0])   # n, behaviour ok, details ok, faithful
    fallbacks, warnings = 0, 0
    for line in lines:
        dec = handle_line(line, parser)
        fallbacks += dec.request.parser.endswith("(fallback)")
        warnings += bool(dec.request.warnings)
        if args.show and dec.request.warnings:
            print(f"   {dec.request_id} warnings: {dec.request.warnings}")
        g = GOLD[dec.request_id]
        beh_ok = dec.behaviour.value == g["behaviour"]
        errs = check_details(dec, g["expect"]) if beh_ok else ["wrong behaviour"]
        untraced = untraced_numbers(dec.explanation, dec)
        k = by_kind[g["kind"]]
        k[0] += 1; k[1] += beh_ok; k[2] += beh_ok and not errs; k[3] += not untraced
        flag = "OK " if beh_ok and not errs and not untraced else "XX "
        if args.show or flag == "XX ":
            print(f"{flag}{dec.request_id} want {g['behaviour']:<10} got {dec.behaviour.value:<10}"
                  f"{' | ' + '; '.join(errs) if errs else ''}{' | untraced ' + str(untraced) if untraced else ''}")
            if args.show:
                print("     " + dec.explanation)
    print(f"\n{'kind':<14}{'n':>4}{'behaviour':>11}{'decision':>10}{'faithful':>10}")
    tot = [0, 0, 0, 0]
    for kind, (n, b, d, f) in sorted(by_kind.items()):
        print(f"{kind:<14}{n:>4}{b:>11}{d:>10}{f:>10}")
        tot = [a + x for a, x in zip(tot, (n, b, d, f))]
    print(f"{'TOTAL':<14}{tot[0]:>4}{tot[1]:>11}{tot[2]:>10}{tot[3]:>10}")
    print(f"\nparser: {args.parser} · requests with validation warnings: {warnings} · "
          f"fell back to regex: {fallbacks}" + ("  <- LLM NOT USED, check API key" if fallbacks else ""))


if __name__ == "__main__":
    main()
