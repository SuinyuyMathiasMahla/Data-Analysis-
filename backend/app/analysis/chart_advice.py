"""Which charts help a reader understand a statistical test's result.

Chosen from the test's method and its variable roles, using the stored schema for
variable types. Each idea is a chart configuration the Visualization studio can draw
(see visualization.CHART_TYPES) together with a plain-language reason.
"""
from __future__ import annotations

from typing import Any

CORRELATION = {"pearson", "spearman", "kendall", "simple_linear_regression"}
GROUPS = {"independent_t_test", "one_way_anova", "mann_whitney", "kruskal_wallis"}
REPEATED = {"paired_t_test", "wilcoxon", "friedman", "repeated_measures_anova"}
ASSOCIATION = {"chi_square", "fisher_exact"}
REGRESSION = {"multiple_linear_regression", "logistic_regression", "poisson_regression", "negative_binomial_regression"}
MULTIVARIATE = {"pca", "factor_analysis", "cluster_analysis", "cronbach_alpha"}


def _names(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def _all_names(variables: dict) -> list[str]:
    out: list[str] = []
    for value in variables.values():
        out += _names(value)
    return list(dict.fromkeys(out))


def _numeric(name: str, schema: dict) -> bool:
    return (schema.get(name) or {}).get("type") in ("numeric", "integer")


def chart_ideas(method: str | None, variables: dict, schema: dict) -> list[dict]:
    """Chart ideas for one test. Empty when the test has no variables to chart."""
    names = _all_names(variables)
    if not names or not method:
        return []
    ideas: list[dict] = []

    def add(chart_type: str, title: str, reason: str, **config: Any) -> None:
        ideas.append({"chart_type": chart_type, "title": title, "reason": reason, **config})

    if method in CORRELATION:
        a, b = (_names(variables.get("x")) or names[:1])[0], (_names(variables.get("y")) or names[1:2] or names[:1])[0]
        if a != b:
            add("scatter", f"{b} against {a}", "A scatter plot shows the direction and form of the relationship; each dot is one person.", x=a, y=b)
            add("regression", f"Fitted line: {b} on {a}", "The fitted line shows how much the outcome changes with the predictor, with its uncertainty.", x=a, y=b)
    elif method in GROUPS:
        group = next((n for n in names if not _numeric(n, schema)), None)
        outcome = next((n for n in names if _numeric(n, schema) and n != group), None)
        if group and outcome:
            add("group_comparison", f"Mean {outcome} by {group}",
                "Group means with 95% intervals show whether the groups plausibly differ, and by how much.", x=group, y=outcome)
            add("box", f"{outcome} by {group}", "A box plot compares the typical value, the spread and any outliers in each group.", x=group, y=outcome)
    elif method in REPEATED:
        measures = [n for n in names if _numeric(n, schema)][:3]
        for m in measures:
            add("box", f"Spread of {m}", "A box plot shows the typical value, spread and outliers of each measurement.", y=m)
    elif method in ASSOCIATION:
        if len(names) >= 2:
            add("heatmap", f"{names[0]} by {names[1]}", "A heatmap of counts shows how the two categories combine.", x=names[0], y=names[1])
    elif method in REGRESSION:
        outcome = _names(variables.get("outcome"))[:1] or names[:1]
        predictors = [p for p in _names(variables.get("predictors")) if p != outcome[0]] or [n for n in names if n != outcome[0]]
        if outcome and predictors:
            x, y = predictors[0], outcome[0]
            if _numeric(x, schema) and _numeric(y, schema):
                add("regression", f"{y} against {x}", "The fitted line shows how the outcome changes as the predictor changes.", x=x, y=y)
            elif _numeric(y, schema):
                add("group_comparison", f"Mean {y} by {x}", "Group means with 95% intervals show how the outcome differs between groups.", x=x, y=y)
    elif method in MULTIVARIATE:
        numeric = [n for n in names if _numeric(n, schema)][:12]
        if len(numeric) >= 2:
            add("correlation_matrix", "Correlation matrix", "A correlation matrix shows how strongly each pair of variables moves together.", columns=numeric)
    if not ideas:
        first = names[0]
        if _numeric(first, schema):
            add("histogram", f"Distribution of {first}", "A histogram shows the shape, centre and spread of the variable.", x=first)
        else:
            add("bar", f"Frequency of {first}", "A bar chart shows how often each category occurs.", x=first)
    return ideas[:3]
