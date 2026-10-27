"""Plain-English explanations of the statistical results.

Every number comes from the statistical engine's output. This module only explains what the numbers mean, in words that a reader
who is not a statistician can follow. It never calculates or changes a value."""
from __future__ import annotations

import re
from typing import Any

from app.analysis.variable_choice import _words


def _pct(value: float) -> str:
    return f"{abs(value) * 100:.0f}%"


def cap(text: str) -> str:
    """The text with its first letter capitalised, for a sentence that starts with a label."""
    return text[:1].upper() + text[1:] if text else text


def p_text(p: float) -> str:
    """The p-value as it is written in a sentence: 'below 0.001', or three decimals."""
    return "below 0.001" if p < 0.001 else f"{p:.3f}"


def mid(label: str) -> str:
    """A label written in the middle of a sentence: the first word is lower-cased unless it is an acronym such as GPA."""
    if not label or re.match(r"[A-Z]{2,}\b", label):
        return label
    return label[:1].lower() + label[1:]


def variable_label(name: str | None, labels: dict[str, str]) -> str:
    """The variable's label from the data dictionary, or its name written in words."""
    if not name:
        return "not recorded"
    return labels.get(name) or name.replace("_", " ")


def variable_names(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


def roles(result: dict, labels: dict[str, str]) -> tuple[str | None, str | None]:
    """The outcome (the thing measured) and the predictor or grouping (what it is compared or related to), in words."""
    v = result.get("variables") or {}
    outcome = next(iter(variable_names(v.get("outcome")) or variable_names(v.get("y")) or variable_names(v.get("second"))), None)
    predictor = next(iter(variable_names(v.get("group")) or variable_names(v.get("x")) or variable_names(v.get("first"))
                         or variable_names(v.get("predictors"))), None)
    if predictor == outcome:
        predictor = None
    return (variable_label(outcome, labels) if outcome else None, variable_label(predictor, labels) if predictor else None)


def describe_p(p: float | None, alpha: float) -> str:
    if p is None:
        return "The p-value could not be calculated."
    if p < 0.001:
        chance = "fewer than 1 in 1,000"
        value = "below 0.001"
    else:
        chance = f"about {round(p * 100)} in 100"
        value = f"{p:.3f}"
    side = "below" if p < alpha else "above"
    return (f"The p-value is {value}. It is the chance of seeing a result this strong, or stronger, if there were really no effect: "
            f"{chance} similar studies would show it by chance alone. That is {side} the cut-off of {alpha:g} used for this study.")


def describe_effect(effect: dict) -> str:
    name, value, magnitude = (effect.get("name") or "effect size"), effect.get("value"), effect.get("magnitude")
    if value is None:
        return ""
    lowered = name.lower()
    strength = f", a {magnitude} one" if magnitude else ""
    if lowered == "r" or lowered.startswith("r ") or "correlation" in lowered or ("coefficient" in lowered and "r²" not in lowered):
        if value > 0:
            direction = "Both measures tend to rise and fall together."
        elif value < 0:
            direction = "When one measure goes up, the other tends to go down."
        else:
            direction = "There is no direction to the link."
        text = f"The strength of the link is {value:.2f}{strength}. The value runs from -1 to +1, where 0 means no link. {direction}"
    elif "cohen" in lowered or "hedges" in lowered or "glass" in lowered:
        text = (f"The average gap between the groups is {abs(value):.2f} standard deviations{strength}. "
                "A standard deviation is the usual spread of the values, so this compares the gap with how much people vary.")
    elif "eta" in lowered:
        text = f"About {_pct(value)} of the differences in the measured values is linked to the groups{strength}."
    elif "cramér" in lowered or "cramer" in lowered:
        text = f"The link between the two categories is {magnitude or 'measured'} (strength {value:.2f} on a scale from 0 to 1)."
    elif "odds ratio" in lowered:
        text = f"The odds of the outcome are {value:.2f} times as large (1 means no difference){strength}."
    elif "r²" in lowered or "r-squared" in lowered or "r squared" in lowered:
        text = f"The predictors explain about {_pct(value)} of the variation in the outcome{strength}."
    elif "rank-biserial" in lowered:
        text = f"The difference in ranks between the groups is {magnitude or 'measured'} ({value:.2f} on a scale from -1 to +1)."
    else:
        text = f"{name} is {value:.2f}{strength}."
    ci_low, ci_high = effect.get("ci_low"), effect.get("ci_high")
    if ci_low is not None and ci_high is not None:
        text += f" The 95% confidence interval runs from {ci_low:.2f} to {ci_high:.2f}: the true value most likely lies in this range."
        if ci_low < 0 < ci_high:
            text += " Because the range includes zero, the direction of the effect is not certain."
    return text


def describe_statistic(result: dict) -> str:
    statistic = result.get("statistic") or {}
    if statistic.get("value") is None:
        return ""
    df = result.get("df")
    df_text = ""
    if df not in (None, "", []):
        def whole(x):
            return int(x) if isinstance(x, float) and x.is_integer() else x
        listed = [whole(x) for x in df] if isinstance(df, list) else [whole(df)]
        df_text = f" with {', '.join(str(x) for x in listed)} degrees of freedom"
    return (f"The test statistic is {statistic.get('name', 't')} = {statistic['value']:.2f}{df_text}. It measures how large the "
            "pattern is compared with the normal variation in the data: the bigger it is, the stronger the evidence.")


def describe_conditions(result: dict) -> str:
    checks = result.get("assumptions") or []
    if not checks:
        return "No conditions were recorded for this test."
    not_met = [c for c in checks if c.get("satisfied") is False]
    if not not_met:
        return "The conditions this test needs were met."
    names = "; ".join(c["name"].lower() for c in not_met)
    return (f"Some conditions were not fully met: {names}. The result should be read with more caution, because the test assumes these conditions hold.")


def hypothesis_lines(hypothesis: dict | None) -> tuple[str, str]:
    """The null (H0) and alternative (H1) statements, as written by the researcher. Empty strings when none were entered."""
    if not hypothesis:
        return "", ""
    return (hypothesis.get("null_text") or "", hypothesis.get("alternative_text") or "")


def verdict(decision: str | None, p: float | None, alpha: float) -> tuple[str, str]:
    """Which statement is true for this study's data, and why. Returns (headline, reason)."""
    shown = p_text(p) if p is not None else "not available"
    if decision == "reject_null":
        return ("The alternative hypothesis (H1) is the true statement for this study. The null hypothesis (H0) is false for these data.",
                f"The p-value ({shown}) is below the cut-off of {alpha:g}. A pattern this strong would be unlikely to appear by chance "
                "if H0 were true, so H0 is rejected and H1 is accepted.")
    return ("The null hypothesis (H0) is the statement the data support. The alternative hypothesis (H1) is not supported.",
            f"The p-value ({shown}) is above the cut-off of {alpha:g}. The data do not show a pattern strong enough to rule out chance, "
            "so H0 cannot be rejected. This does not prove H0 is true: a larger study may still find a real effect.")


def direction_note(hypothesis: dict | None, result: dict) -> str:
    direction = (hypothesis or {}).get("direction", "non_directional")
    if direction != "non_directional" and result.get("alternative", "two-sided") == "two-sided":
        return (" Note: this hypothesis predicted a direction, but the test checked both directions. Confirm that the observed direction "
                "matches the prediction before claiming support.")
    return ""


def term_name(name: str) -> str:
    """The term an effect refers to, without the 'Odds ratio: ' prefix the engine adds."""
    return name.split(": ", 1)[1] if name.lower().startswith("odds ratio: ") else name


def is_odds_ratio(effect: dict) -> bool:
    return "odds ratio" in (effect.get("name") or "").lower()


def direction_words(effect: dict) -> str:
    """The direction of an effect, read correctly: an odds ratio is compared with 1, a coefficient with 0."""
    value = effect["value"]
    if is_odds_ratio(effect):
        if abs(value - 1) < 0.005:
            return "no change in odds"
        return "higher odds (odds ratio above 1)" if value > 1 else "lower odds (odds ratio below 1)"
    if value == 0:
        return "no clear direction"
    return "a positive direction" if value > 0 else "a negative direction"


def direction_clause(effect: dict, predictor: str, outcome: str) -> str:
    """One plain sentence, without a full stop, for how an effect links a predictor with an outcome."""
    value = effect["value"]
    if is_odds_ratio(effect):
        term = term_name(effect["name"])
        if abs(value - 1) < 0.005:
            return f"{term} makes no clear difference to the odds of {outcome}"
        return f"{term} goes with {'higher' if value > 1 else 'lower'} odds of {outcome} (odds ratio {value:.2f})"
    if value == 0:
        return f"there is no clear direction between {predictor} and {outcome}"
    return f"higher {predictor} goes with {'higher' if value > 0 else 'lower'} {outcome}"


def all_predictors(result: dict, labels: dict[str, str]) -> list[str]:
    """Every predictor the model or test used, in words, without the outcome."""
    v = result.get("variables") or {}
    outcome_name = next(iter(variable_names(v.get("outcome")) or variable_names(v.get("y")) or variable_names(v.get("second"))), None)
    names = (variable_names(v.get("predictors")) or variable_names(v.get("group")) or variable_names(v.get("x"))
             or variable_names(v.get("first")))
    return [variable_label(n, labels) for n in names if n != outcome_name]


def mismatch_sentence(question: str | None, result: dict, labels: dict[str, str]) -> str | None:
    """A warning when none of the words in the research question appear in the variables that were analysed."""
    words = set(_words(question or ""))
    v = result.get("variables") or {}
    names = [n for key in ("outcome", "y", "second", "group", "x", "first", "predictors") for n in variable_names(v.get(key))]
    if not names or not words:
        return None
    tokens: set[str] = set()
    for name in names:
        tokens |= set(re.findall(r"[a-z0-9]+", f"{name} {labels.get(name) or ''}".lower()))
    if words & tokens:
        return None
    used = ", ".join(variable_label(n, labels) for n in names)
    return (f"Check the variables: none of the words in the question appear in the variables that were analysed ({used}). "
            "The answer is only as good as the match between the question and these variables, so confirm that they measure what the question asks.")
