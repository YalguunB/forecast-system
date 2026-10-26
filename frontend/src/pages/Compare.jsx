import { useMemo } from "react";
import { api } from "../api.js";
import { go } from "../App.jsx";
import { ErrorNote, Loading, Plot, plotLayout, useLoad } from "../components.jsx";
import { MODEL_LABELS, fmt } from "../labels.js";

const PALETTE = ["#2c6cb0", "#3e7d5a", "#8e5bb5", "#c2851a", "#b5483b", "#4a8d9c"];

// FR-F4: загваруудыг ижил эхлэл дээр харьцуулах
export default function Compare({ params }) {
  const exps = useLoad(() => api.get("/experiments"), []);
  const list = (exps.data || []).filter((e) => ["validation_done", "locked", "test_done"].includes(e.status));
  const eid = params.experiment || list[0]?.id;
  const series = useLoad(() => (eid ? api.get(`/forecasts/series?experiment_id=${eid}`) : Promise.resolve([])), [eid]);
  const sid = params.series || series.data?.[0]?.series_id;
  const split = params.split || "validation";
  const cmp = useLoad(() => (eid && sid ? api.get(`/forecasts/compare?experiment_id=${eid}&series=${sid}&split=${split}${params.origin ? `&origin_date=${params.origin}` : ""}`) : Promise.resolve(null)), [eid, sid, split, params.origin]);
  const nav = (p) => go("compare", { experiment: eid, series: sid, split, origin: params.origin, ...p });
  const c = cmp.data;

  const traces = useMemo(() => {
    if (!c) return [];
    const before = c.values.filter((v) => !v.after_origin), after = c.values.filter((v) => v.after_origin);
    return [
      { x: before.map((v) => v.day), y: before.map((v) => v.value), name: "Түүх", mode: "lines", line: { color: "#7b8a92", width: 1.3 } },
      { x: after.map((v) => v.day), y: after.map((v) => v.value), name: "Бодит утга", mode: "markers", marker: { color: "#1b2b33", size: 6, symbol: "circle-open" } },
      ...c.runs.map((r, i) => ({ x: r.forecast.map((p) => p.target_date), y: r.forecast.map((p) => p.y_hat),
        name: `${MODEL_LABELS[r.model] || r.model}${r.role === "baseline" ? " (суурь)" : ""}`, mode: "lines",
        line: { color: PALETTE[i % PALETTE.length], width: 2, dash: r.role === "baseline" ? "dash" : "solid" } })),
    ];
  }, [c]);

  if (exps.loading) return <Loading />;
  return (
    <>
      <h1>Загвар харьцуулалт</h1>
      <p className="muted">Бүх загварыг нэг эхлэлээс, ижил түүхээр таамагласан. Validation-д бүх загвар, тестэд зөвхөн сонгосон ба суурь загвар харагдана.</p>
      {!list.length ? <p className="muted">Validation дууссан туршилт алга.</p> : (
        <div className="row" style={{ marginBottom: "1rem" }}>
          <div className="grow"><label htmlFor="e">Туршилт</label>
            <select id="e" value={eid} onChange={(e) => go("compare", { experiment: e.target.value })}>
              {list.map((e) => <option key={e.id} value={e.id}>#{e.id} {e.name} — {e.target_label}</option>)}
            </select></div>
          <div className="grow"><label htmlFor="s">Цуваа</label>
            <select id="s" value={sid || ""} onChange={(e) => nav({ series: e.target.value, origin: undefined })}>
              {(series.data || []).map((s) => <option key={s.series_id} value={s.series_id}>{s.product_id} / {s.branch_id} ({s.class})</option>)}
            </select></div>
          <div><label htmlFor="sp">Хуваалт</label>
            <select id="sp" value={split} onChange={(e) => nav({ split: e.target.value, origin: undefined })}>
              <option value="validation">Validation</option><option value="test">Тест</option>
            </select></div>
          {c && <div><label htmlFor="o">Эхлэл</label>
            <select id="o" value={c.origin_date} onChange={(e) => nav({ origin: e.target.value })}>
              {c.origins.map((o) => <option key={o} value={o}>{o}</option>)}
            </select></div>}
        </div>
      )}
      <ErrorNote error={cmp.error} />
      {c && (
        <>
          <div className="panel">
            <p className="small"><b>{c.target_label}</b>, {c.unit}, эхлэл {c.origin_date}</p>
            <Plot data={traces} useResizeHandler style={{ width: "100%", height: 380 }} config={{ displayModeBar: false, responsive: true }}
              layout={plotLayout({ shapes: [{ type: "line", x0: c.origin_date, x1: c.origin_date, yref: "paper", y0: 0, y1: 1, line: { dash: "dot", width: 1, color: "#7b8a92" } }] })} />
          </div>
          <div className="panel table-wrap">
            <table>
              <thead><tr><th>Загвар</th>{[7, 14, 30].map((h) => <th key={h} className="num">MASE H = {h}</th>)}<th className="num">Bias H = 30</th></tr></thead>
              <tbody>{c.runs.map((r) => (
                <tr key={r.run_id}><td>{MODEL_LABELS[r.model] || r.model}{r.role === "baseline" ? " (суурь)" : ""}</td>
                  {[7, 14, 30].map((h) => { const m = r.metrics[h]?.MASE; return <td key={h} className="num" title={m?.undefined_reason || ""}>{m ? (m.value === null ? "тодорхойгүй" : fmt(m.value, 3)) : "—"}</td>; })}
                  <td className="num">{fmt(r.metrics[30]?.Bias?.value, 2)}</td></tr>))}
              </tbody>
            </table>
            <p className="small muted">Нэг эхлэлийн алдаа санамсаргүй хэлбэлзэлтэй; загварын сонголтыг бүх эхлэл, цувааны дунджаар хийдэг (Туршилтын дэлгэц).</p>
          </div>
        </>
      )}
    </>
  );
}
