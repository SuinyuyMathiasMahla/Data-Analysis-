import { Link } from "react-router-dom";

import { Icon } from "../../components/ui";

const STEPS = [
  "Describe your research project, questions and hypotheses.",
  "Upload your data as CSV, Excel or JSON, or type it in.",
  "Review the data quality report and fix problems, with every change logged.",
  "Explore the data and get a recommended statistical test with the reasons for it.",
  "Run the test: assumptions, effect sizes and confidence intervals are checked for you.",
  "Turn results into findings, conclusions and recommendations you can trace back.",
  "Download the report as PDF or Word, with tables, charts and an appendix.",
];

export default function Landing() {
  return (
    <>
      <section className="landing-hero">
        <div className="inner">
          <div>
            <span className="eyebrow">For undergraduate, Master's and PhD research</span>
            <h1>Every conclusion in your thesis, <em>traceable</em> to the data behind it.</h1>
            <p>
              A research data analysis workspace for undergraduate, Master's and PhD projects. It takes you from a raw dataset to a
              statistically sound report, and keeps the full chain of evidence along the way.
            </p>
            <div className="row" style={{ marginTop: "1.5rem" }}>
              <Link className="btn primary" to="/register">Create an account</Link>
              <Link className="btn" to="/login">Sign in</Link>
            </div>
          </div>
        </div>
      </section>

      <section className="landing-section">
        <h2>How a project runs</h2>
        <p className="muted">Seven guided steps, each one recorded.</p>
        <div className="how-grid">
          {STEPS.map((text) => (
            <div key={text}><p>{text}</p></div>
          ))}
        </div>
      </section>

      <section className="landing-section" style={{ paddingTop: 0 }}>
        <div className="grid cols-3">
          <div className="panel feature">
            <div className="stat-icon"><Icon name="chart" /></div>
            <h3>Statistics you can defend</h3>
            <p className="small">
              Numbers come only from the statistical engine (SciPy, statsmodels, scikit-learn). Assumptions are checked before a test is
              trusted, and an alternative is suggested when they fail.
            </p>
          </div>
          <div className="panel feature">
            <div className="stat-icon"><Icon name="spark" /></div>
            <h3>An assistant that cannot invent results</h3>
            <p className="small">
              The AI assistant explains engine output in plain language. Every number in its replies is checked against the computed
              results, and anything it cannot trace is flagged.
            </p>
          </div>
          <div className="panel feature">
            <div className="stat-icon"><Icon name="repeat" /></div>
            <h3>Reproducible by design</h3>
            <p className="small">
              Each analysis stores the dataset version, variables, settings and software versions, so you can re-run it later and get
              the same answer for your examiner.
            </p>
          </div>
        </div>
        <p className="small muted" style={{ marginTop: "1.5rem" }}>
          Not included yet: survival analysis, time-series models, MANOVA, ordinal regression and structural equation modelling. The platform
          says so when one of them is the right method instead of producing output.
        </p>
      </section>
    </>
  );
}
