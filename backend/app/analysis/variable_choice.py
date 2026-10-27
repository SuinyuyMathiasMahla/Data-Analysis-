"""Choosing the outcome (dependent) and predictor (independent) variables of a research question from its wording and the
dataset's variables. It is used when the AI assistant is off, unreachable or unsure, so that every question still gets an
analysis. It only ever returns variables that exist in the dataset, and it says which words it matched, so the choice can be checked."""
from __future__ import annotations

import re

NUMERIC = ("numeric", "integer")
STOP = {"is", "the", "a", "an", "of", "in", "and", "or", "to", "by", "are", "there", "does", "do", "did", "how", "what", "which", "that",
        "with", "on", "for", "from", "as", "at", "be", "it", "its", "this", "study", "research", "question", "significant", "significantly",
        "level", "levels", "minus", "plus", "s", "between", "among", "across", "groups", "group", "factors", "factor",
        "average", "mean", "number", "total", "percent", "proportion", "overall", "typical", "usual", "many", "much"}
# words after which the variable named is the outcome ("predict GPA", "affects GPA", "related to GPA")
OUTCOME_CUES = {"predict", "predicts", "affect", "affects", "influence", "influences", "explain", "explains", "impact", "impacts",
                "determine", "determines", "to", "with"}
COMPARISON = {"difference", "differ", "differs", "different", "compare", "compared", "comparison", "between", "across", "among", "groups",
              "group", "levels", "level"}
RELATION = {"relate", "related", "relationship", "link", "linked", "association", "associated", "affect", "affects", "influence",
            "influences", "predict", "predicts", "predictor", "predictors", "effect", "effects", "change", "changes", "explain", "explains"}


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOP and len(w) > 1]


def _name_words(variable: dict) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", f"{variable['name']} {variable.get('label') or ''}".lower())) - STOP


def _is_usable(variable: dict) -> bool:
    return variable.get("data_type") != "identifier" and variable.get("role") != "identifier"


def choose_variables(question: str, variables: list[dict], dependent: str | None = None) -> dict:
    """Pick the outcome and the predictors for a question.

    ``variables`` are dicts with name, label, data_type and role. If ``dependent`` is given (the outcome is already linked),
    only the predictors are chosen. Returns {dependent, independent, matched, basis}; dependent is None only when the dataset
    has no variable that can be analysed. ``matched`` lists the words from the question that matched variable names."""
    usable = [v for v in variables if _is_usable(v)]
    if not usable:
        return {"dependent": None, "independent": [], "matched": [], "basis": "the dataset has no variables that can be analysed"}
    question_words = set(_words(question))
    score = {v["name"]: len(question_words & _name_words(v)) for v in usable}
    matched = sorted({w for v in usable for w in question_words & _name_words(v)})
    by_name = {v["name"]: v for v in usable}
    notes: list[str] = []

    if dependent is None:
        tokens = re.findall(r"[a-z0-9]+", (question or "").lower())
        first_at = {v["name"]: min((i for i, t in enumerate(tokens) if t in _name_words(v) and t not in STOP), default=len(tokens))
                    for v in usable if score[v["name"]]}
        cues = [i for i, t in enumerate(tokens) if t in OUTCOME_CUES]
        after_cue = [v for v in usable if score[v["name"]] and cues and first_at[v["name"]] > cues[-1]]
        if after_cue:
            best = max(after_cue, key=lambda v: (score[v["name"]], -first_at[v["name"]]))
            notes.append(f"'{best['name']}' is the outcome because the question names it after a word such as 'predict', 'affect' or 'to'")
        else:
            numeric = [v for v in usable if v.get("data_type") in NUMERIC]
            pool = numeric or usable
            best = max(pool, key=lambda v: (score[v["name"]], -first_at.get(v["name"], len(tokens)), -len(v["name"])))
            if score[best["name"]]:
                notes.append(f"'{best['name']}' is the outcome because its name matches the question")
            else:
                notes.append(f"no variable name matches the question, so the first numeric variable, '{best['name']}', is the outcome")
        dependent = best["name"]
    dependent_var = by_name.get(dependent) or next(v for v in usable if v["name"] == dependent)

    others = [v for v in usable if v["name"] != dependent]
    ranked = sorted((v for v in others if score[v["name"]] > 0), key=lambda v: (-score[v["name"]], v["name"]))
    independent = [v["name"] for v in ranked][:3]
    if not independent:
        comparing = bool(question_words & COMPARISON)
        candidates = [v for v in others if (v.get("data_type") not in NUMERIC) == comparing] or others
        if candidates:
            independent = [candidates[0]["name"]]
            kind = "a grouping variable" if comparing else "a predictor"
            notes.append(f"no predictor is named in the question, so '{independent[0]}' was chosen as {kind}, the first variable that fits")
    if independent and any(score[n] for n in independent):
        notes.insert(0, f"predictor{'s' if len(independent) > 1 else ''}: {', '.join(repr(n) for n in independent)} "
                        "(matched on the wording of the question)")
    return {"dependent": dependent_var["name"], "independent": independent, "matched": matched, "basis": "; ".join(notes)}


def needs_predictor(question: str) -> bool:
    """A question that compares or relates things needs a predictor. Descriptive questions do not."""
    return bool(set(_words(question)) & (COMPARISON | RELATION))
