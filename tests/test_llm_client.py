"""LLM client behaviour with a fake Anthropic client (owner: A). No API key needed."""
import json
from types import SimpleNamespace

import agent.llm as llm

SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"],
          "additionalProperties": False}


class FakeBadRequest(Exception):
    status_code = 400


class FakeClient:
    def __init__(self, reject_effort):
        self.reject_effort, self.calls = reject_effort, []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if self.reject_effort and "effort" in kw["output_config"]:
            raise FakeBadRequest("output_config.effort: not supported with this model")
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text='{"x": 7}')],
                               usage=SimpleNamespace(input_tokens=11, output_tokens=3))


def _setup(monkeypatch, tmp_path, client):
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(llm, "_client", client)
    monkeypatch.setattr(llm, "_effort_rejected", False)
    monkeypatch.setattr(llm, "settings", lambda: {"model": "claude-haiku-5-5", "effort": "low", "max_tokens": 64})


def test_effort_is_dropped_once_when_rejected(monkeypatch, tmp_path):
    c = FakeClient(reject_effort=True)
    _setup(monkeypatch, tmp_path, c)
    assert llm.call_json("sys", "msg 1", SCHEMA) == {"x": 7}
    assert llm.call_json("sys", "msg 2", SCHEMA) == {"x": 7}
    assert [("effort" in k["output_config"]) for k in c.calls] == [True, False, False]
    rec = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert rec["effort"] is None and rec["usage"]["output_tokens"] == 3


def test_cache_means_one_call_per_message(monkeypatch, tmp_path):
    c = FakeClient(reject_effort=False)
    _setup(monkeypatch, tmp_path, c)
    for _ in range(3):
        llm.call_json("sys", "same message", SCHEMA)
    assert len(c.calls) == 1 and c.calls[0]["output_config"]["effort"] == "low"
    assert "temperature" not in c.calls[0]          # Haiku 5.5 rejects sampling parameters


def test_other_errors_become_llmerror(monkeypatch, tmp_path):
    class Boom(FakeClient):
        def create(self, **kw):
            raise ConnectionError("offline")
    _setup(monkeypatch, tmp_path, Boom(False))
    try:
        llm.call_json("sys", "m", SCHEMA)
    except llm.LLMError as e:
        assert "offline" in str(e)
    else:
        raise AssertionError("expected LLMError")
