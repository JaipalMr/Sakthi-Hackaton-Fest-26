import json

from backend.app.assistant import briefing
from backend.app.assistant.llm_provider import LLMTurn, _to_openai_messages, build_provider
from backend.app.config import Settings
from backend.app.schemas import AssistantContext, BriefingRequest
from tests.conftest import FEST, ORIGIN

REQ = BriefingRequest(context=AssistantContext(festival_id=FEST, forecast_origin=ORIGIN, horizon_steps=8, target_step=3))


class Fake:
    name, model = "fake", "fake-model"

    def __init__(self, out):
        self.out = out

    def complete(self, system, messages, tools):
        assert tools == []
        if isinstance(self.out, Exception):
            raise self.out
        return LLMTurn(self.out)


def test_briefing_demo_mode_is_labelled(svc):
    r = briefing.build(svc, REQ)
    assert r.mode == "demo" and r.narrative.startswith("[DEMO MODE") and r.headline and r.top_risks


def test_briefing_live_uses_llm_text(svc):
    r = briefing.build(svc, REQ, provider=Fake("Situation is stable."))
    assert r.mode == "live_llm" and r.narrative == "Situation is stable." and r.provider == "fake"


def test_briefing_flags_ungrounded_numbers(svc):
    r = briefing.build(svc, REQ, provider=Fake("Expect 98765 passengers."))
    assert r.warnings and "98765" in r.warnings[0]


def test_briefing_falls_back_on_error(svc):
    r = briefing.build(svc, REQ, provider=Fake(TimeoutError("t")))
    assert r.mode == "demo" and r.fallback_reason


def test_briefing_endpoint(client, ctx_body):
    r = client.post("/api/briefing", json={"context": {**ctx_body, "target_step": 3}})
    assert r.status_code == 200 and r.json()["mode"] == "demo" and r.json()["top_risks"]


def test_openai_message_translation():
    msgs = [{"role": "user", "content": "hi"},
            {"role": "assistant", "content": [{"type": "text", "text": "ok"}, {"type": "tool_use", "id": "a1", "name": "get_stop_data", "input": {"x": 1}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a1", "content": "{}"}]}]
    out = _to_openai_messages("sys", msgs)
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[2]["tool_calls"][0]["function"]["name"] == "get_stop_data" and json.loads(out[2]["tool_calls"][0]["function"]["arguments"]) == {"x": 1}
    assert out[3] == {"role": "tool", "tool_call_id": "a1", "content": "{}"}


def test_openai_provider_selected_and_local_needs_no_key():
    assert build_provider(Settings(llm_provider="openai")) is None
    p = build_provider(Settings(llm_provider="openai", openai_base_url="http://localhost:11434/v1", llm_model="llama3.1"))
    assert p is not None and p.name == "openai" and p.model == "llama3.1"
