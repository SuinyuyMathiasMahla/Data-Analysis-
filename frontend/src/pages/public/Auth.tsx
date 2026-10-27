import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { Alert, Button, ErrorNote, Field, Icon } from "../../components/ui";
import { useAction } from "../../hooks/useApi";
import { api } from "../../services/api";
import { useAuth } from "../../services/auth";

const PASSWORD_HINT = "At least 10 characters, with upper- and lower-case letters and a digit.";

function AuthShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="auth-wrap">
      <aside className="auth-aside" aria-hidden="true">
        <h2>From raw data to a defensible thesis.</h2>
        <ul>
          <li><Icon name="trace" /> Every conclusion traceable to its evidence</li>
          <li><Icon name="shield" /> Assumptions checked before any test is trusted</li>
          <li><Icon name="report" /> Export PDF, Word, Excel or CSV reports</li>
        </ul>
      </aside>
      <main className="auth-main">{children}</main>
    </div>
  );
}

export function Login() {
  const { user, signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { busy, error, run } = useAction();
  const target = (location.state as { from?: string } | null)?.from ?? "/dashboard";

  if (user) return <Navigate to={target} replace />;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    run(() => signIn(email, password)).then((signedIn) => {
      if (signedIn) navigate(target, { replace: true });
    });
  };
  return (
    <AuthShell>
      <form className="panel auth-card stack" onSubmit={submit}>
        <h1>Sign in</h1>
        <ErrorNote message={error} />
        <Field label="E-mail address">
          <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password">
          <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Button type="submit" variant="primary" busy={busy}>Sign in</Button>
        <p className="small">
          <Link to="/forgot-password">Forgot your password?</Link> No account yet? <Link to="/register">Create one</Link>.
        </p>
      </form>
    </AuthShell>
  );
}

export function Register() {
  const navigate = useNavigate();
  const { signIn } = useAuth();
  const [form, setForm] = useState({ full_name: "", email: "", password: "", institution: "", department: "", academic_level: "" });
  const { busy, error, run } = useAction();
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    run(async () => {
      await api.post("/auth/register", {
        ...form,
        institution: form.institution || null,
        department: form.department || null,
        academic_level: form.academic_level || null,
      });
      await signIn(form.email, form.password);
      navigate("/dashboard", { replace: true });
    });
  };
  return (
    <AuthShell>
      <form className="panel auth-card stack" onSubmit={submit}>
        <h1>Create your account</h1>
        <p className="small muted">Your projects and data are private to your account unless you add a supervisor or collaborator.</p>
        <ErrorNote message={error} />
        <Field label="Full name">
          <input type="text" autoComplete="name" required minLength={2} value={form.full_name} onChange={set("full_name")} />
        </Field>
        <Field label="E-mail address">
          <input type="email" autoComplete="email" required value={form.email} onChange={set("email")} />
        </Field>
        <Field label="Password" hint={PASSWORD_HINT}>
          <input type="password" autoComplete="new-password" required minLength={10} value={form.password} onChange={set("password")} />
        </Field>
        <Field label="Institution (optional)">
          <input type="text" value={form.institution} onChange={set("institution")} />
        </Field>
        <Field label="Department (optional)">
          <input type="text" value={form.department} onChange={set("department")} />
        </Field>
        <Field label="Level of study (optional)">
          <select value={form.academic_level} onChange={set("academic_level")}>
            <option value="">Not specified</option>
            <option value="undergraduate">Undergraduate</option>
            <option value="masters">Master's</option>
            <option value="phd">PhD</option>
          </select>
        </Field>
        <Button type="submit" variant="primary" busy={busy}>Create account</Button>
        <p className="small">Already registered? <Link to="/login">Sign in</Link>.</p>
      </form>
    </AuthShell>
  );
}

export function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const { busy, error, run } = useAction();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    run(() => api.post<{ message: string }>("/auth/forgot-password", { email })).then((r) => r && setSent(r.message));
  };
  return (
    <AuthShell>
      <form className="panel auth-card stack" onSubmit={submit}>
        <h1>Reset your password</h1>
        <ErrorNote message={error} />
        {sent ? <Alert kind="ok">{sent}</Alert> : (
          <>
            <Field label="E-mail address" hint="We will send a link that is valid for one hour.">
              <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <Button type="submit" variant="primary" busy={busy}>Send reset link</Button>
          </>
        )}
        <p className="small"><Link to="/login">Back to sign in</Link></p>
      </form>
    </AuthShell>
  );
}

export function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const { busy, error, run } = useAction();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    run(() => api.post<{ message: string }>("/auth/reset-password", { token, new_password: password })).then((r) => r && setDone(r.message));
  };
  return (
    <AuthShell>
      <form className="panel auth-card stack" onSubmit={submit}>
        <h1>Choose a new password</h1>
        {!token && <Alert kind="error">This page needs the link from the password-reset e-mail.</Alert>}
        <ErrorNote message={error} />
        {done ? <Alert kind="ok">{done} <Link to="/login">Sign in</Link></Alert> : (
          <>
            <Field label="New password" hint={PASSWORD_HINT}>
              <input type="password" autoComplete="new-password" required minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
            <Button type="submit" variant="primary" busy={busy} disabled={!token}>Change password</Button>
          </>
        )}
      </form>
    </AuthShell>
  );
}

export function VerifyEmail() {
  const [params] = useSearchParams();
  const token = params.get("token");
  const [message, setMessage] = useState<string | null>(null);
  const { error, run } = useAction();
  useEffect(() => {
    if (token) run(() => api.post<{ message: string }>("/auth/verify-email", { token })).then((r) => r && setMessage(r.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);
  return (
    <AuthShell>
      <div className="panel auth-card stack">
        <h1>E-mail verification</h1>
        {!token && <Alert kind="error">This page needs the link from the verification e-mail.</Alert>}
        <ErrorNote message={error} />
        {message && <Alert kind="ok">{message}</Alert>}
        {token && !message && !error && <p className="muted">Verifying…</p>}
        <p className="small"><Link to="/dashboard">Go to your dashboard</Link></p>
      </div>
    </AuthShell>
  );
}
