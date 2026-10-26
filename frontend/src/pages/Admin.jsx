import { useState } from "react";
import { api } from "../api.js";
import { ErrorNote, useLoad } from "../components.jsx";
import { ROLE_LABELS, VERSION_STATUS } from "../labels.js";

// UC-09: хэрэглэгч, архив, аудит
export default function Admin() {
  const [tab, setTab] = useState("users");
  return (
    <>
      <h1>Удирдлага</h1>
      <div className="tabs" role="tablist">
        {[["users", "Хэрэглэгч"], ["archive", "Архив"], ["audit", "Аудит"]].map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>
      {tab === "users" && <Users />}
      {tab === "archive" && <Archive />}
      {tab === "audit" && <Audit />}
    </>
  );
}

function Users() {
  const users = useLoad(() => api.get("/users"), []);
  const [f, setF] = useState({ username: "", full_name: "", password: "", roles: [] });
  const [err, setErr] = useState(null);
  const toggle = (u, r) => api.patch(`/users/${u.id}`, { roles: u.roles.includes(r) ? u.roles.filter((x) => x !== r) : [...u.roles, r] }).then(users.reload).catch(setErr);
  return (
    <>
      <div className="panel table-wrap">
        <ErrorNote error={err} />
        <table>
          <thead><tr><th>Нэвтрэх нэр</th><th>Нэр</th>{Object.values(ROLE_LABELS).map((l) => <th key={l}>{l}</th>)}<th>Идэвхтэй</th></tr></thead>
          <tbody>{(users.data || []).map((u) => (
            <tr key={u.id}><td>{u.username}</td><td>{u.full_name}</td>
              {Object.keys(ROLE_LABELS).map((r) => <td key={r}><input type="checkbox" aria-label={`${u.username}: ${ROLE_LABELS[r]}`} checked={u.roles.includes(r)} onChange={() => toggle(u, r)} /></td>)}
              <td><input type="checkbox" aria-label={`${u.username} идэвхтэй`} checked={u.is_active} onChange={() => api.patch(`/users/${u.id}`, { is_active: !u.is_active }).then(users.reload)} /></td>
            </tr>))}
          </tbody>
        </table>
      </div>
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Шинэ хэрэглэгч</h3>
        <div className="row">
          <div className="grow"><label htmlFor="un">Нэвтрэх нэр</label><input id="un" value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} /></div>
          <div className="grow"><label htmlFor="fn">Нэр</label><input id="fn" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></div>
          <div className="grow"><label htmlFor="pw">Нууц үг (8+ тэмдэгт)</label><input id="pw" type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></div>
        </div>
        <div style={{ margin: "0.75rem 0" }}>
          {Object.entries(ROLE_LABELS).map(([r, l]) => (
            <label key={r} style={{ display: "inline-flex", gap: 6, marginRight: 14 }}>
              <input type="checkbox" checked={f.roles.includes(r)} onChange={(e) => setF({ ...f, roles: e.target.checked ? [...f.roles, r] : f.roles.filter((x) => x !== r) })} />{l}
            </label>
          ))}
        </div>
        <button disabled={!f.username || f.password.length < 8 || !f.roles.length} onClick={() => api.post("/users", f).then(() => { setF({ username: "", full_name: "", password: "", roles: [] }); users.reload(); }).catch(setErr)}>Хэрэглэгч нэмэх</button>
      </div>
    </>
  );
}

function Archive() {
  const versions = useLoad(() => api.get("/dataset-versions"), []);
  return (
    <div className="panel table-wrap">
      <p className="small muted">Архивласан хувилбар устахгүй, шинэ туршилтад сонгогдохгүй болно.</p>
      <table>
        <thead><tr><th>Өгөгдөл</th><th>Төлөв</th><th>Хугацаа</th><th className="num">Мөр</th><th></th></tr></thead>
        <tbody>{(versions.data || []).map((v) => (
          <tr key={v.id}><td>{v.dataset} v{v.version_no}</td><td>{VERSION_STATUS[v.status]}</td><td>{v.date_min} – {v.date_max}</td><td className="num">{v.row_count}</td>
            <td>{v.archived_at ? <span className="badge">Архивласан</span> : <button className="quiet" onClick={() => api.post(`/dataset-versions/${v.id}/archive`).then(versions.reload)}>Архивлах</button>}</td></tr>))}
        </tbody>
      </table>
    </div>
  );
}

function Audit() {
  const log = useLoad(() => api.get("/audit?limit=300"), []);
  return (
    <div className="panel table-wrap">
      <table>
        <thead><tr><th>Хэзээ</th><th>Хэрэглэгч</th><th>Үйлдэл</th><th>Объект</th><th>Дэлгэрэнгүй</th></tr></thead>
        <tbody>{(log.data || []).map((a) => (
          <tr key={a.id}><td className="small">{new Date(a.at).toLocaleString("mn-MN")}</td><td>{a.username || "систем"}</td><td>{a.action}</td>
            <td>{a.object_type} {a.object_id}</td><td className="small"><code>{JSON.stringify(a.detail)}</code></td></tr>))}
        </tbody>
      </table>
    </div>
  );
}
