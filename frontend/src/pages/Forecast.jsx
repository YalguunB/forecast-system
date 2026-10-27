import { useMemo, useState } from "react";
import { api } from "../api.js";
import { go } from "../App.jsx";
import { ErrorNote, Help, Intro, Loading, Plot, plotLayout, useLoad } from "../components.jsx";
import { HORIZONS, PERIOD, PERIOD_LONG, STATES, accuracyLevel, fmt, monthLabel, seriesLabel, MODEL_LABELS } from "../labels.js";

const METRIC_LABELS = { WAPE: "Сарын алдаа, %", SUM_APE: "Нийт дүнгийн алдаа, %", MAE: "Сарын дундаж алдаа", Bias: "Хэлбийлт",
  SUM_AE: "Нийт дүнгийн зөрүү", COVERAGE: "Хүрээнд багтсан", RMSE: "RMSE", MASE: "MASE", RMSSE: "RMSSE", WIDTH: "Хүрээний өргөн", PINBALL: "Pinball" };
const PCT = new Set(["WAPE", "SUM_APE", "COVERAGE"]);

// UC-03, 05, 06, 07 нэг дэлгэцэд: бүтээгдэхүүн бүрийн сарын таамаглал ба сар/улирал/жилийн нийлбэр (FR-04)
export default function Forecast({ params, user }) {
  const exps = useLoad(() => api.get("/experiments"), []);
  const done = (exps.data || []).filter((e) => e.status === "test_done" && !e.archived_at);
  const eid = params.experiment || done[0]?.id;
  const series = useLoad(() => (eid ? api.get(`/forecasts/series?experiment_id=${eid}`) : Promise.resolve([])), [eid]);
  const sid = params.series || series.data?.[0]?.series_id;
  const horizon = Number(params.h || 12);
  const split = params.split || "live";
  const origin = params.origin;
  const fc = useLoad(() => (eid && sid ? api.get(`/forecasts?experiment_id=${eid}&series=${sid}&horizon=${horizon}&split=${split}${origin ? `&origin_date=${origin}` : ""}${params.run ? `&run_id=${params.run}` : ""}`) : Promise.resolve(null)),
    [eid, sid, horizon, split, origin, params.run]);
  const nav = (patch) => go("forecast", { experiment: eid, series: sid, h: horizon, split, origin, run: params.run, ...patch });
  const isManager = user.roles.includes("manager");
  const canExport = ["executive", "manager"].some((r) => user.roles.includes(r));
  const [q, setQ] = useState("");

  if (exps.loading) return <Loading />;
  if (!done.length) return (<><h1>Бүтээгдэхүүний таамаглал</h1><Intro><p>Бэлэн таамаглал алга байна. Менежер «Таамаглал бэлтгэх» хэсэгт 3 алхмыг дуусгасны дараа энд гарна.</p></Intro></>);
  const f = fc.data;
  const list = (series.data || []).filter((s) => !q || seriesLabel(s).toLowerCase().includes(q.toLowerCase()) || (s.product_category || "").toLowerCase().includes(q.toLowerCase()));
  return (
    <>
      <h1>Бүтээгдэхүүний таамаглал</h1>
      <p className="muted">Бүтээгдэхүүнээ сонгоод ирэх сар, улирал эсвэл жилийн борлуулалтын таамаглалыг сар бүрээр нь харна.</p>
      <div className="row" style={{ marginBottom: "1rem" }}>
        <div className="grow"><label htmlFor="e">Таамаглал</label>
          <select id="e" value={eid} onChange={(e) => go("forecast", { experiment: e.target.value })}>
            {done.map((e) => <option key={e.id} value={e.id}>{e.name} — {e.target_label}</option>)}
          </select></div>
        <div className="grow"><label htmlFor="s">Бүтээгдэхүүн</label>
          <div className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
            <input aria-label="Бүтээгдэхүүн хайх" placeholder="Хайх…" value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 120 }} />
            <select id="s" value={sid || ""} onChange={(e) => nav({ series: e.target.value, origin: undefined, run: undefined })}>
              {list.map((s) => <option key={s.series_id} value={s.series_id}>{seriesLabel(s)}{s.product_category ? ` · ${s.product_category}` : ""}</option>)}
            </select>
          </div></div>
        <div><label>Хугацаа <Help k="horizon" /></label>
          <div className="tabs" role="tablist" style={{ margin: 0 }}>
            {HORIZONS.map(([h, l]) => <button key={h} role="tab" aria-selected={h === horizon} className={h === horizon ? "on" : ""} onClick={() => nav({ h, run: undefined, origin: undefined })}>{l}</button>)}
          </div></div>
        <div><label htmlFor="sp">Харах</label>
          <select id="sp" value={split} onChange={(e) => nav({ split: e.target.value, origin: undefined, run: undefined })}>
            <option value="live">Ирээдүйн таамаглал</option><option value="test">Өнгөрсөнд хэр зөв байсныг шалгах</option>
          </select></div>
      </div>
      <ErrorNote error={fc.error} />
      {fc.loading && !f ? <Loading /> : f && (
        <>
          <div className="target-banner" aria-label="Таамаглалын тодорхойлолт">
            <span className="target">{f.target_label}</span>
            <span className="fact">Бүтээгдэхүүн <b>{seriesLabel(f.series)}</b></span>
            {f.series.product_category && <span className="fact">Ангилал <b>{f.series.product_category}</b></span>}
            <span className="fact">Нэгж <b>{f.unit}</b></span>
            <span className="fact">Сүүлийн бүтэн сар <Help k="origin" /> <b>{monthLabel(f.origin_date)}</b></span>
            <span className="fact">Хугацаа <b>{PERIOD[f.horizon]} ({f.horizon} сар)</b></span>
            <span className="fact">Арга <b>{MODEL_LABELS[f.model] || f.model}</b></span>
            <span className="fact" title="Мөшгих дугаар (run)">№ <b>{f.run_id}</b></span>
          </div>
          {split === "live" && <Summary f={f} />}
          {split === "test" && <Intro><p>Систем өнгөрсөн нэг сарын байдлаар таамаглаж, дараа нь бодитоор хэд зарагдсаныг (цэгээр) харьцуулна. Шугам цэгүүдэд ойр байх тусам таамаглал зөв.
            {f.period_total.actual !== null && <> Энэ эхлэлээс {PERIOD_LONG[f.horizon]}-ын нийт: таамаглал <b>{fmt(f.period_total.forecast, 0)}</b>, бодит <b>{fmt(f.period_total.actual, 0)}</b> {f.unit}.</>}</p></Intro>}
          {split === "test" && (
            <div className="row" style={{ marginBottom: "0.5rem" }}>
              <div><label htmlFor="o">Сүүлийн мэдэгдэх сар</label>
                <select id="o" value={f.origin_date} onChange={(e) => nav({ origin: e.target.value })}>
                  {f.origins.map((o) => <option key={o} value={o}>{monthLabel(o, true)}</option>)}
                </select></div>
              <div><label htmlFor="r">Арга</label>
                <select id="r" value={f.run_id} onChange={(e) => nav({ run: e.target.value })}>
                  {f.available_runs.map((r) => <option key={r.run_id} value={r.run_id}>{MODEL_LABELS[r.model] || r.model}{r.role === "baseline" ? " (суурь)" : " — сонгосон"}</option>)}
                </select></div>
            </div>
          )}
          <div className="split">
            <div className="panel">
              <ForecastChart f={f} />
              {f.interval.available
                ? <p className="small muted">Цэнхэр зурвас: сар бүрийн 80%-ийн хүрээ <Help k="interval" />. Улирал, жилийн нийлбэрт хүрээг нэмж тооцохгүй.</p>
                : <p className="small muted">Энэ арга хүрээ (интервал) гаргадаггүй тул зурвас зураагүй.</p>}
              <MonthTable f={f} />
            </div>
            <div>
              <Metrics f={f} />
              {isManager && split === "live" && <Adjust f={f} onSaved={fc.reload} />}
              {f.adjusted.length > 0 && (
                <div className="panel small">
                  <h3 style={{ marginTop: 0 }}>Гараар хийсэн засвар</h3>
                  <p className="muted">Графикт улбар шар ромбоор харагдана. Анхны таамаглал хэвээр.</p>
                  {f.adjusted.map((a) => <div key={a.target_date}>{monthLabel(a.target_date)}: {fmt(a.original_value)} → <b>{fmt(a.adjusted_value)}</b> — {a.reason} ({a.username})</div>)}
                </div>
              )}
              {canExport && (
                <div className="panel">
                  <h3 style={{ marginTop: 0 }}>Татаж авах</h3>
                  <p className="small muted">Бүх бүтээгдэхүүний сар бүрийн таамаглал ба сар, улирал, жилийн нийлбэр нэг файлд. Залруулга тусдаа баганад.</p>
                  <div className="row">
                    <button className="quiet" onClick={() => api.download(`/export/forecasts?experiment_id=${eid}&split=${split}&format=xlsx`, `forecast_exp${eid}_${split}.xlsx`)}>Excel татах</button>
                    <button className="quiet" onClick={() => api.download(`/export/forecasts?experiment_id=${eid}&split=${split}&format=csv`, `forecast_exp${eid}_${split}.csv`)}>CSV татах</button>
                  </div>
                </div>
              )}
            </div>
          </div>
          {split === "test" && <Explain runId={f.run_id} sid={sid} horizon={horizon} />}
        </>
      )}
    </>
  );
}

// Энгийн хэллэгээр товч дүгнэлт: хугацааны нийт, өмнөх оны ижил үетэй харьцуулалт, найдвартай байдал
function Summary({ f }) {
  const total = f.period_total.adjusted ?? f.period_total.forecast;
  const k = f.horizon;
  // өмнөх оны ижил саруудын бодит борлуулалт (түүх 36 сар хүртэл)
  const byMonth = Object.fromEntries(f.history.map((h) => [h.month, h.value]));
  const ly = f.forecast.map((p) => { const [y, m] = p.target_date.split("-"); return byMonth[`${Number(y) - 1}-${m}-01`]; });
  const lyTotal = ly.every((v) => v !== undefined && v !== null) ? ly.reduce((a, v) => a + v, 0) : null;
  const change = lyTotal ? total / lyTotal - 1 : null;
  const sel = f.test_metrics.find((m) => m.metric === "WAPE" && m.role !== "baseline");
  const base = f.test_metrics.find((m) => m.metric === "WAPE" && m.role === "baseline");
  const period = f.test_metrics.find((m) => m.metric === "SUM_APE" && m.role !== "baseline");
  const acc = accuracyLevel(sel?.value, base?.value);
  const better = sel?.value != null && base?.value ? 1 - sel.value / base.value : null;
  const first = f.forecast[0]?.target_date, last = f.forecast[f.forecast.length - 1]?.target_date;
  return (
    <div className="summary">
      <div className="big">{fmt(total, 0)}<small>{f.unit}, {PERIOD_LONG[k]}</small></div>
      <div>
        <p><b>{seriesLabel(f.series)}</b> {k === 1 ? <>{monthLabel(first, true)}-д</> : <>{monthLabel(first)}–{monthLabel(last)} хугацаанд</>} нийт <b>{fmt(total, 0)} {f.unit}</b> орчим
          {k > 1 && <> (сард дунджаар {fmt(total / k, 0)})</>} зарагдана гэж таамаглаж байна.
          {change !== null && <> Өмнөх оны ижил үетэй харьцуулахад <b>{change >= 0 ? "+" : ""}{(change * 100).toFixed(0)}%</b>.</>}
          {f.period_total.adjusted != null && <> (гараар засварыг тооцсон; загварын анхны дүн {fmt(f.period_total.forecast, 0)})</>}</p>
        <p>Найдвартай байдал: <span className={`grade ${acc.tone}`}>{acc.label}</span> {acc.text}
          {better !== null && better > 0 && <> Энгийн аргаас алдаа <b>{(better * 100).toFixed(0)}%</b> бага.</>}
          {period?.value != null && k > 1 && <> {PERIOD[k]}ын нийт дүнгийн алдаа дунджаар <b>{(period.value * 100).toFixed(0)}%</b>.</>} <Help k="WAPE" /></p>
      </div>
    </div>
  );
}

function ForecastChart({ f }) {
  const traces = useMemo(() => {
    const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
    const sky = css("--sky") || "#2c6cb0", saffron = css("--saffron") || "#c2851a", ink = css("--ink-2") || "#4a5a63";
    const t = [];
    t.push({ x: f.history.map((h) => h.month), y: f.history.map((h) => h.value), name: "Өмнөх сарууд", type: "scatter",
      mode: "lines+markers", marker: { size: 4 }, line: { color: ink, width: 1.6 }, connectgaps: false,
      customdata: f.history.map((h) => h.reason || ""), hovertemplate: "%{y:,.0f}<extra>%{customdata}</extra>" });
    const gaps = f.history.filter((h) => h.value === null);
    if (gaps.length) t.push({ x: gaps.map((h) => h.month), y: gaps.map(() => 0), name: "Тодорхойгүй сар", type: "scatter", mode: "markers",
      marker: { symbol: "x", size: 8, color: STATES.missing.color }, customdata: gaps.map((h) => h.reason), hovertemplate: "%{customdata}<extra></extra>" });
    if (f.actual.length) t.push({ x: f.actual.map((h) => h.month), y: f.actual.map((h) => h.value), name: "Бодит борлуулалт", type: "scatter",
      mode: "markers", marker: { color: ink, size: 9, symbol: "circle-open", line: { width: 2 } }, hovertemplate: "%{y:,.0f}" });
    if (f.interval.available) {
      t.push({ x: f.forecast.map((p) => p.target_date), y: f.forecast.map((p) => p.q_hi), type: "scatter", mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip" });
      t.push({ x: f.forecast.map((p) => p.target_date), y: f.forecast.map((p) => p.q_lo), type: "scatter", mode: "lines", line: { width: 0 },
        fill: "tonexty", fillcolor: "rgba(44,108,176,0.15)", name: "80% хүрээ", hoverinfo: "skip" });
    }
    const last = f.history[f.history.length - 1];
    const join = last && last.value !== null && f.split === "live" ? [{ target_date: last.month, y_hat: last.value }] : [];
    t.push({ x: [...join, ...f.forecast].map((p) => p.target_date), y: [...join, ...f.forecast].map((p) => p.y_hat), name: "Таамаглал", type: "scatter",
      mode: "lines+markers", line: { color: sky, width: 2.6 }, marker: { size: 6 }, hovertemplate: "%{y:,.0f}" });
    if (f.adjusted.length) t.push({ x: f.adjusted.map((a) => a.target_date), y: f.adjusted.map((a) => a.adjusted_value), name: "Гараар засвар",
      type: "scatter", mode: "markers", marker: { color: saffron, size: 11, symbol: "diamond" }, hovertemplate: "%{y:,.0f}" });
    return t;
  }, [f]);
  return (
    <Plot data={traces} useResizeHandler style={{ width: "100%", height: 400 }} config={{ displayModeBar: false, responsive: true }}
      layout={plotLayout({
        xaxis: { type: "date", tickformat: "%Y.%m", dtick: "M3", gridcolor: "rgba(128,140,150,0.15)" },
        yaxis: { gridcolor: "rgba(128,140,150,0.15)", rangemode: "tozero", title: { text: `${f.unit} / сар` } },
        shapes: [{ type: "line", x0: f.origin_date, x1: f.origin_date, yref: "paper", y0: 0, y1: 1, line: { dash: "dot", width: 1, color: "#7b8a92" } }],
        annotations: [{ x: f.origin_date, yref: "paper", y: 1, text: "сүүлийн бүтэн сар", showarrow: false, xanchor: "right", font: { size: 11 } }],
      })} />
  );
}

// Сар бүрийн таамаглал, хүрээ, залруулга, (тест бол) бодит утга — нийлбэр мөртэй
function MonthTable({ f }) {
  const adj = Object.fromEntries(f.adjusted.map((a) => [a.target_date, a.adjusted_value]));
  const act = Object.fromEntries(f.actual.map((a) => [a.month, a.value]));
  const hasAct = f.split !== "live";
  return (
    <div className="table-wrap" style={{ marginTop: 8 }}>
      <table>
        <thead><tr><th>Сар</th><th className="num">Таамаглал</th>{f.interval.available && <th className="num">80% хүрээ</th>}
          {f.adjusted.length > 0 && <th className="num">Засвар</th>}{hasAct && <th className="num">Бодит</th>}</tr></thead>
        <tbody>
          {f.forecast.map((p) => (
            <tr key={p.target_date}><td>{monthLabel(p.target_date, true)}</td><td className="num">{fmt(p.y_hat, 0)}</td>
              {f.interval.available && <td className="num small">{fmt(p.q_lo, 0)} – {fmt(p.q_hi, 0)}</td>}
              {f.adjusted.length > 0 && <td className="num">{adj[p.target_date] !== undefined ? fmt(adj[p.target_date], 0) : ""}</td>}
              {hasAct && <td className="num">{act[p.target_date] === null ? <span title="тодорхойгүй сар">—</span> : fmt(act[p.target_date], 0)}</td>}</tr>))}
          {f.forecast.length > 1 && (
            <tr className="total"><td><b>{PERIOD[f.horizon]}ын нийт</b></td><td className="num"><b>{fmt(f.period_total.forecast, 0)}</b></td>
              {f.interval.available && <td className="num small muted">нэмэхгүй</td>}
              {f.adjusted.length > 0 && <td className="num"><b>{fmt(f.period_total.adjusted, 0)}</b></td>}
              {hasAct && <td className="num"><b>{fmt(f.period_total.actual, 0)}</b></td>}</tr>)}
        </tbody>
      </table>
    </div>
  );
}

function Metrics({ f }) {
  if (!f.test_metrics.length) return null;
  const by = {};
  for (const m of f.test_metrics) (by[m.metric] ||= {})[m.role === "baseline" ? "base" : "sel"] = m;
  const order = ["WAPE", "SUM_APE", "MAE", "Bias", "SUM_AE", "COVERAGE"].filter((k) => by[k]);
  return (
    <div className="panel">
      <h3 style={{ marginTop: 0 }}>Өнгөрсөнд хэр зөв байсан бэ</h3>
      <p className="small muted">Сүүлийн 12 сард сар бүрээс {PERIOD_LONG[f.horizon]}-ын таамаглал гаргаж, бодит борлуулалттай харьцуулсан дундаж. Бага байх тусам сайн.</p>
      <table>
        <thead><tr><th>Үзүүлэлт</th><th className="num">Сонгосон арга</th><th className="num">Энгийн арга <Help k="baseline" /></th></tr></thead>
        <tbody>{order.map((k) => (
          <tr key={k}><td>{METRIC_LABELS[k]} <Help k={k} /></td>
            {["sel", "base"].map((w) => {
              const m = by[k][w];
              return <td key={w} className="num" title={m?.undefined_reason || ""}>{m ? (m.value === null ? "тодорхойгүй" : PCT.has(k) ? `${(m.value * 100).toFixed(0)}%` : fmt(m.value, 1)) : "—"}</td>;
            })}</tr>))}
        </tbody>
      </table>
      <div className="small muted" style={{ marginTop: 8 }}>
        Сарын дүнг өдрийн бүртгэлээс нэгтгэсэн. Өдрийн төлөв <Help k="day_state" />: {Object.entries(f.data_states).map(([, v]) => `${v.label} ${v.n}`).join(", ")}
      </div>
    </div>
  );
}

function Adjust({ f, onSaved }) {
  const [date, setDate] = useState(f.forecast[0]?.target_date);
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const [err, setErr] = useState(null);
  const orig = f.forecast.find((p) => p.target_date === date)?.y_hat;
  return (
    <div className="panel">
      <h3 style={{ marginTop: 0 }}>Таамаглалыг гараар засах</h3>
      <p className="small muted">Урамшуулал, том захиалга зэрэг системд мэдэгдээгүй шалтгаан байвал. Анхны таамаглал устахгүй.</p>
      <label htmlFor="ad">Сар</label>
      <select id="ad" value={date} onChange={(e) => setDate(e.target.value)}>
        {f.forecast.map((p) => <option key={p.target_date} value={p.target_date}>{monthLabel(p.target_date, true)} — загвар {fmt(p.y_hat, 0)}</option>)}
      </select>
      <label htmlFor="av" style={{ marginTop: 8 }}>Залруулсан утга ({f.unit})</label>
      <input id="av" type="number" min="0" step="any" value={value} onChange={(e) => setValue(e.target.value)} placeholder={fmt(orig, 0)} />
      <label htmlFor="ar" style={{ marginTop: 8 }}>Шалтгаан</label>
      <input id="ar" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Жишээ: урамшуулал төлөвлөсөн" />
      <button className="warn" style={{ marginTop: 8 }} disabled={value === "" || reason.trim().length < 3} onClick={async () => {
        setErr(null);
        try {
          await api.post("/adjustments", { run_id: f.run_id, series_id: f.series.id, target_date: date, adjusted_value: Number(value), reason });
          setValue(""); setReason(""); onSaved();
        } catch (x) { setErr(x); }
      }}>Засвар хадгалах</button>
      <ErrorNote error={err} />
    </div>
  );
}

function Explain({ runId, sid, horizon }) {
  const ex = useLoad(() => api.get(`/forecasts/${runId}/explain?series=${sid}`), [runId, sid]);
  if (!ex.data) return null;
  const rows = ex.data.target_windows.map((w) => ({
    ...w,
    wape: ex.data.per_origin.find((p) => p.origin_date === w.origin_date && p.horizon === horizon && p.metric === "WAPE"),
    sum: ex.data.per_origin.find((p) => p.origin_date === w.origin_date && p.horizon === horizon && p.metric === "SUM_AE"),
  })).filter((r) => r.wape);
  return (
    <>
      <h2>Сар бүрийн эхлэлийн алдаа</h2>
      <div className="panel table-wrap">
        <p className="small muted">Эхлэл бүрээс {PERIOD_LONG[horizon]}-ын таамаглалын алдаа, зорилтот хугацааны өдрийн төлөвтэй. {ex.data.feature_behaviour.note}</p>
        <table>
          <thead><tr><th>Сүүлийн мэдэгдэх сар</th><th className="num">Сарын алдаа, %</th><th className="num">Нийт дүнгийн зөрүү</th><th>Зорилтот хугацааны өдрийн төлөв</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.origin_date}><td>{monthLabel(r.origin_date, true)}</td>
              <td className="num" title={r.wape?.undefined_reason || ""}>{r.wape?.value == null ? "тодорхойгүй" : `${(r.wape.value * 100).toFixed(0)}%`}</td>
              <td className="num">{fmt(r.sum?.value, 0)}</td>
              <td className="small">{Object.entries(r.states).map(([k, n]) => `${STATES[k].label} ${n}`).join(", ")}</td></tr>))}
          </tbody>
        </table>
        {ex.data.failures.length > 0 && <div className="notice warn">{ex.data.failures.length} эхлэлд загвар бүтэлгүйтэж {ex.data.failures[0].fallback_model} ажилласан: {ex.data.failures[0].reason}</div>}
      </div>
    </>
  );
}
