"""Readiness gate for the client package.



Runs on the assembled report snapshot, before any file is rendered. Every issue it returns is blocking: the package is not

generated until the researcher resolves each one. Each issue has a code, the place it was found and the action that fixes it.



Number consistency: every p-value and sample size quoted in the narrative must appear in a table of the same report. Checked

here for p-values and "n = N" counts. Other numbers in free text are not parsed.

"""

from __future__ import annotations



import re

from typing import Any



from app.reports.renderers import INTROS, SECTION_TITLES, _section_blocks



P_VALUE_TEXT = re.compile(r"\bp\s*=\s*(0?\.\d+)")

N_TEXT = re.compile(r"\bn\s*=\s*(\d+)")

PLACEHOLDER = re.compile(r"\[\s*(edit|todo|insert|tbd|placeholder)|\blorem ipsum\b|\bTODO\b|\bTBD\b|placeholder text", re.IGNORECASE)

CONTENT_KINDS = {"p", "bullet", "table", "figure", "note"}
# Quality issues that bias results if left unhandled. Shared with the wizard step checks.
SERIOUS_QUALITY_CODES = {"impossible_value", "invalid_numeric", "suspicious_code", "inconsistent_category", "invalid_date"}





def _issue(code: str, where: str, message: str, action: str) -> dict[str, str]:

    return {"code": code, "where": where, "message": message, "action": action}





def _strings(value: Any):

    """Every text value in the snapshot, except timestamps and identifiers."""

    if isinstance(value, str):

        yield value

    elif isinstance(value, dict):

        for key, item in value.items():

            if key not in ("generated_at", "storage_key", "checksum", "original_checksum", "checksum_sha256"):

                yield from _strings(item)

    elif isinstance(value, (list, tuple)):

        for item in value:

            yield from _strings(item)





def _narrative(content: dict) -> list[str]:

    """Text that quotes numbers: the summary, findings, conclusions, recommendations, decisions and test write-ups."""

    texts = list(content.get("executive_summary") or [])

    for f in content.get("findings") or []:

        texts += [f.get("statement") or "", f.get("statistical_evidence") or "", f.get("interpretation") or ""]

    texts += [c.get("text") or "" for c in content.get("conclusions") or []]

    texts += [r.get("text") or "" for r in content.get("recommendations") or []]

    texts += [h.get("interpretation") or "" for h in content.get("hypotheses") or []]

    for test in content.get("inferential") or []:

        texts += [test.get("apa") or "", test.get("summary") or ""]

    return texts





def _tables_numbers(content: dict) -> tuple[set[float], set[int]]:

    """The p-values and sample sizes that appear in the report's tables, rounded the way the tables show them."""

    p_values = set()

    sizes = set()

    for test in content.get("inferential") or []:

        if test.get("p_value") is not None:

            p_values.add(round(float(test["p_value"]), 3))
            if float(test["p_value"]) < 0.001:
                p_values.add(0.001)          # tables show such values as "< 0.001"; the text may round them to .001

        if test.get("n") is not None:

            sizes.add(int(test["n"]))

    for h in content.get("hypotheses") or []:

        for key in ("p_value", "p_adjusted"):

            if h.get(key) is not None:

                p_values.add(round(float(h[key]), 3))
                if float(h[key]) < 0.001:
                    p_values.add(0.001)

    # p-values printed in the tables of each test (coefficients, post-hoc comparisons, assumption checks)
    for test in content.get("inferential") or []:
        for table in test.get("tables") or []:
            columns = [str(c).strip().lower() for c in table.get("columns") or []]
            for col, name in enumerate(columns):
                if name in ("p", "p-value", "p value") or "adjusted p" in name or name.startswith("p (") or name == "p (holm)":
                    for row in table.get("rows") or []:
                        try:
                            value = float(row[col])
                        except (IndexError, TypeError, ValueError):
                            continue
                        if 0 <= value <= 1:
                            p_values.add(round(value, 3))
                            if value < 0.001:
                                p_values.add(0.001)
    dataset = content.get("dataset") or {}

    for key in ("rows",):

        if dataset.get(key) is not None:

            sizes.add(int(dataset[key]))

    for step in (content.get("data_quality") or {}).get("cleaning") or []:

        for key in ("rows_before", "rows_after"):

            if step.get(key) is not None:

                sizes.add(int(step[key]))

    return p_values, sizes





def _number_issues(content: dict) -> list[dict[str, str]]:

    issues = []

    p_values, sizes = _tables_numbers(content)

    for text in dict.fromkeys(_narrative(content)):      # each sentence once: the summary repeats the conclusions

        for match in P_VALUE_TEXT.finditer(text):

            value = round(float(match.group(1)), 3)

            if not any(abs(value - shown) < 0.0006 for shown in p_values):

                issues.append(_issue("number_mismatch", "narrative",

                                     f"The text quotes p = {match.group(1)}, which does not appear in any table.",

                                     "Regenerate the report so the text and the tables come from the same results."))

        for match in N_TEXT.finditer(text):

            if int(match.group(1)) not in sizes:

                issues.append(_issue("sample_size_mismatch", "narrative",

                                     f"The text quotes n = {match.group(1)}, which no table of the report reports.",

                                     "Check the sample size against the tables and correct the text or the analysis."))

    return issues





def check(content: dict, *, references: list[str] | None = None) -> list[dict[str, str]]:

    issues: list[dict[str, str]] = []



    # 1. every hypothesis has a result, or a recorded reason for having none

    for h in content.get("hypotheses") or []:

        if h.get("test") is None and not h.get("not_tested_reason"):

            issues.append(_issue("hypothesis_without_result", h["code"],

                                 f"{h['code']} has no analysis result and no recorded reason.",

                                 "Run the planned test for this hypothesis, or record in the hypothesis why it was not tested."))



    # 2. serious data problems left in the analysed data: impossible values, invalid numbers, missing-value codes, inconsistent coding
    quality_issues = (content.get("data_quality") or {}).get("issues") or []
    serious = [i for i in quality_issues if i.get("code") in SERIOUS_QUALITY_CODES]
    if serious:
        names = ", ".join(sorted({i["code"] for i in serious}))
        issues.append(_issue("unhandled_invalid_values", "data_quality",
                             f"{len(serious)} serious data problem(s) remain in the analysed data ({names}).",
                             "Correct them in the cleaning step, or set them to missing with a recorded reason."))

    # 3. multiple-testing adjustment: every secondary decision must use the adjusted p-value

    hyps = content.get("hypotheses") or []

    secondary = [h for h in hyps[1:] if h.get("test") is not None and h.get("p_value") is not None]

    if len(secondary) > 1:

        for h in secondary:

            if h.get("p_adjusted") is None:

                issues.append(_issue("multiplicity_not_applied", h["code"],

                                     f"{h['code']} is one of {len(secondary)} secondary tests but has no multiple-testing adjustment.",

                                     "Re-run the report so Holm adjustment is applied across the distinct secondary tests."))



    # 4. placeholder text anywhere in the narrative

    for text in _strings(content):

        match = PLACEHOLDER.search(text)

        if match:

            issues.append(_issue("placeholder_text", "narrative", f"Placeholder text found: '{text[:80]}'.",

                                 "Replace the placeholder with the real content, or remove the sentence."))

            break



    # 5. empty sections

    for key, title in SECTION_TITLES:

        blocks = _section_blocks(content, key)

        # the introduction every section starts with does not count as content
        if not any(kind in CONTENT_KINDS and payload != INTROS.get(key) for kind, payload in blocks):

            issues.append(_issue("empty_section", title, f"Section '{title}' has no content.",

                                 "Complete the wizard step that feeds this section, or exclude the section."))



    # 6. references: any method named in the report needs a reference list

    methods = (content.get("methodology") or {}).get("methods") or []

    if methods and not [r for r in (references or []) if r and r.strip()]:

        issues.append(_issue("missing_references", "references",

                             "The report names statistical methods but no reference list was supplied.",

                             "Add the bibliographic references for the methods used in the package options."))





    # 7. every number quoted in the text appears in a table, and the sample sizes agree

    issues.extend(issue for issue in _number_issues(content) if issue not in issues)     # one issue per wrong number

    return issues

