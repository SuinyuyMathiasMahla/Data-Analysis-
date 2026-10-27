import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ResultView } from "../components/ResultView";
import type { EngineResult } from "../types";

const result: EngineResult = {
  method: "pearson",
  method_name: "Pearson correlation",
  n: 240,
  variables: { x: "social_media_hours", y: "gpa" },
  alpha: 0.05,
  statistic: { name: "r", value: -0.3089998 },
  df: 238,
  p_value: 0.00000105,
  significant: true,
  decision: "reject_null",
  apa: "r(238) = -0.309, p < .001, 95% CI [-0.419, -0.190]",
  summary: "There is a statistically significant moderate negative association between social_media_hours and gpa.",
  effect_sizes: [{ name: "Pearson correlation coefficient", value: -0.309, magnitude: "moderate", ci_low: -0.419, ci_high: -0.19 }],
  assumptions: [
    { name: "Normality of gpa", test: "Shapiro-Wilk", statistic: 0.98, p_value: 0.01, satisfied: false, note: "The distribution departs from normality." },
    { name: "Independence of observations", test: null, statistic: null, p_value: null, satisfied: null, note: "A property of the study design." },
  ],
  warnings: ["Extreme values are present and can inflate or mask a Pearson correlation."],
  tables: [],
};

describe("ResultView", () => {
  it("shows the engine's numbers without recomputing them", () => {
    render(<ResultView result={result} datasetVersion={8} />);
    expect(screen.getByText("r(238) = -0.309, p < .001, 95% CI [-0.419, -0.190]")).toBeInTheDocument();
    expect(screen.getByText("< .001")).toBeInTheDocument();
    expect(screen.getByText("Reject H0")).toBeInTheDocument();
    expect(screen.getByText("Dataset version 8")).toBeInTheDocument();
  });

  it("marks the result as computed by the statistical engine", () => {
    render(<ResultView result={result} />);
    expect(screen.getByText("Computed by the statistical engine")).toBeInTheDocument();
  });

  it("does not hide failed assumptions or warnings", () => {
    render(<ResultView result={result} />);
    expect(screen.getByText("1 not met")).toBeInTheDocument();
    expect(screen.getByText("Not met")).toBeInTheDocument();
    expect(screen.getByText("You judge")).toBeInTheDocument();
    expect(screen.getByText(/Extreme values are present/)).toBeInTheDocument();
  });

  it("says 'Fail to reject H0' for a non-significant result", () => {
    render(<ResultView result={{ ...result, p_value: 0.4, significant: false, decision: "fail_to_reject_null" }} />);
    expect(screen.getByText("Fail to reject H0")).toBeInTheDocument();
  });
});
