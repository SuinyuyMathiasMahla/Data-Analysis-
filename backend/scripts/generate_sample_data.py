"""Generate the sample research dataset used in the docs and the workflow test.

The data are SIMULATED (fixed random seed) for a fictional survey on social
media use and academic performance. Realistic data-quality problems are
injected on purpose so the quality and cleaning steps have something to find.

    python backend/scripts/generate_sample_data.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parents[2] / "sample_data" / "student_performance.csv"


def build(n: int = 240, seed: int = 20260) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    gender = rng.choice(["Male", "Female"], n, p=[0.48, 0.52])
    department = rng.choice(["Computer Science", "Business", "Education", "Engineering"], n, p=[0.3, 0.27, 0.2, 0.23])
    year = rng.choice([1, 2, 3, 4], n, p=[0.3, 0.28, 0.24, 0.18])
    age = np.clip(np.round(17.5 + year + rng.normal(0, 1.4, n)), 17, 32).astype(int)
    social = np.clip(rng.gamma(4.0, 0.95, n), 0.2, 11).round(1)
    study = np.clip(18 - 1.1 * social + rng.normal(0, 4.2, n), 1, 40).round(1)
    sleep = np.clip(7.4 - 0.18 * social + rng.normal(0, 0.9, n), 3.5, 10).round(1)
    attendance = np.clip(88 - 1.6 * social + 0.35 * study + rng.normal(0, 7, n), 35, 100).round(0)
    dept_shift = pd.Series(department).map({"Computer Science": 0.10, "Business": -0.05, "Education": 0.0, "Engineering": -0.12}).to_numpy()
    gpa = np.clip(2.35 + 0.035 * study - 0.075 * social + 0.008 * (attendance - 80) + dept_shift + rng.normal(0, 0.36, n), 0.8, 4.0).round(2)
    passed = np.where(gpa + rng.normal(0, 0.15, n) >= 2.4, "Yes", "No")
    stress_base = 2.2 + 0.22 * social - 0.25 * (sleep - 7) + rng.normal(0, 0.6, n)
    stress = {f"stress_q{i}": np.clip(np.round(stress_base + rng.normal(0, 0.7, n)), 1, 5).astype(int) for i in range(1, 6)}
    library = rng.poisson(np.exp(0.2 + 0.07 * study - 0.05 * social))
    pre = np.clip(55 + 6 * (gpa - 2.8) + rng.normal(0, 9, n), 10, 100).round(0)
    post = np.clip(pre + 4.5 + rng.normal(0, 6.5, n), 10, 100).round(0)
    usage = pd.cut(social, [0, 2.5, 5, 24], labels=["Low", "Moderate", "High"]).astype(str)

    df = pd.DataFrame({
        "student_id": np.arange(1001, 1001 + n), "age": age, "gender": gender, "department": department, "year_of_study": year,
        "social_media_hours": social, "usage_level": usage, "study_hours": study, "sleep_hours": sleep, "attendance_pct": attendance,
        "gpa": gpa, "passed": passed, **stress, "library_visits": library, "pre_test": pre, "post_test": post,
    }).astype(object)

    # ---- injected data-quality problems (documented in sample_data/README.md) ----
    for col, k in [("sleep_hours", 6), ("study_hours", 4), ("attendance_pct", 3), ("gender", 2)]:
        df.loc[rng.choice(n, k, replace=False), col] = None            # missing values
    df.loc[17, "age"] = -5                                              # impossible value
    df.loc[101, "age"] = 199                                            # impossible value
    df.loc[58, "study_hours"] = "abc"                                   # text in a numeric column
    df.loc[140, "social_media_hours"] = 23.5                            # extreme outlier
    df.loc[[5, 44, 90], "gender"] = ["male", "FEMALE", "Male "]         # inconsistent categories
    df.loc[[12, 70], "department"] = ["computer science", "Bussiness"]  # case + misspelling
    df.loc[33, "attendance_pct"] = 140                                  # impossible percentage
    df = pd.concat([df, df.iloc[[20, 21, 150]]], ignore_index=True)     # duplicate rows
    return df


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frame = build()
    frame.to_csv(OUT, index=False)
    print(f"Wrote {len(frame)} rows x {frame.shape[1]} columns to {OUT}")
