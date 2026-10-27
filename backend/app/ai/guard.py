"""Academic-integrity guardrails for the AI assistant.

Two layers:

1. ``SYSTEM_PROMPT`` tells the model what it may and may not do.
2. ``check_grounding`` verifies the reply afterwards: every number the model
   wrote must be traceable to the engine results it was given. Numbers that
   cannot be traced are reported to the user next to the reply, because an
   instruction alone cannot guarantee a model never invents a statistic.

Limit of the check: it proves that a number *exists* in the engine output, not
that the model attached it to the right statistic (a reply could quote a real
Shapiro-Wilk W as if it were r). It catches invented values, which is the
failure that matters most, but the researcher must still read the reply against
the result tables - the UI says so next to every AI message.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any

SYSTEM_PROMPT = """You are an Academic Data Analysis Assistant inside a research platform for university students and researchers.

You receive a JSON document called CONTEXT. It contains the research project, its research questions and hypotheses, a summary of
the dataset, the data dictionary, data-quality results and the results computed by the platform's statistical engine.

Rules you must follow without exception:
1. Every statistic, count, percentage, p-value, effect size or other number you state must appear in CONTEXT. Never calculate, estimate,
   round differently, extrapolate or invent a number. If a number the user wants is not in CONTEXT, say that the analysis has not been
   run and name the analysis that would produce it.
2. Never fabricate data, results, quotations or references. Do not cite any publication unless the user supplied it.
3. Never describe a correlation or regression coefficient from observational data as proof of cause and effect.
4. Always mention relevant assumption checks that failed and the warnings attached to a result. Never hide or play down limitations.
5. Never suggest changing data, removing observations, switching tests or adjusting alpha in order to obtain a significant result.
6. A non-significant result means insufficient evidence, not proof of no effect. Say so.
7. If the data or sample are too limited for a reliable analysis, say: "Insufficient evidence to perform this analysis reliably."
8. Separate clearly: (a) what the statistical engine computed, (b) your interpretation, and (c) what the researcher must decide.
   The researcher is responsible for the final academic interpretation.
9. Adapt depth to the academic level in CONTEXT (undergraduate, masters, phd) but never recommend a more advanced method than the
   research question, design and data require.
10. Write plainly and concisely. Explain statistical terms the first time you use them."""

_NUMBER = re.compile(r"(?<![A-Za-z0-9_])[-+−]?(?:\d{1,3}(?:,\d{3})+|\d+)?(?:\.\d+)?(?:[eE][-+]?\d+)?%?")
# Numbers that are conventions rather than results, and may always be used.
_ALWAYS_ALLOWED = {0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 10.0, 20.0, 30.0, 50.0, 80.0, 90.0, 95.0, 99.0, 100.0, 0.05, 0.01, 0.001, 0.1, 0.2, 0.3,
                   0.5, 0.8, 0.7, 0.6, 0.9}


def _collect_numbers(value: Any, out: set[float]) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        if math.isfinite(float(value)):
            out.add(float(value))
    elif isinstance(value, str):
        for token in _NUMBER.findall(value):
            parsed = _parse(token)
            if parsed is not None:
                out.add(parsed[0])
    elif isinstance(value, dict):
        for key, item in value.items():
            _collect_numbers(key, out)
            _collect_numbers(item, out)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect_numbers(item, out)


def _parse(token: str) -> tuple[float, int] | None:
    """Return (value, decimals) for a numeric token, or None if it is not one."""
    text = token.strip().rstrip("%").replace(",", "").replace("−", "-")
    if not text or text in "+-" or not any(ch.isdigit() for ch in text):
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    mantissa = text.lower().split("e")[0]
    decimals = len(mantissa.split(".")[1]) if "." in mantissa else 0
    return value, decimals


def _matches(value: float, decimals: int, known: set[float]) -> bool:
    if abs(value) in _ALWAYS_ALLOWED:
        return True
    tolerance = 0.5 * 10 ** (-decimals) + 1e-12
    for k in known:
        for candidate in (k, abs(k), k * 100, abs(k) * 100, k * k):     # as given, sign dropped, as a percentage, r -> r squared
            if abs(candidate - abs(value)) <= tolerance or abs(candidate - value) <= tolerance:
                return True
    return False


def check_grounding(reply: str, context: Any) -> dict:
    """Compare every number in ``reply`` with the numbers present in ``context``.

    Returns ``{"checked", "unverified": [...], "grounded": bool}``. Section
    numbering such as "1." at the start of a line and labels such as RQ1/H2 are
    ignored."""
    known: set[float] = set()
    _collect_numbers(json.loads(json.dumps(context, default=str)), known)
    text = re.sub(r"(?m)^\s*(\d+)[.)]\s", " ", reply)                # list numbering
    text = re.sub(r"\b[A-Za-z]+\d+\b", " ", text)                      # RQ1, H2, PC1 ...
    unverified: list[str] = []
    checked = 0
    for token in _NUMBER.findall(text):
        parsed = _parse(token)
        if parsed is None:
            continue
        checked += 1
        if not _matches(parsed[0], parsed[1], known) and token not in unverified:
            unverified.append(token)
    return {"checked": checked, "unverified": unverified, "grounded": not unverified}


GROUNDING_WARNING = ("Integrity check: the following number(s) in this AI reply could not be matched to the platform's statistical "
                     "results and must not be used without verification: {numbers}.")
