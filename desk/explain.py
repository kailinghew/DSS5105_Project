"""
explain.py — faithfulness guard.

The explanation may be written by a template (default) or polished by the LLM, but
every number in it must appear in decision.facts, which is filled only from tool
outputs. untraced_numbers() is the check the eval runs on every reply.

The check matches a number to the kind of fact it describes, not just to any number
in the tool outputs: a date (e.g. "Apr 8") must come from an ETA / due / split date,
a "$" amount from a cost, a "%" from a defect rate, "N pcs" or "N-piece" from a
quantity, "N of M workshops" / "N open orders" from a count, and "N days late" from
the lateness of the earliest option. Numbers without a nearby marker keep the old
any-fact rule. Order/request/workshop ids (ORD-063, R07, W3) are ignored.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from typing import Iterator

from .schemas import Decision

_NUM = re.compile(r"(?<![A-Za-z-])\d[\d,]*(?:\.\d+)?")
_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
_IDS = re.compile(r"\b(?:ORD|R|W)-?\d+\b")

# (role, pattern) pairs, most specific first. Each match "protects" its span from the
# bare-number fallback. Every capturing group of a match is a traced number.
_ROLE_PATTERNS = [
    ("cost", re.compile(r"\$([\d,]+(?:\.\d+)?)")),
    ("percent", re.compile(r"(\d+(?:\.\d+)?)\s*%")),
    ("days", re.compile(r"(\d+(?:\.\d+)?)\s*days?\s+late")),
    ("date", re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})\b")),
    ("pieces", re.compile(r"\b(\d[\d,]*)\s*pcs?\b"
                          r"|\b(\d[\d,]*)-piece\b"
                          r"|\b(\d[\d,]*)\s+to\s+[A-Z][A-Za-z]*\b")),
    ("count", re.compile(r"\b(\d+)\s+of\s+(\d+)\s+workshops?\b"
                         r"|\b(\d+)\s+open\s+orders?\b")),
]


def fmt_date(d: date) -> str:
    return f"{_MONTHS[d.month - 1]} {d.day}"


def _canon(s: str) -> str:
    s = s.replace(",", "")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _number_spans(text: str) -> list[tuple[int, int, str, str]]:
    """Every number in `text` as (start, end, role, raw_match)."""
    found: list[tuple[int, int, str, str]] = []
    covered: list[tuple[int, int]] = []
    for role, pat in _ROLE_PATTERNS:
        for m in pat.finditer(text):
            covered.append((m.start(), m.end()))
            for g in m.groups():
                if g is not None:
                    found.append((m.start(), m.end(), role, g))
    for m in _NUM.finditer(text):
        if any(m.start() < e and s < m.end() for s, e in covered):
            continue
        found.append((m.start(), m.end(), "general", m.group(0)))
    found.sort(key=lambda x: (x[0], -x[1]))
    return found


def _role_of_key(key: str) -> str:
    k = key.lower()
    if k in {"eta", "eta_date", "due", "today"}:
        return "date"
    if "cost" in k:
        return "cost"
    if "defect" in k:
        return "percent"
    if "pieces" in k:
        return "pieces"
    if "days" in k or "slack" in k or "queue" in k:
        return "days"
    if k.startswith("n_") or "match" in k:
        return "count"
    return "general"


def _fact_numbers(x, key: str | None = None) -> Iterator[tuple[str, str]]:
    """Yield (canonical_number, role) for every number reachable in the facts."""
    if isinstance(x, bool) or x is None:
        return
    if isinstance(x, date):
        yield _canon(str(x.day)), "date"
        return
    if isinstance(x, (int, float)):
        role = _role_of_key(key) if key else "general"
        for form in (str(x), f"{x:.1f}", f"{x:.2f}", str(round(x))):
            yield _canon(form), role
        return
    if isinstance(x, str):
        if re.fullmatch(r"\d{4}-\d\d-\d\d", x):
            yield _canon(str(date.fromisoformat(x).day)), "date"
            return
        for _, _, role, raw in _number_spans(_IDS.sub(" ", x)):
            yield _canon(raw), role
        return
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _fact_numbers(v, k)
        return
    if isinstance(x, (list, tuple)):
        for v in x:
            yield from _fact_numbers(v, key)


def _allowed(decision: Decision) -> dict[str, set[str]]:
    allowed = defaultdict(set)
    for num, role in _fact_numbers(decision.facts, None):
        allowed[role].add(num)
    for _, _, role, raw in _number_spans(_IDS.sub(" ", decision.request.raw_text)):
        allowed[role].add(_canon(raw))
    return allowed


def untraced_numbers(text: str, decision: Decision) -> list[str]:
    """Numbers in `text` that no fact (or the request itself) contains with the same
    role. Bare numbers fall back to matching any fact. Ids are ignored."""
    allowed = _allowed(decision)
    cleaned = _IDS.sub(" ", text)
    out = []
    for _, _, role, raw in _number_spans(cleaned):
        num = _canon(raw)
        if role == "general":
            ok = any(num in vals for vals in allowed.values())
        else:
            ok = num in allowed[role]
        if not ok:
            out.append(raw)
    return out
