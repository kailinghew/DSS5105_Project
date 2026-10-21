"""Reply content for the awkward cases (owner: A). No API key needed."""
from agent.desk_agent import handle_line
from desk.explain import untraced_numbers
from desk.schemas import Behaviour

R14 = "R14 [08:59] Boss: QuickStitch for the scarves on ORD-103?"
R28 = "R28 [10:08] Priya: Sending ORD-002 outside — 1000 crewneck sweaters. Who has room this week? Due Mar 29."


def test_r14_refuses_and_says_the_date_is_impossible_too():
    d = handle_line(R14)
    assert d.behaviour == Behaviour.REFUSE
    assert d.facts["refused"]["workshop"] == "W1"
    assert "No other workshop can make Apr 4 either" in d.explanation
    assert d.facts["earliest"]["days_late"] == 13 and len(d.options) == 3
    assert untraced_numbers(d.explanation, d) == []


def test_refusal_with_an_on_time_alternative_is_unchanged():
    d = handle_line("R08 [08:29] Priya: Send ORD-073 (400 hoodies) to FreshStart, their quote was good.")
    assert d.behaviour == Behaviour.REFUSE and "on time for Apr 20" in d.explanation
    assert "earliest" not in d.facts


def test_impossible_reply_does_not_overclaim_earliest():
    # the split finishes before the fastest single shop, so "earliest" must say "single workshop"
    d = handle_line(R28)
    assert d.behaviour == Behaviour.IMPOSSIBLE
    assert "earliest single workshop" in d.explanation and "already overdue" in d.explanation
    assert "(still late)" in d.options[1]
    assert untraced_numbers(d.explanation, d) == []
