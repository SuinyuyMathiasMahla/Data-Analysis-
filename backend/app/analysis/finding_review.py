"""The review of one finding, in the eight-part structure of the brief: research question, variables, test and why, how the calculation
was done, the result and what the numbers mean, insight, leads that support the conclusion, and the visualisation.

Every number comes from the stored result. The write-up explains it; it does not calculate anything new."""
from __future__ import annotations

from app.analysis import plain_english
from app.analysis.evidence import _is_difference_test, plain_method


def review(number: int, finding: dict, labels: dict[str, str], question_text: str | None) -> list[str]:
    """The eight parts for one finding. Lines are returned in order; the chart is attached by the report."""
    result = finding.get("result") or {}
    title = finding.get("title") or f"Finding {number}"
    lines = [f"FINDING {number}: {title}", ""]
    if not result:
        lines += ["1. RESEARCH QUESTION RESTATED: " + (question_text or "Not linked to a research question."),
                  f"4. THE RESULT: {finding.get('statement') or 'No statistical result is stored for this finding.'}"]
        return lines

    alpha = result.get("alpha", 0.05)
    p, n = result.get("p_value"), result.get("n")
    outcome, predictor = plain_english.roles(result, labels)
    outcome, predictor = outcome or "the outcome", predictor or "the predictor"
    difference = _is_difference_test(result)
    effect = next((e for e in result.get("effect_sizes") or [] if e.get("value") is not None), None)
    statistic = result.get("statistic") or {}
    method = plain_method(result.get("method_name") or title)
    filter_note = finding.get("filter_note")
    decision = result.get("decision")

    lines += ["1. RESEARCH QUESTION RESTATED: " + (question_text or "Not linked to a research question."), ""]
    lines += ["2. VARIABLES USED:",
              f"- Independent Variable (IV): {predictor}. This is the factor compared between groups, or the factor the outcome is related to.",
              f"- Dependent Variable (DV): {outcome}. This is the outcome that was measured.",
              f"- Sample size used: n = {n} records after exclusions." + (f" {filter_note}" if filter_note else ""), ""]
    lines += ["3. STATISTICAL TEST USED AND WHY:",
              f"The test used is {method}. It was chosen by the rule engine from the type of each variable and from whether the data met "
              f"the conditions the test needs. {plain_english.describe_conditions(result)}", ""]
    lines += ["4. HOW THE CALCULATION WAS DONE:",
              f"- The records were grouped by {predictor}." if difference else
              f"- Each record was used as a pair of values: {predictor} and {outcome}.",
              f"- The test statistic ({statistic.get('name', 'statistic')}) measures how large the pattern is compared with the normal "
              "variation in the data: the larger it is, the further the data are from no link or no difference.",
              f"- The degrees of freedom ({result.get('df')}) represent how much independent information the test used.",
              "- The p-value was derived from the statistic: it is the chance of a result this large, or larger, if there were no real link "
              "or difference.", ""]
    lines += ["5. THE RESULT AND WHAT THE NUMBERS MEAN:",
              f"- {(plain_english.describe_statistic(result) or 'The test statistic was not recorded.').split(' It measures')[0]}.",
              f"- {plain_english.describe_p(p, alpha)}"]
    if effect is not None:
        lines.append(f"- {plain_english.describe_effect(effect)}")
    lines.append("")
    lines += ["6. INSIGHT FROM THE RESULT:"]
    if decision == "reject_null":
        lines.append(f"The result indicates a real pattern between {plain_english.mid(predictor)} and {plain_english.mid(outcome)} in this sample. "
                     "It is not only a chance result at the chosen threshold.")
    else:
        lines.append(f"The result does not show a clear pattern between {plain_english.mid(predictor)} and {plain_english.mid(outcome)}. "
                     "This does not prove that no pattern exists.")
    if effect is not None and effect.get("magnitude"):
        practical = ("large enough to matter in practice" if effect["magnitude"].lower() in ("moderate", "medium", "strong", "large")
                     else "small, so its practical importance is limited even where the result is clear")
        lines.append(f"The effect is {effect['magnitude']}, which means it is {practical}.")
    if difference:
        lines.append("The group figures in the descriptive results show which groups differ; this test only shows whether the difference "
                     "is larger than chance.")
    if filter_note:
        lines.append(f"Anomaly: {filter_note}")
    if not plain_english.describe_conditions(result).startswith("The conditions"):
        lines.append("Some conditions were not met, so the exact figures are less reliable than the direction of the result.")
    lines.append("")
    lines += ["7. LEADS THAT SUPPORT THE CONCLUSION:"]
    leads = [f"The p-value is {'below 0.001' if p is not None and p < 0.001 else f'{p:.3f}' if p is not None else 'not available'}, "
             f"against a threshold of {alpha:g}."]
    if effect is not None:
        leads.append(f"The effect is {effect.get('magnitude') or 'recorded'} ({effect['name']} = {effect['value']:.2f}).")
    if effect is not None and effect.get("ci_low") is not None and effect.get("ci_high") is not None:
        leads.append(f"The 95% confidence interval runs from {effect['ci_low']:.2f} to {effect['ci_high']:.2f}.")
    leads.append(f"The analysis used {n} records.")
    leads.append("All conditions the test needs were met." if not (plain_english.describe_conditions(result).startswith("Some"))
                 else "Some conditions the test needs were not met.")
    lines += [f"- {lead}" for lead in leads[:5]]
    lines.append("")
    lines += ["8. VISUALISATION:",
              f"A chart is drawn for this finding in the report: {finding.get('chart_title') or 'no chart could be drawn for this finding'}."]
    return lines
