import { api } from "../api.js";
import { go } from "../App.jsx";
import { ErrorNote, JobProgress, Loading, useLoad } from "../components.jsx";
import { EXP_STEPS, JOB_STATUS, JOB_TYPE, ROLE_DESC, ROLE_LABELS, accuracyLevel, branchText, fmt, monthLabel, pct, seriesLabel } from "../labels.js";
import { biasText, trackGrade } from "./Tracking.jsx";

export default function Dashboard({ user }) {
  const can = (...r) => r.some((x) => user.roles.includes(x));
  const viewer = can("executive", "manager");
  const isManager = can("manager");
  const versions = useLoad(() => api.get("/dataset-versions"), []);
  const exps = useLoad(() => (viewer ? api.get("/experiments") : Promise.resolve([])), []);
  const jobs = useLoad(() => api.get("/jobs?limit=8"), []);

  if (user.roles.length === 1 && user.roles[0] === "admin") return <AdminHome user={user} />;
  if (versions.loading || exps.loading) return <Loading />;

  const vs = (versions.data || []).filter((v) => !v.archived_at);
  const es = (exps.data || []).filter((e) => !e.archived_at);
  const hasData = vs.length > 0;
  const cleanData = vs.some((v) => v.status === "validated");
  const failed = vs.find((v) => v.status === "failed");
  const inProgress = es.find((e) => e.status !== "test_done");
  const ready = es.filter((e) => e.status === "test_done");
  const running = (jobs.data || []).filter((j) => ["queued", "running"].includes(j.status));

  const steps = [
    { title: "Өгөгдөл оруулах", done: hasData,
      text: hasData ? `${vs.length} файл оруулсан.` : "Борлуулалтын CSV эсвэл Excel файлаа оруулна.",
      action: isManager && { label: hasData ? "Шинэ файл оруулах" : "Файл оруулах", to: ["import"] } },
    { title: "Өгөгдөл шалгах", done: cleanData,
      text: failed ? "Нэг файлд засах алдаа байна." : cleanData ? "Өгөгдөл бэлэн." : "Систем автоматаар шалгана.",
      action: hasData && { label: failed ? "Алдааг засах" : "Шалгалтыг харах", to: ["quality", failed ? { version: failed.id } : {}] } },
    { title: "Таамаглал бэлтгэх", done: ready.length > 0,
      text: inProgress ? `${inProgress.name}: ${Object.fromEntries(EXP_STEPS)[inProgress.status].toLowerCase()}.` : ready.length ? `${ready.length} таамаглал бэлэн.` : "Систем хамгийн тохирох аргыг сонгоно.",
      action: cleanData && isManager && { label: inProgress ? "Үргэлжлүүлэх" : "Шинэ таамаглал", to: ["experiments", inProgress ? { id: inProgress.id } : {}] } },
    { title: "Үр дүн харах", done: false,
      text: ready.length ? "Барааны таамаглал, тайлан, Excel." : "Таамаглал бэлэн болмогц харагдана.",
      action: ready.length && { label: "Тайлан нээх", to: ["reports", { experiment: ready[0].id }] } },
  ];
  const nextIdx = steps.findIndex((s) => !s.done);

  return (
    <>
      <h1>Сайн байна уу, {user.full_name || user.username}</h1>
      <p className="muted">
        {isManager ? <>Салбар: <b>{branchText(user.branches)}</b></> : "Бүх салбарын таамаглал, тайлан."}
      </p>
      <ErrorNote error={versions.error || exps.error} />
      {isManager && (!user.branches || user.branches.length === 0) && (
        <div className="notice warn">Танд салбар оноогоогүй байна. Админд хандана уу.</div>
      )}

      {isManager && <ol className="flow">
        {steps.map((s, i) => (
          <li key={s.title} className={s.done ? "done" : i === nextIdx ? "next" : ""}>
            <span className="n" aria-hidden="true">{s.done ? "✓" : i + 1}</span>
            <b>{s.title}</b>
            <span>{s.text}</span>
            {s.action && <button className={i === nextIdx ? "" : "quiet"} onClick={() => go(...s.action.to)}>{s.action.label}</button>}
          </li>
        ))}
      </ol>}
      {!isManager && ready.length === 0 && (
        <div className="intro"><p>Бэлэн таамаглал алга.</p></div>
      )}

      {running.length > 0 && (
        <>
          <h2>Ажиллаж байна</h2>
          {running.map((j) => <JobProgress key={j.id} jobId={j.id} onDone={() => { jobs.reload(); versions.reload(); exps.reload(); }} />)}
        </>
      )}

      {ready.length > 0 && <Headline exp={ready.find((e) => e.target === "demand") || ready[0]} />}

      <Attention failed={failed} ready={ready[0]} />

      {ready.length > 0 && (
        <>
          <h2>Бэлэн таамаглалууд</h2>
          <div className="panel table-wrap">
            <table>
              <thead><tr><th>Нэр</th><th>Төрөл</th><th>Өгөгдөл</th><th></th></tr></thead>
              <tbody>{ready.map((e) => (
                <tr key={e.id}>
                  <td>{e.name}</td><td>{e.target_label}</td><td>{e.dataset}</td>
                  <td className="row" style={{ gap: 8 }}>
                    <button className="quiet" onClick={() => go("reports", { experiment: e.id })}>Тайлан</button>
                    <button className="quiet" onClick={() => go("forecast", { experiment: e.id })}>Бараагаар</button>
                  </td>
                </tr>))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {jobs.data?.length > 0 && (
        <>
          <h2>Сүүлийн ажлууд</h2>
          <div className="panel table-wrap">
            <table>
              <thead><tr><th>Ажил</th><th>Төлөв</th><th>Тэмдэглэл</th><th>Хэзээ</th></tr></thead>
              <tbody>{jobs.data.map((j) => (
                <tr key={j.id}>
                  <td>{JOB_TYPE[j.type] || j.type}</td>
                  <td><span className={`badge ${j.status === "done" ? "ok" : j.status === "failed" ? "bad" : "info"}`}>{JOB_STATUS[j.status]}</span></td>
                  <td className="small">{j.error ? j.error.split("\n")[0] : j.progress?.stage || ""}</td>
                  <td className="small">{new Date(j.created_at).toLocaleString("mn-MN")}</td>
                </tr>))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}

// Хамгийн сүүлийн бэлэн таамаглалын гол дүн: ирэх 12 сарын нийт, найдвартай байдал, бодит гүйцэтгэл
function Headline({ exp }) {
  const rep = useLoad(() => api.get(`/reports/dashboard?experiment_id=${exp.id}&horizon=12`), [exp.id]);
  const trk = useLoad(() => api.get(`/forecasts/tracking?experiment_id=${exp.id}&horizon=12`).catch(() => null), [exp.id]);
  const r = rep.data;
  if (!r) return rep.loading ? <p className="muted small">Гол дүнг тооцож байна…</p> : null;
  const ss = r.series || [];
  const units = [...new Set(ss.map((s) => s.unit).filter(Boolean))];
  const oneUnit = units.length <= 1;                      // өөр нэгжтэй барааг нийлбэрлэхгүй
  const ok = ss.every((s) => s.total_forecast !== null);
  const total = ok ? ss.reduce((a, s) => a + s.total_forecast, 0) : null;
  const lyOk = ss.every((s) => s.last_year !== null);
  const ly = lyOk ? ss.reduce((a, s) => a + s.last_year, 0) : null;
  const ch = total !== null && ly ? total / ly - 1 : null;
  const a = accuracyLevel(r.kpi.wape_selected, r.kpi.wape_baseline);
  const dem = r.experiment.target === "demand";
  const whatGen = dem ? "эрэлтийн" : "борлуулалтын", whatWith = dem ? "эрэлттэй" : "борлуулалттай";
  const t = trk.data?.available ? trk.data : null;
  const fm = r.forecast_months;
  return (
    <>
      <h2>Гол дүн: {exp.name}</h2>
      <div className="summary">
        {oneUnit && total !== null
          ? <div className="big">{fmt(total, 0)}<small>{r.experiment.unit}, ирэх 12 сар</small></div>
          : <div className="big">{ss.length}<small>барааны таамаглал</small></div>}
        <div>
          <p>{monthLabel(fm[0], true)} – {monthLabel(fm[fm.length - 1], true)}: {ss.length} барааны {whatGen} таамаглал
            {oneUnit && ch !== null ? <>, өнгөрсөн 12 сараас <b>{ch >= 0 ? "+" : "−"}{Math.abs(ch * 100).toFixed(1)}%</b></> : null}.</p>
          <p>Найдвартай байдал: <span className={`grade ${a.tone}`}>{a.label}</span> {a.text}{" "}
            {r.kpi.share_improved !== null && <>Барааны {pct(r.kpi.share_improved)}-д энгийн аргаас сайн.</>}</p>
          {t ? (
            <p>Бодит гүйцэтгэл ({t.months_compared} сар): <span className={`grade ${trackGrade(t.overall.wape).tone}`}>{trackGrade(t.overall.wape).label}</span>{" "}
              сарын алдаа <b>{pct(t.overall.wape)}</b>. {biasText(t.overall.bias)}</p>
          ) : <p className="small muted">Шинэ сарын файл оруулмагц таамаглалыг бодит {whatWith} харьцуулна.</p>}
          <div className="row" style={{ marginTop: 8 }}>
            <button onClick={() => go("reports", { experiment: exp.id })}>Тайлан</button>
            <button className="quiet" onClick={() => go("forecast", { experiment: exp.id })}>Бараагаар</button>
            <button className="quiet" onClick={() => go("tracking", { experiment: exp.id })}>Гүйцэтгэл</button>
          </div>
        </div>
      </div>
    </>
  );
}

// «Анхаарах зүйл»: бүх барааг нэг бүрчлэн шалгах шаардлагагүй — зөвхөн эдгээрийг (exception list)
function Attention({ failed, ready }) {
  const rep = useLoad(() => (ready ? api.get(`/reports/dashboard?experiment_id=${ready.id}&horizon=1`) : Promise.resolve(null)), [ready?.id]);
  const items = [];
  if (failed) items.push({ tone: "bad", tag: "Өгөгдөлд алдаа", title: failed.dataset,
    text: "Алдааг засах хүртэл энэ файлыг ашиглахгүй.", to: ["quality", { version: failed.id }], btn: "Засах" });
  const series = rep.data?.series || [];
  const worse = series.filter((s) => s.test?.WAPE?.selected != null && s.test?.WAPE?.baseline != null && s.test.WAPE.selected > s.test.WAPE.baseline)
    .sort((a, b) => (b.test.WAPE.selected - b.test.WAPE.baseline) - (a.test.WAPE.selected - a.test.WAPE.baseline));
  for (const s of worse.slice(0, 3)) items.push({ tone: "warn", tag: "Энгийн аргаас муу", title: seriesLabel(s),
    text: `Алдаа ${pct(s.test.WAPE.selected)}, энгийн арга ${pct(s.test.WAPE.baseline)}.`,
    to: ["forecast", { experiment: ready.id, series: s.id }], btn: "Шалгах" });
  const shaky = series.filter((s) => (s.test?.WAPE?.selected ?? 0) >= 0.4 && !worse.includes(s));
  if (shaky.length) items.push({ tone: "info", tag: "Алдаа өндөр", title: `${shaky.length} бараа`,
    text: `Сарын алдаа 40%-иас их: ${shaky.slice(0, 3).map(seriesLabel).join(", ")}${shaky.length > 3 ? "…" : ""}. Улирал, жилийн нийт дүн илүү найдвартай.`,
    to: ["reports", { experiment: ready.id }], btn: "Тайлан" });
  if (!failed && !ready) return null;
  return (
    <>
      <h2>Анхаарах зүйл</h2>
      <div className="panel">
        {rep.loading ? <p className="muted small">Шалгаж байна…</p> : !items.length
          ? <p style={{ margin: 0 }}><span className="badge ok">Хэвийн</span> Анхаарах зүйл алга.</p>
          : <ul className="attn">{items.map((it, i) => (
              <li key={i}>
                <span className={`badge ${it.tone}`}>{it.tag}</span>
                <div className="what"><b>{it.title}</b><span>{it.text}</span></div>
                <button className="quiet" onClick={() => go(...it.to)}>{it.btn}</button>
              </li>))}
              {worse.length > 3 && <li className="small muted">Бусад {worse.length - 3} бараа тайланд байна.</li>}
            </ul>}
      </div>
    </>
  );
}

function AdminHome({ user }) {
  return (
    <>
      <h1>Сайн байна уу, {user.full_name || user.username}</h1>
      <div className="intro">
        <ol>
          {Object.entries(ROLE_LABELS).map(([k, l]) => <li key={k}><b>{l}</b>: {ROLE_DESC[k].charAt(0).toLowerCase() + ROLE_DESC[k].slice(1)}</li>)}
        </ol>
      </div>
      <button onClick={() => go("admin")}>Хэрэглэгч нэмэх</button>
    </>
  );
}
