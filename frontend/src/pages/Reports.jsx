import { useMemo, useState } from "react";
import { api } from "../api.js";
import { go } from "../App.jsx";
import { ErrorNote, Help, Loading, Plot, plotLayout, useLoad } from "../components.jsx";
import { HORIZONS, PERIOD, PERIOD_LONG, accuracyLevel, MODEL_LABELS, fmt, monthLabel, pct, productLabel, PERIOD_OF, horizonsFor, PRELIM_NOTE } from "../labels.js";

// Categorical slots (validated default palette, fixed order). Өнгө ангиллыг дагана (эрэмбийг биш).
const SLOTS = ["#3a6ea5", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
const GRAY = "#8a949b", INK = "#3c474e";
const CLASS = {
  smooth: "Тогтвортой", erratic: "Хэлбэлзэлтэй", intermittent: "Тасалдалтай", lumpy: "Бөөгнөрсөн", unknown: "Тодорхойгүй",
};
const MONTHS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"];
const sum = (a) => a.reduce((s, v) => s + (v ?? 0), 0);
const sumStrict = (a) => (a.length && a.every((v) => v !== null && v !== undefined) ? sum(a) : null);
const median = (a) => {
  const v = a.filter((x) => x !== null && x !== undefined).sort((x, y) => x - y);
  if (!v.length) return null;
  const m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
};
const change = (a, b) => (a !== null && b ? a / b - 1 : null);
const chg = (c) => (c === null || c === undefined ? "—" : `${c >= 0 ? "▲" : "▼"} ${Math.abs(c * 100).toFixed(1)}%`);
const cfg = { displayModeBar: false, responsive: true };
const grid = "rgba(128,140,150,0.15)";

// Бүлэглэх: түлхүүр (ангилал / бүтээгдэхүүний нэр) бүрээр таамаглал, өмнөх өгөгдлийн ижил үе, сар бүрийн нийлбэр
function groupBy(series, keyFn, nMonths) {
  const g = {};
  for (const s of series) {
    const k = keyFn(s);
    const r = (g[k] ||= { key: k, n: 0, fc: 0, fcOk: true, ly: 0, lyOk: true, months: Array(nMonths).fill(0), wape: [], base: [], cats: new Set(), ids: [] });
    r.n += 1; r.ids.push(s.id); r.cats.add(s.category);
    if (s.total_forecast === null) r.fcOk = false; else r.fc += s.total_forecast;
    if (s.last_year === null) r.lyOk = false; else r.ly += s.last_year;
    s.forecast.forEach((v, i) => { r.months[i] += v ?? 0; });
    r.wape.push(s.test?.WAPE?.selected); r.base.push(s.test?.WAPE?.baseline);
  }
  return Object.values(g).map((r) => {
    const fc = r.fcOk ? r.fc : null, ly = r.lyOk ? r.ly : null;
    return { ...r, fc, ly, change: change(fc, ly), wapeMed: median(r.wape), baseMed: median(r.base) };
  }).sort((a, b) => (b.fc ?? -1) - (a.fc ?? -1));
}

export default function Reports({ params }) {
  const exps = useLoad(() => api.get("/experiments"), []);
  const done = (exps.data || []).filter((e) => e.status === "test_done" && !e.archived_at);
  const eid = params.experiment || done[0]?.id;
  const exp = done.find((e) => String(e.id) === String(eid));
  const H_LIST = horizonsFor(exp);
  const horizon = H_LIST.some(([h]) => h === Number(params.h)) ? Number(params.h) : H_LIST[H_LIST.length - 1][0];
  const rep = useLoad(() => (exps.data && eid ? api.get(`/reports/dashboard?experiment_id=${eid}&horizon=${horizon}`) : Promise.resolve(null)), [!!exps.data, eid, horizon]);
  const [cats, setCats] = useState([]);
  const [branch, setBranch] = useState("");
  const [products, setProducts] = useState([]);
  const [q, setQ] = useState("");
  const [view, setView] = useState("category");
  const [showAll, setShowAll] = useState(false);
  const r = rep.data;

  // Ангилал → өнгө: бүх ангиллын цагаан толгойн дарааллаар (шүүлтүүр өнгийг өөрчлөхгүй); 8-аас олон бол «бусад» саарал
  const catColor = useMemo(() => {
    const all = [...new Set((r?.series || []).map((s) => s.category))].sort((a, b) => a.localeCompare(b));
    return Object.fromEntries(all.map((c, i) => [c, i < SLOTS.length ? SLOTS[i] : GRAY]));
  }, [r]);

  const sel = useMemo(() => {
    if (!r) return [];
    const ql = q.trim().toLowerCase();
    return r.series.filter((s) => (!cats.length || cats.includes(s.category)) && (!branch || s.branch_id === branch)
      && (!products.length || products.includes(productLabel(s)))
      && (!ql || productLabel(s).toLowerCase().includes(ql) || s.product_id.toLowerCase().includes(ql)));
  }, [r, cats, branch, products, q]);

  const agg = useMemo(() => {
    if (!r) return null;
    const n = r.forecast_months.length;
    const hist = r.history_months.map((_, i) => sum(sel.map((s) => s.history[i])));
    const fc = r.forecast_months.map((_, i) => sum(sel.map((s) => s.forecast[i])));
    // өмнөх өгөгдлийн ижил сарууд: түүхийн массиваас (сүүлийн 24 сар) индексээр
    const lyIdx = r.forecast_months.map((m) => r.history_months.findIndex((h) => h === `${Number(m.slice(0, 4)) - 1}${m.slice(4)}`));
    const lyMonths = lyIdx.map((i) => (i >= 0 ? hist[i] : null));
    const total = sumStrict(sel.map((s) => s.total_forecast));
    const ly = sumStrict(sel.map((s) => s.last_year));
    const last12 = sum(hist.slice(-12));
    // Менежерийн гар засвар: тоо ба системийн анхны таамаглалаас зөрүү (нийт дүнд засвар орсон)
    const nAdj = sel.reduce((a, s) => a + (s.n_adjusted || 0), 0);
    const adjDelta = sel.reduce((a, s) => a + ((s.total_forecast ?? 0) - (s.total_system ?? s.total_forecast ?? 0)), 0);
    const pairs = sel.filter((s) => s.test?.WAPE?.selected != null && s.test?.WAPE?.baseline != null);
    return {
      hist, fc, lyMonths, total, ly, last12, change: change(total, ly), n, nAdj, adjDelta,
      wapeSel: median(sel.map((s) => s.test?.WAPE?.selected)), wapeBase: median(sel.map((s) => s.test?.WAPE?.baseline)),
      periodErr: median(sel.map((s) => s.test?.SUM_APE?.selected)),
      improved: pairs.length ? pairs.filter((s) => s.test.WAPE.selected < s.test.WAPE.baseline).length / pairs.length : null,
      byCat: groupBy(sel, (s) => s.category, n),
      byProduct: groupBy(sel, (s) => productLabel(s), n),
    };
  }, [r, sel]);

  const toggle = (list, set, v) => set(list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  const filtered = cats.length || branch || products.length || q;

  if (exps.loading) return <Loading />;
  if (!done.length) return (<><h1>Тайлан</h1><p className="muted">Бэлэн таамаглал алга.</p></>);
  const P = PERIOD[horizon];

  return (
    <div className="dash">
      <div className="dash-head">
        <div>
          <h1>Тайлан</h1>
          {r && <p className="muted small">{r.experiment.target_label} · {r.experiment.dataset} · {monthLabel(r.experiment.last_month, true)} хүртэл · {r.experiment.unit}</p>}
        </div>
        <div className="row no-print">
          <button className="quiet" onClick={() => api.download(`/reports/summary.xlsx?experiment_id=${eid}&horizon=${horizon}`, `report_exp${eid}_${horizon}m.xlsx`)}>Excel татах</button>
          <button className="quiet" onClick={() => window.print()}>Хэвлэх</button>
        </div>
      </div>

      <div className="slicers no-print">
        <div className="slicer-row">
          <div className="sl-exp"><label htmlFor="re">Таамаглал</label>
            <select id="re" value={eid} onChange={(e) => go("reports", { experiment: e.target.value, h: horizon })}>
              {done.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
            </select></div>
          <div><label>Хугацаа <Help k="horizon" /></label>
            <div className="seg">
              {H_LIST.map(([h, l]) => <button key={h} className={h === horizon ? "on" : ""} aria-pressed={h === horizon} onClick={() => go("reports", { experiment: eid, h })}>{l}</button>)}
            </div></div>
          {r && [...new Set(r.series.map((s) => s.branch_id))].length > 1 && <div><label htmlFor="rb">Салбар</label>
            <select id="rb" value={branch} onChange={(e) => setBranch(e.target.value)}>
              <option value="">Бүгд</option>
              {[...new Set(r.series.map((s) => s.branch_id))].map((b) => <option key={b}>{b}</option>)}
            </select></div>}
          <div className="sl-q"><label htmlFor="rq">Бараа хайх</label>
            <input id="rq" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Нэр эсвэл код" /></div>
        </div>
        {r && (
          <div className="cat-row" role="group" aria-label="Ангилал">
            <span className="cat-label">Ангилал <Help k="category" /></span>
            <div className="cats">
              <button className={`cat ${!cats.length ? "on" : ""}`} aria-pressed={!cats.length} onClick={() => setCats([])}>Бүгд</button>
              {Object.keys(catColor).map((c) => (
                <button key={c} className={`cat ${cats.includes(c) ? "on" : ""}`} aria-pressed={cats.includes(c)} onClick={() => toggle(cats, setCats, c)}
                        style={{ "--c": catColor[c] }}>
                  <i />{c}</button>))}
            </div>
            {filtered ? <button className="quiet mini" onClick={() => { setCats([]); setBranch(""); setProducts([]); setQ(""); }}>Шүүлтүүр цэвэрлэх</button> : null}
          </div>
        )}
      </div>
      {products.length > 0 && <p className="small">Сонгосон: <b>{products.join(", ")}</b></p>}

      {exp?.preliminary && <div className="notice warn small" role="status">{PRELIM_NOTE}</div>}
      <ErrorNote error={rep.error} />
      {rep.loading && !r ? <Loading /> : r && agg && (
        <>
          <div className="kpis">
            <Kpi label={r.experiment.target === "demand" ? "Сүүлийн 12 сарын эрэлт" : "Сүүлийн 12 сарын борлуулалт"} value={fmt(agg.last12, 0)} sub={`${r.experiment.unit}, ${sel.length} бараа`} />
            <Kpi label={`Таамаглал: ${PERIOD_LONG[horizon]}`} value={fmt(agg.total, 0)}
              sub={<>{agg.change === null ? r.experiment.unit : `${chg(agg.change)} өмнөх өгөгдлөөс`}
                {agg.nAdj > 0 && <><br />Гар засвар {agg.nAdj} сар ({agg.adjDelta >= 0 ? "+" : "−"}{fmt(Math.abs(agg.adjDelta), 0)}) орсон</>}</>} />
            <Kpi label={<>Найдвартай байдал <Help k="WAPE" /></>} value={accuracyLevel(agg.wapeSel, agg.wapeBase).label}
                 sub={`сарын алдаа ${pct(agg.wapeSel)} (энгийн арга ${pct(agg.wapeBase)})`} />
            {horizon > 1 && <Kpi label={<>{PERIOD_OF[horizon]} нийт дүнгийн алдаа <Help k="SUM_APE" /></>} value={pct(agg.periodErr)} sub={exp?.preliminary ? "өнгөрсөн 3 сараар шалгасан" : "өнгөрсөн 12 сараар шалгасан"} />}
            <Kpi label={<>Энгийн аргаас сайн <Help k="baseline" /></>} value={pct(agg.improved)} sub="барааны хувь" />
          </div>

          <div className="tiles">
            <Tile span={8} title={`Сарын борлуулалт ба ${PERIOD_OF[horizon].toLowerCase()} таамаглал`}
                  note="Цэнхэр: таамаглал. Тасархай шугам: өмнөх өгөгдлийн мөн сар.">
              <Plot data={[
                { x: r.history_months, y: agg.hist, name: r.experiment.target === "demand" ? "Өнгөрсөн эрэлт" : "Бодит борлуулалт", type: "bar", marker: { color: GRAY }, hovertemplate: "%{x|%Y.%m}: %{y:,.0f}<extra>Бодит</extra>" },
                { x: r.forecast_months, y: agg.fc, name: "Таамаглал", type: "bar", marker: { color: SLOTS[0] }, hovertemplate: "%{x|%Y.%m}: %{y:,.0f}<extra>Таамаглал</extra>" },
                { x: r.forecast_months, y: agg.lyMonths, name: "Өмнөх өгөгдлийн мөн сар", type: "scatter", mode: "lines+markers",
                  line: { color: INK, width: 2, dash: "dot" }, marker: { size: 8 }, hovertemplate: "%{y:,.0f}<extra>Өмнөх өгөгдлийн мөн сар</extra>" },
              ]} layout={plotLayout({ height: 320, bargap: 0.25, hovermode: "closest", xaxis: { type: "date", tickformat: "%Y.%m", dtick: "M3", gridcolor: grid },
                yaxis: { title: { text: `${r.experiment.unit} / сар` }, rangemode: "tozero", gridcolor: grid } })}
                style={{ width: "100%" }} useResizeHandler config={cfg} />
            </Tile>

            <Tile span={4} title="Ангиллын эзлэх хувь">
              <Plot data={[{ type: "pie", hole: 0.6, sort: false, direction: "clockwise",
                labels: agg.byCat.map((c) => c.key), values: agg.byCat.map((c) => c.fc ?? 0),
                marker: { colors: agg.byCat.map((c) => catColor[c.key]), line: { color: "#fff", width: 2 } },
                textinfo: "percent", hovertemplate: "%{label}: %{value:,.0f} (%{percent})<extra></extra>" }]}
                layout={plotLayout({ height: 320, showlegend: true, legend: { orientation: "h", y: -0.05 }, margin: { l: 8, r: 8, t: 8, b: 8 } })}
                onClick={(ev) => { const k = ev.points?.[0]?.label; if (k) toggle(cats, setCats, k); }}
                style={{ width: "100%" }} useResizeHandler config={cfg} />
            </Tile>

            <Tile span={horizon > 1 || !r.season ? (horizon > 1 ? 4 : 12) : 6} title={`Ангиллаар: ${PERIOD_OF[horizon].toLowerCase()} таамаглал`} note="Саарал: өмнөх өгөгдөл. Дарж шүүнэ.">
              <Plot data={[
                { type: "bar", orientation: "h", name: "Өмнөх өгөгдөл", y: [...agg.byCat].reverse().map((c) => c.key), x: [...agg.byCat].reverse().map((c) => c.ly),
                  marker: { color: GRAY }, hovertemplate: "%{y}: %{x:,.0f}<extra>Өмнөх өгөгдөл</extra>" },
                { type: "bar", orientation: "h", name: "Таамаглал", y: [...agg.byCat].reverse().map((c) => c.key), x: [...agg.byCat].reverse().map((c) => c.fc),
                  marker: { color: [...agg.byCat].reverse().map((c) => catColor[c.key]) }, hovertemplate: "%{y}: %{x:,.0f}<extra>Таамаглал</extra>" },
              ]} layout={plotLayout({ height: Math.max(260, agg.byCat.length * 46 + 70), barmode: "group", bargap: 0.3, bargroupgap: 0.08, hovermode: "closest",
                margin: { l: 110, r: 12, t: 8, b: 40 }, yaxis: { automargin: true }, xaxis: { rangemode: "tozero", gridcolor: grid } })}
                onClick={(ev) => { const k = ev.points?.[0]?.y; if (k) toggle(cats, setCats, k); }} style={{ width: "100%" }} useResizeHandler config={cfg} />
            </Tile>

            {horizon === 1 && r.season && (
              <Tile span={6} title="Он, сараар" note="Бараан өнгө: их борлуулалт.">
                <Plot data={[{ type: "heatmap", z: r.season.z, x: MONTHS, y: r.season.rows.map(String),
                  colorscale: [[0, "#e4ecf5"], [0.5, "#86a6cb"], [1, "#2f5687"]], xgap: 2, ygap: 2,
                  hovertemplate: "%{y} оны %{x}-р сар: %{z:,.0f}<extra></extra>", colorbar: { thickness: 10 } }]}
                  layout={plotLayout({ height: Math.max(260, r.season.rows.length * 34 + 90), yaxis: { autorange: "reversed", type: "category" }, xaxis: { title: { text: "сар" }, type: "category" }, hovermode: "closest" })}
                  style={{ width: "100%" }} useResizeHandler config={cfg} />
              </Tile>
            )}

            {horizon > 1 && (
              <Tile span={8} title="Сар бүрийн таамаглал ангиллаар">
                <Plot data={agg.byCat.map((c) => ({ type: "bar", name: c.key, x: r.forecast_months, y: c.months, marker: { color: catColor[c.key], line: { color: "#fff", width: 1 } },
                  hovertemplate: `${c.key}: %{y:,.0f}<extra></extra>` }))}
                  layout={plotLayout({ height: 320, barmode: "stack", bargap: 0.3, hovermode: "x unified", xaxis: { type: "date", tickformat: "%Y.%m", dtick: "M1", gridcolor: grid },
                    yaxis: { title: { text: r.experiment.unit }, rangemode: "tozero", gridcolor: grid } })}
                  style={{ width: "100%" }} useResizeHandler config={cfg} />
              </Tile>
            )}

            <Tile span={7} title="Хамгийн их таамагласан 15 бараа" note="Саарал: өмнөх өгөгдөл. Дарж шүүнэ.">
              <TopProducts rows={agg.byProduct} catColor={catColor} onPick={(p) => toggle(products, setProducts, p)} picked={products} />
            </Tile>
            <div className="tile-stack s-5">
              <Tile title="Хамгийн их өөрчлөгдөх бараа" note="Өмнөх өгөгдлийн мөн үетэй харьцуулсан. Дарж шүүнэ.">
                <Movers rows={agg.byProduct} onPick={(p) => toggle(products, setProducts, p)} />
              </Tile>
              <Tile title="Барааны найдвартай байдал" note="Бараа бүрийн сарын алдаагаар ангилсан.">
                <Reliability rows={sel} />
              </Tile>
            </div>



            {horizon > 1 && r.season && (
              <Tile span={6} title="Он, сараар" note="Бараан өнгө: их борлуулалт.">
                <Plot data={[{ type: "heatmap", z: r.season.z, x: MONTHS, y: r.season.rows.map(String),
                  colorscale: [[0, "#e4ecf5"], [0.5, "#86a6cb"], [1, "#2f5687"]], xgap: 2, ygap: 2,
                  hovertemplate: "%{y} оны %{x}-р сар: %{z:,.0f}<extra></extra>", colorbar: { thickness: 10 } }]}
                  layout={plotLayout({ height: Math.max(260, r.season.rows.length * 34 + 90), yaxis: { autorange: "reversed", type: "category" }, xaxis: { title: { text: "сар" }, type: "category" }, hovermode: "closest" })}
                  style={{ width: "100%" }} useResizeHandler config={cfg} />
              </Tile>
            )}

            <Tile span={horizon > 1 && r.season ? 6 : 12} title={<>Аргуудын сарын алдаа <Help k="WAPE" /></>} note="Бага нь сайн.">
              <MethodBars validation={r.validation} wide={!(horizon > 1 && r.season)} />
            </Tile>
          </div>

          <div className="tabs" role="tablist" style={{ marginTop: "1.5rem" }}>
            {[["category", "Ангиллаар"], ["product", "Бараагаар"], ["series", "Бараа, салбараар"]].map(([k, l]) => (
              <button key={k} role="tab" aria-selected={view === k} className={view === k ? "on" : ""} onClick={() => setView(k)}>{l}</button>))}
          </div>
          {view === "category" && <GroupTable rows={agg.byCat} label="Ангилал" months={r.forecast_months} total={agg.total} color={catColor} />}
          {view === "product" && <GroupTable rows={agg.byProduct} label="Бараа" months={r.forecast_months} total={agg.total} showCats limit={showAll ? undefined : 20}
            onMore={agg.byProduct.length > 20 ? () => setShowAll(!showAll) : null} showAll={showAll} />}
          {view === "series" && (
            <div className="panel table-wrap">
              <table>
                <thead><tr><th>Бараа</th><th>Ангилал</th><th>Салбар</th><th>Төрөл</th><th>Арга</th>
                  <th className="num">Таамаглал</th><th className="num">Өмнөх өгөгдөл</th><th className="num">Өөрчлөлт</th>
                  <th className="num">Сарын алдаа</th><th className="num">Энгийн арга</th><th></th></tr></thead>
                <tbody>{[...sel].sort((a, b) => (b.total_forecast ?? 0) - (a.total_forecast ?? 0)).slice(0, showAll ? undefined : 20).map((s) => (
                  <tr key={s.id}><td>{productLabel(s)}</td><td>{s.category}</td><td>{s.branch_id}</td><td>{CLASS[s.class]}</td><td>{MODEL_LABELS[s.model] || s.model}</td>
                    <td className="num">{fmt(s.total_forecast, 0)}</td><td className="num">{fmt(s.last_year, 0)}</td><td className="num">{chg(s.growth)}</td>
                    <td className="num">{pct(s.test?.WAPE?.selected)}</td><td className="num">{pct(s.test?.WAPE?.baseline)}</td>
                    <td><a href={`#/forecast?experiment=${eid}&series=${s.id}&h=${horizon}`}>Харах</a></td></tr>))}
                </tbody>
              </table>
              {sel.length > 20 && <button className="quiet" style={{ marginTop: 8 }} onClick={() => setShowAll(!showAll)}>{showAll ? "Хураах" : `Бүгдийг харах (${sel.length})`}</button>}
            </div>
          )}
          <p className="small muted">{r.note}</p>
        </>
      )}
    </div>
  );
}

function GroupTable({ rows, label, months, total, color, showCats, limit, onMore, showAll }) {
  const monthCols = months.length > 1 && months.length <= 12;
  return (
    <div className="panel table-wrap">
      <table>
        <thead><tr><th>{label}</th>{showCats && <th>Ангилал</th>}<th className="num">Тоо</th><th className="num">Таамаглал</th><th className="num">Эзлэх хувь</th>
          <th className="num">Өмнөх өгөгдөл</th><th className="num">Өөрчлөлт</th><th className="num">Сарын алдаа <Help k="WAPE" /></th>
          {monthCols && months.map((m) => <th key={m} className="num small">{monthLabel(m)}</th>)}</tr></thead>
        <tbody>{rows.slice(0, limit).map((g) => (
          <tr key={g.key}><td>{color && <i className="swatch" style={{ background: color[g.key] }} />}{g.key}</td>
            {showCats && <td className="small">{[...g.cats].join(", ")}</td>}
            <td className="num">{g.n}</td><td className="num"><b>{fmt(g.fc, 0)}</b></td>
            <td className="num">{total && g.fc !== null ? `${((g.fc / total) * 100).toFixed(1)}%` : "—"}</td>
            <td className="num">{fmt(g.ly, 0)}</td><td className="num">{chg(g.change)}</td>
            <td className="num" title={`энгийн арга ${pct(g.baseMed)}`}>{pct(g.wapeMed)}</td>
            {monthCols && g.months.map((v, i) => <td key={i} className="num small">{fmt(v, 0)}</td>)}</tr>))}
          <tr className="total"><td><b>Нийт</b></td>{showCats && <td />}<td className="num">{sum(rows.map((g) => g.n))}</td><td className="num"><b>{fmt(total, 0)}</b></td><td className="num">100%</td>
            <td className="num">{fmt(sumStrict(rows.map((g) => g.ly)), 0)}</td><td className="num">{chg(change(total, sumStrict(rows.map((g) => g.ly))))}</td><td />
            {monthCols && months.map((_, i) => <td key={i} className="num small">{fmt(sum(rows.map((g) => g.months[i])), 0)}</td>)}</tr>
        </tbody>
      </table>
      {onMore && <button className="quiet" style={{ marginTop: 8 }} onClick={onMore}>{showAll ? "Хураах" : `Бүгдийг харах (${rows.length})`}</button>}
    </div>
  );
}

function Kpi({ label, value, sub }) {
  return <div className="kpi"><span className="kpi-label">{label}</span><b>{value}</b><span className="kpi-sub">{sub}</span></div>;
}

function Tile({ title, note, span, children }) {
  return (
    <section className={`tile ${span ? `s-${span}` : ""}`}>
      <h3>{title}</h3>
      {children}
      {note && <p className="small muted" style={{ margin: "0.25rem 0 0" }}>{note}</p>}
    </section>
  );
}

function TopProducts({ rows, catColor, onPick, picked }) {
  const top = rows.slice(0, 15).reverse();
  const op = (p) => (!picked.length || picked.includes(p) ? 1 : 0.35);
  return (
    <Plot data={[
      { type: "bar", orientation: "h", name: "Өмнөх өгөгдөл", y: top.map((g) => g.key), x: top.map((g) => g.ly),
        marker: { color: GRAY, opacity: top.map((g) => op(g.key)) }, hovertemplate: "%{y}: %{x:,.0f}<extra>Өмнөх өгөгдөл</extra>" },
      { type: "bar", orientation: "h", name: "Таамаглал", y: top.map((g) => g.key), x: top.map((g) => g.fc),
        marker: { color: top.map((g) => catColor[[...g.cats][0]] || SLOTS[0]), opacity: top.map((g) => op(g.key)) },
        customdata: top.map((g) => [...g.cats].join(", ")), hovertemplate: "%{y} (%{customdata}): %{x:,.0f}<extra>Таамаглал</extra>" },
    ]} layout={plotLayout({ height: Math.max(320, top.length * 30 + 70), barmode: "group", bargap: 0.3, bargroupgap: 0.06, hovermode: "closest",
      margin: { l: 120, r: 12, t: 8, b: 40 }, yaxis: { automargin: true }, xaxis: { rangemode: "tozero", gridcolor: grid } })}
      onClick={(ev) => ev.points?.[0] && onPick(ev.points[0].y)} style={{ width: "100%" }} useResizeHandler config={cfg} />
  );
}

function MethodBars({ validation, wide }) {
  const labels = (v) => (MODEL_LABELS[v.model] || v.model) + (v.model === "ets" && v.params?.trend ? " (өсөлттэй)" : "");
  const keys = [...new Set(validation.map(labels))].reverse();
  return (
    <Plot data={HORIZONS.map(([h, l], i) => ({
      type: "bar", orientation: "h", name: l, y: keys, x: keys.map((k) => validation.find((v) => labels(v) === k && v.horizon === h)?.wape),
      marker: { color: SLOTS[i] }, hovertemplate: `%{y}, ${l}: %{x:.1%}<extra></extra>`,
    }))} layout={plotLayout({ height: Math.max(280, keys.length * (wide ? 30 : 40) + 70), barmode: "group", bargap: 0.25, bargroupgap: 0.06, hovermode: "closest",
      margin: { l: 150, r: 12, t: 30, b: 30 }, legend: { orientation: "h", x: 0, y: 1.08, xanchor: "left" },
      xaxis: { tickformat: ".0%", rangemode: "tozero", gridcolor: grid }, yaxis: { automargin: true } })}
      style={{ width: "100%" }} useResizeHandler config={cfg} />
  );
}

// Өмнөх өгөгдлийн мөн үеэс хамгийн их өсөх 5, буурах 5 бараа (хувиар)
function Movers({ rows, onPick }) {
  const ok = rows.filter((g) => g.change !== null && g.ly > 0);
  const up = [...ok].sort((a, b) => b.change - a.change).slice(0, 5).filter((g) => g.change > 0);
  const down = [...ok].sort((a, b) => a.change - b.change).slice(0, 5).filter((g) => g.change < 0);
  const list = [...down.reverse(), ...up.reverse()].reverse();
  if (!list.length) return <p className="small muted">Харьцуулах өмнөх өгөгдөл алга.</p>;
  const css = (n, d) => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || d;
  const okC = css("--ok", "#0f7b5a"), badC = css("--danger", "#c23b30");
  const rev = [...list].reverse();
  const pctTxt = (c) => `${c >= 0 ? "+" : "−"}${Math.abs(c * 100).toFixed(0)}%`;
  return (
    <Plot data={[{ type: "bar", orientation: "h", y: rev.map((g) => `${g.key}  ${pctTxt(g.change)}`), x: rev.map((g) => g.change),
      marker: { color: rev.map((g) => (g.change >= 0 ? okC : badC)) }, customdata: rev.map((g) => g.key),
      hovertemplate: "%{y}<extra></extra>" }]}
      layout={plotLayout({ height: Math.max(220, list.length * 26 + 50), margin: { l: 120, r: 16, t: 8, b: 24 }, showlegend: false, hovermode: "closest",
        xaxis: { tickformat: ".0%", zeroline: true, zerolinecolor: "rgba(128,140,150,0.6)", gridcolor: grid }, yaxis: { automargin: true } })}
      onClick={(ev) => ev.points?.[0] && onPick(ev.points[0].customdata)} style={{ width: "100%" }} useResizeHandler config={cfg} />
  );
}

// Хэдэн бараа «Сайн», «Дунд», «Сул» вэ (сарын алдаа ба энгийн аргатай харьцуулалтаар)
function Reliability({ rows }) {
  const order = [["Сайн", "--ok", "#0f7b5a"], ["Дунд", "--saffron", "#9a5b00"], ["Энгийн аргаас муу", "--ink-3", "#7a869a"], ["Сул", "--danger", "#c23b30"], ["Тодорхойгүй", "--line-2", "#cfd7e3"]];
  const counts = Object.fromEntries(order.map(([l]) => [l, 0]));
  for (const s of rows) counts[accuracyLevel(s.test?.WAPE?.selected, s.test?.WAPE?.baseline).label] += 1;
  const shown = order.filter(([l]) => counts[l] > 0);
  const total = rows.length || 1;
  const css = (n, d) => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || d;
  return (
    <div className="rel">
      <div className="rel-bar" role="img" aria-label={shown.map(([l]) => `${l} ${counts[l]}`).join(", ")}>
        {shown.map(([l, v, d]) => <span key={l} style={{ flex: counts[l], background: css(v, d) }} />)}
      </div>
      <ul>
        {shown.map(([l, v, d]) => (
          <li key={l}><i style={{ background: css(v, d) }} />{l}<b>{counts[l]}</b><span>{Math.round((counts[l] / total) * 100)}%</span></li>))}
      </ul>
    </div>
  );
}
