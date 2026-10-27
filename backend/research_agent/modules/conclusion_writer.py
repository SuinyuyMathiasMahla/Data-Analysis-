"""
conclusion_writer.py
--------------------
Sends statistical results to the Groq API (LLaMA 3.1) and receives
professionally written academic conclusions and recommendations.
One conclusion is generated per hypothesis/finding.

Requires: pip install groq
Env var:  GROQ_API_KEY
"""

import os
import json
from typing import Optional


def _get_client():
    try:
        from groq import Groq
        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable is not set.")
        return Groq(api_key=api_key)
    except ImportError:
        raise ImportError(
            "Groq package not installed. Run: pip install groq"
        )


def _call_llm(client, prompt: str, max_tokens: int = 1200) -> str:
    """Send a prompt to Groq LLaMA 3.1 and return the response text."""
    response = client.chat.completions.create(
        model="llama-3.1-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=0.3,
    )
    return response.choices[0].message.content


def write_conclusions(
    analysis_results: list[dict],
    project_context: dict,
) -> list[dict]:
    """
    For each analysis result, generate a structured academic conclusion.

    project_context keys:
      title, general_objective, specific_objectives,
      study_population, methodology
    """
    try:
        client = _get_client()
    except Exception as e:
        # If client fails, return fallback for all
        return [_fallback_conclusion(i + 1, r) for i, r in enumerate(analysis_results)]

    conclusions = []
    for i, result in enumerate(analysis_results, start=1):
        conclusion = _write_single_conclusion(client, i, result, project_context)
        conclusions.append(conclusion)

    summary = _write_overall_summary(client, conclusions, analysis_results, project_context)
    return conclusions + [summary]


def _write_single_conclusion(client, idx: int, result: dict, ctx: dict) -> dict:
    """Generate one academic conclusion via Groq API."""

    stat_block = json.dumps({
        "test_used":      result.get("test"),
        "test_reason":    result.get("reason"),
        "result":         result.get("result"),
        "effect_size":    result.get("effect_size"),
        "significant":    result.get("significant"),
        "p_value":        result.get("p_value"),
        "group_stats":    result.get("group_stats"),
        "interpretation": result.get("interpretation"),
        "assumptions":    result.get("assumptions"),
    }, indent=2, default=str)

    prompt = f"""You are an expert academic research analyst writing the Conclusions and
Recommendations section of a formal research report.

PROJECT CONTEXT:
Title: {ctx.get('title', 'Research Study')}
General Objective: {ctx.get('general_objective', '')}
Study Population: {ctx.get('study_population', '')}
Methodology: {ctx.get('methodology', 'Quantitative')}

FINDING {idx}:
Research Question: {result.get('h0', '').replace('H0: ', '').replace('H0:', '')}
IV (Independent Variable): {result.get('iv')}
DV (Dependent Variable): {result.get('dv')}
H0 (Null Hypothesis): {result.get('h0')}
H1 (Alternative Hypothesis): {result.get('h1')}

STATISTICAL RESULTS:
{stat_block}

Write a structured academic conclusion for Finding {idx} using EXACTLY this format
(use these exact headings):

CONCLUSION {idx} — [restate the research question in full]

HYPOTHESIS VERDICT:
State whether H0 was Accepted or Rejected and H1 was Accepted or Rejected.
Give one sentence citing the test name, test statistic, and p-value.

SUMMARY OF EVIDENCE:
3–5 sentences summarising the key findings. Reference specific numbers
(test statistic, means, percentages, effect size). Do not describe the methodology.

DIRECT ANSWER:
Begin with Yes, No, or Partially. Give a 2–3 sentence evidence-based answer
to the research question. Include the test statistic and p-value.

STRENGTH OF EVIDENCE:
Rate as Strong / Moderate / Weak. Justify in one sentence based on p-value,
effect size, sample size, and whether assumptions were met.

LIMITATION:
One specific, precise limitation for this conclusion — not a generic disclaimer.

RECOMMENDATION {idx}:
A specific, actionable recommendation directed at a named audience. State
the action, expected benefit, and reference the finding that justifies it.

Write in third person academic style. Every claim must reference a number from
the statistical results. Do NOT include charts or visualisations.
Do NOT use vague language like 'big difference' — use the actual statistic."""

    try:
        text = _call_llm(client, prompt, max_tokens=1200)
    except Exception as e:
        text = _fallback_text(idx, result, e)

    return {
        "finding_id":      idx,
        "iv":              result.get("iv"),
        "dv":              result.get("dv"),
        "test":            result.get("test"),
        "significant":     result.get("significant"),
        "p_value":         result.get("p_value"),
        "h0":              result.get("h0"),
        "h1":              result.get("h1"),
        "conclusion_text": text,
        "type":            "individual",
    }


def _write_overall_summary(client, conclusions: list[dict], results: list[dict], ctx: dict) -> dict:
    """Generate the overall conclusions summary section."""

    verdicts = "\n".join([
        f"- Finding {c['finding_id']}: {c['test']} | p={c['p_value']} | "
        f"{'H0 Rejected' if c['significant'] else 'H0 Retained'}"
        for c in conclusions if c.get("type") == "individual"
    ])

    prompt = f"""You are writing the OVERALL CONCLUSIONS SUMMARY section of an academic research report.

PROJECT:
Title: {ctx.get('title')}
General Objective: {ctx.get('general_objective')}

HYPOTHESIS VERDICTS FROM ALL FINDINGS:
{verdicts}

Write the Overall Conclusions Summary with these EXACT sections:

GENERAL CONCLUSION:
A paragraph of 5–7 sentences synthesising ALL findings into one coherent answer
to the general objective. Reference specific statistics from the findings.

HYPOTHESIS SUMMARY TABLE:
Produce a markdown table:
| Hypothesis | Test Used | Test Statistic | p-value | Decision | Verdict |

STUDY STRENGTHS AND LIMITATIONS:
Two short paragraphs — one on strengths, one on limitations of the overall study.

FUTURE RESEARCH:
Three numbered recommendations for future studies, each with a justification
tied to a specific limitation or unanswered question from the findings.

Write in formal third-person academic style."""

    try:
        text = _call_llm(client, prompt, max_tokens=1000)
    except Exception as e:
        text = f"[Overall summary generation failed: {e}]"

    return {
        "finding_id":      "summary",
        "conclusion_text": text,
        "type":            "overall_summary",
    }


def _fallback_text(idx: int, result: dict, error: Exception) -> str:
    return (
        f"[Conclusion generation failed: {error}]\n\n"
        f"Fallback: The analysis of '{result.get('iv')}' vs '{result.get('dv')}' "
        f"yielded p = {result.get('p_value')}. "
        f"{'H0 is rejected.' if result.get('significant') else 'H0 is retained.'}"
    )


def _fallback_conclusion(idx: int, result: dict) -> dict:
    return {
        "finding_id":      idx,
        "iv":              result.get("iv"),
        "dv":              result.get("dv"),
        "test":            result.get("test"),
        "significant":     result.get("significant"),
        "p_value":         result.get("p_value"),
        "h0":              result.get("h0"),
        "h1":              result.get("h1"),
        "conclusion_text": _fallback_text(idx, result, "Client initialisation failed"),
        "type":            "individual",
    }
