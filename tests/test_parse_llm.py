"""parse_llm tests with a fake LLM — no API key or network needed."""
import agent.llm as llm
from agent.desk_agent import handle
from agent.parse import LLM_SCHEMA, llm_system_prompt, parse_llm
from desk.schemas import Behaviour, ConstraintKind

R12 = ("R12 [08:48] Ravi: ORD-053 — 800 polo shirts for UrbanThread, due Apr 10. "
       "Boss says nothing new to QuickStitch this week, they're swamped.")


def fake(output):
    def _call(system, user, schema, use_cache=True):
        return output
    return _call


def base(**kw):
    d = {"order_id": None, "pieces": None, "due_date": None, "customer": None, "product": None,
         "suggested_workshop": None, "constraints": [], "missing": [], "question_type": None}
    d.update(kw)
    return d


def test_good_extraction_routes_like_a_dispatcher(monkeypatch):
    monkeypatch.setattr(llm, "call_json", fake(base(
        order_id="ORD-053", pieces=800, due_date="2026-04-10", customer="UrbanThread", product="Polo shirt",
        constraints=[{"kind": "exclude_workshop", "value": "QuickStitch", "imposed_by": "Boss",
                      "source_text": "nothing new to QuickStitch"}])))
    req = parse_llm(R12)
    assert req.parser.startswith("llm:") and not req.warnings
    assert req.constraints[0].kind == ConstraintKind.EXCLUDE_WORKSHOP and req.constraints[0].value == "W1"
    assert req.constraints[0].imposed_by == "Boss"
    d = handle(req)
    assert d.behaviour == Behaviour.ALLOCATE and d.chosen != "W1"


def test_invented_numbers_are_dropped(monkeypatch):
    monkeypatch.setattr(llm, "call_json", fake(base(order_id="ORD-053", pieces=750, due_date="2026-04-12")))
    req = parse_llm(R12)
    assert req.pieces == 800              # 750 not in message -> dropped, filled from orders.csv
    assert req.due_date.day == 10         # Apr 12 not in message -> dropped, filled from orders.csv
    assert len(req.warnings) == 2


def test_invented_order_id_is_dropped(monkeypatch):
    monkeypatch.setattr(llm, "call_json", fake(base(order_id="ORD-061", customer="Harbor Knits", product="Scarf",
                                                    missing=["pieces"])))
    req = parse_llm("R01 [07:53] Chen: Need scarves for Harbor Knits sent out today, usual quantities.")
    assert req.order_id is None and len(req.candidate_orders) == 2
    assert handle(req).behaviour == Behaviour.CLARIFY


def test_falls_back_to_regex_when_llm_down(monkeypatch):
    def boom(*a, **k):
        raise llm.LLMError("no key")
    monkeypatch.setattr(llm, "call_json", boom)
    req = parse_llm(R12)
    assert req.parser == "baseline(fallback)" and "no key" in req.warnings[0]


def test_prompt_has_no_inbox_lines():
    inbox = (llm.ROOT / "data" / "dispatch_requests.txt").read_text()
    for line in inbox.splitlines():
        if line.startswith("R"):
            assert line.split(": ", 1)[1][:30] not in llm_system_prompt()


def test_schema_follows_structured_output_rules():
    def walk(s):
        if s.get("type") == "object":
            assert s["additionalProperties"] is False
            assert set(s["required"]) == set(s["properties"])
            for v in s["properties"].values():
                walk(v)
        if s.get("type") == "array":
            walk(s["items"])
    walk(LLM_SCHEMA)
    assert LLM_SCHEMA["properties"]["question_type"] == {"type": ["string", "null"]}


def test_unsupported_question_type_is_dropped(monkeypatch):
    monkeypatch.setattr(llm, "call_json", fake(base(question_type="history")))
    req = parse_llm(R12)
    assert req.question_type == "history"

    monkeypatch.setattr(llm, "call_json", fake(base(question_type="unknown")))
    req = parse_llm(R12)
    assert req.question_type is None
    assert "unsupported value" in req.warnings[0]


def test_named_customer_lists_matching_orders(monkeypatch):
    # "the TrendCart order": Claude fills the customer; the code finds the 6 open orders and asks
    monkeypatch.setattr(llm, "call_json", fake(base(customer="TrendCart")))
    req = parse_llm("R03 [08:03] Priya: Can we get the TrendCart order moving? They are chasing.")
    assert len(req.candidate_orders) == 6
    d = handle(req)
    assert d.behaviour == Behaviour.CLARIFY and d.facts["n_matches"] == 6


def test_new_order_is_not_matched_to_old_ones(monkeypatch):
    monkeypatch.setattr(llm, "call_json", fake(base(customer="Loom & Leaf", missing=["order"])))
    req = parse_llm("R10 [08:38] Mei: New rush coming in from Loom & Leaf — details to follow, "
                    "but book capacity somewhere good.")
    assert req.candidate_orders == [] and handle(req).behaviour == Behaviour.CLARIFY
