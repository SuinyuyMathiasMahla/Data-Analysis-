# Statistical methods

This document states what each method computes, the assumptions it checks, how
results are worded, and how the numbers were verified.

## Principles

1. **One source of numbers.** Every statistic comes from `backend/app/statistics`.
   The AI assistant, findings and reports only quote those results.
2. **Method choice follows the question and the data**, not the academic level:
   research question → design (independent or paired) → variable types →
   sample characteristics → distribution → assumption checks.
3. **Assumptions are checked before a test is trusted**, and a failed
   assumption produces a warning that names the alternative.
4. **No p-value without an effect size**, and a confidence interval wherever
   one is defined.
5. **Wording.** A significant correlation or regression coefficient is described
   as an association. A non-significant result is "insufficient evidence", never
   "no effect". Too little data raises *"Insufficient evidence to perform this
   analysis reliably."* instead of returning a number.
6. **Unimplemented methods refuse.** They are registered so they can be named
   as the right method, and return HTTP 501 with an explanation.

## Variable types

Imported columns get a *type* (numeric, integer, categorical, boolean,
datetime, text, identifier) and a *measurement level* (nominal, ordinal,
interval, ratio). Inference rules (`analysis/profiling.py`):

- at least 90% of non-missing values parse as numbers → numeric; the rest are
  reported as invalid values;
- whole numbers with at most 7 distinct values between 0 and 10 → ordinal
  (rating scales); with 2 distinct values → nominal;
- unique whole numbers in a column named like an id → identifier;
- text with few distinct values → categorical; mostly distinct or long → free text.

The researcher can correct the level in the data dictionary; the recommender
uses the corrected level. For analysis each variable is classed as continuous,
ordinal, binary, nominal, datetime or other.

## Data Quality Score

`score = 100 − Σ weight × min(1, 5 × share affected)`

| Dimension | Weight | Share measured |
|---|---|---|
| Completeness | 40 | cells that are missing |
| Validity | 25 | cells that are not valid for their type or outside the plausible range |
| Uniqueness | 20 | rows that exactly duplicate an earlier row |
| Consistency | 10 | categorical cells spelled inconsistently |
| Structure | 5 | columns that are empty or constant |

Shares are multiplied by 5 and capped, so 20% affected already costs the full
weight. Outliers, duplicate identifiers, near-zero variance, highly correlated
variables (|r| ≥ 0.90), VIF > 10, sentinel codes (99, 999, −99 …) and
straight-lined rating items are **reported but do not lower the score**: they
are analytic warnings, not errors, and scoring them would reward deleting data.
Plausible ranges come from the data dictionary, or from name-based defaults
(age 0–120, percentages 0–100, GPA 0–5, non-negative durations and counts).

## Missing data

Analyses use listwise deletion on the variables involved (pairwise for
correlation matrices) and always report how many records were excluded.
Imputation is an explicit, logged cleaning step; imputing more than 20% of a
variable adds a caution. Multiple imputation is not implemented.

## Method recommendation rules

| Situation | Primary | Alternative when assumptions fail |
|---|---|---|
| Two continuous variables | Pearson | Spearman (non-normal with n < 30, or extreme values) |
| An ordinal variable involved | Spearman | Kendall (small n, many ties) |
| Continuous outcome, 2 independent groups | t-test (Welch if variances differ) | Mann-Whitney (ordinal, or non-normal with a group < 30) |
| Continuous outcome, 3+ independent groups | One-way ANOVA (+ Welch, Tukey) | Kruskal-Wallis |
| Two paired measurements | Paired t-test | Wilcoxon signed-rank |
| Three or more repeated measurements | Repeated-measures ANOVA | Friedman |
| Two categorical variables | Chi-square | Fisher's exact (2×2 with small expected counts) |
| Binary outcome, numeric predictor(s) | Logistic regression | – |
| Continuous outcome, several predictors | Multiple linear regression | robust (HC3) standard errors |
| Count outcome | Poisson | Negative binomial (variance/mean > 2) |
| Ordinal outcome with several predictors, time-to-event | named, **not implemented** | – |

Academic level adds follow-up guidance only (effect sizes and a chart for
undergraduates; diagnostics, controls and reliability for Master's; power
analysis, sensitivity analysis, multiplicity and clustering for PhD).

## Implemented methods

### Descriptive
Count, missing, mean with 95% t-interval, median, mode, min, max, range,
variance and SD (n − 1), SEM, quartiles (linear interpolation), IQR, coefficient
of variation (ratio data with positive values only), skewness and excess
kurtosis (bias-corrected). Categorical: counts, percentages of valid cases,
cumulative percentages, Wilson intervals.

### Correlation
| Method | Output | Checks |
|---|---|---|
| Pearson | r, df = n − 2, p, Fisher-z 95% CI, r² | normality of both variables, extreme values (3 × IQR), linearity hint (Pearson vs Spearman) |
| Spearman | ρ, p, CI with Bonett–Wright standard error | monotonicity (to judge), share of ties |
| Kendall τ-b | τ, p, approximate CI | – |

Strength labels (Cohen): < .10 negligible, < .30 weak, < .50 moderate, ≥ .50 strong.

### Association
- **Chi-square test of independence** without continuity correction (the Yates
  result is shown for 2×2 tables). Cramér's V, odds ratio for 2×2 (Woolf CI,
  Haldane–Anscombe correction for zero cells). Cochran's rule is checked: no
  expected count below 1 and at most 20% below 5.
- **Fisher's exact test** for 2×2 tables.

### Group comparisons
| Method | Output | Checks |
|---|---|---|
| Independent t-test | Student and Welch; Welch is reported when Levene (median-centred) rejects equal variances; mean difference with CI; Cohen's d (pooled SD, CI), Hedges' g | normality per group, variances |
| Paired t-test | t, mean difference CI, d_z | normality of differences, extreme differences |
| One-way ANOVA | ANOVA table, η², ω², Welch's ANOVA, Tukey HSD when significant | normality of residuals, variances |
| Repeated-measures ANOVA | F, partial η², Greenhouse–Geisser ε and corrected p (reported as the main p when ε < 0.75), Holm-adjusted paired t-tests | sphericity via ε, residual normality |
| Mann-Whitney U | U, p (exact for small samples), rank-biserial correlation | similar shapes (to judge) |
| Wilcoxon signed-rank | W, p, matched-pairs rank-biserial correlation | symmetry of differences |
| Kruskal-Wallis | H, ε², Holm-adjusted pairwise Mann-Whitney tests | similar shapes (to judge) |
| Friedman | χ², Kendall's W | – |

Directional (`greater`, `less`) alternatives are available for the two-sample
and correlation tests; use them only for a hypothesis stated in advance.

### Regression
- **Linear (simple and multiple).** Ordinary least squares in closed form.
  B, SE, t, p, 95% CI, standardised β, VIF; R², adjusted R², F, RMSE, AIC, BIC,
  Cohen's f². Categorical predictors are dummy-coded against the first level.
  Diagnostics: Shapiro-Wilk on residuals, Breusch–Pagan (Koenker), Durbin–Watson,
  VIF, Cook's distance, residual plots. Optional HC3 robust standard errors.
- **Binary logistic.** Maximum likelihood by iteratively reweighted least
  squares. B, SE, Wald z, odds ratios with CI; likelihood-ratio χ², McFadden and
  Nagelkerke R², AIC, classification table, AUC. Checks events per variable
  (≥ 10) and VIF, and warns on complete or quasi-complete separation.
- **Poisson.** IRLS; rate ratios with CI; likelihood-ratio χ²; Pearson
  dispersion statistic with a warning above 1.5.
- **Negative binomial** and **linear mixed-effects (random intercept)** call
  statsmodels (ICC reported for mixed models).

### Multivariate
- **PCA** on the correlation matrix: eigenvalues, variance explained, loadings,
  Kaiser criterion, KMO, Bartlett's test.
- **Exploratory factor analysis**: maximum likelihood (scikit-learn) with
  varimax rotation, communalities, cross-loading and weak-item warnings.
- **K-means clustering** on standardised variables; k chosen by silhouette
  score when not given; fixed random seed.
- **Cronbach's alpha** with corrected item-total correlations and
  alpha-if-item-deleted.

### Power and sample size
Noncentral t, F and χ² distributions (Fisher-z approximation for correlations)
for the independent and paired t-test, correlation, one-way ANOVA, chi-square
and multiple regression. Three modes are kept apart and labelled:
prospective sample size, prospective power for an assumed effect, and post-hoc
"observed" power, which always carries a warning that it restates the p-value.

### Not implemented
Factorial ANOVA / ANCOVA, MANOVA, ordinal regression, other GLM families,
time-series models, survival analysis, structural equation modelling.

## Multiple comparisons

Post hoc tests are adjusted (Tukey, Holm). Correlation matrices and separate
analyses are not; the report adds a limitation when five or more significance
tests were run.

## Verification

`backend/tests` checks the engine against independent references:

| Reference | Used for |
|---|---|
| R `t.test` on `sleep` | Welch, Student and paired t-tests, confidence intervals |
| R `aov`, `TukeyHSD`, `oneway.test`, `kruskal.test` on `PlantGrowth` | ANOVA table, post hoc p-values, Welch's ANOVA, Kruskal-Wallis |
| R `lm` on `mtcars` | simple and multiple regression coefficients, SE, R², F |
| R `glm(binomial)` on `mtcars` | logistic coefficients, SE, deviances, AIC |
| SciPy `linregress`, scikit-learn, direct likelihood maximisation | OLS, logistic and Poisson estimates and standard errors |
| G\*Power 3.1 | required sample sizes and power |
| Hand calculation | descriptives, chi-square, Spearman, repeated-measures ANOVA, Cronbach's alpha, exact rank tests |
| statsmodels (where installed) | OLS, HC3, Breusch–Pagan, Durbin–Watson, Logit, Poisson GLM |

Two conventions to be aware of: AIC for linear models counts only the
coefficients (as statsmodels does), so it is 2 lower than R's `AIC(lm)`; and the
correlation sample size for r = .30 at 80% power is 85 (Fisher-z approximation)
where the exact method gives 84.

## AI interpretation

The assistant receives a JSON context of engine results and a system prompt
with the integrity rules (no invented numbers, references or causal claims; no
hiding of assumptions; no suggestion to change data or tests to reach
significance). After each reply, every number in it is compared with the
numbers in the context; unmatched numbers are shown to the user as an integrity
warning and stored with the message. The check proves a number exists in the
engine output, not that it was attached to the right statistic, so AI replies
still need reading against the result tables.
