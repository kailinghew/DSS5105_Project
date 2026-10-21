"""
simulate.py — the shared evaluation harness for Track 2 (subcontractor allocation).

Every team runs its allocator through this file, so the numbers in your report are
comparable with everybody else's. The whole thing is ~350 lines, a quarter of it this
note — read it once and you will understand exactly how your system is being scored.

WHAT IT DOES

It replays the orders in data/orders.csv, one by one in date order, and asks your
allocator to choose a workshop for each. Each workshop behaves according to its
profile card in data/workshops.csv:

    * it can only make what it is equipped for (`makes` vs the order's `category`)
    * it may be unavailable (`status` = SUSPENDED) or capped (`max_batch_pieces`)
    * it processes `capacity_pieces_per_day` pieces per day, first come first served,
      and it starts the run already holding `current_queue_days` of work

      A NOTE ON DATES. The run starts on the first order's date, 2026-01-01, so this
      simulator treats `current_queue_days` as each workshop's queue on that day. The
      data dictionary defines the same column as the queue on 2026-04-01 ("today"),
      which is the right reading for the chat inbox. Reusing one set of numbers for
      both is deliberate: it gives every team an identical, known starting state for
      the replay. Do not derive the 1 April queues from this run, or the reverse.
    * a batch also costs `pickup_lead_days` for transport
    * with probability `defect_rate` the batch comes back defective and half of it
      is redone (more delay)
    * each piece costs `cost_per_piece`

WHAT IT ASSUMES (written down in v3; none of this is new behaviour)

    * It is a counterfactual replay: "what if every one of the 120 orders had been sent
      outside on its order_date?" So ignore `status`, `current_stage`, `completed_date`
      and `days_late` in orders.csv — they describe what happened in-house. Day 0 is
      the first order_date, 2026-01-01 (see the note on dates above).
    * A workshop takes the whole job as one unit of work. There are no stages inside a
      workshop, capacity is the same for every product, and workshops work 7 days a week.
    * One batch goes to one workshop. Splitting a batch is not modelled here; if your
      chat layer proposes a split, that lives outside the simulator.
    * Your allocator is called 120 times per run (and you will do many runs), so it should
      be your deterministic allocation policy — the same one your chat agent calls as a
      tool. Putting an LLM call inside the allocator is not expected.

Choosing a workshop that cannot take the batch is an error, not a bad score — your
system is expected to check capability, capacity and eligibility before it commits,
exactly like a real dispatcher. The helper `eligible_workshops()` below is the rule,
and you may call it from your own code.

HOW TO USE IT

    from simulate import Simulator, eligible_workshops

    def my_allocator(batch, workshops, queues):
        # batch:     {"order_id", "category", "pieces", "sent_date", "due_date"}
        # workshops: {workshop_id: Workshop}  (see the dataclass below)
        # queues:    {workshop_id: days of work currently in its queue}
        candidates = eligible_workshops(batch, workshops)
        return candidates[0].workshop_id     # your logic here

    sim = Simulator()
    sim.run(my_allocator, name="my_policy")
    sim.report()

Run this file directly to see the three baseline policies you have to beat:

    python simulate.py

Add --shock to close a random workshop for two weeks mid-run (for the
robustness objective). The closure is day 30 to day 44 of the run, i.e. 2026-01-31 to
2026-02-14, and the closed workshop does no work at all in that window:

    python simulate.py --shock

Your allocator is not told about the closure. The only trace is in `queues`: once a
batch is stuck there, that workshop's queue jumps.

The simulator is deterministic (seeded), so everyone sees the same numbers. The seed
decides which batches come back defective and which workshop --shock closes, so one
seed is one roll of the dice. Report robustness as an average over several:

    python simulate.py --shock --seeds 10      # seeds 5105..5114, averaged
    python simulate.py --seed 7                # or any single seed

    from simulate import average_over_seeds, print_table
    print_table(average_over_seeds({"my_policy": my_allocator}, range(5105, 5115), shock=True))

(v3 changed two things under --shock only: a batch already being worked on when the
workshop closes now pauses for the closure instead of carrying on, and the choice of
workshop no longer shifts the defect draws. Runs without --shock give exactly the
numbers they always did; re-run your --shock results.)

OPTIONAL EXTENSION: --stages (v3, opt-in — the default run is unchanged)

    python simulate.py --stages

This loads data/orders_stages.csv and data/workshops_stages.csv, which add one column
each: the stage an order is at when it goes outside (`dispatch_stage`) and the stages each
workshop is equipped for (`stages`). A workshop is then eligible only if it covers
every stage from the dispatch stage through PACKING — a fourth question next to
"can they make it, are they allowed, is the batch within their limit". The batch dict
gains a "from_stage" key and eligible_workshops() applies the rule for you. In this
replay `dispatch_stage` just means "the stage from which the workshop takes the batch
over"; for in-progress orders it is their stage on 2026-04-01, which is the reading the
chat inbox needs (the same one-column-two-dates convention as the note above). Work is
still pieces / capacity whatever the stage (a deliberate simplification: change it
and say so if you disagree).
"""

import argparse
import csv
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
STAGES = ["KNITTING", "ASSEMBLY", "WASHING", "PACKING"]


@dataclass
class Workshop:
    workshop_id: str
    name: str
    capacity: int        # pieces per day
    lead_days: int       # pickup + delivery overhead
    defect_rate: float   # chance a batch comes back defective
    cost: float          # per piece
    makes: set           # product categories it is equipped for
    status: str          # ACTIVE or SUSPENDED
    max_batch: int       # max pieces per batch (None = no cap)
    queue0: float        # days of work already in hand at the start of the run (2026-01-01)
    notes: str
    stages: frozenset = frozenset(STAGES)   # only differs with --stages


def eligible_workshops(batch, workshops):
    """The three questions a dispatcher asks: can they make it, are they allowed
    to take work, and is the batch within their limit. Returns a list of Workshops.
    With --stages there is a fourth: do they cover every stage the batch still needs."""
    out = []
    for w in workshops.values():
        if w.status != "ACTIVE":
            continue
        if batch["category"] not in w.makes:
            continue
        if w.max_batch is not None and batch["pieces"] > w.max_batch:
            continue
        if not remaining_stages(batch) <= w.stages:
            continue
        out.append(w)
    return out


def remaining_stages(batch):
    """Stages the batch still needs: from its dispatch stage through PACKING.
    Empty without --stages, so the check in eligible_workshops() always passes."""
    if "from_stage" not in batch:
        return set()
    return set(STAGES[STAGES.index(batch["from_stage"]):])


def load_workshops(stages=False):
    with open(DATA / ("workshops_stages.csv" if stages else "workshops.csv"), encoding="utf-8") as f:
        return {
            r["workshop_id"]: Workshop(
                r["workshop_id"], r["name"], int(r["capacity_pieces_per_day"]),
                int(r["pickup_lead_days"]), float(r["defect_rate"]),
                float(r["cost_per_piece"]), set(r["makes"].split("+")),
                r["status"],
                int(r["max_batch_pieces"]) if r["max_batch_pieces"] else None,
                float(r["current_queue_days"]), r["notes"],
                frozenset(r["stages"].split("+")) if stages else frozenset(STAGES),
            )
            for r in csv.DictReader(f)
        }


def load_batches(stages=False):
    with open(DATA / ("orders_stages.csv" if stages else "orders.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    batches = [
        {
            "order_id": r["order_id"],
            "category": r["category"],
            "pieces": int(r["pieces"]),
            "sent_date": date.fromisoformat(r["order_date"]),
            "due_date": date.fromisoformat(r["due_date"]),
            **({"from_stage": r["dispatch_stage"]} if stages else {}),
        }
        for r in rows
    ]
    batches.sort(key=lambda b: b["sent_date"])
    return batches


class Simulator:
    def __init__(self, shock=False, seed=5105, stages=False):
        self.workshops = load_workshops(stages)
        self.batches = load_batches(stages)
        self.shock = shock
        self.seed = seed
        self.results = {}   # name -> list of per-batch outcomes

    def run(self, allocator, name):
        rng = random.Random(self.seed)
        day0 = self.batches[0]["sent_date"]
        # queue_free[w] = day number when the workshop finishes everything it holds
        queue_free = {w_id: w.queue0 for w_id, w in self.workshops.items()}

        # The shock target has its own random stream, so the defect draws below are the
        # same with and without --shock and the two runs differ only by the closure.
        # (The +6 keeps the default seed closing the same workshop as before v3, and makes
        # seeds 5105..5114 between them close every active workshop.)
        shock_target, shock_start, shock_end = None, 30, 44
        if self.shock:
            shock_target = random.Random(self.seed + 6).choice(
                [w.workshop_id for w in self.workshops.values() if w.status == "ACTIVE"])

        outcomes = []
        for batch in self.batches:
            day = (batch["sent_date"] - day0).days
            queues = {w: max(0.0, queue_free[w] - day) for w in self.workshops}
            choice = allocator(dict(batch), self.workshops, queues)

            ok = {w.workshop_id for w in eligible_workshops(batch, self.workshops)}
            if choice not in ok:
                w = self.workshops.get(choice)
                reason = "unknown workshop" if w is None else (
                    f"status={w.status}" if w.status != "ACTIVE"
                    else f"cannot make {batch['category']}" if batch["category"] not in w.makes
                    else f"does not do {sorted(remaining_stages(batch) - w.stages)}"
                    if not remaining_stages(batch) <= w.stages
                    else f"batch of {batch['pieces']} exceeds its {w.max_batch}-piece limit")
                raise ValueError(
                    f"{name}: {choice} cannot take {batch['order_id']} ({reason}). "
                    "Check eligible_workshops() before committing.")

            w = self.workshops[choice]
            start = max(day, queue_free[choice])
            work_days = batch["pieces"] / w.capacity
            defective = rng.random() < w.defect_rate
            if defective:
                work_days *= 1.5                  # half the batch is redone
            finish = start + work_days
            if shock_target == choice:
                if shock_start <= start < shock_end:
                    finish = shock_end + work_days        # closed: work waits until it reopens
                elif start < shock_start < finish:
                    finish += shock_end - shock_start     # caught mid-job: work pauses
            queue_free[choice] = finish

            done_day = finish + w.lead_days
            done_date = day0 + timedelta(days=round(done_day))
            outcomes.append({
                "workshop": choice,
                "pieces": batch["pieces"],
                "turnaround": done_day - day,
                "late": done_date > batch["due_date"],
                "days_late": max(0, (done_date - batch["due_date"]).days),
                "defective": defective,
                "cost": batch["pieces"] * w.cost,
            })
        self.results[name] = outcomes
        return outcomes

    @staticmethod
    def metrics(out):
        """The headline numbers for one run. `late days` is the mean over ALL batches
        (on-time ones count as 0); `% def pcs` is defective batches weighted by size."""
        days = sorted(o["turnaround"] for o in out)
        n = len(out)
        pieces = sum(o["pieces"] for o in out)
        by_w = {}
        for o in out:
            by_w[o["workshop"]] = by_w.get(o["workshop"], 0) + o["pieces"]
        return {
            "mean days": sum(days) / n,
            "p90 days": days[int(0.9 * n)],
            "% late": 100 * sum(o["late"] for o in out) / n,
            "late days": sum(o["days_late"] for o in out) / n,
            "% defect": 100 * sum(o["defective"] for o in out) / n,
            "% def pcs": 100 * sum(o["pieces"] for o in out if o["defective"]) / pieces,
            "cost": sum(o["cost"] for o in out),
            "max share": 100 * max(by_w.values()) / pieces,
        }

    def report(self):
        print_table({name: self.metrics(out) for name, out in self.results.items()})


def print_table(rows):
    """rows: {policy name: metrics dict}"""
    header = (f"{'policy':<16}{'mean days':>10}{'p90 days':>10}{'% late':>8}{'late days':>11}"
              f"{'% defect':>10}{'% def pcs':>11}{'cost':>12}{'max share':>11}")
    print(header)
    print("-" * len(header))
    for name, m in rows.items():
        print(f"{name:<16}{m['mean days']:>10.1f}{m['p90 days']:>10.1f}{m['% late']:>7.0f}%"
              f"{m['late days']:>11.1f}{m['% defect']:>9.0f}%{m['% def pcs']:>10.0f}%"
              f"{m['cost']:>12,.0f}{m['max share']:>10.0f}%")


def average_over_seeds(allocators, seeds, shock=False, stages=False):
    """Run every allocator once per seed and average the metrics.
    allocators: {name: function}. Returns {name: metrics dict}."""
    totals = {}
    for seed in seeds:
        sim = Simulator(shock=shock, seed=seed, stages=stages)
        for name, allocator in allocators.items():
            m = sim.metrics(sim.run(allocator, name))
            totals[name] = {k: totals.get(name, {}).get(k, 0) + v for k, v in m.items()}
    return {name: {k: v / len(seeds) for k, v in m.items()} for name, m in totals.items()}


# ------------------------- the three baselines to beat -------------------------
# Note that even the dumbest baseline checks eligibility first. So must you.

def random_choice(batch, workshops, queues):
    """Picks any eligible workshop at random. If you cannot beat this, something is wrong."""
    ok = eligible_workshops(batch, workshops)
    return random.Random(batch["order_id"]).choice(ok).workshop_id


def greedy_biggest(batch, workshops, queues):
    """Always the highest-capacity eligible workshop. Watch what the queue does to it."""
    ok = eligible_workshops(batch, workshops)
    return max(ok, key=lambda w: w.capacity).workshop_id


def cheapest(batch, workshops, queues):
    """Always the cheapest eligible workshop. Great cost, and look at everything else."""
    ok = eligible_workshops(batch, workshops)
    return min(ok, key=lambda w: w.cost).workshop_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--shock", action="store_true",
                        help="close a random workshop for two weeks mid-run")
    parser.add_argument("--seed", type=int, default=5105,
                        help="which defects happen and which workshop --shock closes")
    parser.add_argument("--seeds", type=int, metavar="N",
                        help="average over N seeds, starting at --seed")
    parser.add_argument("--stages", action="store_true",
                        help="optional extension: stage capabilities (uses the *_stages.csv files)")
    args = parser.parse_args()

    baselines = {"random": random_choice, "greedy_biggest": greedy_biggest, "cheapest": cheapest}
    if args.seeds:
        print(f"average over seeds {args.seed}..{args.seed + args.seeds - 1}")
        print_table(average_over_seeds(baselines, range(args.seed, args.seed + args.seeds),
                                       shock=args.shock, stages=args.stages))
    else:
        sim = Simulator(shock=args.shock, seed=args.seed, stages=args.stages)
        for name, allocator in baselines.items():
            sim.run(allocator, name)
        sim.report()
