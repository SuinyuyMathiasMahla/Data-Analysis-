# Sample data

`student_performance.csv` is **simulated** data (fixed random seed) for a
fictional survey on social media use and academic performance. It is not real
and must not be cited. Regenerate it with:

```bash
python backend/scripts/generate_sample_data.py
```

243 rows, 20 columns: `student_id`, `age`, `gender`, `department`,
`year_of_study`, `social_media_hours` (per day), `usage_level`, `study_hours`
(per week), `sleep_hours`, `attendance_pct`, `gpa`, `passed`, `stress_q1` …
`stress_q5` (1–5 ratings), `library_visits` (count), `pre_test`, `post_test`.

## Problems injected on purpose

| Problem | Where |
|---|---|
| 3 exact duplicate rows | the last three rows |
| Impossible ages | `-5` and `199` |
| Text in a numeric column | `study_hours = abc` |
| Impossible percentage | `attendance_pct = 140` |
| Extreme value | `social_media_hours = 23.5` |
| Inconsistent categories | `male`, `FEMALE`, `Male ` in `gender`; `computer science` in `department` |
| Misspelling | `Bussiness` in `department` |
| Missing values | 6 in `sleep_hours`, 4 in `study_hours`, 3 in `attendance_pct`, 2 in `gender` |

## Things to try

| Question | Variables | Expect |
|---|---|---|
| Is social media use related to GPA? | `social_media_hours`, `gpa` | a negative correlation; Spearman is recommended while the 23.5 value is present |
| Does GPA differ by usage level? | `gpa` by `usage_level` | one-way ANOVA with Tukey comparisons |
| What predicts GPA? | `gpa` ~ `study_hours` + `social_media_hours` + `attendance_pct` | multiple regression with a heteroscedasticity warning |
| What predicts passing? | `passed` ~ `study_hours` | logistic regression |
| Did scores improve? | `pre_test`, `post_test` (paired) | paired t-test |
| Is the stress scale reliable? | `stress_q1` … `stress_q5` | Cronbach's alpha about 0.86 |
| Library visits | `library_visits` ~ `study_hours` (count outcome) | Poisson regression |
