import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";

import { Alert, Button, ErrorNote, PageHead, Source } from "../components/ui";
import { AIReplyView } from "../components/widgets";
import { useAction, useApi } from "../hooks/useApi";
import { useProject } from "../layouts/ProjectLayout";
import { api } from "../services/api";
import type { AIReply } from "../types";

interface Turn { role: "user" | "assistant"; content: string; reply?: AIReply }
interface Review extends AIReply { highlights: string[]; next_steps: string[] }
const TOPICS = ["p-value", "effect size", "confidence interval", "correlation", "normality", "regression", "ANOVA", "chi-square", "power", "null hypothesis"];

export default function Assistant() {
  const { project, dataset } = useProject();
  const status = useApi<{ llm_configured: boolean; provider: string | null; model: string | null; mode: string }>("/ai/status");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [conversation, setConversation] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const [review, setReview] = useState<Review | null>(null);
  const chat = useAction();
  const reviewing = useAction();
  const end = useRef<HTMLDivElement | null>(null);
  useEffect(() => end.current?.scrollIntoView?.({ behavior: "smooth", block: "nearest" }), [turns]);

  const send = (text: string) => {
    if (!text.trim()) return;
    setTurns((t) => [...t, { role: "user", content: text }]);
    setMessage("");
    chat.run(() => api.post<AIReply & { conversation_id: number }>(`/projects/${project.id}/ai/chat`, { message: text, conversation_id: conversation })).then((reply) => {
      if (!reply) return;
      setConversation(reply.conversation_id);
      setTurns((t) => [...t, { role: "assistant", content: reply.content, reply }]);
    });
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    send(message);
  };
  const runReview = () => reviewing.run(() => api.post<Review>(`/projects/${project.id}/ai/analyze`, { dataset_id: dataset?.id ?? null })).then((r) => r && setReview(r));

  return (
    <div className="stack">
      <PageHead title="AI research assistant">
        Ask about your dataset, your results or a statistical concept. The assistant only sees summaries of this project, never the raw rows, and it explains results; it does not compute them.
      </PageHead>
      {status.data && (
        status.data.llm_configured
          ? <Alert kind="info">Connected to a language model ({status.data.provider}, {status.data.model}). Every number in its replies is checked against the statistical engine's output, and anything that cannot be matched is flagged.</Alert>
          : <Alert kind="info">No language model is configured, so answers come from the built-in rule engine: explanations of your computed results and a glossary of core concepts. An administrator can connect a provider in the server settings.</Alert>
      )}
      <section className="panel stack">
        <div className="row between">
          <div className="grow"><h2>Review my project</h2><p className="muted small" style={{ margin: 0 }}>Summarises the dataset, points out data-quality and methodological issues, and lists which research questions still need analysis.</p></div>
          <Button busy={reviewing.busy} disabled={!dataset} onClick={runReview}>Review project</Button>
        </div>
        <ErrorNote message={reviewing.error} />
        {!dataset && <p className="small muted">Upload a dataset first.</p>}
        {review && (
          <>
            <AIReplyView reply={review} />
            {review.next_steps.length > 0 && (
              <div><h3>Next steps</h3><ul>{review.next_steps.map((s, i) => <li key={i}>{s}</li>)}</ul><Link className="btn small" to="../analysis">Go to Run analysis</Link></div>
            )}
          </>
        )}
      </section>
      <section className="panel stack">
        <h2>Ask a question</h2>
        <div className="row">
          {TOPICS.map((t) => <Button key={t} small onClick={() => send(`What is ${/^[aeiouAE]/.test(t) ? "an" : "a"} ${t}?`)}>{t}</Button>)}
        </div>
        <div className="chat" aria-live="polite">
          {turns.map((turn, i) => turn.role === "user"
            ? <div key={i} className="bubble user"><Source kind="human" label="You" /> {turn.content}</div>
            : turn.reply ? <AIReplyView key={i} reply={turn.reply} /> : null)}
          {chat.busy && <p className="muted small">Thinking…</p>}
          <div ref={end} />
        </div>
        <ErrorNote message={chat.error} />
        <form className="row" onSubmit={submit} style={{ alignItems: "flex-end" }}>
          <label className="grow field"><span className="label">Your question</span>
            <textarea style={{ minHeight: "3.5rem" }} maxLength={4000} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="e.g. What does my correlation result mean for RQ1?" />
          </label>
          <Button type="submit" variant="primary" busy={chat.busy} disabled={!message.trim()}>Ask</Button>
        </form>
        <p className="table-note">The assistant supports your reasoning. It does not replace the statistical engine or your own judgement, and you are responsible for the final interpretation.</p>
      </section>
    </div>
  );
}
