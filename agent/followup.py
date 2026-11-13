"""Answers to the desk's own questions: a two-message exchange read as one request.

When the desk asks ("6 open orders match: which one?", "please confirm the date"), the
dispatcher's next message is often only the missing piece: "the cardigans one",
"ORD-017", "the second one", "Apr 20". Read alone, such a line has no order and the desk
asks again. Here it is read against the question it answers:

    q = handle_line(question_line, parser)        # behaviour CLARIFY
    d = answer(q.request, answer_line, parser)     # the merged request, decided again

What the answer states wins; what it does not state is kept from the question; anything
still unknown is asked again. The parser (Claude or regex) only reads the answer line;
merging and the order lookup are plain code, so no number can come from the model.
"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Callable

from agent.desk_agent import handle
from agent.parse import DATE, resolve_order, split_line
from desk.tools import find_orders, get_order
from desk.schemas import Decision, Objective, ParsedRequest

_ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3,
             "fourth": 4, "4th": 4, "fifth": 5, "5th": 5, "sixth": 6, "6th": 6,
             "last": -1}


def _stated_date(text: str) -> bool:
    return bool(DATE.search(text) or re.search(r"\b2026-\d{2}-\d{2}\b", text))


def _stated_pieces(text: str, pieces: int | None) -> bool:
    if pieces is None:
        return False
    digits = re.sub(r"(?<=\d),(?=\d{3})", "", text)
    return re.search(rf"(?<![\w-]){pieces}(?!\d)", digits) is not None


def _pick_ordinal(text: str, candidates: list[str]) -> str | None:
    """'the second one' / 'the 2nd' / 'the last one' -> that entry of the list the desk showed."""
    for word, n in _ORDINALS.items():
        if re.search(rf"\b{word}\b", text, re.I):
            idx = n - 1 if n > 0 else len(candidates) - 1
            return candidates[idx] if 0 <= idx < len(candidates) else None
    return None


def merge(question: ParsedRequest, ans: ParsedRequest) -> ParsedRequest:
    """The request the two messages make together, before order resolution."""
    _, _, _, text = split_line(ans.raw_text)
    q = question
    req = replace(
        q,
        raw_text=f"{q.raw_text} — answer from {ans.sender}: {text}",
        constraints=q.constraints + [c for c in ans.constraints
                                     if (c.kind, c.value) not in {(k.kind, k.value) for k in q.constraints}],
        missing=list(q.missing),
        candidate_orders=[],
        warnings=q.warnings + ans.warnings,
        parser=ans.parser,
        suggested_workshop=ans.suggested_workshop or q.suggested_workshop,
        customer=ans.customer or q.customer,
        product=ans.product or q.product,
    )

    # the order: an explicit id, else "the second one" from the list shown, else the
    # list narrowed by the customer/product the two messages name together
    order = ans.order_id if ans.order_id and not ans.question_type else None
    if not order and q.candidate_orders:
        order = _pick_ordinal(text, q.candidate_orders)
        if not order and (ans.customer or ans.product):
            ids = {o["order_id"] for o in find_orders(customer=req.customer, product=req.product)}
            narrowed = [o for o in q.candidate_orders if o in ids]
            if len(narrowed) == 1:
                order = narrowed[0]
            elif narrowed:
                req.candidate_orders = narrowed
            else:
                named = " ".join(x for x in (req.customer, req.product) if x)
                req.warnings.append(f"None of the {len(q.candidate_orders)} orders listed matches "
                                    f"“{named}”; still asking which one.")
    if order:
        req.order_id = order
        o = get_order(order)
        if o and q.customer and o["customer"] != q.customer:
            req.warnings.append(f"{order} is a {o['customer']} order, but the question was about "
                                f"{q.customer}. Check it is the right one before confirming.")
    if req.order_id and "order" in req.missing:
        req.missing.remove("order")

    # values: only what the answer actually states replaces the question's
    if _stated_pieces(text, ans.pieces):
        req.pieces = ans.pieces
        if "pieces" in req.missing:
            req.missing.remove("pieces")
    if _stated_date(text) and ans.due_date:
        req.due_date = ans.due_date
        if "due_date" in req.missing:
            req.missing.remove("due_date")
    return req


def answer(question: ParsedRequest, answer_line: str,
           parser: Callable[[str], ParsedRequest], objective: Objective | None = None) -> Decision:
    """Decide the request formed by the desk's question and the dispatcher's answer."""
    req = merge(question, parser(answer_line))
    if req.order_id:
        req = resolve_order(req, req.customer, req.product)   # fill what is still unstated
    elif not req.candidate_orders:
        req.candidate_orders = list(question.candidate_orders)
        if "order" not in req.missing:
            req.missing.append("order")
    return handle(req, objective)
