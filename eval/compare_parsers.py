"""
compare_parsers.py — Claude Haiku vs the regex baseline, request by request (owner: A).

    python -m eval.compare_parsers                          # the 30 dev requests   (A1, A2)
    python -m eval.compare_parsers --file eval/heldout.txt \\
        --labels eval/heldout_labels.json --name heldout    # B's held-out set     (A4, run ONCE)

For every request both parsers go through the same agent and are scored against the
gold labels with the same checks as run_inbox: right behaviour, right decision details,
faithful explanation (no untraced numbers). Prints a per-kind table and every request
where the two parsers disagree, and writes eval/results/compare_<name>.md (paste into the
report) and .json. Refuses to run if Claude is unavailable, so a regex-vs-regex table can
never be mistaken for a result.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from agent import llm
from agent.desk_agent import handle_line
from agent.parse import LLM_SCHEMA, llm_system_prompt, parse_baseline, parse_llm
from desk.data import DATA, ROOT
from desk.explain import untraced_numbers
from eval.run_inbox import check_details

OUT = ROOT / "eval" / "results"


def score(dec, gold) -> dict:
    beh_ok = dec.behaviour.value == gold["behaviour"]
    errs = check_details(dec, gold["expect"]) if beh_ok else [f"wrong behaviour: {dec.behaviour.value}"]
    untraced = untraced_numbers(dec.explanation, dec)
    r = dec.request
    return {
        "behaviour": dec.behaviour.value, "behaviour_ok": beh_ok, "decision_ok": beh_ok and not errs,
        "faithful": not untraced, "errors": errs, "untraced": untraced, "warnings": r.warnings,
        "extracted": {"order_id": r.order_id, "pieces": r.pieces, "due": str(r.due_date) if r.due_date else None,
                      "suggested": r.suggested_workshop, "missing": r.missing, "question": r.question_type,
                      "constraints": [f"{c.kind.value}:{c.value or ''}@{c.imposed_by}" for c in r.constraints],
                      "candidates": len(r.candidate_orders)},
        "chosen": dec.chosen, "reply": dec.explanation,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(DATA / "dispatch_requests.txt"))
    ap.add_argument("--labels", default=str(ROOT / "eval" / "gold_labels.json"))
    ap.add_argument("--name", default="dev")
    args = ap.parse_args()

    gold = json.loads(Path(args.labels).read_text())
    lines = [l for l in Path(args.file).read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#")]
    missing = [l.split()[0] for l in lines if l.split()[0] not in gold]
    if missing:
        raise SystemExit(f"no gold label for {missing} in {args.labels}")

    def claude(line):
        return parse_llm(line, fallback=False)

    rows, tokens = [], [0, 0]
    model = llm.settings()["model"]
    for line in lines:
        rid = line.split()[0]
        try:
            d_llm = handle_line(line, claude)
        except llm.LLMError as e:
            raise SystemExit(f"Claude unavailable ({e}). Run  python -m eval.check_llm  first.")
        d_rx = handle_line(line, parse_baseline)
        g = gold[rid]
        rows.append({"id": rid, "kind": g["kind"], "want": g["behaviour"], "line": line,
                     "regex": score(d_rx, g), "claude": score(d_llm, g)})
        rec = llm.CACHE_DIR / f"{llm.cache_key(model, llm_system_prompt(), line.strip(), LLM_SCHEMA)}.json"
        if rec.exists():
            u = json.loads(rec.read_text()).get("usage", {})
            tokens[0] += u.get("input_tokens", 0); tokens[1] += u.get("output_tokens", 0)

    # ---- per-kind table
    agg = defaultdict(lambda: {"n": 0, "regex": [0, 0, 0], "claude": [0, 0, 0]})
    for r in rows:
        for k in (r["kind"], "TOTAL"):
            a = agg[k]
            a["n"] += 1
            for p in ("regex", "claude"):
                s = r[p]
                a[p][0] += s["behaviour_ok"]; a[p][1] += s["decision_ok"]; a[p][2] += s["faithful"]
    order = sorted(k for k in agg if k != "TOTAL") + ["TOTAL"]
    md = [f"# Parser comparison: {args.name} ({len(rows)} requests, model {model})", "",
          "Columns: behaviour right / decision details right / explanation faithful.", "",
          "| kind | n | regex | Claude |", "|---|---|---|---|"]
    print(f"\n{'kind':<14}{'n':>3}   {'regex (beh/dec/faith)':>22}   {'Claude (beh/dec/faith)':>23}")
    for k in order:
        a = agg[k]
        rx, cl = "/".join(map(str, a["regex"])), "/".join(map(str, a["claude"]))
        print(f"{k:<14}{a['n']:>3}   {rx:>22}   {cl:>23}")
        md.append(f"| {k} | {a['n']} | {rx} | {cl} |")

    # ---- disagreements and failures
    md += ["", "## Requests where the parsers differ or Claude fails", ""]
    print("\nwhere they differ or Claude fails:")
    for r in rows:
        rx, cl = r["regex"], r["claude"]
        if rx["decision_ok"] == cl["decision_ok"] and cl["decision_ok"] and cl["faithful"] \
                and rx["extracted"] == cl["extracted"]:
            continue
        head = (f"{r['id']} [{r['kind']}] want {r['want']}: regex {rx['behaviour']}"
                f"{' ok' if rx['decision_ok'] else ' FAIL'}, Claude {cl['behaviour']}{' ok' if cl['decision_ok'] else ' FAIL'}")
        print(" " + head)
        md += [f"### {head}", "", f"> {r['line']}", ""]
        for p in ("regex", "claude"):
            s = r[p]
            detail = f"{p}: {json.dumps(s['extracted'])}"
            extra = "; ".join(s["errors"] + [f"untraced {s['untraced']}" if s["untraced"] else ""] +
                              [f"warnings {s['warnings']}" if s["warnings"] else ""]).strip("; ")
            print(f"     {detail}" + (f"\n       -> {extra}" if extra else ""))
            md.append(f"- **{p}**: `{json.dumps(s['extracted'])}`" + (f" — {extra}" if extra else ""))
        md.append("")

    md += ["", f"Tokens for the Claude calls in this run (from the cache): {tokens[0]:,} input, "
           f"{tokens[1]:,} output."]
    print(f"\ntokens (from cache): {tokens[0]:,} in, {tokens[1]:,} out")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"compare_{args.name}.md").write_text("\n".join(md), encoding="utf-8")
    (OUT / f"compare_{args.name}.json").write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
    print(f"wrote eval/results/compare_{args.name}.md and .json")


if __name__ == "__main__":
    main()
