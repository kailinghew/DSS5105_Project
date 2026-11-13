import json
from dataclasses import asdict

import pytest

from agent.conversation import merge_turn, objective_for
from agent.desk_agent import handle
from agent.parse import parse_baseline


def read(text, previous=None):
    return merge_turn("R00 [09:00] Dispatcher: " + text, parse_baseline, previous)


def test_bare_answers_complete_the_same_order_and_keep_exclusions():
    draft = read("ORD-066. Quantity is TBC. The deadline is still to be confirmed. Avoid QuickStitch.")
    assert set(draft.request.missing) == {"pieces", "due_date"}
    draft = read("Apr 18", draft)
    assert draft.request.missing == ["pieces"]
    draft = read("700", draft)
    decision = handle(draft.request, objective_for(0))
    assert decision.behaviour.value == "allocate"
    assert decision.request.pieces == 700
    assert read("Make that 650", draft).request.pieces == 650
    assert decision.request.order_id == "ORD-066"
    assert decision.request.due_date.isoformat() == "2026-04-18"
    assert any(c.excluded_by for c in decision.candidates if c.workshop_id == "W1")


def test_ambiguous_order_choices_and_context_stay_bounded():
    draft = read("Harbor Knits needs the scarves.")
    assert set(draft.request.candidate_orders) == {"ORD-061", "ORD-108"}
    with pytest.raises(ValueError, match="outside"):
        read("ORD-015", draft)
    draft = read("ORD-061", draft)
    for _ in range(16):
        draft = read("Recheck", draft)
    assert draft.turn == 18
    assert draft.request.order_id == "ORD-061"
    assert len(json.dumps(asdict(draft), default=str)) < 900


def test_split_permission_and_exclusion_are_enforced():
    draft = read("ORD-108, 2,000 scarves due Apr 12. Do not split.")
    result = handle(draft.request, objective_for(2), no_split=draft.no_split)
    assert result.behaviour.value == "impossible"
    assert not any(option.startswith("split") for option in result.options)
    draft = read("You may split the batch. Avoid Nimble Needle.", draft)
    assert not draft.no_split
    result = handle(draft.request, objective_for(2), no_split=draft.no_split)
    assert result.behaviour.value == "impossible"
    assert all("Nimble Needle" not in option for option in result.options)


def test_slider_changes_the_real_pick_without_relaxing_due_date():
    draft = read("ORD-053, 800 polo shirts, due Apr 10.")
    low_cost = handle(draft.request, objective_for(0))
    low_defect = handle(draft.request, objective_for(4))
    assert low_cost.chosen == "W5"
    assert low_defect.chosen == "W2"
    assert all(next(c for c in d.candidates if c.workshop_id == d.chosen).meets_due
               for d in (low_cost, low_defect))
    update = read("Quick update on ORD-015: bumped it from 300 to 301 vests. Could FreshStart take it?")
    assert update.request.pieces == 301
    assert handle(update.request, objective_for(2)).behaviour.value == "refuse"
