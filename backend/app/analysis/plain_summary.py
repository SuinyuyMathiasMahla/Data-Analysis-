"""Plain-language summaries for everyday readers, one per hypothesis.

Each summary has seven parts: the question, the answer, how strong the link or difference is, whether it could be a fluke, a note of
caution, what the result does not mean, and a one-sentence takeaway. It is built only from the stored results and their labels, so it
adds no numbers or claims, and it avoids statistical terms. Each summary stays under 250 words."""
from __future__ import annotations

import math

from app.analysis import plain_english
from app.analysis.evidence import _is_difference_test, _main_test

STRENGTH_WORDS = {"negligible": "very weak", "weak": "weak", "small": "weak", "moderate": "moderate", "medium": "moderate",
                  "strong": "strong", "large": "strong"}


def _strength(magnitude: str | None) -> str:
    return STRENGTH_WORDS.get((magnitude or "").lower(), "measurable")


def _is_correlation(effect_name: str) -> bool:
    lowered = effect_name.lower()
    return lowered == "r" or lowered.startswith("r ") or "correlation" in lowered or "coefficient" in lowered


def _question(rq: dict) -> str:
    text = rq["text"].strip()
    return text if text.endswith("?") else f"{text}?"


def _answer(result: dict, labels: dict[str, str]) -> str:
    outcome, predictor = plain_english.roles(result, labels)
    outcome, predictor = outcome or "the outcome", predictor or "the other factor"
    n = result.get("n")
    records = f"Among the {n} records" if n is not None else "In the data"
    supported = result.get("decision") == "reject_null"
    effect = next((e for e in result.get("effect_sizes") or [] if e.get("value") is not None), None)
    if _is_difference_test(result):
        if supported:
            return f"Yes. {records}, {outcome} differs between the groups of {plain_english.mid(predictor)}."
        return f"No. {records}, we did not find a clear difference in {outcome} between the groups of {plain_english.mid(predictor)}."
    if supported:
        if effect is not None:
            return f"Yes. {records}, {plain_english.direction_clause(effect, plain_english.mid(predictor), plain_english.mid(outcome))}."
        return f"Yes. {records}, {plain_english.mid(predictor)} and {plain_english.mid(outcome)} are linked."
    return f"No. {records}, we did not find a clear link between {plain_english.mid(predictor)} and {plain_english.mid(outcome)}."


def _strength_line(result: dict) -> str:
    effect = next((e for e in result.get("effect_sizes") or [] if e.get("value") is not None), None)
    if effect is None:
        return "How strong is it? The size of the effect was not recorded for this test."
    value = effect["value"]
    if plain_english.is_odds_ratio(effect) and not effect.get("magnitude"):
        line = (f"How strong is the link? The odds ratio is {value:.2f}. A value of 1 means no change in the odds, so the further "
                "the value is from 1, the stronger the link.")
    else:
        word = _strength(effect.get("magnitude"))
        if _is_correlation(effect["name"]):
            line = (f"How strong is the link? It is {word}. The scale runs from -1, a perfect opposite link, through 0, no link, "
                    f"to +1, a perfect same-direction link. The figure here is {value:.2f}.")
        elif "cohen" in effect["name"].lower() or "hedges" in effect["name"].lower():
            line = f"How strong is the difference? It is {word}: the groups differ by about {abs(value):.2f} of the usual spread of the values."
        else:
            line = f"How strong is it? It is {word}. The figure here is {value:.2f}."
    if effect.get("ci_low") is not None and effect.get("ci_high") is not None:
        line += f" The true figure most likely falls between {effect['ci_low']:.2f} and {effect['ci_high']:.2f}."
    return line


def _fluke_line(result: dict, agreeing: int) -> str:
    p, alpha = result.get("p_value"), result.get("alpha", 0.05)
    if p is None:
        return "Could it be a fluke? The chance could not be worked out for this test."
    if p < alpha:
        chance = "less than 1 in 1,000 times" if p < 0.001 else f"about {math.ceil(p * 100)} times in 100"
        line = (f"Could it be a fluke? Not likely. If there were truly no connection, a result this strong would show up by chance "
                f"{chance}.")
    else:
        line = (f"Could it be a fluke? Quite possibly. If there were truly no connection, a result this strong would show up by chance "
                f"about {round(p * 100)} times in 100.")
    if agreeing:
        line += " A second test gave the same answer."
    return line


def _caution_line(result: dict) -> str | None:
    reasons = []
    if any(a.get("satisfied") is False for a in result.get("assumptions") or []):
        reasons.append("some checks the test relies on were not fully met, because the values are not spread evenly")
    if result.get("n") is not None and result["n"] < 30:
        reasons.append(f"the group of records is small ({result['n']})")
    if not reasons:
        return None
    return ("A note of caution: " + " and ".join(reasons) + ". This lowers how much we should trust the exact figures, "
            "though the direction of the result is still worth noting.")


def summarise(rq: dict, group: list[dict], labels: dict[str, str], hypothesis: dict | None = None) -> list[str]:
    """The seven parts for one hypothesis. ``group`` holds the findings (tests) of that hypothesis, and the main test is used."""
    main = _main_test(group)
    result = main.get("result") or {}
    if not result:
        return []
    decision = result.get("decision")
    agreeing = sum(1 for other in group if other is not main and (other.get("result") or {}).get("decision") == decision
                   and other.get("result"))
    outcome, predictor = plain_english.roles(result, labels)
    outcome, predictor = outcome or "the outcome", predictor or "the other factor"
    supported = decision == "reject_null"
    effect = next((e for e in result.get("effect_sizes") or [] if e.get("value") is not None), None)
    word = _strength(effect.get("magnitude")) if effect else None

    if supported and word:
        takeaway = (f"In one sentence: {plain_english.cap(predictor)} and {plain_english.mid(outcome)} are linked in this sample, "
                    f"the link is {word}, and it does not prove that one causes the other.")
    elif supported:
        takeaway = (f"In one sentence: {plain_english.cap(predictor)} and {plain_english.mid(outcome)} are linked in this sample, "
                    "but this does not prove that one causes the other.")
    else:
        takeaway = (f"In one sentence: the data did not show a clear link between {plain_english.mid(predictor)} and "
                    f"{plain_english.mid(outcome)}, so the result is not proof that none exists.")

    not_mean = ("What this does NOT mean: a link does not prove that one causes the other, unless the study was designed to test cause. "
                "Another factor that affects both measures, such as family or study habits, could explain the pattern.")
    lines = [
        f"The question: {_question(rq)}",
        f"The answer: {_answer(result, labels)}",
        _strength_line(result),
        _fluke_line(result, agreeing),
    ]
    caution = _caution_line(result)
    if caution:
        lines.append(caution)
    lines += [not_mean, takeaway]
    return lines


def build(rq_list: list[dict], findings: list[dict], labels: dict[str, str]) -> list[dict]:
    """A plain-language summary for each hypothesis of each research question that has a finding."""
    out: list[dict] = []
    for rq in rq_list:
        linked = [f for f in findings if f.get("research_question_id") == rq["id"]]
        groups: dict = {}
        for finding in linked:
            groups.setdefault(finding.get("hypothesis_id"), []).append(finding)
        for key, group in groups.items():
            lines = summarise(rq, group, labels, group[0].get("hypothesis"))
            if lines:
                out.append({"code": rq["code"], "lines": lines})
    return out
