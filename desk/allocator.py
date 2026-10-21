"""
allocator.py — the simulator-facing policy. Deterministic, no LLM.

    from desk.allocator import make_policy
    sim.run(make_policy("lateness"), name="desk_lateness")

It calls the very same tools.allocate() the chat agent uses; the only extra is the
state the simulator replay needs (load shares for the fairness objective, and the
stall watch for the robust objective).
"""
from __future__ import annotations

import json
from pathlib import Path

from .data import ROOT, eligible_workshops
from .schemas import Objective
from .tools import allocate

CONFIG = ROOT / "config" / "objectives.json"


def load_objective(name: str | None = None, path: Path = CONFIG) -> Objective:
    cfg = json.loads(Path(path).read_text())
    name = name or cfg["primary"]
    return Objective(name=name, **cfg["objectives"][name])


class Policy:
    """Callable with the simulator's signature: (batch, workshops, queues) -> workshop id."""

    STALL_DAYS = 14        # how long a stalled shop is avoided after we notice
    STALL_TOLERANCE = 0.5  # queue may exceed our expectation by this much before we call it stalled

    def __init__(self, objective: Objective):
        self.objective = objective
        self.reset()

    def reset(self):
        self.last_day = None
        self.expected = {}
        self.loaded = {}
        self.total = 0.0
        self.stalled_since = {}

    def __call__(self, batch, workshops, queues):
        day = batch["sent_date"].toordinal()
        if self.last_day is not None and day < self.last_day:   # a new run started
            self.reset()
        if self.objective.stall_watch and self.last_day is not None:
            dt = day - self.last_day
            for w_id, q in queues.items():
                if q > max(0.0, self.expected.get(w_id, q) - dt) + self.STALL_TOLERANCE:
                    self.stalled_since[w_id] = day
        q = dict(queues)
        # a stalled shop is made to look very busy rather than removed, so the policy
        # still has an answer if it is the only eligible one
        for w_id, since in self.stalled_since.items():
            if day - since < self.STALL_DAYS:
                q[w_id] = q[w_id] + 100.0
        choice, _ = allocate(batch["category"], batch["pieces"], batch["sent_date"],
                             batch["due_date"], q, self.objective,
                             loaded=self.loaded, total=self.total,
                             eligible_ids={w.workshop_id for w in eligible_workshops(batch, workshops)})
        w = workshops[choice]
        self.loaded[choice] = self.loaded.get(choice, 0) + batch["pieces"]
        self.total += batch["pieces"]
        self.last_day = day
        self.expected = dict(queues)
        self.expected[choice] = queues[choice] + batch["pieces"] / w.capacity
        return choice


def make_policy(objective_name: str | None = None) -> Policy:
    return Policy(load_objective(objective_name))


def earliest_finish_rule(batch, workshops, queues):
    """The simple rule-based allocator we must beat (no LLM, ~5 lines):
    queue + processing + transport, smallest wins."""
    from .data import eligible_workshops
    ok = eligible_workshops(batch, workshops)
    return min(ok, key=lambda w: (queues[w.workshop_id] + batch["pieces"] / w.capacity
                                  + w.lead_days, w.workshop_id)).workshop_id
