"""
explain.py — faithfulness guard.

The explanation may be written by a template (default) or polished by the LLM, but
every number in it must appear in decision.facts, which is filled only from tool
outputs. untraced_numbers() is the check the eval runs on every reply.
"""
from __future__ import annotations

import re
from datetime import date

from .schemas import Decision

_NUM = re.compile(r"(?<![A-Za-z-])\d[\d,]*(?:\.\d+)?")
_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def fmt_date(d: date) -> str:
    return f"{_MONTHS[d.month - 1]} {d.day}"


def _flatten(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from _flatten(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _flatten(v)
    elif isinstance(x, date):
        yield str(x.day); yield str(x.month); yield str(x.year)
    elif isinstance(x, bool) or x is None:
        return
    elif isinstance(x, (int, float)):
        yield _canon(str(x))
        yield _canon(f"{x:.1f}"); yield _canon(f"{x:.2f}"); yield _canon(str(round(x)))
    elif isinstance(x, str):
        iso = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d)", x)
        if iso:
            yield from _flatten(date(*map(int, iso.groups())))
            return
        for m in _NUM.findall(x):
            yield _canon(m)


def _canon(s: str) -> str:
    s = s.replace(",", "")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def untraced_numbers(text: str, decision: Decision) -> list[str]:
    """Numbers in `text` that no tool output (decision.facts) or the request itself
    contains. Order ids (ORD-063) and request ids (R07) are ignored."""
    allowed = set(_flatten(decision.facts)) | set(_flatten(decision.request.raw_text))
    cleaned = re.sub(r"\b(ORD|R|W)-?\d+\b", " ", text)
    return [m for m in _NUM.findall(cleaned) if _canon(m) not in allowed]
