"""AI service used by the API layer.

The pipeline is always:

    engine results -> structured context -> (LLM | rule engine) -> grounding check -> reply

The statistical engine is the only source of numbers. When no LLM provider is
configured the service answers from the rule engine and says so in the reply
metadata (``source = "rule_engine"``); it never dresses a template up as AI.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from app.ai.guard import GROUNDING_WARNING, SYSTEM_PROMPT, check_grounding
from app.ai.providers import AIProvider, AIUnavailableError
from app.statistics.effect_sizes import describe_effect

logger = logging.getLogger(__name__)

GLOSSARY: dict[str, str] = {
    "p_value": "The p-value is the probability of seeing a result at least as extreme as yours if the null hypothesis were true. "
               "A small p-value (below your alpha, usually 0.05) means the data are hard to explain by chance alone. It is not the "
               "probability that the hypothesis is true, and it says nothing about how large or important the effect is.",
    "effect_size": "An effect size measures how big a difference or relationship is, independent of sample size. A result can be "
                   "statistically significant yet too small to matter in practice, which is why effect sizes are reported with p-values.",
    "confidence_interval": "A 95% confidence interval is a range of values that is compatible with your data. If the study were repeated "
                           "many times, about 95% of such intervals would contain the true value. A wide interval means an imprecise estimate.",
    "correlation": "A correlation coefficient (-1 to +1) describes the direction and strength of the relationship between two variables. "
                   "Correlation alone never shows that one variable causes the other.",
    "normality": "Many tests assume values (or residuals) follow a bell-shaped normal distribution. When this fails in a small sample, "
                 "rank-based (non-parametric) tests are safer.",
    "regression": "Regression estimates how an outcome changes when a predictor changes by one unit, holding other predictors constant. "
                  "R-squared is the share of variation in the outcome that the model accounts for.",
    "anova": "ANOVA tests whether the means of three or more groups differ. A significant F only says that at least one group differs; "
             "post hoc tests show which ones.",
    "chi_square": "The chi-square test compares the counts you observed in a table with the counts expected if the two variables were unrelated.",
    "power": "Statistical power is the probability that a study detects an effect of a given size if it really exists. "
             "It is planned before data collection; 80% is the usual target.",
    "null_hypothesis": "The null hypothesis (H0) states that there is no effect or relationship. A test either rejects H0 or fails to reject it; "
                       "failing to reject H0 is not proof that H0 is true.",
}


@dataclass
class AIReply:
    content: str
    source: str                    # "llm" or "rule_engine"
    provider: str | None = None
    model: str | None = None
    grounding: dict | None = None
    notice: str | None = None      # shown to the user above the reply
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"content": self.content, "source": self.source, "provider": self.provider, "model": self.model,
                "grounding": self.grounding, "notice": self.notice, **self.extra}


RULE_ENGINE_NOTICE = ("No AI provider is configured, so this text was produced by the platform's rule engine directly from the "
                      "statistical results. It is not written by a language model.")


def explain_result_rule_based(result: dict) -> str:
    """Deterministic explanation of one engine result."""
    lines = [f"What was computed (statistical engine): {result.get('method_name', 'Analysis')} on n = {result.get('n')} records."]
    if result.get("apa"):
        lines.append(f"Result: {result['apa']}.")
    if result.get("summary"):
        lines.append(f"Interpretation: {result['summary']}")
    for effect in (result.get("effect_sizes") or [])[:3]:
        if effect.get("value") is not None:
            lines.append("Effect size: " + describe_effect(effect) + (f" {effect['note']}" if effect.get("note") else ""))
    checks = result.get("assumptions") or []
    failed = [a for a in checks if a.get("satisfied") is False]
    unknown = [a for a in checks if a.get("satisfied") is None]
    if checks:
        lines.append(f"Assumptions: {len(checks) - len(failed) - len(unknown)} met, {len(failed)} not met, {len(unknown)} to be judged by you.")
    for a in failed:
        lines.append(f"- Not met: {a['name']}. {a.get('note') or ''}".rstrip())
    for a in unknown:
        lines.append(f"- For you to judge: {a['name']}. {a.get('note') or ''}".rstrip())
    for w in result.get("warnings") or []:
        lines.append(f"Warning: {w}")
    lines.append("What you must decide: whether the method fits your research question and design, whether the effect is large enough "
                 "to matter in your field, and how the limitations above affect your conclusion.")
    return "\n".join(lines)


def _json_object(text: str) -> dict | None:
    """The JSON object in a model reply, tolerating code fences and a sentence before or after it."""
    cleaned = _strip_code_fence(text or "")
    try:
        data = json.loads(cleaned)
    except ValueError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except ValueError:
            return None
    return data if isinstance(data, dict) else None


# A request above PROMPT_LIMIT characters is compacted first. COMPACT_LEVELS are (list items kept, text characters kept), tried in order.
PROMPT_LIMIT = 16000
COMPACT_LEVELS = ((20, 400), (8, 200), (4, 120))


def compact(value, list_limit: int, text_limit: int):
    """A copy of a context with long lists and long texts shortened, so that it still says what it says, in less space."""
    if isinstance(value, dict):
        return {k: compact(v, list_limit, text_limit) for k, v in value.items()}
    if isinstance(value, list):
        return [compact(v, list_limit, text_limit) for v in value[:list_limit]]
    if isinstance(value, str) and len(value) > text_limit:
        return value[:text_limit] + "..."
    return value


class AIService:
    def __init__(self, provider: AIProvider | None, enabled: bool = True) -> None:
        self.provider = provider if enabled else None

    @property
    def available(self) -> bool:
        return self.provider is not None

    def status(self) -> dict:
        return {"llm_configured": self.available, "provider": self.provider.name if self.provider else None,
                "model": self.provider.model if self.provider else None,
                "mode": "llm" if self.available else "rule_engine"}

    # ------------------------------------------------------------------ #
    def _ask(self, context: dict, instruction: str, history: list[dict] | None = None) -> AIReply:
        if not self.provider:
            raise AIUnavailableError("No AI provider is configured.")
        # a context that is too large is compacted before sending; if the provider still refuses it (HTTP 413), it is compacted further
        attempts = [context, *(compact(context, *level) for level in COMPACT_LEVELS)]
        text = None
        for index, ctx in enumerate(attempts):
            last = index == len(attempts) - 1
            prompt = f"CONTEXT (JSON):\n{json.dumps(ctx, default=str, ensure_ascii=False)}\n\nTASK:\n{instruction}"
            if len(prompt) > PROMPT_LIMIT and not last:
                continue
            messages = [*(history or []), {"role": "user", "content": prompt}]
            try:
                text = self.provider.complete(SYSTEM_PROMPT, messages)
                context = ctx
                break
            except AIUnavailableError as exc:
                if "HTTP 413" not in str(exc) or last:
                    raise
        if not text:
            raise AIUnavailableError("The AI provider returned an empty reply.")
        grounding = check_grounding(text, {"context": context, "history": history or [], "task": instruction})
        notice = None
        if not grounding["grounded"]:
            notice = GROUNDING_WARNING.format(numbers=", ".join(grounding["unverified"][:15]))
            logger.warning("AI reply contained %d unverified number(s)", len(grounding["unverified"]))
        return AIReply(text, "llm", self.provider.name, self.provider.model, grounding, notice)

    def _fallback(self, text: str, reason: str | None = None) -> AIReply:
        notice = RULE_ENGINE_NOTICE if not reason else f"The AI provider is unavailable ({reason}). " + RULE_ENGINE_NOTICE.split(", so ")[1].capitalize()
        return AIReply(text, "rule_engine", notice=notice)

    def _run(self, context: dict, instruction: str, fallback_text: str, history: list[dict] | None = None) -> AIReply:
        if not self.available:
            return self._fallback(fallback_text)
        try:
            return self._ask(context, instruction, history)
        except AIUnavailableError as exc:
            logger.warning("AI provider failed: %s", exc)
            return self._fallback(fallback_text, str(exc))

    # ------------------------------------------------------------------ #
    def explain_result(self, context: dict, result: dict, question: str | None = None) -> AIReply:
        instruction = ("Explain the statistical result in CONTEXT.focus to the researcher. Structure the answer as: "
                       "1) what the engine computed, 2) what it means in plain language, 3) assumption checks and warnings, "
                       "4) how it relates to the research question or hypothesis, 5) what the researcher must judge."
                       + (f"\nThe researcher asks: {question}" if question else ""))
        return self._run(context, instruction, explain_result_rule_based(result))

    def explain_concept(self, context: dict, concept: str) -> AIReply:
        key = concept.strip().lower().replace("-", "_").replace(" ", "_")
        fallback = GLOSSARY.get(key) or next((text for name, text in GLOSSARY.items() if name in key or key in name), None)
        if fallback is None:
            fallback = ("This concept is not in the built-in glossary. Available topics: " + ", ".join(sorted(GLOSSARY)) +
                        ". Configure an AI provider for open-ended explanations.")
        return self._run(context, f"Explain the statistical concept '{concept}' for this researcher's academic level, "
                                  "using their own variables as the example where possible. Do not state any results that are not in CONTEXT.", fallback)

    def explain_chart(self, context: dict, chart_meta: dict) -> AIReply:
        notes = " ".join(chart_meta.get("notes") or [])
        fallback = (f"Chart: {chart_meta.get('title')} ({chart_meta.get('chart_type')}), based on {chart_meta.get('n')} records. {notes} "
                    "The rule engine can describe how to read this chart type but cannot describe its visual pattern; "
                    "run the matching statistical test to quantify what you see.")
        instruction = (
            "Explain the chart described in CONTEXT.focus.chart to someone who is NOT a statistician. You cannot see the image, so rely "
            "only on the chart details and results in CONTEXT. Use short sentences and everyday words. Avoid jargon; if a technical word "
            "is unavoidable, explain it in brackets. Do not invent numbers. Use these five headings in this order, each followed by "
            "one to three short bullet points or short sentences: What this chart shows; How to read it; What to notice; "
            "Careful with this; Does this prove a difference. Under What this chart shows, give the plain meaning in one or two "
            "sentences. Under How to read it, explain what the bars, dots or lines and their heights mean, and what the error "
            "bars mean in plain words. Under Careful with this, name data problems such as mixed spellings of the same category "
            "or missing values, and anything that stops the chart from proving a point. Under Does this prove a difference, say "
            "clearly whether this chart alone shows a real difference, and if not, which test would answer the question."
        )
        return self._run(context, instruction, fallback)

    def comment_on_recommendation(self, context: dict, recommendation: dict) -> AIReply:
        lines = [f"Recommended analysis: {recommendation['primary']['name']}", "", "Why:"]
        lines += [f"- {w}" for w in recommendation["why"]]
        if recommendation["assumption_checks"]:
            lines += ["", "Assumptions checked on your data:"]
            for a in recommendation["assumption_checks"]:
                mark = "met" if a["satisfied"] is True else "NOT met" if a["satisfied"] is False else "to be judged"
                lines.append(f"- {a['name']}: {mark}. {a.get('note') or ''}".rstrip())
        if recommendation["warnings"]:
            lines += ["", "Warnings:"] + [f"- {w}" for w in recommendation["warnings"]]
        if recommendation["alternatives"]:
            lines += ["", "Alternatives:"] + [f"- {a['name']}: {a['reason']}" for a in recommendation["alternatives"]]
        if recommendation["level_notes"]:
            lines += ["", f"For {recommendation['academic_level']} level work:"] + [f"- {n}" for n in recommendation["level_notes"]]
        return self._run(context, "CONTEXT.focus holds the method recommendation produced by the platform's rule engine from the variable types "
                                  "and assumption checks. Explain it to the researcher: why this method fits their question and design, what "
                                  "each failed assumption means, and when to use the alternative. Do not recommend a different method unless "
                                  "the rule engine's reasoning is clearly contradicted by CONTEXT, and say so explicitly if you do.", "\n".join(lines))

    def analyze_project(self, context: dict, eda_highlights: list[str], next_steps: list[str]) -> AIReply:
        lines = ["Dataset overview (from the statistical engine):"] + [f"- {h}" for h in eda_highlights]
        quality = context.get("data_quality")
        if quality:
            lines += ["", f"Data quality score: {quality['score']}%."] + [f"- {i['message']}" for i in quality["issues"][:6]]
        if next_steps:
            lines += ["", "Suggested next steps:"] + [f"- {s}" for s in next_steps]
        return self._run(context, "Review this research project: summarise the dataset, point out methodological or data-quality problems, "
                                  "state which research questions have and have not been analysed, and suggest the next analyses. "
                                  "Use only numbers present in CONTEXT.", "\n".join(lines))

    def draft_section(self, context: dict, kind: str, engine_draft: str) -> AIReply:
        instruction = {
            "findings": "Rewrite the engine-drafted findings in CONTEXT.focus as clear academic prose, one paragraph per finding. Keep every number exactly as given.",
            "conclusions": "Draft conclusions that follow strictly from the findings in CONTEXT.focus. Each conclusion must name the finding(s) it rests on. Add no new claims.",
            "recommendations": "Draft practical recommendations, each explicitly tied to a finding in CONTEXT.focus. No generic advice unrelated to the findings.",
            "limitations": "Describe the limitations listed in CONTEXT.focus in academic prose. Do not remove or soften any of them.",
        }.get(kind)
        if instruction is None:
            raise ValueError(f"Unknown section: {kind}")
        return self._run(context, instruction, engine_draft)

    def choose_method(self, context: dict, candidates: list[dict], rule_choice: str) -> dict:
        """Pick one test from the rule engine's implemented candidates and give the reason.

        The model may only choose a method that is in ``candidates``; anything else,
        or no provider at all, returns the rule engine's choice with no AI reason.
        """
        keys = [c["method"] for c in candidates]
        fallback = {"method": rule_choice, "reason": None, "source": "rule_engine", "notice": None}
        if not self.available:
            return fallback
        instruction = ("CONTEXT.focus.candidates lists the statistical tests the rule engine can run for this research question, "
                       "with its reasons. Choose the ONE candidate that best fits this research question and this analysis as a whole, "
                       "taking into account the other research questions and hypotheses in CONTEXT. CONTEXT.focus.failed_assumptions_on_this_data "
                       "lists assumptions the data did NOT meet: do not choose a candidate that requires an assumption on that list "
                       "(for example normality for Pearson or a t-test) when a candidate that does not require it is offered; name the "
                       "failed assumption in the reason. Reply with only a JSON object and "
                       'nothing else, in this form: {"method": "<one key from candidates>", "reason": "<two to four sentences for the '
                       'methodology section; use only numbers present in CONTEXT>"}.')
        try:
            reply = self._ask(context, instruction)
            data = json.loads(_strip_code_fence(reply.content))
            method, reason = data.get("method"), data.get("reason")
            if method not in keys or not isinstance(reason, str) or not reason.strip():
                raise AIUnavailableError("The AI did not choose one of the offered tests.")
        except (AIUnavailableError, ValueError, AttributeError) as exc:
            logger.warning("AI method choice not used: %s", exc)
            return {**fallback, "notice": str(exc)}
        return {"method": method, "reason": reason.strip(), "source": "llm", "notice": reply.notice,
                "provider": reply.provider, "model": reply.model, "grounding": reply.grounding}

    def _json_reply(self, context: dict, instruction: str):
        """One structured reply from the model: (parsed JSON, AIReply), or None if unavailable or unusable."""
        if not self.available:
            return None
        try:
            reply = self._ask(context, instruction)
            return json.loads(_strip_code_fence(reply.content)), reply
        except (AIUnavailableError, ValueError, AttributeError) as exc:
            logger.warning("AI structured reply not used: %s", exc)
            return None

    def plain_finding(self, context: dict) -> dict | None:
        """Rewrite one engine finding so that a reader who is not a statistician can follow it."""
        keys = ("title", "what_was_tested", "what_we_found", "what_it_means", "how_sure")
        instruction = ("CONTEXT.focus.finding is one statistical finding. Rewrite it for a reader who is not a statistician, using only "
                       "numbers and facts in CONTEXT.focus.finding and keeping every number exactly as given. Reply with only a JSON object "
                       '{"title": "<short plain title>", "what_was_tested": "<one or two sentences in everyday words>", '
                       '"what_we_found": "<one or two sentences>", "what_it_means": "<one or two sentences on the practical meaning, '
                       'without claiming cause unless the design supports it>", "how_sure": "<one sentence on how strong the evidence is '
                       'and the main caveat>"}.')
        result = self._json_reply(context, instruction)
        if result is None or not isinstance(result[0], dict):
            return None
        data, reply = result
        if not all(isinstance(data.get(k), str) and data[k].strip() for k in keys):
            return None
        return {**{k: data[k].strip() for k in keys}, "grounding": reply.grounding, "notice": reply.notice}

    def write_conclusion(self, context: dict) -> str | None:
        """One conclusion answering a research question, from its findings only (CONTEXT.focus)."""
        instruction = ("CONTEXT.focus.research_question is a research question and CONTEXT.focus.findings are the findings that answer it. "
                       "Write ONE conclusion for a reader who is not a statistician, using only those findings. Start by answering the question "
                       "(yes, partly, or no). Then state whether each hypothesis in the findings was supported by the data or not, saying that "
                       "a supported hypothesis is accepted as true for this study and that a non-supported one is not proven false. Explain the "
                       "statistics in everyday words and keep every number exactly as given. Say how strong the evidence is and claim no more "
                       "than the findings support. Reply with only a JSON object {\"text\": \"<four to eight sentences>\"}.")
        result = self._json_reply(context, instruction)
        if result is None or not isinstance(result[0], dict):
            return None
        text = result[0].get("text")
        return text.strip() if isinstance(text, str) and text.strip() else None

    def write_recommendations(self, context: dict, finding_ids: list[int]) -> list[dict] | None:
        """Practical recommendations, each tied to findings listed in CONTEXT.focus.findings."""
        instruction = ("CONTEXT.focus.findings lists the findings with their ids. Write practical recommendations for the researcher, at most "
                       "one per finding, each tied to the finding it comes from. No generic advice unrelated to the findings. Reply with only "
                       'a JSON object {"items": [{"text": "<one or two sentences>", "finding_ids": [<ids from CONTEXT.focus.findings>]}]}.')
        result = self._json_reply(context, instruction)
        if result is None or not isinstance(result[0], dict):
            return None
        known = set(finding_ids)
        out = []
        for item in result[0].get("items") or []:
            text = item.get("text") if isinstance(item, dict) else None
            ids = [i for i in (item.get("finding_ids") or []) if i in known] if isinstance(item, dict) else []
            if isinstance(text, str) and text.strip() and ids:
                out.append({"text": text.strip(), "finding_ids": list(dict.fromkeys(ids))})
        return out or None

    def map_variables(self, context: dict, names: list[str]) -> dict:
        """Identify the dependent and independent variables a research question is about.

        Only names in ``names`` (the dataset's own variables) are accepted. Always returns a dict with a ``status``:
        "mapped" (with dependent, independent, source), "no_match" (the reply named no dataset variable as the outcome),
        "unusable" (no JSON answer could be read), or "unavailable" (no provider, or it could not be reached).
        Every non-mapped result carries a ``reason`` the researcher can read. A reply that cannot be used is sent back
        to the model once with the problem described, so it can correct its own answer.
        """
        if not self.available:
            return {"status": "unavailable", "reason": "the AI assistant is turned off or not configured"}
        if not names:
            return {"status": "no_match", "reason": "the dataset has no variables"}
        instruction = ("CONTEXT.focus.plan_for.research_question is a research question. Using CONTEXT.focus.dataset_variables (match on "
                       "name and label), identify "
                       "the dependent (outcome) variable the question asks about and the independent (predictor or grouping) variables it "
                       "uses. Use ONLY names listed in dataset_variables, exactly as written. If the question names no outcome that exists "
                       "in the data, set dependent to null. Reply with only a JSON object and nothing else, in this form: "
                       '{"dependent": "<name or null>", "independent": ["<name>", ...]}.')
        history: list[dict] = []
        problem = None
        for attempt in range(3):
            try:
                reply = self._ask(context, instruction, history)
            except AIUnavailableError as exc:          # provider busy or unreachable: wait longer each time, then give up
                if attempt == 2:
                    logger.warning("AI variable mapping failed: %s", exc)
                    return {"status": "unavailable", "reason": f"the AI provider could not answer ({exc})"}
                time.sleep(5 * (attempt + 1))
                continue
            data = _json_object(reply.content)
            if data is None:
                problem = "The reply was not a JSON object."
            elif data.get("dependent") is not None and data.get("dependent") not in names:
                problem = f"'{data.get('dependent')}' is not a variable in the dataset. Use only the listed names."
            else:
                break
            logger.warning("AI variable mapping reply not usable (attempt %d): %s", attempt + 1, problem)
            history = [{"role": "assistant", "content": reply.content},
                       {"role": "user", "content": f"That reply cannot be used: {problem} Answer again with only the JSON object."}]
        else:
            return {"status": "unusable", "reason": f"the AI reply could not be used ({problem})"}
        if data.get("dependent") is None:
            return {"status": "no_match", "reason": "the question names no outcome variable that exists in the dataset"}
        known = set(names)
        dependent = data["dependent"]
        independent = [n for n in (data.get("independent") or []) if isinstance(n, str) and n in known and n != dependent]
        return {"status": "mapped", "dependent": dependent, "independent": list(dict.fromkeys(independent)), "source": "llm",
                "notice": reply.notice}

    def decide_missing(self, context: dict, columns: list[dict]) -> dict[str, dict] | None:
        """Ask the model what to do with each column that has missing values.

        ``columns`` are facts from the data (name, share missing, type, role) and the options allowed for each column. The reply is
        used only for listed columns and only for an allowed option, so the model cannot invent a column or an action. Returns
        {column: {"action", "reason"}}, or None when there is no provider or no usable answer.
        """
        if not self.available or not columns:
            return None
        instruction = ("CONTEXT.focus.missing_columns lists each column that has missing values, with its share missing, its type, "
                       "its role, and the actions allowed for it. For EACH column choose exactly one action from its 'allowed' list: "
                       "impute_median (fill with the median; numeric columns only), impute_mode (fill with the most frequent value), "
                       "delete_records (remove the records with this value missing), drop_column (remove the variable). "
                       "Fill small shares; delete records when the share is tiny or the column is the outcome; remove a variable only when "
                       "most of it is missing. Give a one-sentence reason a researcher can check. Reply with only a JSON object and nothing "
                       'else, in this form: {"decisions": [{"column": "<name exactly as listed>", "action": "<one allowed action>", '
                       '"reason": "<one sentence>"}]}')
        result = self._json_reply(context, instruction)
        if result is None:
            return None
        parsed, _ = result
        out: dict[str, dict] = {}
        for item in (parsed or {}).get("decisions") or []:
            if isinstance(item, dict) and isinstance(item.get("column"), str):
                out[item["column"]] = {"action": item.get("action"), "reason": item.get("reason")}
        return out or None

    def diagnose_issues(self, context: dict, issues: list[dict]) -> dict[str, str] | None:
        """Explain each blocking issue in plain language: where it comes from and what the researcher should do.

        Returns {code: explanation}, or None when there is no provider or no usable answer. The model may only explain the
        issues it is given; it does not change any data.
        """
        if not self.available or not issues:
            return None
        instruction = ("CONTEXT.focus.blocking_issues lists problems that stop a client package being built. For each issue, in plain "
                       "language for the researcher: say where the problem comes from in this project (use CONTEXT only) and the "
                       "one thing to do next. Do not invent numbers, references or results. Reply with only a JSON object and nothing "
                       'else, in this form: {"explanations": [{"code": "<issue code exactly as listed>", "explanation": "<two sentences>"}]}')
        result = self._json_reply(context, instruction)
        if result is None:
            return None
        parsed, _ = result
        wanted = {i["code"] for i in issues}
        out = {item["code"]: str(item["explanation"])[:500] for item in (parsed or {}).get("explanations") or []
               if isinstance(item, dict) and item.get("code") in wanted and item.get("explanation")}
        return out or None

    def chat(self, context: dict, history: list[dict], message: str) -> AIReply:
        fallback = None
        key = message.strip().lower()
        for name, text in GLOSSARY.items():
            if name.replace("_", " ") in key or name.replace("_", "-") in key:
                fallback = text
                break
        if fallback is None:
            results = context.get("statistical_results") or []
            if results:
                fallback = ("Here is the most recent result, explained by the rule engine:\n\n" + explain_result_rule_based(results[-1]) +
                            "\n\nFor open questions, configure an AI provider (see README, 'AI configuration'). "
                            "Built-in topics: " + ", ".join(n.replace("_", " ") for n in sorted(GLOSSARY)) + ".")
            else:
                fallback = ("No statistical results exist for this project yet, so there is nothing to interpret. Upload a dataset and run an "
                            "analysis first. Built-in topics I can explain: " + ", ".join(n.replace("_", " ") for n in sorted(GLOSSARY)) + ".")
        trimmed = [{"role": m["role"], "content": m["content"][:4000]} for m in history[-10:] if m["role"] in ("user", "assistant")]
        return self._run(context, message, fallback, trimmed)


def _strip_code_fence(text: str) -> str:
    """Models often wrap JSON in a ```json fence; remove it before parsing."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]
    return text.strip()


def as_public(reply: AIReply) -> dict[str, Any]:
    return reply.as_dict()
