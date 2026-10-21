"""
audit.py — the record the group chat never produced. One JSON line per decision.
"""
from __future__ import annotations

import json
from pathlib import Path

from .data import ROOT
from .schemas import Decision

LOG = ROOT / "logs" / "decisions.jsonl"


def record(decision: Decision, path: Path = LOG) -> dict:
    d = decision.to_dict()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(d) + "\n")
    return d


def confirm(decision: Decision, who: str, path: Path = LOG) -> dict:
    """A human confirms; we log a second line rather than editing history."""
    decision.confirmed_by = who
    return record(decision, path)


def read_log(path: Path = LOG) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
