"""AI layer: grounding check, rule-engine fallback and provider abstraction."""
import pytest

from app.ai import providers
from app.ai.context import build_context, slim_result
from app.ai.guard import SYSTEM_PROMPT, check_grounding
from app.ai.service import AIService
from app.statistics import correlation
import pandas as pd

from tests.reference_data import ANSCOMBE_X, ANSCOMBE_Y


def _result():
    return correlation.pearson(pd.DataFrame({"study_hours": ANSCOMBE_X, "gpa": ANSCOMBE_Y}), "study_hours", "gpa")


def _context(result):
    return build_context(project={"title": "T", "academic_level": "masters", "owner_email": "x@y.z"},
                         research_questions=[{"code": "RQ1", "text": "Is study time related to GPA?"}],
                         hypotheses=[], dataset={"rows": 11, "columns": 2},
                         variables=[{"name": "student_name", "data_type": "text", "stats": {"top_values": [{"value": "Ada", "count": 1}]}},
                                    {"name": "gpa", "data_type": "numeric", "stats": {"mean": 7.5, "top_values": []}}],
                         quality=None, results=[result])


def test_grounded_reply_passes():
    result = _result()
    reply = ("The engine found a strong positive correlation, r = 0.816 (p = .002, n = 11). About 66.7% of the variance is shared. "
             "1. This is an association, not causation. See RQ1.")
    check = check_grounding(reply, _context(result))
    assert check["grounded"], check


def test_invented_statistic_is_caught():
    check = check_grounding("The correlation is r = -0.75 with p = 0.0001.", _context(_result()))
    assert not check["grounded"]
    assert "-0.75" in check["unverified"] and "0.0001" in check["unverified"]


def test_context_excludes_private_material():
    context = _context(_result())
    text = str(context)
    assert "x@y.z" not in text                      # account data never included
    assert "Ada" not in text                        # no example values from free-text columns
    assert "diagnostics" not in slim_result({"diagnostics": {"residuals": [1, 2]}, "n": 3})
    assert context["statistical_results"][0]["source"] == "statistical_engine"


def test_system_prompt_states_the_integrity_rules():
    for phrase in ("Never fabricate", "must appear in CONTEXT", "cause and effect", "Insufficient evidence to perform this analysis reliably"):
        assert phrase in SYSTEM_PROMPT


def test_rule_engine_fallback_is_labelled_and_uses_engine_numbers():
    result = _result()
    reply = AIService(None).explain_result(_context(result), result)
    assert reply.source == "rule_engine" and "not written by a language model" in reply.notice
    assert result["apa"] in reply.content
    assert check_grounding(reply.content, {"r": result})["grounded"]


class _FakeProvider(providers.AIProvider):
    name = "fake"

    def __init__(self, text):
        super().__init__(model="fake-model")
        self.text, self.calls = text, []

    def complete(self, system, messages, max_tokens=1200):
        self.calls.append((system, messages))
        return self.text


def test_llm_reply_with_fabricated_number_gets_a_visible_notice():
    result = _result()
    provider = _FakeProvider("The relationship is very strong, r = 0.5512.")
    reply = AIService(provider).explain_result(_context(result), result)
    assert reply.source == "llm" and reply.provider == "fake"
    assert reply.notice and "0.5512" in reply.notice
    system, messages = provider.calls[0]
    assert system == SYSTEM_PROMPT and "CONTEXT (JSON)" in messages[-1]["content"]


def test_provider_failure_falls_back_to_rule_engine():
    class Broken(_FakeProvider):
        def complete(self, system, messages, max_tokens=1200):
            raise providers.AIUnavailableError("HTTP 500")

    result = _result()
    reply = AIService(Broken("")).explain_result(_context(result), result)
    assert reply.source == "rule_engine" and "unavailable" in reply.notice


def test_provider_factory():
    assert providers.build_provider("none", None) is None
    assert isinstance(providers.build_provider("local", "llama3"), providers.LocalModelProvider)
    assert isinstance(providers.build_provider("openai", "some-model", "key"), providers.OpenAIProvider)
    assert isinstance(providers.build_provider("gemini", "some-model", "key"), providers.GeminiProvider)
    assert isinstance(providers.build_provider("anthropic", "some-model", "key"), providers.AnthropicProvider)
    with pytest.raises(providers.AIUnavailableError):
        providers.build_provider("openai", "")                 # a model name is required
    with pytest.raises(providers.AIUnavailableError):
        providers.build_provider("made-up", "m")


class _ScriptedProvider(providers.AIProvider):
    """Returns the scripted replies in order, then keeps returning the last one."""
    name = "scripted"

    def __init__(self, replies):
        super().__init__(model="scripted-model")
        self.replies, self.calls = list(replies), []

    def complete(self, system, messages, max_tokens=1200):
        self.calls.append(messages)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


_NAMES = ["AI_Frequency", "AI_Reliance", "GPA_post", "Integrity_Score"]
_MAP_CONTEXT = {"focus": {"plan_for": {"research_question": {"code": "RQ4", "text": "Does AI use predict integrity?"}}}}


def test_variable_mapping_accepts_a_fenced_answer():
    provider = _ScriptedProvider(['```json\n{"dependent": "Integrity_Score", "independent": ["AI_Frequency", "AI_Reliance"]}\n```'])
    result = AIService(provider).map_variables(_MAP_CONTEXT, _NAMES)
    assert result["status"] == "mapped" and result["dependent"] == "Integrity_Score"
    assert result["independent"] == ["AI_Frequency", "AI_Reliance"]


def test_unusable_variable_mapping_reply_is_corrected_by_the_assistant_itself():
    provider = _ScriptedProvider(["The outcome is probably the integrity score.",
                                  '{"dependent": "Integrity Score", "independent": []}',
                                  '{"dependent": "Integrity_Score", "independent": ["AI_Reliance"]}'])
    result = AIService(provider).map_variables(_MAP_CONTEXT, _NAMES)
    assert result["status"] == "mapped" and result["dependent"] == "Integrity_Score"
    assert len(provider.calls) == 3
    assert any("not a JSON object" in m["content"] for m in provider.calls[1])                 # each problem is sent back to the model
    assert any("not a variable in the dataset" in m["content"] for m in provider.calls[2])


def test_variable_mapping_reports_why_nothing_was_found():
    no_outcome = AIService(_ScriptedProvider(['{"dependent": null, "independent": []}'])).map_variables(_MAP_CONTEXT, _NAMES)
    assert no_outcome["status"] == "no_match" and "no outcome variable" in no_outcome["reason"]
    off = AIService(None).map_variables(_MAP_CONTEXT, _NAMES)
    assert off["status"] == "unavailable" and "turned off or not configured" in off["reason"]


def test_variable_mapping_gives_up_with_the_provider_error_after_repeated_outages(monkeypatch):
    from app.ai import service as ai_service

    monkeypatch.setattr(ai_service.time, "sleep", lambda seconds: None)
    outage = providers.AIUnavailableError("The AI provider returned an error (HTTP 503).")
    result = AIService(_ScriptedProvider([outage])).map_variables(_MAP_CONTEXT, _NAMES)
    assert result["status"] == "unavailable" and "HTTP 503" in result["reason"]
