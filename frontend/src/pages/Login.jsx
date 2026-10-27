import { useState } from "react";
import { api } from "../api.js";

export default function Login({ onLogin }) {
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try { await api.login(u, p); onLogin(); } catch (x) { setErr(x.message); } finally { setBusy(false); }
  };
  return (
    <div className="login">
      <form className="panel" onSubmit={submit}>
        <h1>Таамаглалын систем</h1>
        <label htmlFor="u">Нэвтрэх нэр</label>
        <input id="u" autoComplete="username" value={u} onChange={(e) => setU(e.target.value)} required />
        <label htmlFor="p" style={{ marginTop: "0.75rem" }}>Нууц үг</label>
        <input id="p" type="password" autoComplete="current-password" value={p} onChange={(e) => setP(e.target.value)} required />
        <button type="submit" disabled={busy} style={{ marginTop: "1rem", width: "100%" }}>Нэвтрэх</button>
        {err && <div className="err" role="alert">{err}</div>}
      </form>
    </div>
  );
}
