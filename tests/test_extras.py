from backend.app import chaos
from backend.app.assistant import extras
from backend.app.assistant.llm_provider import LLMTurn
from backend.app.schemas import AnnouncementRequest, AssistantContext, ChaosRequest, ForecastContext
from tests.conftest import FEST, ORIGIN

CTX = AssistantContext(festival_id=FEST, forecast_origin=ORIGIN, horizon_steps=8, target_step=3)


class Fake:
    name, model = "fake", "fake-model"

    def __init__(self, out):
        self.out = out

    def complete(self, system, messages, tools):
        if isinstance(self.out, Exception):
            raise self.out
        return LLMTurn(self.out)


def test_chaos_score_is_bounded_and_explained(svc):
    r = chaos.run(svc, ForecastContext(festival_id=FEST, forecast_origin=ORIGIN, horizon_steps=8), 3)
    assert 0 <= r.score <= 100 and r.grade in "ABCDF"
    assert len(r.results) == 9 + 10 and all(0 <= x.harm <= 1 for x in r.results)
    assert r.weakest_link.category == "closure" and r.hardening_tips and "WORST slot" in r.method
    assert chaos.run(svc, ForecastContext(festival_id=FEST, forecast_origin=ORIGIN, horizon_steps=8), 3) is r  # cached


def test_chaos_report_demo_and_live(svc):
    d = extras.chaos_report(svc, ChaosRequest(context=CTX))
    assert d.mode == "demo" and d.narrative.startswith("[DEMO MODE")
    live = extras.chaos_report(svc, ChaosRequest(context=CTX), provider=Fake(f"Score {d.score} grade {d.grade}."))
    assert live.mode == "live_llm" and not live.warnings
    bad = extras.chaos_report(svc, ChaosRequest(context=CTX), provider=Fake("Score 98765."))
    assert bad.warnings
    assert extras.chaos_report(svc, ChaosRequest(context=CTX), provider=Fake(RuntimeError("x"))).fallback_reason


def test_announcement_templates_cover_languages(svc):
    r = extras.announcements(svc, AnnouncementRequest(context=CTX, languages=["en", "hi", "ta", "es"]))
    assert [a.lang for a in r.announcements] == ["en", "hi", "ta", "es"] and all(a.source == "template" and a.text for a in r.announcements)
    assert r.crowded_stop and r.crowded_stop in r.announcements[0].text and "DRAFT" in r.disclaimer


def test_announcement_llm_output_is_validated(svc):
    base = extras.announcements(svc, AnnouncementRequest(context=CTX, languages=["en", "hi"]))
    stop = base.crowded_stop
    good = f"en|Attention. {stop} is crowded, please be patient.\nhi|Invented 999 people at {stop}"
    r = extras.announcements(svc, AnnouncementRequest(context=CTX, languages=["en", "hi"]), provider=Fake(good))
    by = {a.lang: a for a in r.announcements}
    assert by["en"].source == "llm" and by["hi"].source == "template"  # hallucinated digits rejected -> template
    assert r.mode == "live_llm"


def test_extra_endpoints(client, ctx_body):
    c = {**ctx_body, "target_step": 3}
    assert client.post("/api/announcements", json={"context": c, "languages": ["en", "ta"]}).status_code == 200
    r = client.post("/api/chaos", json={"context": c})
    assert r.status_code == 200 and r.json()["results"]
    assert client.post("/api/announcements", json={"context": c, "languages": ["xx"]}).status_code == 422
