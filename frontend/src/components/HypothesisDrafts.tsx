import { useState } from "react";

import { api } from "../services/api";
import { errorMessage } from "../utils/format";
import { Alert, Button, ErrorNote } from "./ui";

export interface HypothesisDraft {
  null_text: string;
  alternative_text: string;
  research_question_id: string;
}

type Draft = {
  draft: { null_text: string; alternative_text: string } | null;
  questions: string[];
  note?: string;
};

/**
 * Drafts H0 and H1 for questions that have none. A draft only fills the form; the user reviews it and presses Save.
 * When the assistant cannot tell the outcome or predictor from the linked variables, it asks instead of guessing.
 */
export function HypothesisDrafts({ projectId, questions, onUse }: {
  projectId: number;
  questions: { id: number; code: string; text: string }[];
  onUse: (draft: HypothesisDraft) => void;
}) {
  const [results, setResults] = useState<Record<number, Draft>>({});
  const [error, setError] = useState<string | null>(null);

  if (questions.length === 0) return null;

  const draft = (questionId: number) =>
    api
      .post<Draft>(`/projects/${projectId}/assistant/draft`, { kind: "hypothesis", research_question_id: questionId })
      .then((result) => setResults((list) => ({ ...list, [questionId]: result })))
      .catch((err) => setError(errorMessage(err)));

  return (
    <section className="panel stack" aria-label="Assistant drafts for hypotheses">
      <h2 style={{ margin: 0 }}>Assistant draft</h2>
      <p className="small muted">Questions without a hypothesis. A draft fills the form below; nothing is saved until you press Save.</p>
      <ErrorNote message={error} />
      {questions.map((q) => {
        const result = results[q.id];
        return (
          <div className="stack" key={q.id}>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <span><strong>{q.code}</strong> {q.text}</span>
              <Button small onClick={() => draft(q.id)}>Draft H0 and H1</Button>
            </div>
            {result?.draft && (
              <Alert kind="info">
                <div><strong>H0:</strong> {result.draft.null_text}</div>
                <div><strong>H1:</strong> {result.draft.alternative_text}</div>
                {result.note && <div className="small muted">{result.note}</div>}
                <Button small variant="primary" onClick={() => onUse({ null_text: result.draft!.null_text, alternative_text: result.draft!.alternative_text, research_question_id: String(q.id) })}>
                  Use this draft in the form
                </Button>
              </Alert>
            )}
            {result && result.questions.length > 0 && (
              <Alert kind="warn">
                <div>The assistant needs this before it can draft:</div>
                <ul>{result.questions.map((text) => <li key={text}>{text}</li>)}</ul>
              </Alert>
            )}
          </div>
        );
      })}
    </section>
  );
}
