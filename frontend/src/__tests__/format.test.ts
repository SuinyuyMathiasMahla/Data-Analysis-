import { describe, expect, it } from "vitest";

import { actionLabel, fmtNumber, fmtP, variablesText } from "../utils/format";

describe("number formatting", () => {
  it("shows three decimals and keeps integers whole", () => {
    expect(fmtNumber(0.123456)).toBe("0.123");
    expect(fmtNumber(240)).toBe("240");
    expect(fmtNumber(-0.42166)).toBe("-0.422");
  });

  it("never shows a tiny positive value as zero", () => {
    expect(fmtNumber(0.00004)).toBe("< 0.001");
  });

  it("shows a dash for missing values instead of inventing one", () => {
    expect(fmtNumber(null)).toBe("–");
    expect(fmtNumber(undefined)).toBe("–");
    expect(fmtNumber(Number.NaN)).toBe("–");
  });

  it("formats p-values in APA style", () => {
    expect(fmtP(0.0031)).toBe(".003");
    expect(fmtP(0.00001)).toBe("< .001");
    expect(fmtP(0.5)).toBe(".500");
    expect(fmtP(null)).toBe("–");
  });
});

describe("labels", () => {
  it("describes the variables of an analysis", () => {
    expect(variablesText({ outcome: "gpa", predictors: ["study_hours", "sleep_hours"], group: null })).toBe("outcome: gpa; predictors: study_hours, sleep_hours");
  });

  it("turns audit actions into readable text", () => {
    expect(actionLabel("dataset.cleaned")).toBe("Dataset cleaned");
  });
});
