"""Answers to the desk's own questions (agent/followup.py): two messages read as one request."""
from agent.desk_agent import handle_line
from agent.followup import answer
from agent.parse import parse_baseline
from desk.schemas import Behaviour, ParsedRequest

R03 = "R03 [08:12] Chen: Can we get the TrendCart order moving? Need it soon."
R05 = "R05 [08:14] Mei: ORD-066 needs to go out. New date TBC, will confirm."
R10 = ("R10 [08:38] Mei: New rush coming in from Loom & Leaf — details to follow, "
       "but book capacity somewhere good.")


def _ask(line):
    q = handle_line(line)
    assert q.behaviour == Behaviour.CLARIFY
    return q.request


def test_product_narrows_the_list_to_one_order():
    d = answer(_ask(R03), "R03 [08:20] Chen: the cardigans one", parse_baseline)
    assert d.behaviour == Behaviour.ALLOCATE and d.request.order_id == "ORD-017"


def test_an_order_id_answers_the_question():
    d = answer(_ask(R03), "R03 [08:20] Chen: ORD-017", parse_baseline)
    assert d.behaviour == Behaviour.ALLOCATE and d.request.order_id == "ORD-017"


def test_an_ordinal_picks_from_the_list_the_desk_showed():
    q = _ask(R03)
    d = answer(q, "R03 [08:20] Chen: the second one", parse_baseline)
    assert d.request.order_id == q.candidate_orders[1]


def test_no_match_keeps_asking_and_says_why():
    d = answer(_ask(R03), "R03 [08:20] Chen: the hoodies", parse_baseline)
    assert d.behaviour == Behaviour.CLARIFY and len(d.request.candidate_orders) == 6
    assert any("None of the 6 orders" in w for w in d.request.warnings)


def test_a_date_answers_a_date_question_and_keeps_the_order():
    d = answer(_ask(R05), "R05 [08:30] Mei: Apr 20", parse_baseline)
    assert d.behaviour == Behaviour.ALLOCATE
    assert d.request.order_id == "ORD-066" and d.request.due_date.isoformat() == "2026-04-20"


def test_an_answer_without_the_missing_value_asks_again():
    d = answer(_ask(R05), "R05 [08:30] Mei: still not sure", parse_baseline)
    assert d.behaviour == Behaviour.CLARIFY and "due_date" in d.request.missing


def test_a_new_order_can_be_answered_in_full():
    d = answer(_ask(R10), "R10 [09:00] Mei: ORD-044, 600 pieces, by Apr 22", parse_baseline)
    assert d.behaviour == Behaviour.ALLOCATE and d.request.pieces == 600


def test_claude_reading_of_the_answer_is_merged_the_same_way():
    # what Claude returns for "the cardigans one": a product and nothing else
    def claude_like(line):
        return ParsedRequest(request_id="R03", sender="Chen", time="08:20", raw_text=line,
                             product="Cardigan", missing=["order"], parser="llm:test")
    d = answer(_ask(R03), "R03 [08:20] Chen: the cardigans one", claude_like)
    assert d.behaviour == Behaviour.ALLOCATE and d.request.order_id == "ORD-017"
    assert d.request.parser == "llm:test"


def test_an_order_for_another_customer_is_flagged():
    d = answer(_ask(R03), "R03 [08:20] Chen: ORD-044", parse_baseline)
    assert any("is a" in w and "TrendCart" in w for w in d.request.warnings)
