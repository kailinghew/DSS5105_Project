"""Regression tests for the failure log (eval/failures.md), one per case.

F1-F9 are the regex parser on probe wordings R91-R99; F10 is the order lookup shared by
both parsers (held-out R53/R54). Each test pins the behaviour the failure log expected.
"""
from agent.desk_agent import handle, handle_line
from agent.parse import parse_baseline, resolve_order
from desk.schemas import Behaviour, ConstraintKind, ParsedRequest


def _excluded(req):
    return {c.value for c in req.constraints if c.kind == ConstraintKind.EXCLUDE_WORKSHOP}


def test_f1_steer_clear_of_excludes_the_shop():
    line = ("R91 [12:00] Mei: ORD-010 — 1000 cardigans for Cotton Club, due Apr 25. "
            "Steer clear of QuickStitch, they're overloaded.")
    req = parse_baseline(line)
    assert req.suggested_workshop is None and "W1" in _excluded(req)
    dec = handle(req)
    assert dec.behaviour == Behaviour.ALLOCATE and "QuickStitch" not in dec.explanation.split(":")[0]


def test_f2_skip_excludes_the_shop():
    req = parse_baseline("R92 [12:01] Chen: ORD-010 — 1000 cardigans for Cotton Club, due Apr 25. "
                         "Skip Nimble Needle on this one.")
    assert req.suggested_workshop is None and "W6" in _excluded(req)


def test_f3_anything_but_excludes_the_shop():
    req = parse_baseline("R93 [12:02] Ravi: ORD-010 — 1000 cardigans for Cotton Club, due Apr 25. "
                         "Anything but BudgetWorks.")
    assert req.suggested_workshop is None and "W3" in _excluded(req)


def test_f4_fewest_defects_is_the_lowest_defect_constraint():
    req = parse_baseline("R94 [12:03] Priya: ORD-095 — 800 hoodies for Bright Basics, due Apr 26. "
                         "Fewest defects possible.")
    assert any(c.kind == ConstraintKind.LOWEST_DEFECT_ON_TIME for c in req.constraints)
    dec = handle(req)
    assert dec.behaviour == Behaviour.ALLOCATE and "SteadyHands" in dec.explanation


def test_f5_deadline_still_to_be_confirmed_asks():
    dec = handle_line("R95 [12:04] Boss: ORD-066 — the new deadline is still to be confirmed, but line it up.")
    assert dec.behaviour == Behaviour.CLARIFY and "due_date" in dec.request.missing


def test_f6_quantity_tbc_asks():
    dec = handle_line("R96 [12:05] Mei: ORD-096 — the quantity is TBC, ship Apr 17.")
    assert dec.behaviour == Behaviour.CLARIFY and "pieces" in dec.request.missing


def test_f7_who_handled_is_a_history_question():
    dec = handle_line("R97 [12:06] Chen: Who handled the Maple & Co batch in February?")
    assert dec.behaviour == Behaviour.DECLINE and dec.request.question_type == "history"


def test_f8_ordinal_date_is_read_and_the_order_is_impossible():
    req = parse_baseline("R98 [12:07] Ravi: ORD-017 — 800 cardigans for TrendCart, back by Apr 8th.")
    assert req.due_date.day == 8
    assert handle(req).behaviour == Behaviour.IMPOSSIBLE


def test_f9_same_quantity_as_always_asks_for_order_and_quantity():
    dec = handle_line("R99 [12:08] Priya: The TrendCart beanies — same quantity as always, ship by Apr 17.")
    assert dec.behaviour == Behaviour.CLARIFY
    assert "pieces" in dec.request.missing and len(dec.request.candidate_orders) >= 2
    assert "quantity" in dec.question


def test_f10_product_only_reference_lists_the_matching_orders():
    # what Claude returned for held-out R53: the product, plus "order" in missing
    req = ParsedRequest(request_id="R53", sender="Priya", time="11:30",
                        raw_text="R53 [11:30] Priya: The beanies are waiting — which shops can take them?",
                        missing=["order"])
    req = resolve_order(req, customer=None, product="Beanie")
    assert len(req.candidate_orders) == 6
    assert "6 open orders match" in handle(req).question


def test_f10_a_new_order_still_has_nothing_to_match():
    req = ParsedRequest(request_id="R10", sender="Mei", time="08:38",
                        raw_text="R10 [08:38] Mei: New rush coming in from Loom & Leaf — details to follow, "
                                 "but book capacity somewhere good.",
                        missing=["order"])
    req = resolve_order(req, customer="Loom & Leaf", product=None)
    assert req.candidate_orders == [] and handle(req).behaviour == Behaviour.CLARIFY
