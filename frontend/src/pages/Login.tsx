import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth";

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr("");
    try { await login(email.trim(), pw); nav("/"); }
    catch (x) { setErr((x as Error).message); }
    finally { setBusy(false); }
  };

  return (
    <main className="mx-auto mt-24 max-w-sm px-4">
      <h1 className="text-2xl font-semibold">Blood Match</h1>
      <p className="mb-6 mt-1 text-sm text-ink/70">Hospitals find nearby donors. Donors answer requests.</p>
      <form onSubmit={submit} className="space-y-3">
        <label className="block text-sm">Email
          <input className="field mt-1" type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="block text-sm">Password
          <input className="field mt-1" type="password" required autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} />
        </label>
        {err && <p className="text-sm text-blood" role="alert">{err}</p>}
        <button className="btn btn-primary w-full" disabled={busy}>{busy ? "Logging in…" : "Log in"}</button>
      </form>
    </main>
  );
}
