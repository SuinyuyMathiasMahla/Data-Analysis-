import { useState } from "react";
import type { FormEvent } from "react";

import { Alert, Badge, Button, ErrorNote, Field, Loading, PageHead } from "../components/ui";
import { useAction, useApi } from "../hooks/useApi";
import { api } from "../services/api";
import { useAuth } from "../services/auth";
import type { HistoryEntry, User } from "../types";
import { actionLabel, fmtDate } from "../utils/format";

export function Profile() {
  const { user, setUser } = useAuth();
  const [form, setForm] = useState({ full_name: user?.full_name ?? "", institution: user?.institution ?? "", department: user?.department ?? "", academic_level: user?.academic_level ?? "" });
  const [saved, setSaved] = useState(false);
  const { busy, error, run } = useAction();
  const resend = useAction();
  const [sent, setSent] = useState(false);
  if (!user) return null;
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => { setSaved(false); setForm({ ...form, [key]: e.target.value }); };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    run(() => api.put<User>("/users/me", { full_name: form.full_name, institution: form.institution || null, department: form.department || null, academic_level: form.academic_level || null }))
      .then((updated) => { if (updated) { setUser(updated); setSaved(true); } });
  };
  return (
    <main className="page stack" style={{ maxWidth: 720 }}>
      <PageHead title="Your profile">Your name and institution appear on the cover page of your reports.</PageHead>
      <ErrorNote message={error ?? resend.error} />
      {saved && <Alert kind="ok">Profile saved.</Alert>}
      {!user.is_email_verified && (
        <Alert kind="warn">
          Your e-mail address is not verified yet.{" "}
          {sent ? "A new link has been sent." : <Button small busy={resend.busy} onClick={() => resend.run(() => api.post("/auth/resend-verification")).then((ok) => ok && setSent(true))}>Send the verification link again</Button>}
        </Alert>
      )}
      <form className="panel stack" onSubmit={submit}>
        <Field label="E-mail address" hint="Used to sign in. It cannot be changed here."><input type="email" value={user.email} disabled /></Field>
        <Field label="Full name"><input type="text" required minLength={2} value={form.full_name} onChange={set("full_name")} /></Field>
        <Field label="Institution"><input type="text" value={form.institution} onChange={set("institution")} /></Field>
        <Field label="Department"><input type="text" value={form.department} onChange={set("department")} /></Field>
        <Field label="Level of study">
          <select value={form.academic_level} onChange={set("academic_level")}>
            <option value="">Not specified</option><option value="undergraduate">Undergraduate</option><option value="masters">Master's</option><option value="phd">PhD</option>
          </select>
        </Field>
        <p className="small muted">Account type: {user.roles.join(", ")}. Member since {fmtDate(user.created_at, false)}.</p>
        <div><Button type="submit" variant="primary" busy={busy}>Save profile</Button></div>
      </form>
    </main>
  );
}

interface Note { id: number; title: string; body: string | null; is_read: boolean; created_at: string }

export function Settings() {
  const { signOut } = useAuth();
  const sessions = useApi<{ sessions: { id: number; user_agent: string | null; ip_address: string | null; created_at: string }[] }>("/auth/sessions");
  const notes = useApi<{ notifications: Note[]; unread: number }>("/notifications");
  const ai = useApi<{ llm_configured: boolean; provider: string | null; model: string | null }>("/ai/status");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const { busy, error, run } = useAction();
  const change = (event: FormEvent) => {
    event.preventDefault();
    run(() => api.put<{ message: string }>("/users/me/password", { current_password: current, new_password: next })).then((r) => {
      if (r) { setMessage(r.message); setCurrent(""); setNext(""); }
    });
  };
  return (
    <main className="page stack" style={{ maxWidth: 820 }}>
      <PageHead title="Settings" />
      <ErrorNote message={error} />
      {message && <Alert kind="ok">{message}</Alert>}
      <section className="panel stack">
        <div className="row between"><h2 className="grow">Notifications</h2>
          {notes.data && notes.data.unread > 0 && <Button small onClick={() => run(() => api.post("/notifications/read")).then(notes.reload)}>Mark all as read</Button>}</div>
        {notes.data && notes.data.notifications.length === 0 && <p className="muted">No notifications.</p>}
        {notes.data?.notifications.map((n) => (
          <div key={n.id}><strong>{n.title}</strong> {!n.is_read && <Badge tone="info">new</Badge>} <span className="small muted">{fmtDate(n.created_at)}</span>{n.body && <div className="small">{n.body}</div>}</div>
        ))}
      </section>
      <form className="panel stack" onSubmit={change}>
        <h2>Change password</h2>
        <Field label="Current password"><input type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} /></Field>
        <Field label="New password" hint="At least 10 characters, with upper- and lower-case letters and a digit. Changing it signs you out on other devices.">
          <input type="password" autoComplete="new-password" required minLength={10} value={next} onChange={(e) => setNext(e.target.value)} />
        </Field>
        <div><Button type="submit" busy={busy}>Change password</Button></div>
      </form>
      <section className="panel stack">
        <h2>Where you are signed in</h2>
        {sessions.loading && <Loading />}
        <ul className="small" style={{ margin: 0, paddingLeft: "1.1rem" }}>
          {sessions.data?.sessions.map((s) => <li key={s.id}>{s.user_agent ?? "Unknown device"} ({s.ip_address ?? "unknown address"}), since {fmtDate(s.created_at)}</li>)}
        </ul>
        <div><Button onClick={() => run(() => api.post("/auth/logout?everywhere=true")).then(() => signOut())}>Sign out everywhere</Button></div>
      </section>
      <section className="panel">
        <h2>AI assistant</h2>
        {ai.data && (ai.data.llm_configured
          ? <p>A language model is connected ({ai.data.provider}, {ai.data.model}). Summaries of your project, never raw data rows or your account details, are sent to it when you use the assistant.</p>
          : <p>No language model is connected. The assistant uses the built-in rule engine, and nothing leaves this server.</p>)}
        <p className="small muted">The provider is chosen by the system administrator in the server configuration.</p>
      </section>
    </main>
  );
}

interface AdminSettings { settings: Record<string, unknown>; ai: { llm_configured: boolean; provider: string | null; model: string | null }; note: string }

export function Admin() {
  const [search, setSearch] = useState("");
  const users = useApi<{ users: User[]; total: number }>(`/admin/users?search=${encodeURIComponent(search)}`);
  const stats = useApi<Record<string, any>>("/admin/stats");
  const settings = useApi<AdminSettings>("/admin/settings");
  const activity = useApi<{ activity: HistoryEntry[] }>("/admin/activity?limit=40");
  const { error, run } = useAction();
  const update = (id: number, body: Record<string, unknown>) => run(() => api.put(`/admin/users/${id}`, body)).then(users.reload);
  const toggleRole = (u: User, role: string) => update(u.id, { roles: u.roles.includes(role) ? u.roles.filter((r) => r !== role) : [...u.roles, role] });
  const setSetting = (key: string, value: unknown) => run(() => api.put(`/admin/settings/${key}`, { value })).then(settings.reload);
  return (
    <main className="page stack">
      <PageHead title="Administration">Users, roles, AI settings and system activity.</PageHead>
      <ErrorNote message={error ?? users.error ?? stats.error} />
      {stats.data && (
        <dl className="grid cols-4" style={{ margin: 0 }}>
          {[["Users", stats.data.users], ["Active users", stats.data.active_users], ["Projects", stats.data.projects], ["Datasets", stats.data.datasets],
            ["Analysis runs", stats.data.analysis_runs], ["Failed runs", stats.data.analysis_runs_by_status?.FAILED ?? 0], ["Reports", stats.data.reports]].map(([label, value]) => (
            <div className="panel" key={label}><dt className="small muted">{label}</dt><dd style={{ margin: 0, fontSize: "1.5rem", fontFamily: "var(--serif)" }}>{value}</dd></div>
          ))}
        </dl>
      )}
      <section className="panel stack">
        <h2>AI settings</h2>
        {settings.data && (
          <>
            <p>{settings.data.ai.llm_configured ? `Active provider: ${settings.data.ai.provider} (${settings.data.ai.model}).` : "No language model is active; the rule engine answers."}</p>
            <label className="check">
              <input type="checkbox" checked={settings.data.settings["ai.enabled"] !== false} onChange={(e) => setSetting("ai.enabled", e.target.checked)} />
              <span>Allow the configured language model to be used. When off, the rule engine answers for everyone.</span>
            </label>
            <Field label="Provider" hint="Uses AI_MODEL, AI_API_KEY and AI_BASE_URL from the server environment.">
              <select style={{ maxWidth: 320 }} value={String(settings.data.settings["ai.provider_override"] ?? "")} onChange={(e) => setSetting("ai.provider_override", e.target.value || null)}>
                <option value="">As set in the server environment</option><option value="none">None (rule engine only)</option><option value="openai">OpenAI</option>
                <option value="gemini">Gemini</option><option value="anthropic">Anthropic</option><option value="local">Local model</option>
              </select>
            </Field>
            <p className="small muted">{settings.data.note}</p>
          </>
        )}
      </section>
      <section className="panel stack">
        <div className="row between"><h2 className="grow">Users {users.data ? `(${users.data.total})` : ""}</h2>
          <input type="search" aria-label="Search users" placeholder="Search by name or e-mail" style={{ maxWidth: 280 }} value={search} onChange={(e) => setSearch(e.target.value)} /></div>
        {users.loading && <Loading />}
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>Name</th><th>E-mail</th><th>Roles</th><th>Last sign-in</th><th>Status</th></tr></thead>
            <tbody>
              {users.data?.users.map((u) => (
                <tr key={u.id}>
                  <td>{u.full_name}</td><td>{u.email}{!u.is_email_verified && <span className="small muted"> (unverified)</span>}</td>
                  <td>{["researcher", "supervisor", "admin"].map((role) => (
                    <label key={role} className="small" style={{ marginRight: "0.7rem", whiteSpace: "nowrap" }}><input type="checkbox" checked={u.roles.includes(role)} onChange={() => toggleRole(u, role)} /> {role}</label>
                  ))}</td>
                  <td className="small">{fmtDate(u.last_login_at)}</td>
                  <td><Button small onClick={() => update(u.id, { is_active: !u.is_active })}>{u.is_active ? "Deactivate" : "Reactivate"}</Button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="panel">
        <h2>Recent system activity</h2>
        <ol className="timeline">
          {activity.data?.activity.map((a) => <li key={a.id}><strong>{actionLabel(a.action)}</strong> <span className="small muted">{fmtDate(a.created_at)}{a.user_name ? `, ${a.user_name}` : ""}</span></li>)}
        </ol>
      </section>
    </main>
  );
}
