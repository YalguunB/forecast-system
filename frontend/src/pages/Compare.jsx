import { useMemo, useState } from "react";
import { api } from "../api.js";
import { go } from "../App.jsx";
import { ErrorNote, Help, Loading, Plot, plotLayout, useLoad } from "../components.jsx";
import { runName, seriesLabel, HORIZONS, MODEL_LABELS, fmt, monthLabel, pct, PERIOD_OF } from "../labels.js";

const PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
const runLabel = (r) => (MODEL_LABELS[r.model] || r.model) + (r.model === "ets" && r.params?.trend ? " (өсөлттэй)" : "") + (r.role === "baseline" ? " (энгийн арга)" : "");
const CLASS = { smooth: ["Тогтвортой", "Сар бүр жигд зарагддаг"], erratic: ["Хэлбэлзэлтэй", "Сар бүр, гэхдээ тогтворгүй"],
  intermittent: ["Тасалдалтай", "Зарим сард огт зарагддаггүй"], lumpy: ["Бөөгнөрсөн", "Ховор, их хэмжээгээр"], unknown: ["Тодорхойгүй", "Өгөгдөл хүрэлцээгүй"] };

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
      <h1>Аль арга хамгийн сайн бэ?</h1>
      <p className="muted">Бүх аргыг ижил сар, ижил бараан дээр шалгасан.</p>
      {!list.length ? <p className="muted">Туршсан таамаглал алга.</p> : (
        <div className="row" style={{ marginBottom: "1rem" }}>
          <div className="grow"><label htmlFor="e">Таамаглал</label>
            <select id="e" value={eid} onChange={(e) => go("compare", { experiment: e.target.value })}>
              {list.map((e) => <option key={e.id} value={e.id}>{e.name} ({e.target_label.toLowerCase()})</option>)}
            </select></div>
          <div className="grow"><label htmlFor="s">Бараа</label>
            <select id="s" value={sid || ""} onChange={(e) => nav({ series: e.target.value, origin: undefined })}>
              {(series.data || []).map((s) => <option key={s.series_id} value={s.series_id}>{seriesLabel(s)}{CLASS[s.class] ? ` · ${CLASS[s.class][0]}` : ""}</option>)}
            </select></div>
          <div><label htmlFor="sp">Шалгалт</label>
            <select id="sp" value={split} onChange={(e) => nav({ split: e.target.value, origin: undefined })}>
              <option value="validation">Туршилт</option><option value="test">Эцсийн шалгалт</option>
            </select></div>
          {c && <div><label htmlFor="o">Эхлэх сар</label>
            <select id="o" value={c.origin_date} onChange={(e) => nav({ origin: e.target.value })}>
              {c.origins.map((o) => <option key={o} value={o}>{monthLabel(o, true)}</option>)}
            </select></div>}
        </div>
      )}
      {eid && <Overview eid={eid} />}
      <h2>Нэг бараан дээр харах</h2>
      <p className="small muted">Цэг нь бодит борлуулалт.</p>
      <ErrorNote error={cmp.error} />
      {c && (
        <>
          <div className="panel">
            <p className="small"><b>{c.target_label}</b>, {c.unit} / сар, {monthLabel(c.origin_date, true)}-аас</p>
            <Plot data={traces} useResizeHandler style={{ width: "100%", height: 380 }} config={{ displayModeBar: false, responsive: true }}
              layout={plotLayout({ xaxis: { type: "date", tickformat: "%Y.%m", gridcolor: "rgba(128,140,150,0.15)" }, shapes: [{ type: "line", x0: c.origin_date, x1: c.origin_date, yref: "paper", y0: 0, y1: 1, line: { dash: "dot", width: 1, color: "#7b8a92" } }] })} />
          </div>
          <div className="panel table-wrap">
            <table>
              <thead><tr><th>Арга</th>{HORIZONS.map(([h, l]) => <th key={h} className="num">{PERIOD_OF[h]} алдаа</th>)}<th className="num">Хазайлт, улирал</th></tr></thead>
              <tbody>{c.runs.map((r) => (
                <tr key={r.run_id}><td>{runLabel(r)}</td>
                  {HORIZONS.map(([h]) => { const m = r.metrics[h]?.WAPE; return <td key={h} className="num" title={m?.undefined_reason || ""}>{m ? (m.value === null ? "тодорхойгүй" : pct(m.value)) : "—"}</td>; })}
                  <td className="num">{fmt(r.metrics[3]?.Bias?.value, 1)}</td></tr>))}
              </tbody>
            </table>
            <p className="small muted">«—»: хугацаа хараахан өнгөрөөгүй.</p>
          </div>
        </>
      )}
    </>
  );
}

// Бүх барааны дүгнэлт: энгийн аргаас хэр сайн, арга бүрийн алдаа, хэв шинжээр
function Overview({ eid }) {
  const rep = useLoad(() => api.get(`/experiments/${eid}/report`), [eid]);
  const [hz, setHz] = useState(1);
  const r = rep.data;
  if (!r) return rep.loading ? <Loading /> : <ErrorNote error={rep.error} />;
  const t = r.test.find((x) => x.horizon === hz);
  const val = r.validation.filter((v) => v.horizon === hz && v.mean != null);
  const base = val.find((v) => v.model.startsWith("ma"));
  const rows = [...val].sort((a, b) => a.mean - b.mean);
  const selCounts = r.selection[hz]?.counts || {};
  const cls = r.by_class.filter((x) => x.horizon === hz);
  return (
    <>
      <div className="tabs" role="tablist">
        {HORIZONS.map(([h, l]) => <button key={h} role="tab" aria-selected={hz === h} className={hz === h ? "on" : ""} onClick={() => setHz(h)}>{PERIOD_OF[h]} таамаглал</button>)}
      </div>
      {t && !t.n_compared && (
        <div className="notice warn">{PERIOD_OF[hz]} таамаглалын алдааг хэмжих боломжгүй. Шалгах хугацаа богино.</div>
      )}
      {t && t.n_compared > 0 && (
        <div className="summary">
          <div className="big">{pct(t.share_improved_vs_baseline)}<small>бараанд энгийн аргаас сайн</small></div>
          <div>
            <p>Сонгосон арга {t.n_compared} барааны <b>{Math.round((t.share_improved_vs_baseline ?? 0) * t.n_compared)}</b>-д энгийн аргаас (3 сарын дундаж) бага алдсан.</p>
          </div>
        </div>
      )}
      <div className="panel table-wrap">
        <h3 style={{ marginTop: 0 }}>Арга бүрийн дүн</h3>
        <table>
          <thead><tr><th>Арга</th><th>Энгийн аргатай харьцуулахад <Help k="WAPE" /></th><th className="num">Сарын алдаа</th><th className="num">Сонгосон бараа</th></tr></thead>
          <tbody>{rows.map((v) => {
            const isBase = v === base;
            const d = base && !isBase ? v.mean / base.mean - 1 : null;
            const n = Object.entries(selCounts).filter(([k]) => k === v.model).reduce((a, [, x]) => a + x, 0);
            return (
              <tr key={v.model} style={isBase ? { background: "var(--paper)" } : null}>
                <td>{runName(v.model)}{isBase ? <> <span className="badge">Энгийн арга</span></> : null}</td>
                <td>{isBase ? <span className="muted small">Бусдыг үүнтэй харьцуулна</span>
                  : <span style={{ color: d <= 0 ? "var(--ok)" : "var(--danger)", fontWeight: 600 }}>{Math.abs(d * 100).toFixed(0)}% {d <= 0 ? "бага алддаг" : "их алддаг"}</span>}</td>
                <td className="num">{pct(v.mean)}</td>
                <td className="num">{n ? <span className="badge ok">{n}</span> : <span className="muted">—</span>}</td>
              </tr>);
          })}</tbody>
        </table>
      </div>
      {cls.length > 0 && (
        <>
          <h3>Борлуулалтын төрлөөр <Help k="class" /></h3>
          <div className="grp-cards">{cls.map((x) => {
            const [name, desc] = CLASS[x.class] || [x.class, ""];
            const better = x.selected.median != null && x.baseline.median != null && x.selected.median < x.baseline.median;
            return (
              <div key={x.class}>
                <b>{name} <span className="muted" style={{ fontWeight: 400 }}>· {x.selected.n} бараа</span></b>
                <span className="muted">{desc}</span>
                <span>Сарын алдаа <b>{pct(x.selected.median)}</b> (энгийн арга {pct(x.baseline.median)})</span>
                <span className={`badge ${better ? "ok" : "warn"}`} style={{ alignSelf: "flex-start" }}>{better ? "Энгийн аргаас сайн" : "Энгийн аргаас сайн биш"}</span>
              </div>);
          })}</div>
        </>
      )}
    </>
  );
}
