import { useState } from "react";
import { api } from "../api.js";
import { go } from "../App.jsx";
import { ErrorNote, JobProgress, Loading, useLoad } from "../components.jsx";
import { EXP_STEPS, MODEL_LABELS, fmt, pct } from "../labels.js";

export default function Experiments({ params }) {
  return params.id ? <Detail id={params.id} /> : <List />;
}

function List() {
  const exps = useLoad(() => api.get("/experiments"), []);
  const versions = useLoad(() => api.get("/dataset-versions"), []);
  const defaults = useLoad(() => api.get("/experiments/defaults"), []);
  const [form, setForm] = useState({ name: "", version: "", target: "sales", max_series: 200, level: "global", models: null });
  const [err, setErr] = useState(null);
  const usable = (versions.data || []).filter((v) => v.status === "validated" && !v.archived_at);
  const models = form.models ?? defaults.data?.protocol.models.map((m) => m.name) ?? [];

  const create = async () => {
    setErr(null);
    const base = defaults.data.protocol;
    const protocol = {
      sample: { ...base.sample, max_series: Number(form.max_series) },
      selection_level: form.level,
      models: base.models.filter((m) => models.includes(m.name)),
    };
    try {
      const e = await api.post("/experiments", { name: form.name, dataset_version_id: Number(form.version || usable[0]?.id), target: form.target, protocol });
      go("experiments", { id: e.id });
    } catch (x) { setErr(x); }
  };

  return (
    <>
      <h1>Туршилт</h1>
      <p className="muted">Протокол тогтоож, validation-аар загвар сонгоод, сонголтыг түгжсэний дараа тестийг нэг удаа ажиллуулна.</p>
      <div className="split">
        <div className="panel table-wrap">
          {exps.loading ? <Loading /> : exps.data?.length ? (
            <table>
              <thead><tr><th>#</th><th>Нэр</th><th>Зорилт</th><th>Өгөгдөл</th><th>Төлөв</th></tr></thead>
              <tbody>{exps.data.map((e) => (
                <tr key={e.id} className="clickable" tabIndex={0} onClick={() => go("experiments", { id: e.id })}
                    onKeyDown={(ev) => ev.key === "Enter" && go("experiments", { id: e.id })}>
                  <td>{e.id}</td><td>{e.name}</td><td>{e.target_label}</td><td>{e.dataset} v{e.version_no}</td>
                  <td>{Object.fromEntries(EXP_STEPS)[e.status]}</td>
                </tr>))}
              </tbody>
            </table>
          ) : <p className="muted">Туршилт алга. Баруун талын маягтаар эхнийхийг үүсгэнэ үү.</p>}
        </div>
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Шинэ туршилт</h3>
          <label htmlFor="n">Нэр</label>
          <input id="n" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <label htmlFor="v" style={{ marginTop: 8 }}>Шалгагдсан өгөгдлийн хувилбар</label>
          <select id="v" value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })}>
            {usable.map((v) => <option key={v.id} value={v.id}>{v.dataset} v{v.version_no} ({v.date_min} – {v.date_max})</option>)}
          </select>
          <label htmlFor="t" style={{ marginTop: 8 }}>Зорилт</label>
          <select id="t" value={form.target} onChange={(e) => setForm({ ...form, target: e.target.value })}>
            <option value="sales">Борлуулалт (S)</option>
            <option value="demand">Эрэлт (D) — нөөцийн найдвартай өгөгдөл шаардана</option>
          </select>
          <div className="row" style={{ marginTop: 8 }}>
            <div className="grow"><label htmlFor="ms">Цувааны дээд тоо</label>
              <input id="ms" type="number" min="1" value={form.max_series} onChange={(e) => setForm({ ...form, max_series: e.target.value })} /></div>
            <div className="grow"><label htmlFor="sl">Сонголтын түвшин</label>
              <select id="sl" value={form.level} onChange={(e) => setForm({ ...form, level: e.target.value })}>
                <option value="global">Нийт</option><option value="group">ADI/CV² бүлэг</option><option value="series">Цуваа бүр</option>
              </select></div>
          </div>
          <fieldset style={{ border: 0, padding: 0, marginTop: 8 }}>
            <legend className="small muted">Загвар (seasonal naive нь суурь тул заавал)</legend>
            {(defaults.data?.models || []).map((m) => (
              <label key={m} style={{ display: "inline-flex", gap: 6, marginRight: 12 }}>
                <input type="checkbox" checked={models.includes(m)} disabled={m === "snaive"}
                       onChange={(e) => setForm({ ...form, models: e.target.checked ? [...models, m] : models.filter((x) => x !== m) })} />
                {MODEL_LABELS[m] || m}
              </label>
            ))}
            {defaults.data?.planned_models && <p className="small muted">Дараагийн үе шатанд: {defaults.data.planned_models.join(", ")}</p>}
          </fieldset>
          <button style={{ marginTop: 8 }} disabled={!form.name || !usable.length || !defaults.data} onClick={create}>Ноорог үүсгэх</button>
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
      <a href="#/experiments" className="small">Бүх туршилт</a>
      <h1>#{e.id} {e.name}</h1>
      <p className="muted">{e.target_label} · protocol_hash {e.protocol_hash ? e.protocol_hash.slice(0, 12) + "…" : "түгжигдээгүй"}
        {e.selection_hash && <> · selection_hash {e.selection_hash.slice(0, 12)}…</>}</p>
      <ol className="ladder" aria-label="Туршилтын төлөв">
        {EXP_STEPS.map(([k, l], i) => <li key={k} className={i < stepIdx ? "done" : i === stepIdx ? "current" : ""}>{l}</li>)}
      </ol>
      <ErrorNote error={err} />
      {activeJob && <JobProgress jobId={activeJob} onDone={() => { setJob(null); exp.reload(); }} />}
      {!activeJob && lastJob?.status === "failed" && <div className="notice bad">Сүүлийн ажил бүтэлгүйтэв: {lastJob.error?.split("\n")[0]}</div>}

      <div className="panel">
        {e.status === "draft" && (
          <>
            <p>Протокол одоохондоо засагдана. «Validation эхлүүлэх» дармагц протокол түгжигдэж (protocol_hash), цаашид өөрчлөх бол шинэ туршилт үүсгэнэ.</p>
            <button onClick={() => act(async () => setJob((await api.post(`/experiments/${id}/validate`)).job_id))}>Протоколыг түгжиж validation эхлүүлэх</button>
          </>
        )}
        {e.status === "validating" && !activeJob && (
          <button onClick={() => act(async () => setJob((await api.post(`/experiments/${id}/validate`)).job_id))}>Validation-ийг ижил протоколоор дахин ажиллуулах</button>
        )}
        {e.status === "validation_done" && (
          <>
            <p>Validation-д сонгогдсон загварыг доор шалгаад түгжинэ үү. Түгжсэний дараа сонголт өөрчлөгдөхгүй, тест нэг удаа ажиллана.</p>
            <button className="warn" onClick={() => act(() => api.post(`/experiments/${id}/lock`))}>Сонголтыг түгжих</button>
          </>
        )}
        {e.status === "locked" && !e.test_job_id && (
          <button className="warn" onClick={() => act(async () => setJob((await api.post(`/experiments/${id}/test`)).job_id))}>Эцсийн тестийг ажиллуулах (нэг удаа)</button>
        )}
        {e.status === "test_done" && (
          <div className="row">
            <button onClick={() => go("forecast", { experiment: id })}>Таамаглал харах</button>
            <button className="quiet" onClick={() => api.download(`/experiments/${id}/report?format=xlsx`, `experiment_${id}_report.xlsx`)}>Тайлан татах (Excel)</button>
          </div>
        )}
      </div>

      <details className="panel">
        <summary>Протокол</summary>
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

function Results({ id, status }) {
  const rep = useLoad(() => api.get(`/experiments/${id}/report`), [id, status]);
  const r = rep.data;
  if (!r) return rep.loading ? <Loading /> : <ErrorNote error={rep.error} />;
  return (
    <>
      <h2>Өгөгдөл ба хуваалт</h2>
      <div className="panel small">
        {r.data.dataset} v{r.data.version_no} · validation {r.splits.validation.join(" – ")} ({r.splits.validation_origins.length} эхлэл) ·
        тест {r.splits.test.join(" – ")} ({r.splits.test_origins.length} эхлэл) · хамрагдсан цуваа {r.sample.included}, хасагдсан {r.sample.excluded.length}
      </div>
      <h2>Validation ({r.validation[0]?.metric}, цувааны дундаж)</h2>
      <div className="panel table-wrap">
        <table>
          <thead><tr><th>Загвар</th>{[7, 14, 30].map((h) => <th key={h} className="num">H = {h}</th>)}<th className="num">Тодорхойгүй</th></tr></thead>
          <tbody>{[...new Set(r.validation.map((v) => v.model))].map((m) => {
            const rows = r.validation.filter((v) => v.model === m);
            return <tr key={m}><td>{m}</td>{[7, 14, 30].map((h) => <td key={h} className="num">{fmt(rows.find((x) => x.horizon === h)?.mean, 3)}</td>)}
              <td className="num">{rows.reduce((a, x) => a + x.n_undefined, 0)}</td></tr>;
          })}</tbody>
        </table>
      </div>
      <h2>Сонголт</h2>
      <div className="panel small">
        {Object.entries(r.selection).map(([h, s]) => (
          <div key={h}><b>H = {h}:</b> {Object.entries(s.counts).map(([m, n]) => `${m} — ${n} цуваа`).join("; ")}
            <div className="muted">{s.rules[0]}</div></div>
        ))}
      </div>
      {r.test.length > 0 && (
        <>
          <h2>Тест (нэг удаа, түгжсэн сонголтоор)</h2>
          <div className="panel table-wrap">
            <table>
              <thead><tr><th>Хүрээ</th><th className="num">Сонгосон MASE (медиан)</th><th className="num">Суурь MASE (медиан)</th>
                <th className="num">Суурьаас сайжирсан цуваа</th><th className="num">WAPE (медиан)</th><th className="num">Интервалын хамралт (80%)</th></tr></thead>
              <tbody>{r.test.map((t) => (
                <tr key={t.horizon}><td>{t.horizon} хоног</td><td className="num">{fmt(t.selected_MASE.median, 3)}</td>
                  <td className="num">{fmt(t.baseline_MASE.median, 3)}</td><td className="num">{pct(t.share_improved_vs_baseline)} ({t.n_compared})</td>
                  <td className="num">{pct(t.selected_WAPE.median)}</td><td className="num">{t.interval_coverage_80.n ? pct(t.interval_coverage_80.mean) : "интервал байхгүй"}</td></tr>))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <h2>Бүтэлгүйтэл ба хасагдсан цуваа</h2>
      <div className="panel small">
        {r.failures.length ? <p>{r.failures.length} тохируулалт бүтэлгүйтэж fallback загвар ажилласан (эхнийх: {r.failures[0].model}, {r.failures[0].product_id}/{r.failures[0].branch_id}: {r.failures[0].reason}).</p>
          : <p>Бүтэлгүйтсэн тохируулалт алга.</p>}
        {[...r.sample.excluded].sort((a, b) => a.exclude_reason.startsWith("дэд багцад") - b.exclude_reason.startsWith("дэд багцад")).slice(0, 8).map((x) => <div key={x.series_id}>{x.product_id}/{x.branch_id}: {x.exclude_reason}</div>)}
        {r.sample.excluded.length > 8 && <div className="muted">…бусад {r.sample.excluded.length - 8} нь Excel тайланд</div>}
      </div>
    </>
  );
}
