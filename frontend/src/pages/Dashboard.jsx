import { api } from "../api.js";
import { go } from "../App.jsx";
import { ErrorNote, JobProgress, Loading, useLoad } from "../components.jsx";
import { EXP_STEPS, JOB_STATUS, JOB_TYPE, ROLE_DESC, ROLE_LABELS, branchText, pct, seriesLabel } from "../labels.js";

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
    { title: "Таамаглал гаргуулах", done: ready.length > 0,
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
        {user.roles.map((r) => ROLE_LABELS[r]).join(", ")}
        {isManager && <> · салбар: <b>{branchText(user.branches)}</b></>}
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
          <p className="small muted">Хуудсаа хаасан ч үргэлжилнэ.</p>
          {running.map((j) => <JobProgress key={j.id} jobId={j.id} onDone={() => { jobs.reload(); versions.reload(); exps.reload(); }} />)}
        </>
      )}

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
        <p>Гурван төрлийн хэрэглэгч байна:</p>
        <ol>
          {Object.entries(ROLE_LABELS).map(([k, l]) => <li key={k}><b>{l}</b>: {ROLE_DESC[k].charAt(0).toLowerCase() + ROLE_DESC[k].slice(1)}</li>)}
        </ol>
        <p>Менежер зөвхөн өөрийн салбарыг харна.</p>
      </div>
      <button onClick={() => go("admin")}>Хэрэглэгч нэмэх</button>
    </>
  );
}
