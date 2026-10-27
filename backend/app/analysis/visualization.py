"""Chart rendering (matplotlib, headless).

Every chart is drawn from the stored dataset version by the backend and saved
as a PNG, so it can be downloaded, regenerated from its saved config, and
embedded in PDF/DOCX reports exactly as shown on screen.

Design rules applied to every chart:
* categorical colours come from one fixed, colour-blind-checked order and are
  never cycled past eight series (extra categories fold into "Other");
* magnitude uses a single-hue ramp, signed values a blue-grey-red diverging
  ramp with a neutral midpoint;
* one y-axis only, thin marks, recessive grid, text in ink colours;
* a legend only when there are two or more series; scatter groups also differ
  by marker shape so identity never depends on colour alone.
"""
from __future__ import annotations

import io
import math
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from scipy import stats  # noqa: E402

from app.statistics.descriptive import mean_ci  # noqa: E402
from app.statistics.utils import AnalysisError, numeric, require_columns  # noqa: E402

CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
MARKERS = ["o", "s", "^", "D", "v", "P", "X", "*"]
INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#ffffff"
SEQUENTIAL = LinearSegmentedColormap.from_list("seq_blue", ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])
DIVERGING = LinearSegmentedColormap.from_list("div_blue_red", ["#1c5cab", "#86b6ef", "#f0efec", "#f0a5a4", "#c0302f"])
MAX_SERIES = 8

CHART_TYPES: dict[str, dict[str, Any]] = {
    "bar": {"label": "Bar chart", "needs": "x = category; optional y = numeric (shows the mean of y per category)"},
    "pie": {"label": "Pie chart", "needs": "x = category (6 or fewer categories read best)"},
    "histogram": {"label": "Histogram", "needs": "x = numeric"},
    "box": {"label": "Box plot", "needs": "y = numeric; optional x = category"},
    "violin": {"label": "Violin plot", "needs": "y = numeric; optional x = category"},
    "scatter": {"label": "Scatter plot", "needs": "x, y = numeric; optional hue = category"},
    "line": {"label": "Line chart", "needs": "x = ordered variable, y = numeric; optional hue"},
    "heatmap": {"label": "Heatmap of counts", "needs": "x, y = category"},
    "correlation_matrix": {"label": "Correlation matrix", "needs": "columns = 2+ numeric variables"},
    "regression": {"label": "Regression plot", "needs": "x, y = numeric"},
    "group_comparison": {"label": "Group means with 95% CI", "needs": "x = category, y = numeric"},
    "time_series": {"label": "Time-series plot", "needs": "x = date/time, y = numeric"},
    "qq": {"label": "Normal Q-Q plot", "needs": "x = numeric"},
}


def _style(ax, grid_axis: str | None = "y") -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#b9b8b2")
        ax.spines[side].set_linewidth(0.8)
    ax.tick_params(colors=INK_2, labelsize=9, length=3, width=0.8)
    ax.set_axisbelow(True)
    if grid_axis:
        ax.grid(axis=grid_axis, color=GRID, linewidth=0.8)


def _label(col: str | None, labels: dict[str, str]) -> str:
    return labels.get(col, col) if col else ""


def _cat(series: pd.Series) -> pd.Series:
    return series.map(lambda v: np.nan if pd.isna(v) else (f"{v:g}" if isinstance(v, (float, np.floating)) else str(v)))


def _levels(series: pd.Series, cap: int = MAX_SERIES) -> tuple[pd.Series, list[str]]:
    """Category labels, with everything past the ``cap`` most common folded into 'Other'."""
    labels = _cat(series)
    counts = labels.value_counts()
    keep = list(counts.index[: cap - 1]) if len(counts) > cap else list(counts.index)
    if len(counts) > cap:
        labels = labels.where(labels.isin(keep) | labels.isna(), "Other")
        keep.append("Other")
    numeric_levels = pd.to_numeric(pd.Series(keep), errors="coerce")
    if numeric_levels.notna().all():
        keep = [keep[i] for i in np.argsort(numeric_levels.to_numpy(), kind="stable")]
    elif len(counts) <= cap:
        keep = sorted(keep)
    return labels, keep


def _reorder(order: list[str], preferred: list[str]) -> list[str]:
    """Put categories in the order the researcher asked for (e.g. Low, Moderate, High)."""
    if not preferred:
        return order
    return [p for p in preferred if p in order] + [o for o in order if o not in preferred]


def _default_title(kind: str, x: str, y: str, hue: str) -> str:
    by = f" by {hue}" if hue else ""
    return {
        "bar": f"Mean {y} by {x}" if y else f"Number of records by {x}",
        "pie": f"Share of records by {x}",
        "histogram": f"Distribution of {x}",
        "box": f"{y or x} by {x}" if (x and y) else f"Distribution of {y or x}",
        "violin": f"{y or x} by {x}" if (x and y) else f"Distribution of {y or x}",
        "scatter": f"{y} against {x}{by}",
        "regression": f"{y} against {x} with fitted line",
        "line": f"{y} by {x}{by}",
        "time_series": f"{y} over time{by}",
        "heatmap": f"Number of records by {x} and {y}",
        "correlation_matrix": "Correlation matrix",
        "group_comparison": f"Mean {y} by {x} (95% CI)",
        "qq": f"Normal Q-Q plot of {x}",
    }[kind]


def _legend(ax, title: str | None = None) -> None:
    leg = ax.legend(title=title, frameon=False, fontsize=9, title_fontsize=9, loc="best")
    if leg:
        for text in leg.get_texts():
            text.set_color(INK_2)


def render_chart(df: pd.DataFrame, config: dict, labels: dict[str, str] | None = None) -> tuple[bytes, dict]:
    """Render ``config`` against a typed frame. Returns ``(png_bytes, meta)``;
    ``meta`` describes what was drawn so it can be passed to the AI assistant
    and printed as a figure note."""
    labels = labels or {}
    kind = config.get("chart_type")
    if kind not in CHART_TYPES:
        raise AnalysisError(f"Unknown chart type: {kind}")
    x, y, hue = config.get("x") or None, config.get("y") or None, config.get("hue") or None
    columns = config.get("columns") or []
    require_columns(df, x, y, hue, *columns)
    width = float(min(max(config.get("width", 8), 4), 14))
    height = float(min(max(config.get("height", 5), 3), 10))
    fig, ax = plt.subplots(figsize=(width, height), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    meta: dict[str, Any] = {"chart_type": kind, "x": x, "y": y, "hue": hue, "n": 0, "notes": []}
    xlabel, ylabel = _label(x, labels), _label(y, labels)
    default_title = config.get("title") or _default_title(kind, xlabel, ylabel, _label(hue, labels))
    preferred = [str(v) for v in (config.get("category_order") or [])]

    try:
        if kind == "bar":
            _need(x, "a category variable (x)")
            cats, order = _levels(df[x], 20)
            order = _reorder(order, preferred)
            if y:
                data = pd.DataFrame({"c": cats, "v": numeric(df[y])}).dropna()
                grouped = data.groupby("c")["v"]
                means = grouped.mean().reindex(order)
                err = [(_half_ci(g.to_numpy())) for g in (data.loc[data["c"] == lvl, "v"] for lvl in order)]
                ax.bar(order, means.to_numpy(), color=CATEGORICAL[0], width=0.65, yerr=err, capsize=3,
                       error_kw={"ecolor": INK_2, "elinewidth": 1})
                ylabel = f"Mean {ylabel}"
                meta["notes"].append("Bars show group means; error bars are 95% confidence intervals.")
                meta["n"] = int(len(data))
            else:
                counts = cats.value_counts().reindex(order).fillna(0)
                bars = ax.bar(order, counts.to_numpy(), color=CATEGORICAL[0], width=0.65)
                total = counts.sum()
                if len(order) <= 12 and total:
                    ax.bar_label(bars, labels=[f"{int(v)} ({100 * v / total:.0f}%)" for v in counts], fontsize=8, color=INK_2, padding=2)
                ylabel = "Number of records"
                meta["n"] = int(total)
            _style(ax)
            if max((len(o) for o in order), default=0) > 8 or len(order) > 8:
                plt.setp(ax.get_xticklabels(), rotation=35, ha="right")

        elif kind == "pie":
            _need(x, "a category variable (x)")
            cats, order = _levels(df[x], 6)
            order = _reorder(order, preferred)
            counts = cats.value_counts().reindex(order).fillna(0)
            if counts.sum() == 0:
                raise AnalysisError(f"'{x}' has no data to plot.")
            ax.pie(counts.to_numpy(), labels=[f"{k}\n{int(v)} ({100 * v / counts.sum():.0f}%)" for k, v in counts.items()],
                   colors=CATEGORICAL[: len(order)], startangle=90, counterclock=False,
                   wedgeprops={"edgecolor": SURFACE, "linewidth": 2}, textprops={"color": INK_2, "fontsize": 9})
            ax.axis("equal")
            xlabel = ylabel = ""
            meta["n"] = int(counts.sum())
            if df[x].nunique() > 6:
                meta["notes"].append("Smaller categories are combined into 'Other'. A bar chart shows many categories more accurately.")

        elif kind == "histogram":
            _need(x, "a numeric variable (x)")
            values = numeric(df[x]).dropna().to_numpy()
            _enough(values, 2, x)
            bins = config.get("bins") or "auto"
            ax.hist(values, bins=bins if bins == "auto" else int(bins), color=CATEGORICAL[0], edgecolor=SURFACE, linewidth=1)
            ax.axvline(values.mean(), color=INK, linewidth=1.2, linestyle="--", label=f"Mean = {values.mean():.2f}")
            ax.axvline(np.median(values), color=CATEGORICAL[1], linewidth=1.2, linestyle=":", label=f"Median = {np.median(values):.2f}")
            _legend(ax)
            ylabel = "Number of records"
            _style(ax)
            meta["n"] = int(len(values))

        elif kind in ("box", "violin"):
            _need(y or x, "a numeric variable (y)")
            if not y:                       # allow a single numeric variable given as x
                y, x = x, None
                ylabel, xlabel = _label(y, labels), ""
            if x:
                cats, order = _levels(df[x], 12)
                order = _reorder(order, preferred)
                data = pd.DataFrame({"c": cats, "v": numeric(df[y])}).dropna()
                groups = [data.loc[data["c"] == lvl, "v"].to_numpy() for lvl in order]
                order = [o for o, g in zip(order, groups) if len(g)]
                groups = [g for g in groups if len(g)]
            else:
                groups, order = [numeric(df[y]).dropna().to_numpy()], [ylabel]
            if not groups or sum(len(g) for g in groups) < 2:
                raise AnalysisError("Not enough data to draw this chart.")
            positions = list(range(1, len(groups) + 1))
            if kind == "box":
                bp = ax.boxplot(groups, positions=positions, widths=0.55, patch_artist=True, showmeans=True,
                                medianprops={"color": INK, "linewidth": 1.4},
                                meanprops={"marker": "D", "markerfacecolor": SURFACE, "markeredgecolor": INK, "markersize": 5},
                                flierprops={"marker": "o", "markersize": 4, "markerfacecolor": "none", "markeredgecolor": INK_2},
                                whiskerprops={"color": INK_2}, capprops={"color": INK_2})
                for patch in bp["boxes"]:
                    patch.set(facecolor="#b7d3f6", edgecolor=CATEGORICAL[0], linewidth=1.2)
                meta["notes"].append("Box = interquartile range, line = median, diamond = mean, circles = points beyond 1.5 x IQR.")
            else:
                drawable = [g if len(g) > 1 and np.ptp(g) > 0 else np.array([g.mean() - 1e-9, g.mean() + 1e-9]) for g in groups]
                parts = ax.violinplot(drawable, positions=positions, widths=0.75, showmedians=True, showextrema=True)
                for body in parts["bodies"]:
                    body.set(facecolor="#86b6ef", edgecolor=CATEGORICAL[0], alpha=0.85)
                for key in ("cmedians", "cmins", "cmaxes", "cbars"):
                    parts[key].set(color=INK_2, linewidth=1)
                meta["notes"].append("Width shows the density of observations; the central line is the median.")
            ax.set_xticks(positions)
            ax.set_xticklabels([f"{o}\n(n={len(g)})" for o, g in zip(order, groups)])
            _style(ax)
            meta["n"] = int(sum(len(g) for g in groups))

        elif kind in ("scatter", "regression"):
            _need(x and y, "two numeric variables (x and y)")
            data = pd.DataFrame({"x": numeric(df[x]), "y": numeric(df[y])})
            if hue and kind == "scatter":
                data["h"], order = _levels(df[hue])
            data = data.dropna()
            _enough(data, 3, f"{x} and {y}")
            if hue and kind == "scatter":
                for i, lvl in enumerate(order):
                    part = data[data["h"] == lvl]
                    ax.scatter(part["x"], part["y"], s=28, color=CATEGORICAL[i], marker=MARKERS[i], alpha=0.85,
                               edgecolors=SURFACE, linewidths=0.6, label=f"{lvl} (n={len(part)})")
                _legend(ax, _label(hue, labels))
            else:
                ax.scatter(data["x"], data["y"], s=28, color=CATEGORICAL[0], alpha=0.8, edgecolors=SURFACE, linewidths=0.6)
            if (kind == "regression" or config.get("fit_line")) and data["x"].nunique() > 1:
                fit = stats.linregress(data["x"], data["y"])
                xs = np.linspace(data["x"].min(), data["x"].max(), 100)
                ys = fit.intercept + fit.slope * xs
                n = len(data)
                resid_sd = math.sqrt(((data["y"] - (fit.intercept + fit.slope * data["x"])) ** 2).sum() / max(n - 2, 1))
                sxx = ((data["x"] - data["x"].mean()) ** 2).sum()
                band = stats.t.ppf(0.975, max(n - 2, 1)) * resid_sd * np.sqrt(1 / n + (xs - data["x"].mean()) ** 2 / sxx)
                ax.plot(xs, ys, color=INK, linewidth=1.6, label=f"y = {fit.intercept:.3g} + {fit.slope:.3g}x  (r = {fit.rvalue:.2f})")
                ax.fill_between(xs, ys - band, ys + band, color=INK, alpha=0.10, linewidth=0, label="95% confidence band")
                _legend(ax)
                meta.update(slope=float(fit.slope), intercept=float(fit.intercept), r=float(fit.rvalue))
                meta["notes"].append("Line = least-squares fit; shaded band = 95% confidence interval of the fitted mean.")
            _style(ax, "both")
            meta["n"] = int(len(data))

        elif kind in ("line", "time_series"):
            _need(x and y, "x and a numeric y")
            if kind == "time_series" and pd.api.types.is_numeric_dtype(df[x]):
                raise AnalysisError(f"A time-series plot needs a date/time variable on the x-axis; '{x}' is numeric. Use a line chart instead.")
            xs = pd.to_datetime(df[x], errors="coerce") if kind == "time_series" else df[x]
            if kind == "time_series" and xs.notna().sum() == 0:
                raise AnalysisError(f"'{x}' does not contain dates.")
            data = pd.DataFrame({"x": xs, "y": numeric(df[y])})
            if hue:
                data["h"], order = _levels(df[hue])
            data = data.dropna()
            _enough(data, 2, f"{x} and {y}")
            series = [(lvl, data[data["h"] == lvl]) for lvl in order] if hue else [(None, data)]
            for i, (lvl, part) in enumerate(series):
                agg = part.groupby("x")["y"].mean().sort_index()
                ax.plot(agg.index, agg.to_numpy(), color=CATEGORICAL[i], linewidth=2, marker="o" if len(agg) <= 40 else None,
                        markersize=4, label=lvl)
            if hue:
                _legend(ax, _label(hue, labels))
            if data.groupby("x").size().max() > 1:
                ylabel = f"Mean {ylabel}"
                meta["notes"].append("Where several records share an x value, their mean is plotted.")
            _style(ax)
            if kind == "time_series":
                fig.autofmt_xdate()
            meta["n"] = int(len(data))

        elif kind == "heatmap":
            _need(x and y, "two category variables (x and y)")
            cx, ox = _levels(df[x], 15)
            ox = _reorder(ox, preferred)
            cy, oy = _levels(df[y], 15)
            ct = pd.crosstab(cy, cx).reindex(index=oy, columns=ox).fillna(0)
            image = ax.imshow(ct.to_numpy(), cmap=SEQUENTIAL, aspect="auto", vmin=0)
            ax.set_xticks(range(len(ox)), ox)
            ax.set_yticks(range(len(oy)), oy)
            peak = ct.to_numpy().max() or 1
            for i in range(ct.shape[0]):
                for j in range(ct.shape[1]):
                    value = ct.iat[i, j]
                    ax.text(j, i, f"{int(value)}", ha="center", va="center", fontsize=9, color=SURFACE if value > 0.55 * peak else INK)
            bar = fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
            bar.set_label("Number of records", color=INK_2, fontsize=9)
            bar.ax.tick_params(colors=INK_2, labelsize=8)
            _style(ax, None)
            plt.setp(ax.get_xticklabels(), rotation=35, ha="right")
            meta["n"] = int(ct.to_numpy().sum())

        elif kind == "correlation_matrix":
            cols = columns or [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])][:15]
            if len(cols) < 2:
                raise AnalysisError("Select at least two numeric variables.")
            method = config.get("method", "pearson")
            if method not in ("pearson", "spearman", "kendall"):
                raise AnalysisError("method must be pearson, spearman or kendall.")
            data = pd.DataFrame({c: numeric(df[c]) for c in cols})
            corr = data.corr(method=method, min_periods=4)
            image = ax.imshow(corr.to_numpy(), cmap=DIVERGING, vmin=-1, vmax=1)
            names = [_label(c, labels) for c in cols]
            ax.set_xticks(range(len(cols)), names)
            ax.set_yticks(range(len(cols)), names)
            plt.setp(ax.get_xticklabels(), rotation=40, ha="right")
            if len(cols) <= 12:
                for i in range(len(cols)):
                    for j in range(len(cols)):
                        value = corr.iat[i, j]
                        if pd.notna(value):
                            ax.text(j, i, f"{value:.2f}", ha="center", va="center", fontsize=8, color=SURFACE if abs(value) > 0.6 else INK)
            bar = fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
            bar.set_label(f"{method.title()} correlation", color=INK_2, fontsize=9)
            bar.ax.tick_params(colors=INK_2, labelsize=8)
            _style(ax, None)
            xlabel = ylabel = ""
            meta.update(n=int(len(data.dropna())), columns=cols, method=method)
            meta["notes"].append("Pairwise complete observations; coefficients are not adjusted for multiple comparisons.")

        elif kind == "group_comparison":
            _need(x and y, "a category (x) and a numeric variable (y)")
            cats, order = _levels(df[x], 12)
            order = _reorder(order, preferred)
            data = pd.DataFrame({"c": cats, "v": numeric(df[y])}).dropna()
            order = [o for o in order if (data["c"] == o).sum() > 0]
            means = [data.loc[data["c"] == o, "v"].mean() for o in order]
            err = [_half_ci(data.loc[data["c"] == o, "v"].to_numpy()) for o in order]
            ax.errorbar(range(len(order)), means, yerr=err, fmt="o", color=CATEGORICAL[0], ecolor=INK_2, elinewidth=1.4,
                        capsize=5, markersize=8)
            ax.set_xticks(range(len(order)), [f"{o}\n(n={(data['c'] == o).sum()})" for o in order])
            ax.set_xlim(-0.6, len(order) - 0.4)
            ylabel = f"Mean {ylabel}"
            _style(ax)
            meta["n"] = int(len(data))
            meta["notes"].append("Points are group means; bars are 95% confidence intervals.")

        elif kind == "qq":
            _need(x, "a numeric variable (x)")
            values = numeric(df[x]).dropna().to_numpy()
            _enough(values, 3, x)
            _qq(ax, values)
            xlabel, ylabel = "Theoretical normal quantiles", f"Ordered values of {xlabel}"
            meta["n"] = int(len(values))
            meta["notes"].append("Points close to the line indicate an approximately normal distribution.")

        ax.set_title(default_title, fontsize=12, color=INK, pad=12, loc="left", fontweight="bold")
        if config.get("x_label") is not None or xlabel:
            ax.set_xlabel(config.get("x_label") or xlabel, fontsize=10, color=INK_2)
        if config.get("y_label") is not None or ylabel:
            ax.set_ylabel(config.get("y_label") or ylabel, fontsize=10, color=INK_2)
        meta["title"] = default_title
        return _png(fig), meta
    finally:
        plt.close(fig)


def _need(value, what: str) -> None:
    if not value:
        raise AnalysisError(f"This chart needs {what}.")


def _enough(values, minimum: int, what: str) -> None:
    if len(values) < minimum:
        raise AnalysisError(f"Not enough valid data in {what} to draw this chart.")


def _half_ci(values: np.ndarray) -> float:
    lo, hi = mean_ci(values)
    return 0.0 if lo is None else float((hi - lo) / 2)


def _qq(ax, values: np.ndarray) -> None:
    (osm, osr), (slope, intercept, _r) = stats.probplot(values, dist="norm")
    ax.scatter(osm, osr, s=22, color=CATEGORICAL[0], alpha=0.85, edgecolors=SURFACE, linewidths=0.5)
    ax.plot(osm, intercept + slope * np.asarray(osm), color=INK, linewidth=1.4)
    _style(ax, "both")


def _png(fig) -> bytes:
    buffer = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buffer, format="png", dpi=150, facecolor=SURFACE)
    return buffer.getvalue()


def render_regression_diagnostics(diagnostics: dict, outcome: str) -> bytes:
    """Residuals-vs-fitted, Q-Q and residual histogram for a linear model,
    drawn from the diagnostics stored with the regression result."""
    fitted = np.asarray(diagnostics.get("fitted", []), dtype=float)
    resid = np.asarray(diagnostics.get("residuals", []), dtype=float)
    if len(fitted) < 3:
        raise AnalysisError("This analysis has no stored residuals to plot.")
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    try:
        axes[0].scatter(fitted, resid, s=20, color=CATEGORICAL[0], alpha=0.8, edgecolors=SURFACE, linewidths=0.5)
        axes[0].axhline(0, color=INK, linewidth=1, linestyle="--")
        axes[0].set_xlabel(f"Fitted {outcome}", fontsize=10, color=INK_2)
        axes[0].set_ylabel("Residual", fontsize=10, color=INK_2)
        axes[0].set_title("Residuals vs fitted", fontsize=11, color=INK, loc="left", fontweight="bold")
        _style(axes[0], "both")
        _qq(axes[1], resid)
        axes[1].set_xlabel("Theoretical normal quantiles", fontsize=10, color=INK_2)
        axes[1].set_ylabel("Ordered residuals", fontsize=10, color=INK_2)
        axes[1].set_title("Normal Q-Q plot of residuals", fontsize=11, color=INK, loc="left", fontweight="bold")
        axes[2].hist(resid, bins="auto", color=CATEGORICAL[0], edgecolor=SURFACE, linewidth=1)
        axes[2].set_xlabel("Residual", fontsize=10, color=INK_2)
        axes[2].set_ylabel("Number of records", fontsize=10, color=INK_2)
        axes[2].set_title("Distribution of residuals", fontsize=11, color=INK, loc="left", fontweight="bold")
        _style(axes[2])
        return _png(fig)
    finally:
        plt.close(fig)
