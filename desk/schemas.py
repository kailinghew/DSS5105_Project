"""
schemas.py — the three contracts every part of the desk agrees on.

    ParsedRequest  what the intake agent extracts from one chat message
    Candidate      one workshop, evaluated for one batch by the tools
    Decision       the auditable record: request + candidates + outcome + explanation

Agree these first; then tools, agent, UI and eval can be built in parallel.
Change a field here = tell the whole team.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional


class Behaviour(str, Enum):
    """The five things the desk can do with a request (maps onto the 7 kinds
    in data_dictionary.md: 'complete' and 'constraint' both ALLOCATE,
    'ambiguous' and 'missing' both CLARIFY)."""
    ALLOCATE = "allocate"      # complete (with or without constraints) and meetable
    CLARIFY = "clarify"        # ambiguous order or missing quantity/date -> ask
    REFUSE = "refuse"          # suggested workshop cannot take it -> reason + alternative
    IMPOSSIBLE = "impossible"  # no workshop can make the date -> numbers + options
    DECLINE = "decline"        # cannot be answered from this data -> say so


class ConstraintKind(str, Enum):
    EXCLUDE_WORKSHOP = "exclude_workshop"        # "keep it away from BudgetWorks"
    PREFER_WORKSHOP = "prefer_workshop"          # "send it to FreshStart"
    FASTEST = "fastest"                          # "cost doesn't matter, fastest"
    CHEAPEST_ON_TIME = "cheapest_on_time"        # "cheapest that still makes Apr 13"
    LOWEST_DEFECT_ON_TIME = "lowest_defect_on_time"  # "lowest defect rate you can get"
    SPLIT_ALLOWED = "split_allowed"              # "split it across two shops if faster"


@dataclass
class Constraint:
    kind: ConstraintKind
    value: Optional[str] = None      # e.g. workshop id for EXCLUDE/PREFER
    imposed_by: str = ""             # who said it ("Boss", "Mei", ...) — must be logged
    source_text: str = ""            # the words in the message it came from


@dataclass
class ParsedRequest:
    request_id: str                  # "R07"
    sender: str                      # "Ravi"
    time: str                        # "08:23"
    raw_text: str
    order_id: Optional[str] = None
    pieces: Optional[int] = None
    due_date: Optional[date] = None
    suggested_workshop: Optional[str] = None   # workshop id the sender proposed, if any
    constraints: list[Constraint] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)       # e.g. ["pieces", "due_date"]
    question_type: Optional[str] = None  # set when the message asks something the data
                                         # can't answer: "history", "price", "unknown_order"
    candidate_orders: list[str] = field(default_factory=list)  # filled when ambiguous
    parser: str = "baseline"         # which parser produced this ("baseline" | "llm:<model>")
    warnings: list[str] = field(default_factory=list)  # e.g. LLM value dropped by validation


@dataclass
class Candidate:
    workshop_id: str
    name: str
    eligible: bool
    ineligible_reasons: list[str] = field(default_factory=list)
    queue_days: float = 0.0
    work_days: float = 0.0           # pieces / capacity
    rework_days: float = 0.0         # expected rework allowance: work * 0.5 * defect_rate
    lead_days: int = 0
    eta_days: float = 0.0            # queue + work + rework + lead
    eta_date: Optional[date] = None
    meets_due: Optional[bool] = None
    slack_days: Optional[float] = None   # due - eta (negative = late)
    cost: float = 0.0                # pieces * cost_per_piece
    cost_per_piece: float = 0.0
    defect_rate: float = 0.0
    excluded_by: Optional[str] = None    # who excluded it via a constraint
    score: Optional[float] = None        # objective score, lower is better
    rank: Optional[int] = None


@dataclass
class Objective:
    """The objective is configuration, not code. See config/objectives.json."""
    name: str
    w_late: float = 1.0
    w_defect: float = 0.0
    w_share: float = 0.0
    w_cost: float = 0.0
    stall_watch: bool = False


@dataclass
class Decision:
    request_id: str
    behaviour: Behaviour
    request: ParsedRequest
    objective: str
    candidates: list[Candidate] = field(default_factory=list)
    chosen: Optional[str] = None             # workshop id (ALLOCATE only)
    split: Optional[list[dict]] = None       # [{"workshop_id", "pieces", "eta_date"}] if split
    alternative: Optional[str] = None        # workshop id offered on REFUSE / IMPOSSIBLE
    options: list[str] = field(default_factory=list)   # IMPOSSIBLE: split / accept late / escalate
    question: Optional[str] = None           # CLARIFY: what we ask
    explanation: str = ""                    # human-readable; every number must trace to `facts`
    facts: dict[str, Any] = field(default_factory=dict)  # numbers the explanation may cite
    confirmed_by: Optional[str] = None       # human who confirmed (None = not yet)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict:
        return _jsonable(asdict(self))


def _jsonable(x):
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    if isinstance(x, Enum):
        return x.value
    return x
