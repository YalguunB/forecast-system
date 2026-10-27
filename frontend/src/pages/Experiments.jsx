import { useState } from "react";
import { api } from "../api.js";
import { go } from "../App.jsx";
import { ErrorNote, Help, Intro, JobProgress, Loading, useLoad } from "../components.jsx";
import { accuracyLevel, seriesLabel, EXP_STEPS, HORIZONS, MODEL_LABELS, monthLabel, pct } from "../labels.js";

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
      <h1>Таамаглах</h1>
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
              {info.full_months} бүтэн сар ({monthLabel(info.first_full_month)}–{monthLabel(info.last_full_month)}). Хуваалт: сургалт ≥ {P.train_min_months},
              {" "}арга сонгох {P.val_months}, эцсийн шалгалт {P.test_months} сар.
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
            <legend className="small muted">Турших аргууд («Гулсах дундаж» нь харьцуулах суурь тул заавал)</legend>
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
            <h3 style={{ marginTop: 0 }}>Алхам 1/3: Загваруудыг турших</h3>
            <p>Систем таны өгөгдлийн өмнөх хэсэг дээр бүх аргыг туршиж, хамгийн бага алдаатайг сонгоно. Эхэлсний дараа тохиргоо өөрчлөгдөхгүй.</p>
            <button onClick={() => act(async () => setJob((await api.post(`/experiments/${id}/validate`)).job_id))}>Аргуудыг турших</button>
          </>
        )}
        {e.status === "validating" && !activeJob && (
          <>
            <h3 style={{ marginTop: 0 }}>Алхам 1/3: Загваруудыг турших</h3>
            <p>Өмнөх оролдлого дуусаагүй. Ижил тохиргоогоор дахин эхлүүлж болно.</p>
            <button onClick={() => act(async () => setJob((await api.post(`/experiments/${id}/validate`)).job_id))}>Дахин турших</button>
          </>
        )}
        {e.status === "validating" && activeJob && <p style={{ margin: 0 }}>Систем загваруудыг туршиж байна.</p>}
        {e.status === "validation_done" && (
          <>
            <h3 style={{ marginTop: 0 }}>Алхам 2/3: Сонголтыг түгжих <Help k="lock" /></h3>
            <p>Систем доорх аргыг сонгосон. Шалгаад түгжинэ үү — түгжсэний дараа өөрчлөхгүй.</p>
            <button className="warn" onClick={() => act(() => api.post(`/experiments/${id}/lock`))}>Сонголтыг түгжих</button>
          </>
        )}
        {e.status === "locked" && !e.test_job_id && (
          <>
            <h3 style={{ marginTop: 0 }}>Алхам 3/3: Эцсийн шалгалт <Help k="test" /></h3>
            <p>Сонгосон аргыг сонголтод ашиглаагүй сүүлийн саруудад нэг удаа шалгаж, ирэх 12 сарын таамаглалыг гаргана.</p>
            <button className="warn" onClick={() => act(async () => setJob((await api.post(`/experiments/${id}/test`)).job_id))}>Эцсийн шалгалт хийх</button>
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

function Results({ id, status }) {
  const rep = useLoad(() => api.get(`/experiments/${id}/report`), [id, status]);
  const r = rep.data;
  if (!r) return rep.loading ? <Loading /> : <ErrorNote error={rep.error} />;
  const plain = (lbl) => {
    const [m, ...rest] = String(lbl).split(" ");
    return (MODEL_LABELS[m] || m) + (m === "ets" && rest.join(" ").includes("trend") ? " + тренд" : "");
  };
  const models = [...new Set(r.validation.map((v) => v.model))];
  const hz = HORIZONS.map(([h]) => h);
  const best = Object.fromEntries(hz.map((h) => {
    const rows = r.validation.filter((v) => v.horizon === h && v.mean !== null);
    return [h, rows.length ? rows.reduce((a, b) => (a.mean <= b.mean ? a : b)).model : null];
  }));
  const range = (a) => `${monthLabel(a[0], true)} – ${monthLabel(a[1], true)}`;
  return (
    <>
      <h2>Ашигласан өгөгдөл</h2>
      <div className="panel small">
        <p style={{ margin: 0 }}>{r.data.dataset} (хувилбар {r.data.version_no}), {r.sample.included} бүтээгдэхүүн, сарын түвшинд (сүүлийн бүтэн сар {monthLabel(r.splits.last_complete_month, true)}).
          {" "}Аргуудыг <b>{range(r.splits.validation)}</b> хугацаанд туршиж сонгосон, эцсийн шалгалтыг
          {" "}<b>{range(r.splits.test)}</b> хугацаанд хийсэн (энэ хугацааны өгөгдлийг сонголтод ашиглаагүй).</p>
        {r.sample.excluded.length > 0 && <p className="muted" style={{ marginBottom: 0 }}>{r.sample.excluded.length} бүтээгдэхүүн хасагдсан (доорх «Анхааруулга»-г үзнэ үү).</p>}
      </div>

      <h2>Аргуудын харьцуулалт <Help k="WAPE" /></h2>
      <div className="panel table-wrap">
        <p className="small muted" style={{ marginTop: 0 }}>Сарын алдаа (WAPE) — бага байх тусам сайн. Хугацаа бүрийн хамгийн сайн нь тодоор.</p>
        <table>
          <thead><tr><th>Арга</th>{HORIZONS.map(([h, l]) => <th key={h} className="num">{l}</th>)}</tr></thead>
          <tbody>{models.map((m) => {
            const rows = r.validation.filter((v) => v.model === m);
            return <tr key={m}><td>{plain(m)}</td>{hz.map((h) => {
              const v = rows.find((x) => x.horizon === h)?.mean;
              return <td key={h} className="num" style={best[h] === m ? { fontWeight: 700 } : null}>{pct(v)}</td>;
            })}</tr>;
          })}</tbody>
        </table>
      </div>

      <h2>Систем ямар аргыг сонгосон бэ</h2>
      <div className="panel small">
        {Object.entries(r.selection).map(([h, s]) => (
          <p key={h} style={{ margin: "0.2rem 0" }}><b>{Object.fromEntries(HORIZONS)[h]}ын</b> таамаглалд: {Object.entries(s.counts).map(([m, n]) => `«${plain(m)}» (${n} бүтээгдэхүүн)`).join(", ")}.</p>
        ))}
        <p className="muted" style={{ marginBottom: 0 }}>Арга энгийн «Гулсах дундаж» аргаас сайн биш бол систем энгийн аргыг сонгодог.</p>
      </div>

      {r.test.length > 0 && (
        <>
          <h2>Эцсийн шалгалтын үр дүн <Help k="test" /></h2>
          <div className="panel table-wrap">
            <table>
              <thead><tr><th>Хугацаа</th><th>Үнэлгээ</th><th className="num">Сарын алдаа <Help k="WAPE" /></th><th className="num">Энгийн арга</th>
                <th className="num">Нийт дүнгийн алдаа <Help k="SUM_APE" /></th><th className="num">Энгийн аргаас сайн бүтээгдэхүүн</th><th className="num">Хүрээнд багтсан <Help k="COVERAGE" /></th></tr></thead>
              <tbody>{r.test.map((t) => {
                const a = accuracyLevel(t.selected_WAPE.median, t.baseline_WAPE.median);
                return <tr key={t.horizon}><td>{t.period} ({t.horizon} сар)</td><td><span className={`grade ${a.tone}`}>{a.label}</span></td>
                  <td className="num">{pct(t.selected_WAPE.median)}</td><td className="num">{pct(t.baseline_WAPE.median)}</td>
                  <td className="num">{pct(t.selected_SUM_APE.median)}</td>
                  <td className="num">{pct(t.share_improved_vs_baseline)} ({t.n_compared}-аас)</td>
                  <td className="num">{t.interval_coverage_80.n ? pct(t.interval_coverage_80.mean) : "—"}</td></tr>;
              })}</tbody>
            </table>
            <p className="small muted" style={{ marginBottom: 0 }}>Утгууд нь бүтээгдэхүүнүүдийн медиан. Улирал, жилийн нийт дүнгийн алдаа нь сар бүрийн алдаанаас бага гардаг — сарын зөрүүнүүд бие биенээ нөхдөг.</p>
          </div>
        </>
      )}

      {(r.failures.length > 0 || r.sample.excluded.length > 0) && (
        <>
          <h2>Анхааруулга</h2>
          <div className="panel small">
            {r.failures.length > 0 && <p>{r.failures.length} удаа сонгосон арга ажиллаж чадаагүй тул энгийн арга орлон ажилласан (жишээ: {seriesLabel(r.failures[0])} — {r.failures[0].reason}).</p>}
            {[...r.sample.excluded].sort((a, b) => a.exclude_reason.startsWith("дэд багцад") - b.exclude_reason.startsWith("дэд багцад")).slice(0, 8).map((x) => <div key={x.series_id}>{seriesLabel(x)}: {x.exclude_reason}</div>)}
            {r.sample.excluded.length > 8 && <div className="muted">…бусад {r.sample.excluded.length - 8} нь Excel тайланд</div>}
          </div>
        </>
      )}
    </>
  );
}
