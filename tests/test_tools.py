"""Run: python -m pytest -q   (fast; no LLM, no network)"""
from datetime import date

from agent.desk_agent import handle_line
from desk.allocator import earliest_finish_rule, make_policy
from desk.explain import untraced_numbers
from desk.schemas import Behaviour
from desk.tools import evaluate_all, overload_probe, register_lookup, split_options
from simulate import Simulator


def test_eligibility_reasons():
    c = {x.workshop_id: x for x in register_lookup("TOPS", 400)}
    assert not c["W7"].eligible and "SUSPENDED" in c["W7"].ineligible_reasons[0]
    assert not c["W8"].eligible and "300-piece cap" in c["W8"].ineligible_reasons[0]
    assert not c["W4"].eligible           # accessories only
    assert c["W1"].eligible


def test_eta_matches_hand_calculation():
    # GiantWeave, 1500 pcs on 1 Apr: 3.0 queue + 3.75 work + 0.1125 rework + 4 lead = 10.86 -> Apr 12
    w5 = next(c for c in evaluate_all("TOPS", 1500, date(2026, 4, 1), date(2026, 4, 13)) if c.workshop_id == "W5")
    assert w5.eta_date == date(2026, 4, 12) and w5.meets_due and w5.cost == 1650


def test_overload_probe():
    p = overload_probe("W1", 600)
    assert p["added_days"] == 2.0 and p["queue_after_days"] == 6.0


def test_split_is_capacity_proportional():
    s = split_options("ACCESSORIES", 500)
    assert sum(p["pieces"] for p in s["parts"]) == 500


def test_policy_never_picks_ineligible_and_runs():
    sim = Simulator()
    for name in ("lateness", "fair", "hybrid", "robust"):
        sim.run(make_policy(name), name)        # raises if ineligible
    sim.run(earliest_finish_rule, "rule")


def test_behaviours_on_known_requests():
    assert handle_line("R08 [08:29] Priya: Send ORD-073 (400 hoodies) to FreshStart, their quote was good.").behaviour == Behaviour.REFUSE
    assert handle_line("R18 [09:18] Priya: Any movement on ORD-999? Customer is chasing.").behaviour == Behaviour.DECLINE
    d = handle_line("R21 [09:33] Chen: ORD-081 — 1500 crewneck sweaters for Harbor Knits, due Apr 13. Margin is thin on this one — cheapest shop that can still make Apr 13.")
    assert d.behaviour == Behaviour.ALLOCATE and d.chosen == "W5"
    assert untraced_numbers(d.explanation, d) == []


def test_trace_check_catches_invented_number():
    d = handle_line("R07 [08:23] Ravi: ORD-063 — 100 cardigans. No special requirements, just make Apr 29.")
    assert untraced_numbers(d.explanation + " It will cost $9,999.", d) == ["9,999"]
