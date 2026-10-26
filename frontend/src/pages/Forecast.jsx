import { useMemo, useState } from "react";
import { api } from "../api.js";
import { go } from "../App.jsx";
import { ErrorNote, Loading, Plot, StateLegend, plotLayout, useLoad } from "../components.jsx";
import { MODEL_LABELS, STATES, fmt } from "../labels.js";

const METRIC_LABELS = { MASE: "MASE", RMSSE: "RMSSE", WAPE: "WAPE", MAE: "MAE", Bias: "Хазайлт (Bias)", SUM_AE: "H хоногийн нийлбэрийн алдаа",
  COVERAGE: "Интервалын хамралт", WIDTH: "Интервалын өргөн", PINBALL: "Pinball", RMSE: "RMSE" };

// UC-03, 05, 06, 07 нэг дэлгэцэд (Зураг 4.3)
export default function Forecast({ params, user }) {
  const exps = useLoad(() => api.get("/experiments"), []);
  const done = (exps.data || []).filter((e) => e.status === "test_done");
  const eid = params.experiment || done[0]?.id;
  const series = useLoad(() => (eid ? api.get(`/forecasts/series?experiment_id=${eid}`) : Promise.resolve([])), [eid]);
  const sid = params.series || series.data?.[0]?.series_id;
  const horizon = Number(params.h || 30);
  const split = params.split || "live";
  const origin = params.origin;
  const fc = useLoad(() => (eid && sid ? api.get(`/forecasts?experiment_id=${eid}&series=${sid}&horizon=${horizon}&split=${split}${origin ? `&origin_date=${origin}` : ""}${params.run ? `&run_id=${params.run}` : ""}`) : Promise.resolve(null)),
    [eid, sid, horizon, split, origin, params.run]);
  const nav = (patch) => go("forecast", { experiment: eid, series: sid, h: horizon, split, origin, run: params.run, ...patch });
  const isAnalyst = user.roles.includes("analyst");
  const canExport = ["analyst", "manager", "researcher"].some((r) => user.roles.includes(r));

  if (exps.loading) return <Loading />;
  if (!done.length) return (<><h1>Таамаглал</h1><p className="muted">Тест нь дууссан туршилт алга. Судлаач туршилтыг түгжиж тестийг ажиллуулсны дараа таамаглал энд гарна.</p></>);
  const f = fc.data;
  return (
    <>
      <div className="row" style={{ marginBottom: "1rem" }}>
        <div className="grow"><label htmlFor="e">Туршилт</label>
          <select id="e" value={eid} onChange={(e) => go("forecast", { experiment: e.target.value })}>
            {done.map((e) => <option key={e.id} value={e.id}>#{e.id} {e.name} — {e.target_label}</option>)}
          </select></div>
        <div className="grow"><label htmlFor="s">Бүтээгдэхүүн / салбар</label>
          <select id="s" value={sid || ""} onChange={(e) => nav({ series: e.target.value, origin: undefined, run: undefined })}>
            {(series.data || []).map((s) => <option key={s.series_id} value={s.series_id}>{s.product_id} / {s.branch_id} ({s.class})</option>)}
          </select></div>
        <div><label>Хүрээ</label>
          <div className="tabs" role="tablist" style={{ margin: 0 }}>
            {[7, 14, 30].map((h) => <button key={h} role="tab" aria-selected={h === horizon} className={h === horizon ? "on" : ""} onClick={() => nav({ h, run: undefined })}>{h} хоног</button>)}
          </div></div>
        <div><label htmlFor="sp">Харах</label>
          <select id="sp" value={split} onChange={(e) => nav({ split: e.target.value, origin: undefined, run: undefined })}>
            <option value="live">Ирээдүйн таамаглал</option><option value="test">Тестийн үе (бодит утгатай)</option>
          </select></div>
      </div>
      <ErrorNote error={fc.error} />
      {fc.loading && !f ? <Loading /> : f && (
        <>
          <div className="target-banner" aria-label="Таамаглалын тодорхойлолт">
            <span className="target">{f.target_label}</span>
            <span className="fact">Нэгж <b>{f.unit}</b></span>
            <span className="fact">Эхлэл <b>{f.origin_date}</b></span>
            <span className="fact">Хүрээ <b>{f.horizon} хоног</b></span>
            <span className="fact">Загвар <b>{MODEL_LABELS[f.model] || f.model}</b></span>
            <span className="fact">run <b>{f.run_id}</b></span>
            <span className="fact">Өгөгдөл <b>{f.experiment.dataset} v{f.experiment.version_no}</b></span>
          </div>
          {split === "test" && (
            <div className="row" style={{ marginBottom: "0.5rem" }}>
              <div><label htmlFor="o">Тестийн эхлэл</label>
                <select id="o" value={f.origin_date} onChange={(e) => nav({ origin: e.target.value })}>
                  {f.origins.map((o) => <option key={o} value={o}>{o}</option>)}
                </select></div>
              <div><label htmlFor="r">Загвар</label>
                <select id="r" value={f.run_id} onChange={(e) => nav({ run: e.target.value })}>
                  {f.available_runs.map((r) => <option key={r.run_id} value={r.run_id}>{MODEL_LABELS[r.model] || r.model} ({r.role === "baseline" ? "суурь" : "сонгосон"})</option>)}
                </select></div>
            </div>
          )}
          <div className="split">
            <div className="panel">
              <ForecastChart f={f} />
              {!f.interval.available && <p className="small muted">Энэ загвар таамаглалын интервал гаргадаггүй тул зурвас зураагүй.</p>}
            </div>
            <div>
              <Metrics f={f} />
              {isAnalyst && split === "live" && <Adjust f={f} onSaved={fc.reload} />}
              {f.adjusted.length > 0 && (
                <div className="panel small">
                  <h3 style={{ marginTop: 0 }}>Залруулга</h3>
                  <p className="muted">Анхны таамаглал хэвээр хадгалагдсан; залруулга тусдаа шугамаар харагдана.</p>
                  {f.adjusted.map((a) => <div key={a.target_date}>{a.target_date}: {fmt(a.original_value)} → <b>{fmt(a.adjusted_value)}</b> — {a.reason} ({a.username})</div>)}
                </div>
              )}
              {canExport && (
                <div className="panel">
                  <h3 style={{ marginTop: 0 }}>Экспорт</h3>
                  <p className="small muted">Мөр бүрд зорилтын нэр, хувилбар, залруулга тусдаа баганаар орно.</p>
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

function ForecastChart({ f }) {
  const traces = useMemo(() => {
    const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
    const sky = css("--sky") || "#2c6cb0", saffron = css("--saffron") || "#c2851a", ink = css("--ink-2") || "#4a5a63";
    const t = [];
    const days = [...f.history, ...f.actual];
    t.push({ x: f.history.map((h) => h.day), y: f.history.map((h) => h.value), name: "Түүх (зорилтын утга)", type: "scatter",
      mode: "lines", line: { color: ink, width: 1.4 }, connectgaps: false, hovertemplate: "%{y:.1f}" });
    if (f.actual.length) t.push({ x: f.actual.map((h) => h.day), y: f.actual.map((h) => h.value), name: "Бодит утга", type: "scatter",
      mode: "markers", marker: { color: ink, size: 6, symbol: "circle-open" }, hovertemplate: "%{y:.1f}" });
    if (f.interval.available) {
      t.push({ x: f.forecast.map((p) => p.target_date), y: f.forecast.map((p) => p.q_hi), type: "scatter", mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip" });
      t.push({ x: f.forecast.map((p) => p.target_date), y: f.forecast.map((p) => p.q_lo), type: "scatter", mode: "lines", line: { width: 0 },
        fill: "tonexty", fillcolor: "rgba(44,108,176,0.15)", name: "80% интервал", hoverinfo: "skip" });
    }
    t.push({ x: f.forecast.map((p) => p.target_date), y: f.forecast.map((p) => p.y_hat), name: "Загварын таамаглал", type: "scatter",
      mode: "lines+markers", line: { color: sky, width: 2.4 }, marker: { size: 4 }, hovertemplate: "%{y:.1f}" });
    if (f.adjusted.length) t.push({ x: f.adjusted.map((a) => a.target_date), y: f.adjusted.map((a) => a.adjusted_value), name: "Хэрэглэгчийн залруулга",
      type: "scatter", mode: "markers", marker: { color: saffron, size: 10, symbol: "diamond" }, hovertemplate: "%{y:.1f}" });
    // Өдрийн төлвийн тууз — гүйлгээгүй өдөр бүрийн шалтгаан графикийн доор (FR-F3)
    for (const [k, s] of Object.entries(STATES)) {
      const pts = days.filter((d) => d.state === k);
      if (!pts.length) continue;
      t.push({ x: pts.map((d) => d.day), y: pts.map(() => 1), type: "bar", yaxis: "y2", name: s.label, marker: { color: s.color },
        showlegend: false, hovertemplate: `${s.label}<extra></extra>`, width: 86400000 * 0.9 });
    }
    return t;
  }, [f]);
  const states = [...new Set([...f.history, ...f.actual].map((d) => d.state))];
  return (
    <>
      <Plot data={traces} useResizeHandler style={{ width: "100%", height: 420 }} config={{ displayModeBar: false, responsive: true }}
        layout={plotLayout({
          yaxis: { domain: [0.12, 1], gridcolor: "rgba(128,140,150,0.15)", rangemode: "tozero", title: { text: f.unit } },
          yaxis2: { domain: [0, 0.07], showticklabels: false, showgrid: false, fixedrange: true, range: [0, 1] },
          bargap: 0, barmode: "overlay",
          shapes: [{ type: "line", x0: f.origin_date, x1: f.origin_date, yref: "paper", y0: 0, y1: 1, line: { dash: "dot", width: 1, color: "#7b8a92" } }],
          annotations: [{ x: f.origin_date, yref: "paper", y: 1, text: "эхлэл", showarrow: false, xanchor: "left", font: { size: 11 } }],
        })} />
      <StateLegend states={states} />
    </>
  );
}

function Metrics({ f }) {
  if (!f.test_metrics.length) return null;
  const by = {};
  for (const m of f.test_metrics) (by[m.metric] ||= {})[m.role === "baseline" ? "base" : "sel"] = m;
  const order = ["MASE", "WAPE", "MAE", "Bias", "SUM_AE", "COVERAGE"].filter((k) => by[k]);
  return (
    <div className="panel">
      <h3 style={{ marginTop: 0 }}>Тестийн алдаа, {f.horizon} хоног</h3>
      <p className="small muted">9 тестийн эхлэлийн дундаж. Суурь нь seasonal naive.</p>
      <table>
        <thead><tr><th>Хэмжүүр</th><th className="num">{MODEL_LABELS[f.model] || f.model}</th><th className="num">Суурь</th></tr></thead>
        <tbody>{order.map((k) => (
          <tr key={k}><td>{METRIC_LABELS[k]}</td>
            {["sel", "base"].map((w) => {
              const m = by[k][w];
              return <td key={w} className="num" title={m?.undefined_reason || ""}>{m ? (m.value === null ? "тодорхойгүй" : k === "WAPE" || k === "COVERAGE" ? `${(m.value * 100).toFixed(0)}%` : fmt(m.value, 3)) : "—"}</td>;
            })}</tr>))}
        </tbody>
      </table>
      <div className="small muted" style={{ marginTop: 8 }}>
        Өдрийн төлөв: {Object.entries(f.data_states).map(([, v]) => `${v.label} ${v.n}`).join(", ")}
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
      <h3 style={{ marginTop: 0 }}>Залруулга бүртгэх</h3>
      <label htmlFor="ad">Огноо</label>
      <select id="ad" value={date} onChange={(e) => setDate(e.target.value)}>
        {f.forecast.map((p) => <option key={p.target_date} value={p.target_date}>{p.target_date} — загвар {fmt(p.y_hat, 1)}</option>)}
      </select>
      <label htmlFor="av" style={{ marginTop: 8 }}>Залруулсан утга ({f.unit})</label>
      <input id="av" type="number" min="0" step="any" value={value} onChange={(e) => setValue(e.target.value)} placeholder={fmt(orig, 1)} />
      <label htmlFor="ar" style={{ marginTop: 8 }}>Шалтгаан</label>
      <input id="ar" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Жишээ: урамшуулал төлөвлөсөн" />
      <button className="warn" style={{ marginTop: 8 }} disabled={value === "" || reason.trim().length < 3} onClick={async () => {
        setErr(null);
        try {
          await api.post("/adjustments", { run_id: f.run_id, series_id: f.series.id, target_date: date, adjusted_value: Number(value), reason });
          setValue(""); setReason(""); onSaved();
        } catch (x) { setErr(x); }
      }}>Залруулга хадгалах</button>
      <ErrorNote error={err} />
    </div>
  );
}

function Explain({ runId, sid, horizon }) {
  const ex = useLoad(() => api.get(`/forecasts/${runId}/explain?series=${sid}`), [runId, sid]);
  if (!ex.data) return null;
  const rows = ex.data.target_windows.map((w) => ({
    ...w, mase: ex.data.per_origin.find((p) => p.origin_date === w.origin_date && p.horizon === horizon && p.metric === "MASE"),
  }));
  return (
    <>
      <h2>Алдааг тайлбарлах</h2>
      <div className="panel table-wrap">
        <p className="small muted">Эхлэл бүрийн алдааг зорилтот 30 өдрийн төлөвтэй зэрэгцүүлэв. {ex.data.feature_behaviour.note}</p>
        <table>
          <thead><tr><th>Эхлэл</th><th className="num">MASE (H = {horizon})</th><th className="num">Тэгтэй өдөр</th><th>Зорилтот цонхны төлөв</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.origin_date}><td>{r.origin_date}</td>
              <td className="num" title={r.mase?.undefined_reason || ""}>{r.mase?.value === null ? "тодорхойгүй" : fmt(r.mase?.value, 3)}</td>
              <td className="num">{r.zero_days}</td>
              <td className="small">{Object.entries(r.states).map(([k, n]) => `${STATES[k].label} ${n}`).join(", ")}</td></tr>))}
          </tbody>
        </table>
        {ex.data.failures.length > 0 && <div className="notice warn">{ex.data.failures.length} эхлэлд загвар бүтэлгүйтэж {ex.data.failures[0].fallback_model} ажилласан: {ex.data.failures[0].reason}</div>}
      </div>
    </>
  );
}
