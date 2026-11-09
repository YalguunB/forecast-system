import { useState } from "react";
import { api } from "../api.js";
import { go } from "../App.jsx";
import { ErrorNote, Help, Intro, JobProgress, Loading, StateLegend, useLoad } from "../components.jsx";
import { RULE_PLAIN, RULE_SYSTEM_DID, productLabel, seriesLabel, ACTIONS, SEVERITY, SEVERITY_NOTE, STATES, VERSION_STATUS, fmt, pct } from "../labels.js";

// UC-02: асуудал шийдэх, төлөв батлах; FR-D10 чанарын тайлан
export default function Quality({ params, user }) {
  const versions = useLoad(() => api.get("/dataset-versions"), []);
  const vid = params.version || versions.data?.[0]?.id;
  const steward = user.roles.includes("manager");
  const report = useLoad(() => (vid ? api.get(`/dataset-versions/${vid}/quality`) : Promise.resolve(null)), [vid]);
  const [sev, setSev] = useState(steward ? "blocking" : "");
  const [series, setSeries] = useState(null);
  const [job, setJob] = useState(null);
  const issues = useLoad(() => (vid && steward ? api.get(`/dataset-versions/${vid}/issues?limit=300${sev ? `&severity=${sev}` : ""}`) : Promise.resolve(null)), [vid, sev]);

  return (
    <>
      <h1>Өгөгдөл шалгах</h1>
      <p className="muted">Систем файлыг шалгаад юу олдсон, юу хийсэн, танаас юу хэрэгтэйг доор харуулна.</p>
      <div className="row" style={{ marginBottom: "1rem" }}>
        <div style={{ minWidth: 320 }}>
          <label htmlFor="v">Аль файл</label>
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
          {report.data.usable
            ? <div className="status-bar ok" role="status"><b>✓ Өгөгдөл бэлэн</b><p>Заавал засах алдаа алга. «Таамаглал гаргуулах» хэсэгт ашиглаж болно.{steward ? " Анхааруулгыг дараа ч шийдэж болно." : ""}</p></div>
            : <div className="status-bar bad" role="status"><b>{report.data.blocking_open} алдаа засагдах хүртэл</b><p>энэ файлаар таамаглал гаргахгүй. Бусад нь зөвхөн мэдээлэл — дараа ч шийдэж болно.</p></div>}
          <Counts r={report.data} />

          <h2>Юу олдсон, систем юу хийсэн бэ</h2>
          <div className="panel table-wrap">
            <table>
              <thead><tr><th>Ач холбогдол</th><th>Юу олдсон</th><th className="num">Тоо</th><th>Систем юу хийсэн</th><th>Таны шийдвэр</th></tr></thead>
              <tbody>{[...report.data.by_rule].sort((x, y) => ["blocking", "warning", "info"].indexOf(x.severity) - ["blocking", "warning", "info"].indexOf(y.severity)).map((r, i) => (
                <tr key={i}>
                  <td><span className={`badge ${r.severity === "blocking" ? "bad" : r.severity === "warning" ? "warn" : "info"}`}>{SEVERITY[r.severity]}</span></td>
                  <td title={r.rule_id}>{RULE_PLAIN[r.rule_id] || r.rule_id}</td>
                  <td className="num">{fmt(r.n, 0)}</td>
                  <td className="small">{RULE_SYSTEM_DID[r.rule_id] || "—"}</td>
                  <td>{r.action === "open"
                    ? (steward && r.severity !== "info" ? <button className="quiet mini" onClick={() => { setSev(r.severity); document.getElementById("issues")?.scrollIntoView({ behavior: "smooth" }); }}>Шийдэх</button> : <span className="muted small">{r.severity === "info" ? "Шаардлагагүй" : "Хүлээгдэж байна"}</span>)
                    : <span className="small">{ACTIONS[r.action]}</span>}</td>
                </tr>))}
              </tbody>
            </table>
          </div>

          {steward && (
            <>
              <h2 id="issues">Асуудлуудыг нэг бүрчлэн шийдэх</h2>
              <div className="tabs" role="tablist">
                {[["blocking", "Заавал засах"], ["warning", "Анхааруулга"], ["info", "Мэдээлэл"], ["", "Бүгд"]].map(([k, l]) => (
                  <button key={k} role="tab" aria-selected={sev === k} className={sev === k ? "on" : ""} onClick={() => setSev(k)}>{l}</button>
                ))}
              </div>
              <div className="panel table-wrap">
                <ErrorNote error={issues.error} />
                {issues.data && <BulkDecide vid={vid} items={issues.data.items} onDone={issues.reload} />}
                {issues.data && <IssueTable items={issues.data.items} total={issues.data.total} onChange={issues.reload} />}
                <div className="row" style={{ marginTop: "1rem", alignItems: "center" }}>
                  <button onClick={async () => setJob((await api.post(`/dataset-versions/${vid}/apply`)).job_id)}>
                    Засвар хэрэглэх
                  </button>
                  <span className="small muted">Таны шийдвэрүүдийг өгөгдөлд тусгана. Анхны файл өөрчлөгдөхгүй.</span>
                </div>
                {job && <JobProgress jobId={job} onDone={() => { report.reload(); issues.reload(); }} />}
              </div>
            </>
          )}

          <h2>Бараа бүрийн өдрүүд <Help k="day_state" /></h2>
          <p className="small muted">Мөр дээр дарж тухайн барааны өдөр бүрийн төлвийг календарь дээр харна. Асуудал ихтэй нь эхэнд.</p>
          <SeriesTable rows={report.data.by_series} onPick={setSeries} picked={series} />
          {series && <DayCalendar vid={vid} s={series} />}
        </>
      )}
    </>
  );
}

function BulkDecide({ vid, items, onDone }) {
  const rules = [...new Set(items.filter((i) => i.action === "open").map((i) => i.rule_id))];
  const [rule, setRule] = useState("");
  const [action, setAction] = useState("accepted");
  const [reason, setReason] = useState("");
  const [msg, setMsg] = useState(null);
  if (!rules.length) return null;
  const r = rule || rules[0];
  return (
    <div className="row" style={{ marginBottom: "1rem", alignItems: "flex-end" }}>
      <div><label htmlFor="br">Ижил төрлийн бүх асуудлыг нэг дор</label>
        <select id="br" value={r} onChange={(e) => setRule(e.target.value)}>{rules.map((x) => <option key={x} value={x}>{RULE_PLAIN[x] || x}</option>)}</select></div>
      <div><label htmlFor="ba">Шийдвэр</label>
        <select id="ba" value={action} onChange={(e) => setAction(e.target.value)}>
          <option value="accepted">Хүлээн зөвшөөрөх</option><option value="excluded">Мөрүүдийг хасах</option>
        </select></div>
      <div className="grow"><label htmlFor="bs">Шалтгаан</label>
        <input id="bs" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Жишээ: нэгж нэг төрөл тул хөрвүүлэлт шаардлагагүй" /></div>
      <button disabled={reason.trim().length < 3} onClick={async () => {
        const res = await api.post(`/dataset-versions/${vid}/issues/bulk`, { rule_id: r, action, reason });
        setMsg(`${res.updated} асуудал шийдэгдлээ. «Засвар хэрэглэх» дарна уу.`); setReason(""); onDone();
      }}>Бүгдийг шийдэх</button>
      {msg && <div className="small muted" style={{ flexBasis: "100%" }}>{msg}</div>}
    </div>
  );
}

function IssueTable({ items, total, onChange }) {
  const [edit, setEdit] = useState(null);
  if (!items.length) return <p className="muted">Энэ ангилалд асуудал алга.</p>;
  return (
    <>
      <p className="small muted">{total} асуудал{total > items.length ? `, эхний ${items.length}` : ""}</p>
      <table>
        <thead><tr><th>Юу</th><th>Бараа</th><th>Огноо / мөр</th><th>Тайлбар</th><th>Анхны утга</th><th>Шийдвэр</th></tr></thead>
        <tbody>{items.map((i) => (
          <tr key={i.id}>
            <td className="small" title={i.rule_id}>{RULE_PLAIN[i.rule_id] || i.rule_id}</td><td>{i.product_id ? seriesLabel(i) : "—"}</td>
            <td className="small">{i.day || ""}{i.source_row ? ` · мөр ${i.source_row}` : ""}</td>
            <td className="small clip" title={i.message}>{i.message}</td><td className="small clip" title={i.original_value || ""}>{i.original_value}</td>
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

// Ач холбогдлын тоо: заавал засах / анхааруулга / мэдээлэл (нээлттэй асуудлын тоо)
function Counts({ r }) {
  const n = (sev, open) => r.by_rule.filter((x) => x.severity === sev && (!open || x.action === "open")).reduce((a, x) => a + x.n, 0);
  const cards = [["blocking", "bad"], ["warning", "warn"], ["info", "info"]];
  return (
    <div className="counts">
      {cards.map(([k, tone]) => (
        <div className="count" key={k}><span className={`badge ${tone}`}>{SEVERITY[k]}</span><b>{fmt(n(k, k !== "info"), 0)}</b><span className="small">{SEVERITY_NOTE[k]}</span></div>
      ))}
      <div className="count"><span className="badge ok">Нийт</span><b>{fmt(r.version.row_count, 0)}</b><span className="small">мөр · {r.version.date_min} – {r.version.date_max} · {r.by_series.length} бараа</span></div>
    </div>
  );
}

function SeriesTable({ rows, onPick, picked }) {
  const [all, setAll] = useState(false);
  const sorted = [...rows].sort((a, b) => b.issues - a.issues || b.incomplete_share - a.incomplete_share);
  const shown = all ? sorted : sorted.slice(0, 10);
  return (
    <div className="panel table-wrap">
      <table>
        <thead><tr><th>Бараа</th><th>Салбар</th><th className="num">Хоног</th><th className="num">Зараагүй өдөр</th>
          <th className="num">Шалтгаан тодорхойгүй</th><th className="num">Асуудал</th><th></th></tr></thead>
        <tbody>{shown.map((s) => (
          <tr key={s.series_id} className="clickable" onClick={() => onPick(s)} style={picked?.series_id === s.series_id ? { background: "var(--sky-soft)" } : null}>
            <td>{productLabel(s)}{s.product_name ? <span className="muted small"> · {s.product_id}</span> : null}</td><td>{s.branch_id}</td><td className="num">{s.n_days}</td>
            <td className="num">{pct(s.zero_share)}</td><td className="num">{pct(s.incomplete_share)}</td>
            <td className="num">{s.issues}</td>
            <td><button className="quiet mini" onClick={(e) => { e.stopPropagation(); onPick(s); }}>Календарь</button></td>
          </tr>))}
        </tbody>
      </table>
      {rows.length > 10 && <button className="quiet" style={{ marginTop: 8 }} onClick={() => setAll(!all)}>{all ? "Цөөнийг харуулах" : `Бүх ${rows.length} барааг харах`}</button>}
    </div>
  );
}

const LIGHT = new Set(["open_no_sale", "unknown", "missing"]);
const DOW = ["Да", "Мя", "Лх", "Пү", "Ба", "Бя", "Ня"];

// Сарын календарь: нүд бүр өнгө + үсэгтэй (өнгө дангаараа утга тээхгүй)
function DayCalendar({ vid, s }) {
  const days = useLoad(() => api.get(`/dataset-versions/${vid}/series/${s.series_id}/days`), [s.series_id]);
  const months = [...new Set((days.data || []).map((d) => d.day.slice(0, 7)))];
  const [m, setM] = useState(null);
  const cur = m && months.includes(m) ? m : months[months.length - 1];
  const idx = months.indexOf(cur);
  const inMonth = (days.data || []).filter((d) => d.day.startsWith(cur || "x"));
  const lead = cur ? (new Date(`${cur}-01T00:00:00Z`).getUTCDay() + 6) % 7 : 0;
  const counts = {};
  for (const d of inMonth) counts[d.state] = (counts[d.state] || 0) + 1;
  return (
    <div className="panel">
      <h3 style={{ marginTop: 0 }}>{seriesLabel(s)} — өдөр бүрийн төлөв</h3>
      {!days.data ? <Loading /> : (
        <div className="row" style={{ alignItems: "flex-start", gap: "1.5rem" }}>
          <div style={{ flex: "1 1 360px" }}>
            <div className="row" style={{ alignItems: "center", gap: 8, marginBottom: 8 }}>
              <button className="quiet mini" disabled={idx <= 0} onClick={() => setM(months[idx - 1])} aria-label="Өмнөх сар">‹</button>
              <b style={{ minWidth: 110, textAlign: "center" }}>{cur?.replace("-", " оны ")}-р сар</b>
              <button className="quiet mini" disabled={idx >= months.length - 1} onClick={() => setM(months[idx + 1])} aria-label="Дараагийн сар">›</button>
            </div>
            <div className="cal" role="grid" aria-label="Өдрийн төлвийн календарь">
              {DOW.map((d) => <span key={d} className="dow">{d}</span>)}
              {Array.from({ length: lead }, (_, i) => <span key={`b${i}`} className="d blank" />)}
              {inMonth.map((d) => (
                <span key={d.day} role="gridcell" className={`d ${LIGHT.has(d.state) ? "light" : ""}`} style={{ background: STATES[d.state].color }}
                      title={`${d.day}: ${STATES[d.state].label}, зарагдсан ${fmt(d.sales_qty, 0)}`}>
                  {Number(d.day.slice(8))}<b>{STATES[d.state].code}</b>
                </span>))}
            </div>
          </div>
          <div style={{ flex: "1 1 260px" }} className="cal-legend">
            <p className="why" style={{ margin: "0 0 0.5rem" }}><b>Яагаад 0 гэж бичихгүй вэ?</b> Гүйлгээгүй өдөр «хүн аваагүй» гэсэн үг биш байж болно — дэлгүүр хаалттай, бараа дууссан, эсвэл бүртгэл дутуу байж магадгүй.</p>
            {Object.entries(STATES).map(([k, v]) => (
              <div key={k}><span className={`sw ${LIGHT.has(k) ? "light" : ""}`} style={{ background: v.color }} aria-hidden="true">{v.code}</span>
                <b>{v.label}</b>{counts[k] ? ` · ${counts[k]} өдөр` : ""} <span className="muted">— {v.note}</span></div>))}
          </div>
        </div>
      )}
    </div>
  );
}
