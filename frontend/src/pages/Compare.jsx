import { useMemo } from "react";
import { api } from "../api.js";
import { go } from "../App.jsx";
import { ErrorNote, Loading, Plot, plotLayout, useLoad } from "../components.jsx";
import { seriesLabel, HORIZONS, MODEL_LABELS, fmt, monthLabel, pct } from "../labels.js";

const PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
const runLabel = (r) => (MODEL_LABELS[r.model] || r.model) + (r.model === "ets" && r.params?.trend ? " + тренд" : "") + (r.role === "baseline" ? " (суурь)" : "");

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
      { x: before.map((v) => v.month), y: before.map((v) => v.value), name: "Түүх", mode: "lines+markers", marker: { size: 4 }, line: { color: "#7b8a92", width: 1.5 } },
      { x: after.map((v) => v.month), y: after.map((v) => v.value), name: "Бодит утга", mode: "markers", marker: { color: "#1b2b33", size: 9, symbol: "circle-open", line: { width: 2 } } },
      ...c.runs.map((r, i) => ({ x: r.forecast.map((p) => p.target_date), y: r.forecast.map((p) => p.y_hat),
        name: runLabel(r), mode: "lines",
        line: { color: PALETTE[i % PALETTE.length], width: 2, dash: r.role === "baseline" ? "dash" : "solid" } })),
    ];
  }, [c]);

  if (exps.loading) return <Loading />;
  return (
    <>
      <h1>Харьцуулалт</h1>
      <p className="muted">Нэг бүтээгдэхүүн дээр бүх аргын 12 сарын таамаглалыг нэг сараас эхлүүлж, бодит борлуулалттай (цэг) хамт харуулна. Аль арга яагаад сонгогдсоныг ойлгоход тусална.</p>
      {!list.length ? <p className="muted">Аргуудыг туршсан таамаглал алга.</p> : (
        <div className="row" style={{ marginBottom: "1rem" }}>
          <div className="grow"><label htmlFor="e">Таамаглал</label>
            <select id="e" value={eid} onChange={(e) => go("compare", { experiment: e.target.value })}>
              {list.map((e) => <option key={e.id} value={e.id}>#{e.id} {e.name} — {e.target_label}</option>)}
            </select></div>
          <div className="grow"><label htmlFor="s">Бүтээгдэхүүн</label>
            <select id="s" value={sid || ""} onChange={(e) => nav({ series: e.target.value, origin: undefined })}>
              {(series.data || []).map((s) => <option key={s.series_id} value={s.series_id}>{seriesLabel(s)} ({s.class})</option>)}
            </select></div>
          <div><label htmlFor="sp">Үе</label>
            <select id="sp" value={split} onChange={(e) => nav({ split: e.target.value, origin: undefined })}>
              <option value="validation">Арга сонгох үе</option><option value="test">Эцсийн шалгалтын үе</option>
            </select></div>
          {c && <div><label htmlFor="o">Сүүлийн мэдэгдэх сар</label>
            <select id="o" value={c.origin_date} onChange={(e) => nav({ origin: e.target.value })}>
              {c.origins.map((o) => <option key={o} value={o}>{monthLabel(o, true)}</option>)}
            </select></div>}
        </div>
      )}
      <ErrorNote error={cmp.error} />
      {c && (
        <>
          <div className="panel">
            <p className="small"><b>{c.target_label}</b>, {c.unit} / сар, сүүлийн мэдэгдэх сар {monthLabel(c.origin_date, true)}</p>
            <Plot data={traces} useResizeHandler style={{ width: "100%", height: 380 }} config={{ displayModeBar: false, responsive: true }}
              layout={plotLayout({ xaxis: { type: "date", tickformat: "%Y.%m", gridcolor: "rgba(128,140,150,0.15)" }, shapes: [{ type: "line", x0: c.origin_date, x1: c.origin_date, yref: "paper", y0: 0, y1: 1, line: { dash: "dot", width: 1, color: "#7b8a92" } }] })} />
          </div>
          <div className="panel table-wrap">
            <table>
              <thead><tr><th>Арга</th>{HORIZONS.map(([h, l]) => <th key={h} className="num">Сарын алдаа: {l}</th>)}<th className="num">Хэлбийлт: улирал</th></tr></thead>
              <tbody>{c.runs.map((r) => (
                <tr key={r.run_id}><td>{runLabel(r)}</td>
                  {HORIZONS.map(([h]) => { const m = r.metrics[h]?.WAPE; return <td key={h} className="num" title={m?.undefined_reason || (m ? "" : "энэ эхлэлээс бүтэн хугацаа ажиглагдаагүй")}>{m ? (m.value === null ? "тодорхойгүй" : pct(m.value)) : "—"}</td>; })}
                  <td className="num">{fmt(r.metrics[3]?.Bias?.value, 1)}</td></tr>))}
              </tbody>
            </table>
            <p className="small muted">«—» = энэ эхлэлээс тухайн хугацаа бүтэн ажиглагдаагүй (жишээ нь жилийн алдааг зөвхөн эхний эхлэлээс хэмжинэ). Нэг эхлэлийн алдаа санамсаргүй хэлбэлзэлтэй; загварын сонголтыг бүх эхлэл, цувааны дунджаар хийдэг (Туршилтын дэлгэц).</p>
          </div>
        </>
      )}
    </>
  );
}
