import { useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import { Alert, Button, Card, Field, Logo } from "@/components/ui";
import { BRAND } from "@/brand";
import { useAuth } from "@/lib/auth";
import { useDocumentTitle } from "@/lib/hooks";

function AuthCard({ title, sub, children, foot }: { title: string; sub?: ReactNode; children: ReactNode; foot?: ReactNode }) {
  return (
    <div className="auth">
      <div className="auth-card">
        <div style={{ display: "flex", justifyContent: "center", marginBottom: 24 }}>
          <Logo />
        </div>
        <Card>
          <div className="card-body">
            <h1>{title}</h1>
            {sub && <p className="muted" style={{ marginTop: 6 }}>{sub}</p>}
            <div style={{ marginTop: 24 }}>{children}</div>
          </div>
        </Card>
        {foot && <p className="small muted" style={{ textAlign: "center", marginTop: 20 }}>{foot}</p>}
      </div>
    </div>
  );
}

function safeNext(next: string | null): string {
  return next && next.startsWith("/app") ? next : "/app";
}

export function Login() {
  useDocumentTitle(`Log in — ${BRAND.name}`);
  const { login, me } = useAuth();
  const [params] = useSearchParams();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (me) return <Navigate to={safeNext(params.get("next"))} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      nav(safeNext(params.get("next")), { replace: true });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <AuthCard title="Welcome back" sub="Log in to manage and test your agents." foot={<>No account yet? <Link to="/register" className="strong">Create one</Link></>}>
      <form className="form-grid" onSubmit={submit}>
        <Field label="Email" htmlFor="l-email">
          <input id="l-email" type="email" className="input" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
        </Field>
        <Field label={<span className="row-between" style={{ width: "100%" }}>Password <Link to="/forgot-password" className="small" style={{ fontWeight: 400, color: "var(--accent-text)" }}>Forgot password?</Link></span>} htmlFor="l-pass">
          <input id="l-pass" type="password" className="input" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        {error && <Alert tone="critical">{error}</Alert>}
        <Button variant="primary" type="submit" loading={busy} block size="lg">
          Log in
        </Button>
      </form>
    </AuthCard>
  );
}

export function Register() {
  useDocumentTitle(`Create an account — ${BRAND.name}`);
  const { register, me } = useAuth();
  const nav = useNavigate();
  const [form, setForm] = useState({ name: "", business_name: "", email: "", password: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (me) return <Navigate to="/app" replace />;
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (form.password.length < 8) return setError("Password must be at least 8 characters.");
    setBusy(true);
    setError(null);
    try {
      await register(form);
      nav("/app/agent?new=1", { replace: true });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <AuthCard title="Create your workspace" sub="Your workspace keeps your agents, knowledge and conversations private." foot={<>Already have an account? <Link to="/login" className="strong">Log in</Link></>}>
      <form className="form-grid" onSubmit={submit}>
        <Field label="Your name" htmlFor="r-name">
          <input id="r-name" className="input" required maxLength={80} autoComplete="name" value={form.name} onChange={set("name")} autoFocus />
        </Field>
        <Field label="Business name" htmlFor="r-biz">
          <input id="r-biz" className="input" required maxLength={120} autoComplete="organization" value={form.business_name} onChange={set("business_name")} />
        </Field>
        <Field label="Work email" htmlFor="r-email">
          <input id="r-email" type="email" className="input" required autoComplete="email" value={form.email} onChange={set("email")} />
        </Field>
        <Field label="Password" htmlFor="r-pass" hint="At least 8 characters.">
          <input id="r-pass" type="password" className="input" required minLength={8} autoComplete="new-password" value={form.password} onChange={set("password")} />
        </Field>
        {error && <Alert tone="critical">{error}</Alert>}
        <Button variant="primary" type="submit" loading={busy} block size="lg">
          Create account
        </Button>
      </form>
    </AuthCard>
  );
}

export function ForgotPassword() {
  useDocumentTitle(`Reset password — ${BRAND.name}`);
  const [email, setEmail] = useState("");
  const [result, setResult] = useState<{ email_delivery: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setResult(await api.post<{ email_delivery: boolean }>("/auth/forgot-password", { email }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <AuthCard title="Reset your password" sub="Enter the email of your account." foot={<Link to="/login" className="strong">Back to log in</Link>}>
      {result ? (
        <div className="stack gap-3">
          <Alert tone="good">If an account exists for {email}, a reset link has been issued. It is valid for one hour.</Alert>
          {!result.email_delivery && (
            <Alert tone="warning">
              Email delivery is not configured on this server yet, so the link cannot be sent by email. Ask the platform administrator to reset your access.
            </Alert>
          )}
        </div>
      ) : (
        <form className="form-grid" onSubmit={submit}>
          <Field label="Email" htmlFor="f-email">
            <input id="f-email" type="email" className="input" required value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
          </Field>
          {error && <Alert tone="critical">{error}</Alert>}
          <Button variant="primary" type="submit" loading={busy} block size="lg">
            Send reset link
          </Button>
        </form>
      )}
    </AuthCard>
  );
}

export function ResetPassword() {
  useDocumentTitle(`Choose a new password — ${BRAND.name}`);
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/reset-password", { token, password });
      setDone(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <AuthCard title="Choose a new password" foot={<Link to="/login" className="strong">Back to log in</Link>}>
      {!token ? (
        <Alert tone="critical">This link is incomplete. Request a new reset link.</Alert>
      ) : done ? (
        <div className="stack gap-3">
          <Alert tone="good">Your password has been changed. All other sessions were signed out.</Alert>
          <Link to="/login" className="btn btn-primary btn-block">
            Log in
          </Link>
        </div>
      ) : (
        <form className="form-grid" onSubmit={submit}>
          <Field label="New password" htmlFor="n-pass" hint="At least 8 characters.">
            <input id="n-pass" type="password" className="input" required minLength={8} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus />
          </Field>
          {error && <Alert tone="critical">{error}</Alert>}
          <Button variant="primary" type="submit" loading={busy} block size="lg">
            Save password
          </Button>
        </form>
      )}
    </AuthCard>
  );
}
