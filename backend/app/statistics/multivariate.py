"""Multivariate methods: PCA, exploratory factor analysis, cluster analysis
and scale reliability (Cronbach's alpha)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

from app.statistics import assumptions as A
from app.statistics.utils import (AnalysisError, InsufficientDataError, finalize, fmt_num, new_result, numeric,
                                  require_columns, table)


def _matrix(df: pd.DataFrame, columns: list[str], minimum_vars: int) -> tuple[pd.DataFrame, int]:
    columns = list(dict.fromkeys(columns or []))
    if len(columns) < minimum_vars:
        raise AnalysisError(f"Select at least {minimum_vars} numeric variables.")
    require_columns(df, *columns)
    frame = pd.DataFrame({c: numeric(df[c]) for c in columns})
    complete = frame.dropna()
    constant = [c for c in columns if complete[c].nunique() < 2]
    if constant:
        raise AnalysisError(f"Variable(s) with no variation among complete records: {', '.join(constant)}")
    return complete, int(len(frame) - len(complete))


def kmo_bartlett(data: pd.DataFrame) -> tuple[dict, dict]:
    """Kaiser-Meyer-Olkin sampling adequacy and Bartlett's test of sphericity."""
    n, p = data.shape
    corr = np.corrcoef(data.to_numpy(dtype=float), rowvar=False)
    det = np.linalg.det(corr)
    if det <= 0:
        singular = A._check("Factorability", "Correlation matrix determinant", det, None, False,
                            "The correlation matrix is singular: some variables are exact combinations of others.")
        return singular, singular
    inv = np.linalg.inv(corr)
    scale = np.sqrt(np.outer(np.diag(inv), np.diag(inv)))
    partial = -inv / scale
    np.fill_diagonal(partial, 0)
    off = corr - np.eye(p)
    kmo = float((off**2).sum() / ((off**2).sum() + (partial**2).sum()))
    label = ("unacceptable" if kmo < 0.5 else "miserable" if kmo < 0.6 else "mediocre" if kmo < 0.7
             else "middling" if kmo < 0.8 else "meritorious" if kmo < 0.9 else "marvellous")
    kmo_check = A._check("Sampling adequacy", "Kaiser-Meyer-Olkin (KMO)", kmo, None, bool(kmo >= 0.6),
                         f"KMO = {kmo:.3f} ({label}). Values of 0.60 or above are considered adequate for factoring.")
    chi2 = -(n - 1 - (2 * p + 5) / 6) * math.log(det)
    dof = p * (p - 1) / 2
    pval = float(stats.chi2.sf(chi2, dof))
    bartlett = A._check("Variables are correlated", "Bartlett's test of sphericity", chi2, pval, bool(pval < 0.05),
                        f"chi2({dof:.0f}) = {chi2:.2f}. " + ("The variables are sufficiently inter-correlated." if pval < 0.05
                                                              else "The variables are not sufficiently correlated to be reduced to components/factors."))
    return kmo_check, bartlett


def pca(df, variables, n_components=None, **_):
    """Principal component analysis on standardised variables (correlation matrix)."""
    data, dropped = _matrix(df, variables, 3)
    n, p = data.shape
    if n < max(30, 3 * p):
        raise InsufficientDataError(f"{n} complete record(s) for {p} variables (at least {max(30, 3 * p)} are needed).")
    z = (data - data.mean()) / data.std(ddof=1)
    eigvals, eigvecs = np.linalg.eigh(np.corrcoef(z.to_numpy(), rowvar=False))
    order = np.argsort(eigvals)[::-1]
    eigvals, eigvecs = np.clip(eigvals[order], 0, None), eigvecs[:, order]
    kaiser = int((eigvals > 1).sum())
    k = int(n_components) if n_components else max(1, kaiser)
    if not 1 <= k <= p:
        raise AnalysisError(f"The number of components must be between 1 and {p}.")
    loadings = eigvecs[:, :k] * np.sqrt(eigvals[:k])
    signs = np.sign(loadings[np.abs(loadings).argmax(axis=0), range(k)])
    loadings = loadings * np.where(signs == 0, 1, signs)
    explained = eigvals / eigvals.sum()
    kmo, bartlett = kmo_bartlett(data)

    res = new_result("pca", "Principal component analysis", n=n, variables={"variables": list(data.columns)})
    res["components_retained"] = k
    res["eigenvalues"] = eigvals.tolist()
    res["explained_variance_ratio"] = explained.tolist()
    res["loadings"] = {col: loadings[i].tolist() for i, col in enumerate(data.columns)}
    res["assumptions"] = [kmo, bartlett, A.minimum_sample(n, 5 * p, "PCA (5 cases per variable)")]
    cum = np.cumsum(explained)
    res["tables"] = [
        table("Variance explained", ["Component", "Eigenvalue", "% of variance", "Cumulative %"],
              [[f"PC{i + 1}", float(eigvals[i]), float(100 * explained[i]), float(100 * cum[i])] for i in range(p)],
              note=f"Kaiser criterion (eigenvalue > 1) suggests {kaiser} component(s); {k} retained. Check the scree plot as well."),
        table("Component loadings", ["Variable"] + [f"PC{i + 1}" for i in range(k)] + ["Communality"],
              [[col, *[float(v) for v in loadings[i]], float((loadings[i] ** 2).sum())] for i, col in enumerate(data.columns)]),
    ]
    if kmo["satisfied"] is False:
        res["warnings"].append("Sampling adequacy is poor (KMO < 0.60); the components may not be stable.")
    if dropped:
        res["warnings"].append(f"{dropped} record(s) with a missing value were excluded (listwise deletion).")
    res = finalize(res)
    res["summary"] = (f"PCA of {p} variables (n = {n}) retained {k} component(s) explaining {100 * cum[k - 1]:.1f}% of the total variance. "
                      "Components are mathematical summaries; naming them is a judgement the researcher must justify from the loadings.")
    return res


def _varimax(loadings: np.ndarray, max_iter: int = 500, tol: float = 1e-8) -> np.ndarray:
    p, k = loadings.shape
    rotation = np.eye(k)
    last = 0.0
    for _ in range(max_iter):
        rotated = loadings @ rotation
        u, s, vt = np.linalg.svd(loadings.T @ (rotated**3 - rotated @ np.diag((rotated**2).sum(axis=0)) / p))
        rotation = u @ vt
        if s.sum() < last * (1 + tol):
            break
        last = s.sum()
    return loadings @ rotation


def factor_analysis(df, variables, n_factors=None, rotation="varimax", **_):
    """Exploratory factor analysis (maximum likelihood, optional varimax rotation)."""
    from sklearn.decomposition import FactorAnalysis

    data, dropped = _matrix(df, variables, 4)
    n, p = data.shape
    if n < max(50, 5 * p):
        raise InsufficientDataError(f"{n} complete record(s) for {p} variables (at least {max(50, 5 * p)} are needed for factor analysis).")
    if rotation not in ("varimax", "none"):
        raise AnalysisError("rotation must be 'varimax' or 'none'.")
    z = ((data - data.mean()) / data.std(ddof=1)).to_numpy()
    eigvals = np.sort(np.linalg.eigvalsh(np.corrcoef(z, rowvar=False)))[::-1]
    kaiser = int((eigvals > 1).sum())
    k = int(n_factors) if n_factors else max(1, kaiser)
    if not 1 <= k < p:
        raise AnalysisError(f"The number of factors must be between 1 and {p - 1}.")
    model = FactorAnalysis(n_components=k, random_state=0, max_iter=2000).fit(z)
    loadings = model.components_.T
    if rotation == "varimax" and k > 1:
        loadings = _varimax(loadings)
    order = np.argsort(-(loadings**2).sum(axis=0))
    loadings = loadings[:, order]
    signs = np.sign(loadings.sum(axis=0))
    loadings = loadings * np.where(signs == 0, 1, signs)
    communality = (loadings**2).sum(axis=1)
    ss = (loadings**2).sum(axis=0)
    kmo, bartlett = kmo_bartlett(data)

    res = new_result("factor_analysis", "Exploratory factor analysis", n=n, variables={"variables": list(data.columns)})
    res["factors_retained"] = k
    res["rotation"] = rotation if k > 1 else "none"
    res["eigenvalues"] = eigvals.tolist()
    res["loadings"] = {col: loadings[i].tolist() for i, col in enumerate(data.columns)}
    res["assumptions"] = [kmo, bartlett, A.minimum_sample(n, 10 * p, "factor analysis (10 cases per variable)")]
    res["tables"] = [
        table("Factor loadings" + (" (varimax rotated)" if res["rotation"] == "varimax" else ""),
              ["Variable"] + [f"Factor {i + 1}" for i in range(k)] + ["Communality", "Uniqueness"],
              [[col, *[float(v) for v in loadings[i]], float(communality[i]), float(1 - communality[i])] for i, col in enumerate(data.columns)],
              note="Loadings of about 0.40 or more in absolute value are usually treated as salient."),
        table("Variance explained by factor", ["Factor", "Sum of squared loadings", "% of variance"],
              [[f"Factor {i + 1}", float(ss[i]), float(100 * ss[i] / p)] for i in range(k)]),
        table("Eigenvalues of the correlation matrix", ["Number", "Eigenvalue"], [[i + 1, float(v)] for i, v in enumerate(eigvals)],
              note=f"Kaiser criterion suggests {kaiser} factor(s)."),
    ]
    cross = [col for i, col in enumerate(data.columns) if (np.abs(loadings[i]) >= 0.4).sum() > 1]
    weak = [col for i, col in enumerate(data.columns) if np.abs(loadings[i]).max() < 0.4]
    if cross:
        res["warnings"].append(f"Variable(s) loading on more than one factor (cross-loading): {', '.join(cross)}.")
    if weak:
        res["warnings"].append(f"Variable(s) not loading saliently on any factor: {', '.join(weak)}.")
    if kmo["satisfied"] is False or bartlett["satisfied"] is False:
        res["warnings"].append("The data may not be suitable for factor analysis (see the KMO and Bartlett checks).")
    if dropped:
        res["warnings"].append(f"{dropped} record(s) with a missing value were excluded (listwise deletion).")
    res = finalize(res)
    res["summary"] = (f"Exploratory factor analysis of {p} variables (n = {n}) extracted {k} factor(s) accounting for "
                      f"{100 * ss.sum() / p:.1f}% of the variance. Factor labels must be justified from the pattern of loadings and theory.")
    return res


def cluster_analysis(df, variables, n_clusters=None, **_):
    """K-means clustering on standardised variables. When ``n_clusters`` is not
    given, k = 2..8 is compared by silhouette score."""
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    data, dropped = _matrix(df, variables, 2)
    n, p = data.shape
    if n < 30:
        raise InsufficientDataError(f"{n} complete record(s); at least 30 are needed for cluster analysis.")
    z = ((data - data.mean()) / data.std(ddof=1)).to_numpy()
    scores = []
    if n_clusters:
        k = int(n_clusters)
        if not 2 <= k <= min(15, n - 1):
            raise AnalysisError("The number of clusters must be between 2 and 15.")
    else:
        for candidate in range(2, min(8, n - 1) + 1):
            labels = KMeans(n_clusters=candidate, n_init=10, random_state=0).fit_predict(z)
            scores.append([candidate, float(silhouette_score(z, labels))])
        k = max(scores, key=lambda s: s[1])[0]
    model = KMeans(n_clusters=k, n_init=10, random_state=0).fit(z)
    labels = model.labels_
    silhouette = float(silhouette_score(z, labels))
    quality = "weak" if silhouette < 0.25 else "fair" if silhouette < 0.5 else "good" if silhouette < 0.7 else "strong"
    res = new_result("cluster_analysis", "K-means cluster analysis", n=n, variables={"variables": list(data.columns)})
    res["n_clusters"] = k
    res["silhouette"] = silhouette
    res["cluster_sizes"] = [int((labels == i).sum()) for i in range(k)]
    res["effect_sizes"] = [{"name": "Silhouette score", "value": silhouette, "magnitude": quality, "ci_low": None, "ci_high": None,
                            "ci_level": None, "note": "Ranges from -1 to 1; higher means better-separated clusters."}]
    centres = data.groupby(labels).mean()
    res["tables"] = [table("Cluster profiles (means in original units)", ["Cluster", "N", *data.columns],
                           [[f"Cluster {i + 1}", int((labels == i).sum()), *[float(v) for v in centres.loc[i]]] for i in range(k)])]
    if scores:
        res["tables"].append(table("Silhouette score by number of clusters", ["k", "Silhouette"], scores,
                                   note=f"k = {k} had the highest silhouette score and was selected."))
    res["assumptions"] = [A._check("Cluster structure", "Silhouette score", silhouette, None, bool(silhouette >= 0.25),
                                   f"Silhouette = {silhouette:.3f} ({quality} structure). Below 0.25 there may be no real clusters in the data.")]
    res["warnings"].append("K-means always returns k clusters, even when the data have no real cluster structure. Treat this as exploratory and "
                           "validate the solution. A fixed random seed (0) is used so the result is reproducible.")
    if dropped:
        res["warnings"].append(f"{dropped} record(s) with a missing value were excluded (listwise deletion).")
    res = finalize(res)
    res["summary"] = (f"K-means clustering of {p} standardised variables (n = {n}) produced {k} clusters "
                      f"(sizes: {', '.join(str(s) for s in res['cluster_sizes'])}) with a silhouette score of {fmt_num(silhouette, 3)} ({quality} separation).")
    return res


def cronbach_alpha(df, variables, **_):
    """Internal-consistency reliability of a multi-item scale."""
    data, dropped = _matrix(df, variables, 2)
    n, k = data.shape
    if n < 10:
        raise InsufficientDataError(f"{n} complete record(s).")
    items = data.to_numpy(dtype=float)
    total_var = items.sum(axis=1).var(ddof=1)
    if total_var == 0:
        raise AnalysisError("The total score has no variation.")
    alpha = k / (k - 1) * (1 - items.var(axis=0, ddof=1).sum() / total_var)
    quality = ("unacceptable" if alpha < 0.5 else "poor" if alpha < 0.6 else "questionable" if alpha < 0.7
               else "acceptable" if alpha < 0.8 else "good" if alpha < 0.9 else "excellent")
    rows, negative = [], []
    for i, col in enumerate(data.columns):
        rest = np.delete(items, i, axis=1)
        rest_total = rest.sum(axis=1)
        r = float(np.corrcoef(items[:, i], rest_total)[0, 1]) if rest_total.std() > 0 else None
        if k > 2 and rest_total.var(ddof=1) > 0:
            a_del = (k - 1) / (k - 2) * (1 - rest.var(axis=0, ddof=1).sum() / rest_total.var(ddof=1))
        else:
            a_del = None
        rows.append([col, float(items[:, i].mean()), float(items[:, i].std(ddof=1)), r, a_del])
        if r is not None and r < 0:
            negative.append(col)
    res = new_result("cronbach_alpha", "Reliability analysis (Cronbach's alpha)", n=n, variables={"variables": list(data.columns)})
    res["statistic"] = {"name": "alpha", "value": float(alpha)}
    res["effect_sizes"] = [{"name": "Cronbach's alpha", "value": float(alpha), "magnitude": quality, "ci_low": None, "ci_high": None,
                            "ci_level": None, "note": "0.70 or above is the usual threshold for research use."}]
    res["tables"] = [table("Item statistics", ["Item", "Mean", "SD", "Corrected item-total correlation", "Alpha if item deleted"], rows)]
    res["assumptions"] = [A._check("Items measure one construct", None, None, None, None,
                                   "Alpha assumes the items form a single (unidimensional) scale; check with factor analysis.")]
    if negative:
        res["warnings"].append(f"Item(s) negatively related to the rest of the scale: {', '.join(negative)}. They may need reverse-coding.")
    if dropped:
        res["warnings"].append(f"{dropped} record(s) with a missing value were excluded (listwise deletion).")
    res = finalize(res)
    res["apa"] = f"Cronbach's alpha = {fmt_num(alpha, 3)} ({k} items, n = {n})"
    res["summary"] = f"The {k}-item scale has {quality} internal consistency ({res['apa']})."
    return res
