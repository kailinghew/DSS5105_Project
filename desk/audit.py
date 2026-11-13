"""
audit.py — the record the group chat never produced. One JSON line per decision.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from .data import ROOT
from .schemas import Decision

LOG = ROOT / "logs" / "decisions.jsonl"


def record(decision: Decision, path: Path | None = None) -> dict:
    path = path or LOG
    d = decision.to_dict()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(d) + "\n")
    return d


def confirm(decision: Decision, who: str, path: Path | None = None) -> dict:
    """A human confirms; we log a second line rather than editing history."""
    entry = record(replace(decision, confirmed_by=who), path)
    decision.confirmed_by = who
    return entry


def read_log(path: Path | None = None) -> list[dict]:
    path = path or LOG
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
