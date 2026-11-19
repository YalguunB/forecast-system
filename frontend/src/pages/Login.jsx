import { useState } from "react";
import { api } from "../api.js";
import { Mark } from "../App.jsx";

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
      <section className="side">
        <span className="brand"><Mark />Таамаглал</span>
        <div>
          <h1>Ирэх саруудад хэдэн бараа хэрэгтэйг мэд</h1>
          <p>Борлуулалтын файлаа оруулахад систем шалгаж, хамгийн тохирох аргаар сар, улирал, жилийн эрэлтийг тооцно.</p>
        </div>
        <ol>
          <li><span>1</span>Файлаа оруулна</li>
          <li><span>2</span>Систем шалгана</li>
          <li><span>3</span>Таамаглана</li>
          <li><span>4</span>Тайлангаа харна</li>
        </ol>
      </section>
      <div className="form-side">
      <form onSubmit={submit}>
        <h2>Нэвтрэх</h2>
        <label htmlFor="u">Нэвтрэх нэр</label>
        <input id="u" autoComplete="username" value={u} onChange={(e) => setU(e.target.value)} required />
        <label htmlFor="p" style={{ marginTop: "0.75rem" }}>Нууц үг</label>
        <input id="p" type="password" autoComplete="current-password" value={p} onChange={(e) => setP(e.target.value)} required />
        <button type="submit" disabled={busy} style={{ marginTop: "1rem", width: "100%" }}>Нэвтрэх</button>
        {err && <div className="err" role="alert">{err}</div>}
      </form>
      </div>
    </div>
  );
}
