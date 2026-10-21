"""
data.py — the only place files are read.

Reuses the harness's own Workshop loader and eligibility rule, so the desk and the
simulator can never disagree on who is eligible.

Two dates (see data_dictionary.md): the chat inbox lives on TODAY = 2026-04-01 and uses
current_queue_days as the queue on that morning. The simulator starts on 2026-01-01 with
the same numbers. Never derive one from the other.
"""
from __future__ import annotations

import csv
import sys
from datetime import date
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT / "harness"))

from simulate import Workshop, eligible_workshops, load_workshops  # noqa: E402

TODAY = date(2026, 4, 1)

__all__ = ["TODAY", "Workshop", "eligible_workshops", "workshops", "orders",
           "today_queues", "workshop_by_name"]


@lru_cache(maxsize=None)
def workshops() -> dict[str, Workshop]:
    return load_workshops()


@lru_cache(maxsize=None)
def orders() -> dict[str, dict]:
    with open(DATA / "orders.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = {}
    for r in rows:
        r["pieces"] = int(r["pieces"])
        r["order_date"] = date.fromisoformat(r["order_date"])
        r["due_date"] = date.fromisoformat(r["due_date"])
        out[r["order_id"]] = r
    return out


def today_queues() -> dict[str, float]:
    """Queue (days of work held) on the morning of 2026-04-01 — the chat inbox's view."""
    return {w_id: w.queue0 for w_id, w in workshops().items()}


def workshop_by_name(name: str) -> Workshop | None:
    """'QuickStitch', 'quick stitch', 'W1' -> Workshop. None if no match."""
    key = name.lower().replace(" ", "")
    for w in workshops().values():
        if key in (w.workshop_id.lower(), w.name.lower().replace(" ", "")):
            return w
    return None
