"""GenAI assistant orchestration: live LLM tool-calling loop with a clearly-labelled demo fallback."""
from __future__ import annotations

import logging
import re

from backend.app.assistant import demo
from backend.app.assistant.llm_provider import LLMProvider, build_provider
from backend.app.assistant.tools import run_tool, to_json, tool_schemas
from backend.app.errors import ServiceError
from backend.app.pipeline import Services
from backend.app.schemas import AssistantRequest, AssistantResponse, ToolCallRecord

log = logging.getLogger("assistant")
DISCLAIMER = ("Forecasts come from a model trained on SYNTHETIC data; recommendations are advisory and require human approval. "
              "The assistant explains backend results; it does not decide allocations.")
SYSTEM = """You are the explanation layer of a festival transport command centre.
STRICT RULES:
- You have NO forecasting ability of your own. Every number you state MUST come from a tool result in this conversation.
- Call tools to obtain forecasts, stop data, bus recommendations or simulation results before answering.
- Never invent or alter bus allocations; only describe what get_deployment_recommendations returned, and say they are advisory
  and need human dispatcher approval.
- Distinguish: observed/synthetic input data, model predictions, and simulated assumptions (what-if results are hypothetical).
- The data is SYNTHETIC; mention this when discussing accuracy. If a tool returns an error, say so plainly.
- Be concise (under 160 words). Plain text, no markdown tables."""


def _numbers(text: str) -> set[float]:
    return {float(x) for x in re.findall(r"(?<![A-Za-z\d])\d+(?:\.\d+)?", text)}  # skip ids like S01


def ungrounded_numbers(answer: str, tool_outputs: list[str]) -> list[float]:
    known = set()
    for t in tool_outputs:
        known |= _numbers(t)
    out = []
    for n in sorted(_numbers(answer)):
        if not any(abs(n - k) <= 0.51 or (k and abs(n - k) / abs(k) < 0.01) for k in known):
            out.append(n)
    return out


def _demo(svc: Services, req: AssistantRequest, reason: str | None) -> AssistantResponse:
    calls = demo.plan_tools(req.message, req.context)
    records, results = [], {}
    for name, args in calls:
        try:
            results[name] = run_tool(svc, name, args, req.context)
            records.append(ToolCallRecord(name=name, arguments=args, ok=True))
        except ServiceError:
            raise
        except ValueError as e:
            records.append(ToolCallRecord(name=name, arguments=args, ok=False, error=str(e)))
    ok_calls = [c for c in calls if c[0] in results]
    answer = demo.compose(ok_calls, results, req.context) if (ok_calls or not calls) else demo.PREFIX + "The request could not be run: " + records[0].error
    if reason:
        answer = answer.replace(demo.PREFIX, demo.PREFIX + f"(Live LLM unavailable: {reason}) ", 1)
    return AssistantResponse(answer=answer, mode="demo", provider=None, model=None, fallback_reason=reason,
                             tool_calls=records, grounding=results, disclaimer=DISCLAIMER)


def answer(svc: Services, req: AssistantRequest, provider: LLMProvider | None = None) -> AssistantResponse:
    svc.model.require()
    provider = provider if provider is not None else build_provider(svc.settings)
    if provider is None:
        reason = None if svc.settings.llm_provider in ("none", "") else "no API key configured"
        return _demo(svc, req, reason)

    messages = [{"role": t.role, "content": t.content} for t in req.history[-8:]]
    messages.append({"role": "user", "content": req.message})
    records, results, outputs = [], {}, []
    try:
        for _ in range(svc.settings.llm_max_rounds):
            turn = provider.complete(SYSTEM + f"\nCurrent dashboard context: festival {req.context.festival_id}, forecast origin "
                                     f"{req.context.forecast_origin.isoformat()}, horizon {req.context.horizon_steps} steps, "
                                     f"allocation target step {req.context.target_step}.", messages, tool_schemas())
            if not turn.tool_uses:
                text = turn.text.strip()
                if not text:
                    raise RuntimeError("empty LLM response")
                if not records:
                    return _demo(svc, req, "LLM answered without calling any backend tool (ungrounded) - discarded")
                warnings = []
                bad = ungrounded_numbers(text, outputs)
                if bad:
                    warnings.append(f"Numbers not found in tool outputs (verify before relying on them): {bad[:8]}")
                return AssistantResponse(answer=text, mode="live_llm", provider=provider.name, model=provider.model,
                                         tool_calls=records, grounding=results, warnings=warnings, disclaimer=DISCLAIMER)
            messages.append({"role": "assistant", "content": turn.raw_content})
            blocks = []
            for tu in turn.tool_uses:
                try:
                    res = run_tool(svc, tu.name, tu.input, req.context)
                    payload, err = to_json(res), None
                    results[tu.name] = res
                    outputs.append(payload)
                except ValueError as e:
                    payload, err = f"ERROR: {e}", str(e)
                records.append(ToolCallRecord(name=tu.name, arguments=tu.input, ok=err is None, error=err))
                blocks.append({"type": "tool_result", "tool_use_id": tu.id, "content": payload, **({"is_error": True} if err else {})})
            messages.append({"role": "user", "content": blocks})
        return _demo(svc, req, "LLM exceeded the maximum number of tool rounds")
    except ServiceError:
        raise
    except Exception as exc:  # timeouts, auth errors, rate limits, malformed responses
        log.warning("LLM call failed: %s", exc)
        return _demo(svc, req, f"{type(exc).__name__} while calling the LLM provider")
