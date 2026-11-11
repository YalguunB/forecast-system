import { useState } from "react";
import { api } from "../api.js";
import { ErrorNote, useLoad } from "../components.jsx";
import { AUDIT_ACTIONS, OBJECT_LABELS, PERMISSION_ROWS, ROLE_DESC, ROLE_LABELS, VERSION_STATUS, branchText } from "../labels.js";

// UC-09: хэрэглэгч, архив, аудит
export default function Admin() {
  const [tab, setTab] = useState("users");
  return (
    <>
      <h1>Хэрэглэгч ба эрх</h1>
      <div className="tabs" role="tablist">
        {[["users", "Хэрэглэгч"], ["archive", "Архив"], ["audit", "Бүртгэл"]].map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>
      {tab === "users" && <Users />}
      {tab === "archive" && <Archive />}
      {tab === "audit" && <Audit />}
    </>
  );
}

function BranchPicker({ value, onChange, branches, id }) {
  const all = value.includes("*");
  // Менежер салбаргүй үлдэхгүй: сүүлийн салбарыг унтраавал «Бүх салбар» руу буцна
  const toggle = (b) => {
    const next = value.includes(b) ? value.filter((x) => x !== b) : [...value.filter((x) => x !== "*"), b];
    onChange(next.length ? next : ["*"]);
  };
  return (
    <div className="chips" id={id}>
      <button type="button" className={`chip ${all ? "on" : ""}`} aria-pressed={all} onClick={() => { if (!all) onChange(["*"]); }}>Бүх салбар</button>
      {branches.map((b) => (
        <button type="button" key={b} className={`chip ${!all && value.includes(b) ? "on" : ""}`} aria-pressed={!all && value.includes(b)}
                disabled={all} onClick={() => toggle(b)}>{b}</button>
      ))}
      {!branches.length && <span className="small muted">Салбар хараахан алга.</span>}
    </div>
  );
}

function Users() {
  const users = useLoad(() => api.get("/users"), []);
  const branches = useLoad(() => api.get("/branches"), []);
  const empty = { username: "", full_name: "", password: "", role: "manager", branches: ["*"] };
  const [f, setF] = useState(empty);
  const [editing, setEditing] = useState(null);
  const [err, setErr] = useState(null);
  const [msg, setMsg] = useState(null);
  const save = (u, patch) => api.patch(`/users/${u.id}`, patch).then(() => { users.reload(); setMsg(`«${u.username}» шинэчлэгдлээ.`); }).catch(setErr);
  return (
    <>
      <Permissions />
      <ErrorNote error={err} />
      {msg && <div className="notice">{msg}</div>}
      <div className="panel table-wrap">
        <table>
          <thead><tr><th>Нэвтрэх нэр</th><th>Нэр</th><th>Үүрэг</th><th>Хариуцах салбар</th><th>Идэвхтэй</th></tr></thead>
          <tbody>{(users.data || []).map((u) => {
            const role = u.roles[0] || "";
            return (
              <tr key={u.id}>
                <td>{u.username}</td><td>{u.full_name}</td>
                <td>
                  <select aria-label={`${u.username}: үүрэг`} value={role}
                          onChange={(e) => save(u, { roles: [e.target.value], ...(e.target.value === "manager" && !u.branches?.length ? { branches: ["*"] } : {}) })}>
                    {!role && <option value="">—</option>}
                    {Object.entries(ROLE_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                  </select>
                </td>
                <td>
                  {role !== "manager" ? <span className="muted small">{role === "executive" ? "Бүх салбар (харах)" : "—"}</span>
                    : editing === u.id
                      ? <BranchPicker value={u.branches || []} branches={branches.data || []} onChange={(b) => save(u, { branches: b })} />
                      : <button className="quiet" onClick={() => setEditing(u.id)}>{branchText(u.branches)} · өөрчлөх</button>}
                </td>
                <td><input type="checkbox" aria-label={`${u.username} идэвхтэй`} checked={u.is_active} onChange={() => save(u, { is_active: !u.is_active })} /></td>
              </tr>);
          })}
          </tbody>
        </table>
      </div>
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Шинэ хэрэглэгч</h3>
        <div className="row">
          <div className="grow"><label htmlFor="un">Нэвтрэх нэр (латинаар)</label><input id="un" value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} /></div>
          <div className="grow"><label htmlFor="fn">Овог нэр</label><input id="fn" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></div>
          <div className="grow"><label htmlFor="pw">Нууц үг (8-аас дээш тэмдэгт)</label><input id="pw" type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></div>
        </div>
        <label style={{ marginTop: "0.75rem" }}>Үүрэг</label>
        <div className="chips">
          {Object.entries(ROLE_LABELS).map(([k, l]) => (
            <button type="button" key={k} className={`chip ${f.role === k ? "on" : ""}`} aria-pressed={f.role === k} onClick={() => setF({ ...f, role: k })}>{l}</button>
          ))}
        </div>
        <p className="small muted" style={{ margin: "0.3rem 0 0" }}>{ROLE_DESC[f.role]}</p>
        {f.role === "manager" && (
          <>
            <label style={{ marginTop: "0.75rem" }}>Хариуцах салбар</label>
            <BranchPicker value={f.branches} branches={branches.data || []} onChange={(b) => setF({ ...f, branches: b })} />
          </>
        )}
        <button style={{ marginTop: "1rem" }} disabled={!f.username || f.password.length < 8 || (f.role === "manager" && !f.branches.length)}
          onClick={() => api.post("/users", { username: f.username, full_name: f.full_name, password: f.password, roles: [f.role],
                                              branches: f.role === "manager" ? f.branches : [] })
            .then(() => { setMsg(`«${f.username}» нэмэгдлээ.`); setF(empty); users.reload(); }).catch(setErr)}>Нэмэх</button>
      </div>
    </>
  );
}

function Archive() {
  const versions = useLoad(() => api.get("/dataset-versions"), []);
  return (
    <div className="panel table-wrap">
      <p className="small muted">Архивласан файл устахгүй, шинэ таамаглалд ашиглагдахгүй.</p>
      <table>
        <thead><tr><th>Файл</th><th>Төлөв</th><th>Хугацаа</th><th className="num">Мөр</th><th></th></tr></thead>
        <tbody>{(versions.data || []).map((v) => (
          <tr key={v.id}><td>{v.dataset} ({v.version_no})</td><td>{VERSION_STATUS[v.status]}</td><td>{v.date_min} – {v.date_max}</td><td className="num">{v.row_count}</td>
            <td>{v.archived_at ? <span className="badge">Архивласан</span> : <button className="quiet" onClick={() => api.post(`/dataset-versions/${v.id}/archive`).then(versions.reload)}>Архивлах</button>}</td></tr>))}
        </tbody>
      </table>
    </div>
  );
}

// Үүрэг бүр юу хийж болох вэ (backend-ийн эрхийн тохиргоотой ижил)
function Permissions() {
  const roles = Object.keys(ROLE_LABELS);
  return (
    <div className="panel table-wrap">
      <h3 style={{ marginTop: 0 }}>Үүрэг бүр юу хийж болох вэ?</h3>
      <table>
        <thead><tr><th>Үйлдэл</th>{roles.map((k) => <th key={k} style={{ textAlign: "center" }}>{ROLE_LABELS[k]}</th>)}</tr></thead>
        <tbody>{PERMISSION_ROWS.map(([what, who]) => (
          <tr key={what}><td>{what}</td>{roles.map((k) => <td key={k} style={{ textAlign: "center" }}>{who.includes(k) ? <span className="yes">Тийм</span> : <span className="no">—</span>}</td>)}</tr>))}
        </tbody>
      </table>
    </div>
  );
}

const detailText = (d) => {
  if (!d || !Object.keys(d).length) return "";
  const parts = [];
  if (d.name) parts.push(`«${d.name}»`);
  if (d.reason) parts.push(`шалтгаан: ${d.reason}`);
  if (d.roles) parts.push(`үүрэг: ${d.roles.map((r) => ROLE_LABELS[r] || r).join(", ")}`);
  if (d.n !== undefined) parts.push(`${d.n} бараа`);
  if (d.updated !== undefined) parts.push(`${d.updated} асуудал`);
  if (d.format) parts.push(String(d.format).toUpperCase());
  return parts.join(" · ");
};

function Audit() {
  const log = useLoad(() => api.get("/audit?limit=300"), []);
  return (
    <div className="panel table-wrap">
      <p className="small muted" style={{ marginTop: 0 }}>Бүртгэлийг засах, устгах боломжгүй.</p>
      <table>
        <thead><tr><th>Хэзээ</th><th>Хэн</th><th>Юу хийсэн</th><th>Юуг</th><th>Дэлгэрэнгүй</th></tr></thead>
        <tbody>{(log.data || []).map((a) => (
          <tr key={a.id}><td className="small">{new Date(a.at).toLocaleString("mn-MN")}</td><td>{a.username || "систем"}</td>
            <td title={a.action}>{AUDIT_ACTIONS[a.action] || a.action}</td>
            <td>{OBJECT_LABELS[a.object_type] || a.object_type} #{a.object_id}</td>
            <td className="small">{detailText(a.detail)}
              {a.detail && Object.keys(a.detail).length > 0 && <details><summary className="facts-tech">дэлгэрэнгүй</summary><code className="facts-tech">{JSON.stringify(a.detail)}</code></details>}</td></tr>))}
        </tbody>
      </table>
    </div>
  );
}
