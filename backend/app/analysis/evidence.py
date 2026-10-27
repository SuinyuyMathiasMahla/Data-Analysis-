"""Evidence trail: findings, conclusions, recommendations and limitations.

Everything here is derived *from stored engine results* by fixed rules. Nothing
is invented: a drafted finding quotes the engine's own summary and statistics,
a conclusion is assembled only from findings, and a recommendation always
names the finding it rests on. All drafts are starting points that the
researcher edits; the researcher remains responsible for the interpretation.
"""
from __future__ import annotations

from typing import Any

from app.analysis import plain_english

STAGES = [
    ("project", "Create research project"),
    ("research_questions", "Define research questions"),
    ("hypotheses", "Define hypotheses"),
    ("dataset", "Upload dataset"),
    ("quality", "Check data quality"),
    ("cleaning", "Clean data"),
    ("exploration", "Explore data"),
    ("analysis", "Run analysis"),
    ("findings", "Review findings"),
    ("conclusions", "Conclusions and recommendations"),
    ("charts", "Charts worth drawing"),
    ("report", "Generate report"),
]


def evidence_string(result: dict) -> str:
    """Compact statistical evidence line taken verbatim from the engine output."""
    parts = []
    if result.get("apa"):
        parts.append(result["apa"])
    parts.append(f"n = {result.get('n')}")
    for effect in (result.get("effect_sizes") or [])[:2]:
        if effect.get("value") is not None and effect["name"].split(" ")[0] not in (result.get("apa") or ""):
            text = f"{effect['name']} = {effect['value']:.3f}"
            if effect.get("ci_low") is not None:
                text += f" (95% CI {effect['ci_low']:.3f} to {effect['ci_high']:.3f})"
            parts.append(text)
    return "; ".join(parts)


def evidence_confidence(result: dict) -> tuple[str, list[str]]:
    """Rate how far the statistical evidence can be relied on (low / moderate / high).

    A result is only rated high when it is statistically significant, the effect is at least
    moderate in size, the sample is adequate and no assumption failed. A null result is rated low:
    it cannot show that there is no effect, only that none was detected.
    """
    reasons: list[str] = []
    n = result.get("n") or 0
    failed = [a for a in result.get("assumptions") or [] if a.get("satisfied") is False]
    warnings = result.get("warnings") or []
    alpha = result.get("alpha", 0.05)
    p = result.get("p_value")
    magnitude = next((str(e.get("magnitude") or "").lower() for e in result.get("effect_sizes") or [] if e.get("magnitude")), "")
    score = 2
    if n < 30:
        score -= 1
        reasons.append(f"Small sample (n = {n}).")
    for a in failed:
        reasons.append(f"Assumption not met: {a['name']}. {a.get('note') or ''}".strip())
    if len(failed) >= 2:
        score -= 1
    serious = [w for w in warnings if any(k in w.lower() for k in ("separation", "unreliable", "over-fitted", "overdispers", "too small"))]
    if serious:
        score -= 1
    reasons += [w for w in warnings if w not in reasons]
    if p is not None and p > alpha:
        reasons.append("No statistically significant result: the data are consistent with no effect, but a study of this size may simply "
                       "be unable to detect a real one.")
        return "low", reasons
    if magnitude in ("negligible", "weak", "small"):
        reasons.append(f"The effect is {magnitude}, so its practical importance is limited even though it is statistically significant.")
        score = min(score, 1)
    if score >= 2 and n >= 100 and not failed and magnitude in ("moderate", "strong", "large", "medium"):
        return "high", reasons
    return ("low" if score <= 0 else "moderate"), reasons


def hypothesis_verdict(result: dict, hypothesis: dict | None) -> str | None:
    """Plain statement of the decision about H0. One-sided hypotheses are only
    decided when the test itself was run one-sided."""
    if not hypothesis or result.get("p_value") is None:
        return None
    alpha = result.get("alpha", 0.05)
    code = hypothesis.get("code", "H")
    direction = hypothesis.get("direction", "non_directional")
    note = ""
    if direction != "non_directional" and result.get("alternative", "two-sided") == "two-sided":
        note = (" Note: the hypothesis is directional but the test was two-sided; check that the direction of the effect "
                "matches the hypothesis before claiming support.")
    if result.get("decision") == "reject_null":
        return f"{code}: the null hypothesis is rejected at alpha = {alpha:g} ({result.get('apa') or ''}).{note}"
    return (f"{code}: the null hypothesis is not rejected at alpha = {alpha:g} ({result.get('apa') or ''}). "
            "Failing to reject H0 is not evidence that H0 is true.")


def draft_finding(result: dict, research_question: dict | None = None, hypothesis: dict | None = None) -> dict:
    """Draft one finding from one engine result."""
    confidence, reasons = evidence_confidence(result)
    variables = result.get("variables") or {}
    names = []
    for value in variables.values():
        names += value if isinstance(value, list) else [value] if isinstance(value, str) else []
    title = f"{result.get('method_name', 'Analysis')}: {', '.join(names[:4])}" + ("..." if len(names) > 4 else "")
    interpretation = result.get("summary") or ""
    verdict = hypothesis_verdict(result, hypothesis)
    if verdict:
        interpretation += " " + verdict
    return {
        "title": title[:250],
        "statement": result.get("summary") or "",
        "statistical_evidence": evidence_string(result),
        "interpretation": interpretation.strip(),
        "confidence_level": confidence,
        "limitations_note": " ".join(reasons) or None,
        "source": "engine",
        "research_question_code": (research_question or {}).get("code"),
        "hypothesis_code": (hypothesis or {}).get("code"),
    }


PLAIN_METHODS = [
    (("correlation", "spearman", "kendall"), "a correlation test, which measures how closely two measures move together"),
    (("chi-square", "chi square", "chi2", "fisher"), "a test of whether two categories are linked"),
    (("anova", "kruskal", "tukey", "bonferroni"), "a comparison of averages across several groups"),
    (("t-test", "t test", "welch", "mann", "wilcoxon"), "a comparison between two groups"),
    (("regression",), "a regression, which checks whether the other variables help predict the outcome"),
]
GROUP_METHODS = ("t_test", "mann_whitney", "anova", "kruskal", "chi_square", "fisher", "wilcoxon", "friedman")


def plain_method(name: str | None) -> str:
    """What a statistical test does, in everyday words."""
    lowered = (name or "").lower()
    for keys, text in PLAIN_METHODS:
        if any(key in lowered for key in keys):
            return text
    return f"the statistical test '{name}'" if name else "a statistical test"


def _is_difference_test(result: dict) -> bool:
    method = (result.get("method") or "").lower()
    return "group" in (result.get("variables") or {}) or any(key in method for key in GROUP_METHODS)


def _generated_hypotheses(result: dict, labels: dict[str, str]) -> tuple[str, str]:
    """H0 and H1 written from the variables, for a question that has no hypothesis entered."""
    outcome, predictor = plain_english.roles(result, labels)
    outcome_text = plain_english.mid(outcome or "the outcome")
    predictor_text = plain_english.mid(predictor or "the predictor")
    if _is_difference_test(result):
        return (f"There is no difference in {outcome_text} between the groups of {predictor_text}.",
                f"There is a difference in {outcome_text} between the groups of {predictor_text}.")
    return (f"There is no relationship between {predictor_text} and {outcome_text}.",
            f"There is a relationship between {predictor_text} and {outcome_text}.")


def _direction_sentence(result: dict, outcome: str, predictor: str) -> str:
    """How the predictor moves the outcome, in one sentence. Empty when there is no effect or the test compares groups."""
    effect = first_effect_of(result)
    if effect is None or _is_difference_test(result):
        return ""
    return f"In this sample, {plain_english.direction_clause(effect, plain_english.mid(predictor), plain_english.mid(outcome))}."


def _plain_caveat(result: dict) -> str:
    """The reasons the evidence is not stronger, in plain words. The engine's notes quote technical numbers, so they are not copied."""
    reasons = []
    if result.get("n") is not None and result["n"] < 30:
        reasons.append(f"the sample is small ({result['n']} records)")
    if any(a.get("satisfied") is False for a in result.get("assumptions") or []):
        reasons.append("some conditions the test needs were not met")
    return (" The main reason for caution: " + " and ".join(reasons) + ".") if reasons else ""


def _main_test(group: list[dict]) -> dict:
    """The test that best represents a hypothesis: the one with the smallest p-value, or the first one when none has a p-value."""
    def rank(f: dict) -> float:
        p = (f.get("result") or {}).get("p_value")
        return p if p is not None else 2.0
    return min(group, key=rank)


def _direction_words(result: dict) -> str:
    """The direction of the main effect in plain words, read correctly for odds ratios."""
    effect = first_effect_of(result)
    if effect is None:
        return "no clear direction"
    return plain_english.direction_words(effect)


def first_effect_of(result: dict) -> dict | None:
    return next((e for e in result.get("effect_sizes") or [] if e.get("value") is not None), None)


def _strength_rating(findings: list[dict]) -> str:
    """Strong, Moderate or Weak for the main test of a question, from the engine's confidence rating."""
    confidence = next((f.get("confidence_level") for f in findings if f.get("confidence_level")), None)
    return {"high": "Strong", "moderate": "Moderate", "low": "Weak"}.get(confidence or "", "Weak")


def _conditions_met(result: dict) -> bool:
    return not any(a.get("satisfied") is False for a in result.get("assumptions") or [])


def _sentence_limitation(main: dict, result: dict) -> str:
    """One specific limitation for this conclusion, not a generic caveat."""
    failed = next((a for a in result.get("assumptions") or [] if a.get("satisfied") is False), None)
    test = plain_method(result.get("method_name") or main.get("title"))
    if failed is not None:
        return (f"The condition '{failed['name'].lower()}' was not met for {test}, so the reported figures may be less reliable "
                "and should be read with caution.")
    if result.get("n") is not None and result["n"] < 30:
        return f"The sample is small ({result['n']} records), so the estimates are imprecise and a real effect may have been missed."
    if main.get("filter_note"):
        return f"{main['filter_note']} The conclusion applies to the groups that were compared, not to every group in the data."
    if (result.get("decision") == "reject_null") and not _is_difference_test(result):
        return ("The data are observational: the link shows that the two measures move together in this sample, and other factors that "
                "were not measured may account for it.")
    return "The data come from one sample, so the result may not hold for other groups or settings."


def _recommendation(number: int, rq: dict, primary: dict, labels: dict[str, str], finding_number: int | None,
                    project_title: str | None = None) -> str:
    """A recommendation tied to this result: who acts, what they do, the actual figures, and a measurable outcome."""
    result = primary.get("result") or {}
    outcome, predictor = plain_english.roles(result, labels)
    outcome, predictor = outcome or "the outcome", predictor or "the predictor"
    everyone = plain_english.all_predictors(result, labels)
    factors = ", ".join(everyone) if len(everyone) > 1 else predictor
    n = result.get("n") or 0
    p = plain_english.p_text(result["p_value"]) if result.get("p_value") is not None else "not available"
    effect = first_effect_of(result)
    audience = (f"those responsible for {project_title}" if project_title else "researchers and the project lead")
    basis = f"Finding {finding_number}" if finding_number else "the finding for this question"
    if result.get("decision") == "reject_null":
        clause = (plain_english.direction_clause(effect, plain_english.mid(predictor), plain_english.mid(outcome)) if effect
                  else f"{plain_english.mid(predictor)} and {plain_english.mid(outcome)} are linked")
        body = (f"Audience: {audience}. Action: when planning for {plain_english.mid(outcome)}, give {plain_english.mid(factors)} priority "
                f"as factors to monitor, because {clause} (p {p}). Expected benefit: decisions about {plain_english.mid(outcome)} will rest "
                f"on a link shown in {n} records rather than on assumption. Justified by {basis}. Expected measurable outcome: repeating "
                f"this analysis on a new sample of at least {max(n, 100)} records should again show the same direction at p below 0.05.")
    else:
        body = (f"Audience: {audience}. Action: do not change practice on {plain_english.mid(outcome)} because of "
                f"{plain_english.mid(factors)} alone, since the data show no clear link (p {p}). Expected benefit: avoids acting on a link "
                f"the data did not show. Justified by {basis}. Expected measurable outcome: a larger study of at least {max(2 * n, 100)} "
                "records would show whether a link exists, with p below 0.05 if it does.")
    return f"RECOMMENDATION {number}: {body}"


def _hypothesis_verdict(code: str, decision: str | None) -> str:
    if decision == "reject_null":
        return f"{code} — H0 (Null Hypothesis): Rejected. H1 (Alternative Hypothesis): Accepted."
    if decision == "fail_to_reject_null":
        return f"{code} — H0 (Null Hypothesis): Accepted. H1 (Alternative Hypothesis): Rejected."
    return f"{code} — no decision could be made for this hypothesis."


def _summary_sentences(group: list[dict], labels: dict[str, str]) -> list[str]:
    """Up to five sentences that carry the numbers for one hypothesis, from its main test."""
    main = _main_test(group)
    result = main.get("result") or {}
    if not result:
        return [main.get("statement") or ""]
    outcome, predictor = plain_english.roles(result, labels)
    outcome, predictor = outcome or "the outcome", predictor or "the predictor"
    statistic = result.get("statistic") or {}
    stat_text = (f"{statistic.get('name', 'the statistic')} = {statistic['value']:.2f}"
                 if statistic.get("value") is not None else "no test statistic")
    df = result.get("df")
    if df not in (None, "", []) and not isinstance(df, list):
        stat_text += f" with {int(df) if isinstance(df, float) and df.is_integer() else df} degrees of freedom"
    p_text = plain_english.p_text(result["p_value"]) if result.get("p_value") is not None else "not available"
    sentences = [f"The {result.get('method_name') or 'test'} used {result.get('n')} records and gave {stat_text}, with p {p_text}."]
    everyone = plain_english.all_predictors(result, labels)
    if len(everyone) > 1:
        sentences.append(f"Together, the predictors were {', '.join(everyone)}.")
    effects = [e for e in result.get("effect_sizes") or [] if e.get("value") is not None]
    if effects:
        clauses = "; ".join(plain_english.direction_clause(e, plain_english.mid(predictor), plain_english.mid(outcome)) for e in effects[:4])
        if len(effects) == 1 and effects[0].get("magnitude"):
            strength = f" The effect is {effects[0]['magnitude']}."
        else:
            strength = ""
        single = effects[0] if len(effects) == 1 else None
        ci = (f" The 95% confidence interval runs from {single['ci_low']:.2f} to {single['ci_high']:.2f}."
              if single and single.get("ci_low") is not None and single.get("ci_high") is not None else "")
        sentences.append(f"{plain_english.cap(clauses)}.{strength}{ci}")
    sentences.append("The conditions the test needs were met." if _conditions_met(result)
                     else "Some conditions the test needs were not met, as described in the limitation below.")
    if len(group) > 1:
        sentences.append("A further test on this hypothesis was run; it is reported in the review of findings.")
    return sentences[:5]


def _boundary(result: dict) -> str:
    """The sentence that says what kind of result this is, so that it is never described as the wrong kind."""
    method = f"{result.get('method') or ''} {result.get('method_name') or ''}".lower()
    if "regression" in method or "logistic" in method:
        return ("This is a predictive model: it shows which factors are associated with the outcome, and how strongly, in this sample. "
                "It does not establish that changing a factor would change the outcome.")
    if _is_difference_test(result):
        return "These results describe a difference between groups, which does not by itself establish that the grouping causes the difference."
    return "These results describe a correlation: the two measures move together, which does not establish that one causes the other."


def _direct_answer(primaries: list[dict], labels: dict[str, str], question: str | None = None) -> str:
    """Yes, No or Partially, then the evidence in two or three sentences, then what kind of result it is and any mismatch warning."""
    verdicts: list[str] = []
    sentences: list[str] = []
    boundary = None
    mismatch = None
    for finding in primaries:
        result = finding.get("result") or {}
        decision = result.get("decision")
        if decision is None:
            continue
        outcome, predictor = plain_english.roles(result, labels)
        outcome, predictor = outcome or "the outcome", predictor or "the predictor"
        verdicts.append(decision)
        p = plain_english.p_text(result["p_value"]) if result.get("p_value") is not None else "not available"
        effect = first_effect_of(result)
        if _is_difference_test(result) and "regression" not in f"{result.get('method_name') or ''}".lower():
            if decision == "reject_null":
                sentences.append(f"{plain_english.cap(outcome)} differs between the groups of {plain_english.mid(predictor)} (p {p}).")
            else:
                sentences.append(f"{plain_english.cap(outcome)} does not differ clearly between the groups of "
                                 f"{plain_english.mid(predictor)} (p {p}).")
        elif decision == "reject_null":
            effects = [e for e in result.get("effect_sizes") or [] if e.get("value") is not None]
            if effects:
                clauses = "; ".join(plain_english.direction_clause(e, plain_english.mid(predictor), plain_english.mid(outcome))
                                    for e in effects[:4])
                sentences.append(f"{plain_english.cap(clauses)} (p {p}).")
            else:
                sentences.append(f"{plain_english.cap(predictor)} and {plain_english.mid(outcome)} are linked (p {p}).")
        else:
            sentences.append(f"No clear link was found between {plain_english.mid(predictor)} and {plain_english.mid(outcome)} (p {p}).")
        boundary = boundary or _boundary(result)
        mismatch = mismatch or plain_english.mismatch_sentence(question, result, labels)
    if not verdicts:
        return "No. The analysis did not produce a statistical result that answers this question."
    supported = verdicts.count("reject_null")
    opening = "Yes." if supported == len(verdicts) else ("Partially." if supported else "No.")
    return " ".join([opening] + sentences[:3] + ([mismatch] if mismatch else []) + [boundary])


def _conclusion_block(number: int, rq: dict, groups: list[list[dict]], notes: list[str], labels: dict[str, str],
                      finding_numbers: dict[int, int], project_title: str | None = None) -> list[str]:
    """One conclusion in the standard professional structure (Part 3 of the brief)."""
    question = rq["text"].strip().rstrip("?") + "?"
    lines = [f"CONCLUSION {number} — Research Question {rq['code']}: {question}", ""]
    primaries = [_main_test(group) for group in groups]
    lines.append("HYPOTHESIS VERDICT:")
    for group, primary in zip(groups, primaries):
        code = (group[0].get("hypothesis") or {}).get("code") or "H1"
        decision = (primary.get("result") or {}).get("decision")
        lines.append(_hypothesis_verdict(code, decision))
        result = primary.get("result") or {}
        if result:
            alpha = result.get("alpha", 0.05)
            p = plain_english.p_text(result["p_value"]) if result.get("p_value") is not None else "not available"
            lines.append(f"Basis: {plain_method(result.get('method_name'))}, p {p} against the threshold of {alpha:g}, "
                         f"with {_direction_words(result)}.")
    lines += ["", "SUMMARY OF EVIDENCE:"]
    summary: list[str] = []
    for group in groups:
        summary += _summary_sentences(group, labels)
    lines.append(" ".join(summary[:5]))
    lines += ["", "DIRECT ANSWER TO THE RESEARCH QUESTION:", _direct_answer(primaries, labels, rq["text"])]
    for note in notes:
        lines.append(f"Not analysed: {note}")
    rating = _strength_rating([f for group in groups for f in group])
    main = primaries[0]
    result = main.get("result") or {}
    p = plain_english.p_text(result["p_value"]) if result.get("p_value") is not None else "not available"
    effect = first_effect_of(result)
    if effect is None:
        effect_text = "no effect size was recorded"
    elif effect.get("magnitude"):
        effect_text = f"the effect is {effect['magnitude']}"
    else:
        effect_text = (f"the largest estimated effect is {plain_english.term_name(effect['name'])} ({effect['value']:.2f}), "
                       "which has no standard size label")
    lines += ["", "STRENGTH OF EVIDENCE:",
              f"{rating}. The p-value is {p}, {effect_text}, the sample has {result.get('n')} records, and "
              f"{'all conditions were met' if _conditions_met(result) else 'some conditions were not met'}."]
    mismatch = plain_english.mismatch_sentence(rq["text"], result, labels) if result else None
    lines += ["", "LIMITATION FOR THIS CONCLUSION:",
              mismatch or (_sentence_limitation(main, result) if result else "No statistical result is available.")]
    lines += ["", _recommendation(number, rq, main, labels, finding_numbers.get(main.get("id")), project_title)]
    return lines


def draft_conclusions(findings: list[dict], research_questions: list[dict], unanswered: dict[Any, list[str]] | None = None,
                      labels: dict[str, str] | None = None, project_title: str | None = None) -> list[dict]:
    """One conclusion per research question, in the standard professional structure (verdict, evidence summary, direct answer,
    strength, limitation and a recommendation). A question with no finding is still listed, with the reason."""
    unanswered = unanswered or {}
    labels = labels or {}
    finding_numbers = {f["id"]: i for i, f in enumerate(findings, 1)}
    out: list[dict] = []
    by_rq: dict[Any, list[dict]] = {}
    for f in findings:
        by_rq.setdefault(f.get("research_question_id"), []).append(f)
    for number, rq in enumerate(research_questions, 1):
        linked = by_rq.get(rq["id"], [])
        question = rq["text"].strip().rstrip("?") + "?"
        notes = unanswered.get(rq["id"], [])
        if not linked:
            reason = " ".join(notes) or "No analysis has been completed for it yet."
            text = "\n".join([f"CONCLUSION {number} — Research Question {rq['code']}: {question}", "",
                              "HYPOTHESIS VERDICT:", "Not determined: no analysis has been completed for this question.", "",
                              "DIRECT ANSWER TO THE RESEARCH QUESTION:",
                              "This question could not be answered by the analysis yet.",
                              f"Why: {reason}", "To answer it, run the analysis for this question."])
            out.append({"text": text, "finding_ids": [], "source": "engine", "research_question_id": rq["id"]})
            continue
        groups_map: dict[Any, list[dict]] = {}
        for finding in linked:
            groups_map.setdefault(finding.get("hypothesis_id"), []).append(finding)
        lines = _conclusion_block(number, rq, list(groups_map.values()), notes, labels, finding_numbers, project_title)
        if any(f.get("confidence_level") == "low" for f in linked):
            lines.append("Because the evidence has limitations, this answer is tentative (see the limitations).")
        out.append({"text": "\n".join(lines), "finding_ids": [f["id"] for f in linked], "source": "engine",
                    "research_question_id": rq["id"]})
    unlinked = by_rq.get(None, [])
    if unlinked:
        out.append({"text": "ADDITIONAL RESULTS (not tied to a specific research question):\n- " + "\n- ".join(f["statement"] for f in unlinked),
                    "finding_ids": [f["id"] for f in unlinked], "source": "engine", "research_question_id": None})
    return out


def general_conclusion(findings: list[dict], research_questions: list[dict], labels: dict[str, str] | None = None) -> dict:
    """The study-level conclusion: a synthesis, a hypothesis summary table, the overall strength and limitations, and future research."""
    labels = labels or {}
    tested, supported, limitations, ratings = [], 0, [], []
    rows: list[list[Any]] = []
    answers: list[str] = []
    for rq in research_questions:
        linked = [f for f in findings if f.get("research_question_id") == rq["id"]]
        if not linked:
            answers.append(f"{rq['code']} could not be answered yet")
            continue
        groups_map: dict[Any, list[dict]] = {}
        for finding in linked:
            groups_map.setdefault(finding.get("hypothesis_id"), []).append(finding)
        primaries = [_main_test(g) for g in groups_map.values()]
        verdicts = [(p.get("result") or {}).get("decision") for p in primaries if (p.get("result") or {}).get("decision")]
        if verdicts:
            supported += verdicts.count("reject_null")
            tested += verdicts
        answers.append(_direct_answer(primaries, labels).split(". ")[0].rstrip(".") + f" for {rq['code']}")
        ratings.append(f"{_strength_rating(linked)} for {rq['code']}")
        for group, primary in zip(groups_map.values(), primaries):
            result = primary.get("result") or {}
            if not result:
                continue
            code = (group[0].get("hypothesis") or {}).get("code") or "H1"
            stat = plain_english.describe_statistic(result)
            statistic = stat.replace("The test statistic is ", "").split(" with ")[0].rstrip(".") if stat else "not available"
            decision = result.get("decision")
            rows.append([code, result.get("method_name") or "not recorded", statistic,
                         plain_english.p_text(result["p_value"]) if result.get("p_value") is not None else "not available",
                         "Reject H0" if decision == "reject_null" else ("Fail to reject H0" if decision else "Not determined"),
                         "H1 accepted" if decision == "reject_null" else ("H0 accepted" if decision else "Not determined")])
            if not _conditions_met(result):
                limitations.append(_sentence_limitation(primary, result))
        for limitation in (f.get("limitations_note") for f in linked):
            if limitation and "assumption" not in limitation.lower():
                limitations.append(limitation.split(". ")[0].rstrip(".") + ".")
    total = len(tested)
    overall = ("The evidence is consistent across the tested hypotheses." if total and supported == total
               else "The evidence is mixed across the tested hypotheses." if supported else
               "The evidence does not support the tested hypotheses." if total else "No hypothesis could be tested.")
    synthesis = [f"Taken together, the study examined {len(research_questions)} research questions, "
                 f"of which {len(tested)} hypotheses received a statistical decision.",
                 "The answers were: " + "; ".join(answers) + ".",
                 overall]
    limit_unique = list(dict.fromkeys(limitations))[:3]
    strength = (f"Across the study, {supported} of {total} hypotheses were supported. Evidence was rated "
                f"{' and '.join(ratings) or 'not rated'}. The main limitations are: "
                + (" ".join(limit_unique) if limit_unique else "the single sample and the observational design."))
    future = [
        "Replicate the study with a larger sample drawn from a new population to test whether the findings hold, addressing the sample-size "
        "limitation and the generalisability limitation.",
        "Use a longitudinal or experimental design, so that changes in one factor can be tracked over time, to test whether the observed links "
        "reflect cause rather than association.",
        "Re-test the question with additional predictors or a method that does not require the conditions that were not met, to check whether "
        "the reported links remain when other factors are included.",
    ]
    return {"synthesis": " ".join(synthesis), "table": {"columns": ["Hypothesis", "Test Used", "Test Statistic", "p-value", "Decision", "Verdict"],
                                                        "rows": rows},
            "strength": strength, "future": future}


def draft_recommendations(findings: list[dict], study_design: str | None = None, labels: dict[str, str] | None = None,
                         project_title: str | None = None) -> list[dict]:
    """One recommendation per finding, tied to its own result. Findings without a statistical result are skipped."""
    out: list[dict] = []
    for number, f in enumerate(findings, 1):
        if f.get("significant") is None:
            continue
        out.append({"text": _recommendation(number, {}, f, labels or {}, number, project_title), "finding_ids": [f["id"]],
                    "source": "engine", "audience": None})
    return out


def detect_limitations(project: dict, quality_summary: dict | None, results: list[dict], cleaning_ops: list[dict]) -> list[dict]:
    """Limitations that follow from the design, the data and the analyses.
    Returned items are {category, description, evidence}. The caller stores
    them; nothing here ever removes a limitation."""
    out: list[dict] = []

    def add(category: str, description: str, **evidence: Any) -> None:
        out.append({"category": category, "description": description, "evidence": evidence})

    n = None
    if quality_summary:
        n = quality_summary.get("rows")
    design = (project.get("study_design") or "").lower()
    sampling = (project.get("sampling_technique") or "").lower()
    collection = (project.get("data_collection_method") or "").lower()

    if n is not None and n < 100:
        add("sample_size", f"The sample is small (n = {n}), which limits statistical power and the precision of estimates; "
                           "non-significant results may reflect low power rather than the absence of an effect.", n=n)
    if quality_summary and quality_summary.get("missing_pct", 0) >= 5:
        add("missing_data", f"{quality_summary['missing_pct']:.1f}% of data values are missing. If data are not missing completely at random, "
                            "estimates may be biased.", missing_pct=quality_summary["missing_pct"])
    if "cross" in design:
        add("design", "The cross-sectional design captures one point in time, so the direction of relationships and causality cannot be established.",
            study_design=project.get("study_design"))
    elif design and not any(k in design for k in ("experiment", "randomi", "rct")):
        add("design", "The study is observational, so associations may be explained by confounding variables that were not measured or controlled.",
            study_design=project.get("study_design"))
    if any(k in sampling for k in ("convenience", "purposive", "snowball", "volunteer", "quota")):
        add("sampling_bias", f"{project.get('sampling_technique')} sampling is non-probabilistic, so the sample may not represent the population "
                             "and findings should be generalised with caution.", sampling_technique=project.get("sampling_technique"))
    if any(k in collection for k in ("questionnaire", "survey", "self-report", "self report", "interview")):
        add("self_report", "Data were self-reported and may be affected by recall error and social-desirability bias.",
            data_collection_method=project.get("data_collection_method"))
    non_normal, small_cells, hetero, collinear = set(), False, False, False
    for r in results:
        for a in r.get("assumptions") or []:
            if a.get("satisfied") is False:
                name = a["name"].lower()
                if "normality" in name:
                    non_normal.add(r.get("method_name", ""))
                elif "expected cell" in name:
                    small_cells = True
                elif "homoscedasticity" in name:
                    hetero = True
                elif "multicollinearity" in name:
                    collinear = True
    if non_normal:
        add("distribution", "Some variables or residuals departed from normality in: " + ", ".join(sorted(m for m in non_normal if m))
            + ". Parametric p-values for these analyses should be read with caution.", methods=sorted(non_normal))
    if small_cells:
        add("measurement", "Some categories had few observations (small expected cell counts), which weakens tests of association.")
    if hetero:
        add("model", "Residual variance was not constant in at least one regression model; unless robust standard errors were used, its p-values may be inaccurate.")
    if collinear:
        add("model", "Predictors in at least one model were highly inter-correlated, making individual coefficients unstable.")
    n_tests = sum(1 for r in results if r.get("p_value") is not None)
    if n_tests >= 5:
        add("multiple_testing", f"{n_tests} significance tests were run without adjustment for multiple comparisons, which raises the chance of "
                                "at least one false-positive result.", tests=n_tests)
    risky = [op for op in cleaning_ops if op.get("operation") in ("winsorize", "impute", "remove_invalid", "drop_missing")]
    if risky:
        add("data_handling", "Data-cleaning decisions (" + ", ".join(sorted({op['operation'] for op in risky}))
            + ") changed or removed observations; conclusions may be sensitive to these choices. See the cleaning audit trail.",
            operations=[op.get("operation") for op in risky])
    add("generalizability", "Findings apply to the population and setting that were sampled and may not generalise to other institutions, "
                            "regions or time periods.")
    return out


def research_question_status(n_tests_completed: int, n_findings: int) -> tuple[str, str]:
    """Whether a research question has been analysed and can be answered."""
    if n_tests_completed == 0:
        return "not_analysed", "No completed analysis is linked to this research question yet."
    if n_findings == 0:
        return "analysed", "Analysis completed. Review the result and record a finding to answer the question."
    return "answered", "Analysis completed and at least one finding recorded. Evidence exists to answer the question; judge whether it is sufficient."
