import { useState } from "react";
import { api } from "../api.js";
import { go } from "../App.jsx";
import { ErrorNote, Help, Intro, JobProgress, Loading, useLoad } from "../components.jsx";
import { accuracyLevel, plainExclude, runName, seriesLabel, EXP_STEPS, HORIZONS, MODEL_LABELS, monthLabel, pct } from "../labels.js";

export default function Experiments({ params }) {
  return params.id ? <Detail id={params.id} /> : <List />;
}

function List() {
  const exps = useLoad(() => api.get("/experiments"), []);
  const versions = useLoad(() => api.get("/dataset-versions"), []);
  const [form, setForm] = useState({ name: "", version: "", target: "sales", max_series: 200, level: "global", models: null, cats: [] });
  const [err, setErr] = useState(null);
  const usable = (versions.data || []).filter((v) => v.status === "validated" && !v.archived_at);
  const vid = form.version || usable[0]?.id;
  // Анхдагч протокол сонгосон өгөгдлийн бүтэн сарын тоонд тохируулагдана
  const defaults = useLoad(() => api.get(`/experiments/defaults${vid ? `?dataset_version_id=${vid}` : ""}`), [vid]);
  const models = form.models ?? [...new Set(defaults.data?.protocol.models.map((m) => m.name) ?? [])];
  const P = defaults.data?.protocol, info = defaults.data?.data;

  const create = async () => {
    setErr(null);
    const base = defaults.data.protocol;
    const protocol = {
      sample: { ...base.sample, max_series: Number(form.max_series), categories: form.cats.length ? form.cats : null },
      selection_level: form.level,
      models: base.models.filter((m) => models.includes(m.name)),
    };
    try {
      const e = await api.post("/experiments", { name: form.name, dataset_version_id: Number(vid), target: form.target, protocol });
      go("experiments", { id: e.id });
    } catch (x) { setErr(x); }
  };

  return (
    <>
      <h1>Таамаглал гаргуулах</h1>
      <p className="muted">Систем хэд хэдэн аргыг таны өнгөрсөн борлуулалт дээр шалгаж, хамгийн сайныг нь өөрөө сонгоно. Танаас 3 товч дарах л шаардлагатай.</p>
      <div className="split">
        <div className="panel table-wrap">
          {exps.loading ? <Loading /> : exps.data?.length ? (
            <table>
              <thead><tr><th>Нэр</th><th>Юуг таамаглах</th><th>Өгөгдөл</th><th>Төлөв</th></tr></thead>
              <tbody>{exps.data.map((e) => (
                <tr key={e.id} className="clickable" tabIndex={0} onClick={() => go("experiments", { id: e.id })}
                    onKeyDown={(ev) => ev.key === "Enter" && go("experiments", { id: e.id })}>
                  <td>{e.name}</td><td>{e.target_label}</td><td>{e.dataset} v{e.version_no}</td>
                  <td>{Object.fromEntries(EXP_STEPS)[e.status]}</td>
                </tr>))}
              </tbody>
            </table>
          ) : <p className="muted">Одоогоор таамаглал бэлтгээгүй байна. Баруун талын маягтыг бөглөөд эхлүүлнэ үү.</p>}
        </div>
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Шинэ таамаглал</h3>
          <label htmlFor="n">Нэр (жишээ: 2025 оны 1-р улирал)</label>
          <input id="n" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <label htmlFor="v" style={{ marginTop: 8 }}>Өгөгдөл</label>
          <select id="v" value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })}>
            {usable.map((v) => <option key={v.id} value={v.id}>{v.dataset} v{v.version_no} ({v.date_min} – {v.date_max})</option>)}
          </select>
          {info && P && (
            <p className={`small ${info.full_months < 18 ? "notice bad" : "muted"}`} style={{ margin: "0.4rem 0 0" }}>
              {info.full_months} бүтэн сарын өгөгдөл ({monthLabel(info.first_full_month)}–{monthLabel(info.last_full_month)}). Аргууд эхний саруудаас сурч,
              {" "}дараагийн {P.val_months} сард дадлага шалгалт, сүүлийн {P.test_months} сард эцсийн шалгалт өгнө.
              {!info.year_horizon_testable && " Шалгах хугацаа 12 сараас богино тул жилийн таамаглалын алдааг хэмжих боломжгүй (таамаглал гарна)."}
              {info.full_months < 18 && " Өгөгдөл хэт богино — дор хаяж 18 бүтэн сар шаардлагатай."}
            </p>)}
          <label htmlFor="t" style={{ marginTop: 8 }}>Юуг таамаглах <Help k="sales_vs_demand" /></label>
          <select id="t" value={form.target} onChange={(e) => setForm({ ...form, target: e.target.value })}>
            <option value="sales">Борлуулалт (ихэнх тохиолдолд үүнийг сонгоно)</option>
            <option value="demand">Эрэлт — нөөцийн мэдээлэл оруулсан бол</option>
          </select>
          <details style={{ marginTop: 10 }}>
          <summary className="small">Нарийвчилсан тохиргоо (заавал биш)</summary>
          <div className="row" style={{ marginTop: 8 }}>
            <div className="grow"><label htmlFor="ms">Бүтээгдэхүүний дээд тоо</label>
              <input id="ms" type="number" min="1" value={form.max_series} onChange={(e) => setForm({ ...form, max_series: e.target.value })} /></div>
            <div className="grow"><label htmlFor="sl">Аргыг хэрхэн сонгох</label>
              <select id="sl" value={form.level} onChange={(e) => setForm({ ...form, level: e.target.value })}>
                <option value="global">Бүх бүтээгдэхүүнд нэг арга</option><option value="group">Борлуулалтын хэв шинжээр</option><option value="series">Бүтээгдэхүүн бүрд тусад нь</option>
              </select></div>
          </div>
          <fieldset style={{ border: 0, padding: 0, marginTop: 8 }}>
            <legend className="small muted">Турших аргууд («Сүүлийн 3 сарын дундаж» нь харьцуулах суурь тул заавал)</legend>
            {[...new Set((P?.models || []).map((m) => m.name))].map((m) => (
              <label key={m} style={{ display: "inline-flex", gap: 6, marginRight: 12 }}>
                <input type="checkbox" checked={models.includes(m)} disabled={m === P?.baseline.name}
                       onChange={(e) => setForm({ ...form, models: e.target.checked ? [...models, m] : models.filter((x) => x !== m) })} />
                {MODEL_LABELS[m] || m}
              </label>
            ))}
          </fieldset>
          {(defaults.data?.categories || []).length > 1 && (
            <>
              <label style={{ marginTop: 8 }}>Зөвхөн эдгээр ангилал (сонгоогүй бол бүгд)</label>
              <div className="chips">
                {defaults.data.categories.map((c) => (
                  <button type="button" key={c} className={`chip ${form.cats.includes(c) ? "on" : ""}`} aria-pressed={form.cats.includes(c)}
                          onClick={() => setForm({ ...form, cats: form.cats.includes(c) ? form.cats.filter((x) => x !== c) : [...form.cats, c] })}>{c}</button>))}
              </div>
            </>
          )}
          </details>
          <button style={{ marginTop: 12 }} disabled={!form.name || !usable.length || !defaults.data} onClick={create}>Үүсгэх</button>
          {!usable.length && <p className="small muted">Ашиглах боломжтой өгөгдөл алга — эхлээд өгөгдөл оруулж, чанарын алдааг засна.</p>}
          <ErrorNote error={err} />
        </div>
      </div>
    </>
  );
}

function Detail({ id }) {
  const exp = useLoad(() => api.get(`/experiments/${id}`), [id]);
  const [job, setJob] = useState(null);
  const [err, setErr] = useState(null);
  const [protoText, setProtoText] = useState(null);
  const e = exp.data;
  const stepIdx = e ? EXP_STEPS.findIndex(([k]) => k === e.status) : -1;
  const activeJob = job || e?.jobs?.find((j) => ["queued", "running"].includes(j.status))?.id;
  const lastJob = e?.jobs?.[0];
  const act = async (fn) => { setErr(null); try { await fn(); exp.reload(); } catch (x) { setErr(x); } };

  if (exp.loading && !e) return <Loading />;
  if (!e) return <ErrorNote error={exp.error} />;
  return (
    <>
      <a href="#/experiments" className="small">Бүх таамаглал</a>
      <h1>{e.name}</h1>
      <p className="muted">{e.target_label}</p>
      <ol className="ladder" aria-label="Туршилтын төлөв">
        {EXP_STEPS.map(([k, l], i) => <li key={k} className={i < stepIdx ? "done" : i === stepIdx ? "current" : ""}>{l}</li>)}
      </ol>
      <ErrorNote error={err} />
      {activeJob && <JobProgress jobId={activeJob} onDone={() => { setJob(null); exp.reload(); }} />}
      {!activeJob && lastJob?.status === "failed" && <div className="notice bad">Сүүлийн ажил бүтэлгүйтэв: {lastJob.error?.split("\n")[0]}</div>}

      <div className="panel">
        {e.status === "draft" && (
          <>
            <h3 style={{ marginTop: 0 }}>Алхам 1/3: Дадлага шалгалт</h3>
            <p>Систем таны өмнөх борлуулалт дээр бүх аргыг туршиж, хамгийн бага алддагийг сонгоно. Хэдэн минут үргэлжилж магадгүй; хуудсаа хаасан ч үргэлжилнэ. Эхэлсний дараа тохиргоо өөрчлөгдөхгүй.</p>
            <button onClick={() => act(async () => setJob((await api.post(`/experiments/${id}/validate`)).job_id))}>Аргуудыг турших</button>
          </>
        )}
        {e.status === "validating" && !activeJob && (
          <>
            <h3 style={{ marginTop: 0 }}>Алхам 1/3: Дадлага шалгалт</h3>
            <p>Өмнөх оролдлого дуусаагүй. Ижил тохиргоогоор дахин эхлүүлж болно.</p>
            <button onClick={() => act(async () => setJob((await api.post(`/experiments/${id}/validate`)).job_id))}>Дахин турших</button>
          </>
        )}
        {e.status === "validating" && activeJob && <p style={{ margin: 0 }}>Систем аргуудыг туршиж байна. Хуудсаа хаасан ч үргэлжилнэ.</p>}
        {e.status === "validation_done" && (
          <>
            <h3 style={{ marginTop: 0 }}>Алхам 2/3: Сонголтыг баталгаажуулах <Help k="lock" /></h3>
            <p>Систем бараа бүрт тохирох аргыг доор сонгосон. Харж байгаад баталгаажуулна уу.</p>
            <p className="why"><b>Яагаад дараа нь өөрчилж болохгүй вэ?</b> Эцсийн шалгалтын дүнг харсны дараа аргаа солих нь шалгалтын хариуг харчихаад хариулахтай адил — дүн бодитоос сайн харагдана. Өөр арга турших бол шинэ таамаглал эхлүүлнэ.</p>
            <button className="warn" onClick={() => act(() => api.post(`/experiments/${id}/lock`))}>Сонголтыг баталгаажуулах</button>
          </>
        )}
        {e.status === "locked" && !e.test_job_id && (
          <>
            <h3 style={{ marginTop: 0 }}>Алхам 3/3: Эцсийн шалгалт <Help k="test" /></h3>
            <p>Сонгосон аргыг урьд нь хараагүй сүүлийн саруудад нэг удаа шалгаж («бодит амьдрал дээр хэр сайн бэ?»), дараа нь ирэх 12 сарын таамаглалыг гаргана.</p>
            <button className="warn" onClick={() => act(async () => setJob((await api.post(`/experiments/${id}/test`)).job_id))}>Эцсийн шалгалт эхлүүлэх</button>
          </>
        )}
        {e.status === "locked" && e.test_job_id && activeJob && <p style={{ margin: 0 }}>Эцсийн шалгалт ба таамаглал гарч байна…</p>}
        {e.status === "test_done" && (
          <>
            <h3 style={{ marginTop: 0 }}>Таамаглал бэлэн ✓</h3>
            <div className="row">
              <button onClick={() => go("reports", { experiment: id })}>Тайлан харах</button>
              <button className="quiet" onClick={() => go("forecast", { experiment: id })}>Бүтээгдэхүүн бүрээр харах</button>
              <button className="quiet" onClick={() => api.download(`/experiments/${id}/report?format=xlsx`, `experiment_${id}_report.xlsx`)}>Техникийн тайлан (Excel)</button>
            </div>
          </>
        )}
      </div>

      <details className="panel">
        <summary>Техникийн мэдээлэл</summary>
        <p className="small muted">Мөшгих код: protocol_hash {e.protocol_hash ? e.protocol_hash.slice(0, 16) + "…" : "—"}
          {e.selection_hash && <>, selection_hash {e.selection_hash.slice(0, 16)}…</>}</p>
        {e.status === "draft" ? (
          <>
            <textarea aria-label="Протокол (JSON)" value={protoText ?? JSON.stringify(e.protocol, null, 2)} onChange={(x) => setProtoText(x.target.value)} style={{ minHeight: "18rem" }} />
            <button style={{ marginTop: 8 }} disabled={protoText === null} onClick={() => act(async () => {
              await api.put(`/experiments/${id}/protocol`, { protocol: JSON.parse(protoText) }); setProtoText(null);
            })}>Протокол хадгалах</button>
          </>
        ) : <pre className="small" style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(e.protocol, null, 2)}</pre>}
      </details>

      {["validation_done", "locked", "test_done"].includes(e.status) && <Results id={id} status={e.status} />}
    </>
  );
}

const monthsBetween = (a, b) => {
  const [y1, m1] = String(a).split("-").map(Number), [y2, m2] = String(b).split("-").map(Number);
  return (y2 - y1) * 12 + (m2 - m1) + 1;
};

function Results({ id, status }) {
  const rep = useLoad(() => api.get(`/experiments/${id}/report`), [id, status]);
  const [hz, setHz] = useState(1);
  const r = rep.data;
  if (!r) return rep.loading ? <Loading /> : <ErrorNote error={rep.error} />;
  const models = [...new Set(r.validation.map((v) => v.model))];
  const hs = HORIZONS.map(([h]) => h);
  const best = Object.fromEntries(hs.map((h) => {
    const rows = r.validation.filter((v) => v.horizon === h && v.mean !== null);
    return [h, rows.length ? rows.reduce((a, b) => (a.mean <= b.mean ? a : b)).model : null];
  }));
  const range = (a) => `${monthLabel(a[0], true)} – ${monthLabel(a[1], true)}`;
  const sp = r.splits;
  const nTr = monthsBetween(sp.train_start_min, sp.validation[0]) - 1, nVa = monthsBetween(...sp.validation), nTe = monthsBetween(...sp.test);
  const excl = {};
  for (const x of r.sample.excluded) { const k = plainExclude(x.exclude_reason).replace(/: \d+ сар/, ""); (excl[k] ||= []).push(x); }
  const sel = r.selection[hz];
  const nSel = sel ? Object.values(sel.counts).reduce((a, n) => a + n, 0) : 0;
  return (
    <>
      <h2>Сурагчийн шалгалттай адил</h2>
      <div className="panel">
        <p className="small" style={{ marginTop: 0 }}>{r.data.dataset} (хувилбар {r.data.version_no}) · {r.sample.included} бараа · сүүлийн бүтэн сар {monthLabel(sp.last_complete_month, true)}</p>
        <div className="split-bar" role="img" aria-label={`Сурах ${nTr}+ сар, дадлага шалгалт ${nVa} сар, эцсийн шалгалт ${nTe} сар`}>
          <div className="tr" style={{ flex: Math.max(nTr, 6) }}>Сурах · {nTr}+ сар</div>
          <div className="va" style={{ flex: nVa }}>Дадлага · {nVa} сар</div>
          <div className="te" style={{ flex: nTe }}>Эцсийн шалгалт · {nTe} сар</div>
        </div>
        <div className="three">
          <p><b>1. Сурах.</b> Аргууд хуучин борлуулалтаас хэв маягийг сурна — аль сард их зарагддаг, өсөж байна уу гэх мэт.</p>
          <p><b>2. Дадлага шалгалт</b> ({range(sp.validation)}). Аргуудаар таамаглуулж бодит борлуулалттай харьцуулна. Хамгийн бага алдсан нь сонгогдоно.</p>
          <p><b>3. Эцсийн шалгалт</b> ({range(sp.test)}). Сонгосон аргыг урьд нь хараагүй саруудад нэг удаа шалгана.</p>
        </div>
      </div>

      <h2>Систем юуг сонгосон бэ</h2>
      <div className="panel">
        <div className="tabs" role="tablist" style={{ marginBottom: "0.5rem" }}>
          {HORIZONS.map(([h, l]) => <button key={h} role="tab" aria-selected={hz === h} className={hz === h ? "on" : ""} onClick={() => setHz(h)}>{l}ын таамаглал</button>)}
        </div>
        {sel ? (
          <ul className="picks">{Object.entries(sel.counts).sort((a, b) => b[1] - a[1]).map(([m, n]) => (
            <li key={m}><b>{n}</b><div><b>бараанд «{runName(m)}»</b>{m.startsWith("ma") ? <span className="muted small"> — нарийн аргууд энэ энгийн аргаас сайн гараагүй тул үүнийг үлдээсэн</span> : null}</div></li>))}
          </ul>) : <p className="muted">Сонголт хараахан хийгдээгүй.</p>}
        <p className="small muted" style={{ marginBottom: 0 }}>Нийт {nSel} бараа. Арга энгийн «Сүүлийн 3 сарын дундаж»-аас сайн биш бол систем энгийнийг нь үлдээдэг.</p>
      </div>

      {r.test.length > 0 && (
        <>
          <h2>Эцсийн шалгалтын дүн <Help k="test" /></h2>
          <div className="result-cards">{r.test.map((t) => {
            const a = accuracyLevel(t.selected_WAPE.median, t.baseline_WAPE.median);
            const n = Math.round((t.share_improved_vs_baseline ?? 0) * t.n_compared);
            return (
              <div className="panel" key={t.horizon}>
                <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}><b>{t.period}ын таамаглал</b><span className={`grade ${a.tone}`}>{a.label}</span></div>
                <p>Сард дунджаар <b>{pct(t.selected_WAPE.median)}</b> зөрдөг (энгийн арга {pct(t.baseline_WAPE.median)}).</p>
                {t.horizon > 1 && <p>{t.period}ын нийт дүн дунджаар <b>{pct(t.selected_SUM_APE.median)}</b> зөрдөг.</p>}
                <p>{t.n_compared} барааны <b>{n}</b>-д энгийн аргаас сайн.</p>
              </div>);
          })}</div>
          <p className="small muted">Улирал, жилийн нийт дүн сар бүрийнхээс нарийвчлалтай гардаг — сарын зөрүүнүүд бие биенээ нөхдөг. Тоонууд нь бараануудын медиан.</p>
        </>
      )}

      {(r.failures.length > 0 || r.sample.excluded.length > 0) && (
        <>
          <h2>Анхаарах зүйл</h2>
          <div className="panel small">
            {r.failures.length > 0 && <p style={{ marginTop: 0 }}><span className="badge warn">Энгийн аргаар</span> {r.failures.length} удаа сонгосон арга ажиллаж чадаагүй тул хамгийн энгийн аргаар таамагласан (жишээ: {seriesLabel(r.failures[0])}). Нуухгүй — тайланд тусад нь харагдана.</p>}
            {Object.entries(excl).map(([k, xs]) => (
              <p key={k} style={{ margin: "0.3rem 0" }}><b>{xs.length} бараа</b> хасагдсан — {k}. <span className="muted">{xs.slice(0, 5).map(seriesLabel).join(", ")}{xs.length > 5 ? "…" : ""}</span></p>))}
          </div>
        </>
      )}

      <details className="panel">
        <summary>Аргууд тус бүрийн дадлага шалгалтын алдаа <span className="muted small">· нарийвчилсан</span></summary>
        <div className="table-wrap" style={{ marginTop: 8 }}>
          <p className="small muted">Сарын алдаа (WAPE) — бага байх тусам сайн. Хугацаа бүрийн хамгийн сайн нь тодоор. <Help k="WAPE" /></p>
          <table>
            <thead><tr><th>Арга</th>{HORIZONS.map(([h, l]) => <th key={h} className="num">{l}</th>)}</tr></thead>
            <tbody>{models.map((m) => {
              const rows = r.validation.filter((v) => v.model === m);
              return <tr key={m}><td>{runName(m)} <span className="facts-tech">{m.split(" ")[0]}</span></td>{hs.map((h) => {
                const v = rows.find((x) => x.horizon === h)?.mean;
                return <td key={h} className="num" style={best[h] === m ? { fontWeight: 700 } : null}>{pct(v)}</td>;
              })}</tr>;
            })}</tbody>
          </table>
          {r.test.length > 0 && (
            <table style={{ marginTop: 12 }}>
              <thead><tr><th>Хугацаа</th><th className="num">WAPE</th><th className="num">Суурь WAPE</th><th className="num">SUM_APE</th><th className="num">MASE</th><th className="num">Хүрээнд багтсан <Help k="COVERAGE" /></th></tr></thead>
              <tbody>{r.test.map((t) => <tr key={t.horizon}><td>{t.period}</td><td className="num">{pct(t.selected_WAPE.median)}</td><td className="num">{pct(t.baseline_WAPE.median)}</td>
                <td className="num">{pct(t.selected_SUM_APE.median)}</td><td className="num">{t.selected_MASE.median?.toFixed(2) ?? "—"}</td>
                <td className="num">{t.interval_coverage_80.n ? pct(t.interval_coverage_80.mean) : "—"}</td></tr>)}</tbody>
            </table>)}
        </div>
      </details>
    </>
  );
}
