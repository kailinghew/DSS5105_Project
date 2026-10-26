"""Faithfulness: a number must trace to the kind of fact it describes (owner: B)."""
from datetime import date

from desk.explain import untraced_numbers
from desk.schemas import Behaviour, Decision, ParsedRequest


def make_decision(**facts) -> Decision:
    req = ParsedRequest(request_id="R99", sender="Boss", time="09:00",
                        raw_text="ORD-099 — 1500 polo shirts, due Apr 05.")
    return Decision("R99", Behaviour.ALLOCATE, req, "lateness", facts=facts)


def test_a_date_only_traces_to_a_date():
    # Nothing in the facts has an ETA/due/today on the 8th, but the old check let
    # "Apr 8" through because n_workshops == 8.
    dec = make_decision(
        pieces=1500,
        due=date(2026, 4, 5),
        today=date(2026, 4, 1),
        n_eligible=3,
        n_workshops=8,
        candidates={"W1": {"eta": date(2026, 4, 11), "cost": 2250.0,
                           "cost_per_piece": 1.5, "defect_rate": 0.12, "defect_pct": 12,
                           "queue_days": 4.0, "slack": -6.0}},
    )
    assert untraced_numbers("ready about Apr 8.", dec) == ["8"]
    assert untraced_numbers("ready about Apr 11.", dec) == []


def test_a_cost_only_traces_to_a_cost():
    # 500 exists as the batch size, but "$500" claims a price the tools never produced.
    dec = make_decision(
        pieces=500,
        due=date(2026, 4, 20),
        today=date(2026, 4, 1),
        candidates={"W1": {"eta": date(2026, 4, 7), "cost": 480.0,
                           "cost_per_piece": 1.2, "defect_rate": 0.05, "defect_pct": 5}},
    )
    assert untraced_numbers("It will cost $500.", dec) == ["500"]
    assert untraced_numbers("It will cost $480.", dec) == []


def test_a_percentage_only_traces_to_a_defect_rate():
    dec = make_decision(
        pieces=9,
        due=date(2026, 4, 20),
        today=date(2026, 4, 1),
        candidates={"W1": {"eta": date(2026, 4, 7), "cost": 480.0,
                           "cost_per_piece": 1.2, "defect_rate": 0.05, "defect_pct": 5}},
    )
    assert untraced_numbers("defect rate 9%.", dec) == ["9"]
    assert untraced_numbers("defect rate 5%.", dec) == []


def test_counts_still_pass_and_ids_are_ignored():
    dec = make_decision(
        pieces=1500,
        due=date(2026, 4, 5),
        today=date(2026, 4, 1),
        n_eligible=3,
        n_workshops=8,
        candidates={"W1": {"eta": date(2026, 4, 11), "cost": 2250.0,
                           "cost_per_piece": 1.5, "defect_rate": 0.12, "defect_pct": 12}},
    )
    assert untraced_numbers("3 of 8 workshops were eligible. ORD-099 by Apr 5.", dec) == []
