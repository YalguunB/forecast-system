import { useState } from "react";
import { api } from "../api.js";
import { go } from "../App.jsx";
import { ErrorNote, JobProgress, Loading, StateLegend, useLoad } from "../components.jsx";
import { ACTIONS, SEVERITY, STATES, VERSION_STATUS, fmt, pct } from "../labels.js";

// UC-02: асуудал шийдэх, төлөв батлах; FR-D10 чанарын тайлан
export default function Quality({ params, user }) {
  const versions = useLoad(() => api.get("/dataset-versions"), []);
  const vid = params.version || versions.data?.[0]?.id;
  const steward = user.roles.includes("data_steward");
  const report = useLoad(() => (vid ? api.get(`/dataset-versions/${vid}/quality`) : Promise.resolve(null)), [vid]);
  const [sev, setSev] = useState(steward ? "blocking" : "");
  const [series, setSeries] = useState(null);
  const [job, setJob] = useState(null);
  const issues = useLoad(() => (vid && steward ? api.get(`/dataset-versions/${vid}/issues?limit=300${sev ? `&severity=${sev}` : ""}`) : Promise.resolve(null)), [vid, sev]);

  return (
    <>
      <h1>Чанарын шалгалт</h1>
      <div className="row" style={{ marginBottom: "1rem" }}>
        <div style={{ minWidth: 320 }}>
          <label htmlFor="v">Өгөгдлийн хувилбар</label>
          <select id="v" value={vid || ""} onChange={(e) => go("quality", { version: e.target.value })}>
            {(versions.data || []).map((v) => (
              <option key={v.id} value={v.id}>{v.dataset} v{v.version_no} — {VERSION_STATUS[v.status]}{v.archived_at ? " (архив)" : ""}</option>
            ))}
          </select>
        </div>
      </div>
      <ErrorNote error={report.error} />
      {report.loading ? <Loading /> : report.data && (
        <>
          <div className="panel">
            <div className="stat"><b>{fmt(report.data.version.row_count, 0)}</b><span>мөр</span></div>
            <div className="stat"><b>{report.data.version.date_min} – {report.data.version.date_max}</b><span>хамрах хугацаа</span></div>
            <div className="stat"><b>{report.data.by_series.length}</b><span>цуваа</span></div>
            <div className="stat"><b>{report.data.blocking_open}</b><span>шийдэгдээгүй блоклох асуудал</span></div>
            {report.data.usable
              ? <div className="notice">Хувилбар «шалгагдсан» — туршилт, таамаглалд ашиглаж болно.</div>
              : <div className="notice bad">Блоклох асуудал шийдэгдэх хүртэл энэ хувилбар таамаглалд ашиглагдахгүй.</div>}
          </div>

          <h2>Дүрмээр</h2>
          <div className="panel table-wrap">
            <table>
              <thead><tr><th>Дүрэм</th><th>Ноцтой байдал</th><th>Шийдвэр</th><th className="num">Тоо</th></tr></thead>
              <tbody>{report.data.by_rule.map((r, i) => (
                <tr key={i}><td>{r.rule_id}</td>
                  <td><span className={`badge ${r.severity === "blocking" ? "bad" : r.severity === "warning" ? "warn" : "info"}`}>{SEVERITY[r.severity]}</span></td>
                  <td>{ACTIONS[r.action]}</td><td className="num">{r.n}</td></tr>))}
              </tbody>
            </table>
          </div>

          {steward && (
            <>
              <h2>Асуудлууд</h2>
              <div className="tabs" role="tablist">
                {[["blocking", "Блоклох"], ["warning", "Анхааруулга"], ["info", "Мэдээлэл"], ["", "Бүгд"]].map(([k, l]) => (
                  <button key={k} role="tab" aria-selected={sev === k} className={sev === k ? "on" : ""} onClick={() => setSev(k)}>{l}</button>
                ))}
              </div>
              <div className="panel table-wrap">
                <ErrorNote error={issues.error} />
                {issues.data && <IssueTable items={issues.data.items} total={issues.data.total} onChange={issues.reload} />}
                <div className="row" style={{ marginTop: "1rem", alignItems: "center" }}>
                  <button onClick={async () => setJob((await api.post(`/dataset-versions/${vid}/apply`)).job_id)}>
                    Шийдвэрийг хэрэглэж төлөв батлах
                  </button>
                  <span className="small muted">Хассан, залруулсан мөрийг тооцож өдрийн цувааг дахин байгуулна. Анхны мөр өөрчлөгдөхгүй.</span>
                </div>
                {job && <JobProgress jobId={job} onDone={() => { report.reload(); issues.reload(); }} />}
              </div>
            </>
          )}

          <h2>Бүтээгдэхүүнээр</h2>
          <div className="panel table-wrap">
            <table>
              <thead><tr><th>Бүтээгдэхүүн</th><th>Салбар</th><th className="num">Хоног</th><th className="num">Тэгийн хувь</th>
                <th className="num">Дутуу/тодорхойгүй</th><th>Өдрийн төлөв</th><th className="num">Асуудал</th></tr></thead>
              <tbody>{report.data.by_series.map((s) => (
                <tr key={s.series_id} className="clickable" onClick={() => setSeries(s)} tabIndex={0}
                    onKeyDown={(e) => e.key === "Enter" && setSeries(s)}>
                  <td>{s.product_id}</td><td>{s.branch_id}</td><td className="num">{s.n_days}</td>
                  <td className="num">{pct(s.zero_share)}</td><td className="num">{pct(s.incomplete_share)}</td>
                  <td className="small">{Object.entries(s.states).map(([k, n]) => `${STATES[k].label} ${n}`).join(", ")}</td>
                  <td className="num">{s.issues}</td>
                </tr>))}
              </tbody>
            </table>
          </div>
          {series && <DayCalendar vid={vid} s={series} />}
        </>
      )}
    </>
  );
}

function IssueTable({ items, total, onChange }) {
  const [edit, setEdit] = useState(null);
  if (!items.length) return <p className="muted">Энэ ангилалд асуудал алга.</p>;
  return (
    <>
      <p className="small muted">{total} асуудал{total > items.length ? `, эхний ${items.length}` : ""}</p>
      <table>
        <thead><tr><th>Дүрэм</th><th>Цуваа</th><th>Огноо / мөр</th><th>Тайлбар</th><th>Анхны утга</th><th>Шийдвэр</th></tr></thead>
        <tbody>{items.map((i) => (
          <tr key={i.id}>
            <td>{i.rule_id}</td><td>{i.product_id ? `${i.product_id} / ${i.branch_id}` : "—"}</td>
            <td className="small">{i.day || ""}{i.source_row ? ` · мөр ${i.source_row}` : ""}</td>
            <td className="small">{i.message}</td><td className="small">{i.original_value}</td>
            <td>{i.action === "open"
              ? (edit === i.id ? <Decide issue={i} onDone={() => { setEdit(null); onChange(); }} />
                : <button className="quiet" onClick={() => setEdit(i.id)}>Шийдэх</button>)
              : <span className="small">{ACTIONS[i.action]}: {i.reason} ({i.resolved_by_name}){i.corrected_value ? ` → ${i.corrected_value}` : ""}</span>}
            </td>
          </tr>))}
        </tbody>
      </table>
    </>
  );
}

function Decide({ issue, onDone }) {
  const [action, setAction] = useState(issue.source_row ? "excluded" : "accepted");
  const [reason, setReason] = useState("");
  const [value, setValue] = useState("");
  const [err, setErr] = useState(null);
  const correctable = ["DQ-01", "DQ-02"].includes(issue.rule_id) && issue.source_row;
  return (
    <div style={{ minWidth: 240 }}>
      <select value={action} onChange={(e) => setAction(e.target.value)} aria-label="Шийдвэр">
        <option value="accepted">Хүлээн зөвшөөрөх</option>
        {issue.source_row && <option value="excluded">Мөрийг хасах</option>}
        {correctable && <option value="corrected">Утга залруулах</option>}
      </select>
      {action === "corrected" && <input placeholder={issue.rule_id === "DQ-01" ? "Зөв хэмжээ" : "YYYY-MM-DD"} value={value} onChange={(e) => setValue(e.target.value)} style={{ marginTop: 4 }} />}
      <input placeholder="Шалтгаан (заавал)" value={reason} onChange={(e) => setReason(e.target.value)} style={{ marginTop: 4 }} />
      <button style={{ marginTop: 4 }} disabled={reason.trim().length < 3} onClick={async () => {
        try { await api.patch(`/issues/${issue.id}`, { action, reason, corrected_value: action === "corrected" ? value : null }); onDone(); }
        catch (x) { setErr(x); }
      }}>Хадгалах</button>
      <ErrorNote error={err} />
    </div>
  );
}

function DayCalendar({ vid, s }) {
  const days = useLoad(() => api.get(`/dataset-versions/${vid}/series/${s.series_id}/days`), [s.series_id]);
  return (
    <div className="panel">
      <h3>{s.product_id} / {s.branch_id} — өдрийн төлөв</h3>
      <p className="small muted">Нүд бүр нэг өдөр. Гүйлгээгүй өдрийг 0 гэж үзэлгүй, шалтгаанаар нь ангилсан.</p>
      {days.data && (
        <div className="day-grid" role="img" aria-label="Өдрийн төлвийн календар">
          {days.data.map((d) => <span key={d.day} title={`${d.day}: ${STATES[d.state].label}, ${d.sales_qty}`} style={{ background: STATES[d.state].color }} />)}
        </div>
      )}
      <StateLegend />
    </div>
  );
}
