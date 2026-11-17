import { useState } from "react";
import { api } from "../api.js";
import { go } from "../App.jsx";
import { ErrorNote, Help, Intro, Loading, Plot, plotLayout, useLoad } from "../components.jsx";
import { HORIZONS, MODEL_LABELS, fmt, monthLabel, pct, seriesLabel, horizonsFor, PRELIM_NOTE } from "../labels.js";

// Гүйцэтгэл (FR-05, FR-15): таамаглал гаргаснаас хойш бодит өгөгдөл ирсэн саруудад таамаглалыг бодит утгатай харьцуулна.
// Бодит утга бүрдээгүй сарыг харьцуулалтад оруулахгүй, алдааг тэг гэж харуулахгүй (NFR-13).
const GRAY = "#8a949b", BLUE = "#146ef5";

// Бодит гүйцэтгэлийн үнэлгээ: сарын алдаа (WAPE) ба хазайлтаас энгийн үгээр
export function trackGrade(wape) {
  if (wape === null || wape === undefined) return { label: "Тодорхойгүй", tone: "" };
  if (wape < 0.2) return { label: "Сайн таарсан", tone: "ok" };
  if (wape < 0.4) return { label: "Дунд зэрэг", tone: "warn" };
  return { label: "Их зөрсөн", tone: "bad" };
}
export const biasText = (b) => (b === null || b === undefined ? "" : Math.abs(b) < 0.03 ? "Илүү, дутуу аль аль талдаа хазайгаагүй."
  : b > 0 ? `Нийтдээ ${pct(b)} илүү таамагласан.` : `Нийтдээ ${pct(-b)} дутуу таамагласан.`);

export default function Tracking({ params }) {
  const exps = useLoad(() => api.get("/experiments"), []);
  const done = (exps.data || []).filter((e) => e.status === "test_done" && !e.archived_at);
  const eid = params.experiment || done[0]?.id;
  const exp = done.find((e) => String(e.id) === String(eid));
  const H_LIST = horizonsFor(exp);
  const horizon = H_LIST.some(([h]) => h === Number(params.h)) ? Number(params.h) : H_LIST[H_LIST.length - 1][0];
  const tr = useLoad(() => (exps.data && eid ? api.get(`/forecasts/tracking?experiment_id=${eid}&horizon=${horizon}`) : Promise.resolve(null)), [!!exps.data, eid, horizon]);
  const [open, setOpen] = useState(null);
  const [q, setQ] = useState("");
  const t = tr.data;
  const set = (p) => go("tracking", { experiment: eid, h: horizon, ...p });

  if (exps.loading) return <Loading />;
  if (!done.length) return (<><h1>Гүйцэтгэл</h1><Intro><p>Бэлэн таамаглал алга. Эхлээд таамаглал гаргуулна уу.</p></Intro></>);

  const what = t?.experiment.target === "demand" ? "эрэлт" : "борлуулалт";
  const whatWith = what === "эрэлт" ? "эрэлттэй" : "борлуулалттай";
  const unit = t?.unit || "";
  const o = t?.overall;
  const g = trackGrade(o?.wape);
  const items = (t?.items || []).filter((it) => !q || seriesLabel(it).toLowerCase().includes(q.toLowerCase()) || it.product_id.toLowerCase().includes(q.toLowerCase()));

  return (
    <>
      <h1>Гүйцэтгэл</h1>
      <p className="muted">Таамаглал бодит {whatWith} хэр таарсныг харна.</p>
      <div className="slicers">
        <div className="slicer-row">
          <div><label htmlFor="te">Таамаглал</label>
            <select id="te" value={eid} onChange={(e) => set({ experiment: e.target.value })}>
              {done.map((e) => <option key={e.id} value={e.id}>{e.name} ({e.target_label.toLowerCase()})</option>)}
            </select></div>
          <div><label>Хугацаа <Help k="horizon" /></label>
            <div className="seg" role="tablist">
              {H_LIST.map(([h, l]) => <button key={h} role="tab" aria-selected={horizon === h} className={horizon === h ? "on" : ""} onClick={() => set({ h })}>{l}</button>)}
            </div></div>
          <div><label htmlFor="tq">Бараа хайх</label>
            <input id="tq" value={q} placeholder="Нэр эсвэл код" onChange={(e) => setQ(e.target.value)} /></div>
        </div>
      </div>
      {exp?.preliminary && <div className="notice warn small" role="status">{PRELIM_NOTE}</div>}
      <ErrorNote error={tr.error} />
      {tr.loading && <Loading what="Харьцуулж байна" />}

      {t && !t.available && (
        <Intro>
          <p><b>Харьцуулах бодит өгөгдөл алга.</b> {t.message}</p>
          {t.reason === "no_new_data" && (
            <>
              <ol>
                <li>«Өгөгдөл оруулах» хэсэгт <b>«{t.experiment.dataset}»</b> багцыг сонгоно.</li>
                <li>{monthLabel(t.origin_date, true)}-аас хойших борлуулалтыг агуулсан файлаа оруулна.</li>
                <li>Шалгалт дуусмагц энэ хуудас таамаглал, бодит хоёрыг сар бүрээр харьцуулна.</li>
              </ol>
              <button onClick={() => go("import")}>Шинэ сарын файл оруулах</button>
            </>)}
        </Intro>)}

      {t?.available && (
        <>
          <div className="summary">
            <div className="big">{pct(o.wape)}<small>сарын алдаа, {t.months_compared} сар</small></div>
            <div>
              <p><span className={`grade ${g.tone}`}>{g.label}</span> {monthLabel(t.by_month[0].month, true)} – {monthLabel(t.by_month[t.by_month.length - 1].month, true)}:
                {" "}таамаглал <b>{fmt(o.forecast, 0)}</b>, бодит {what} <b>{fmt(o.actual, 0)}</b>{unit ? ` ${unit}` : ""}.</p>
              <p>{biasText(o.bias)} <Help k="WAPE" /></p>
              {t.system_overall && (
                <p className="small">Гараар засаагүй бол алдаа {pct(t.system_overall.wape)} байх байсан
                  {t.system_overall.wape !== null && o.wape !== null ? (o.wape < t.system_overall.wape ? " — засвар сайжруулсан." : o.wape > t.system_overall.wape ? " — засвар муутгасан." : ".") : "."}</p>)}
              {t.months_compared < t.months_total && (
                <p className="small muted">{t.months_total} сарын таамаглалаас {t.months_compared} сарын бодит өгөгдөл ирсэн. Үлдсэн саруудыг тооцоогүй.</p>)}
              <p className="small muted">Бодит өгөгдөл: {t.actual_version.file_name} ({monthLabel(t.actual_version.last_complete_month, true)} хүртэл).</p>
            </div>
          </div>

          <div className="panel">
            <h3 style={{ marginTop: 0 }}>Сар бүрээр: таамаглал ба бодит {what}</h3>
            <Plot data={[
              { x: t.by_month.map((m) => m.month), y: t.by_month.map((m) => m.actual), name: `Бодит ${what}`, type: "bar", marker: { color: GRAY }, hovertemplate: "%{x|%Y.%m}: %{y:,.0f}<extra>Бодит</extra>" },
              { x: t.by_month.map((m) => m.month), y: t.by_month.map((m) => m.forecast), name: "Таамаглал", type: "bar", marker: { color: BLUE }, hovertemplate: "%{x|%Y.%m}: %{y:,.0f}<extra>Таамаглал</extra>" },
            ]} layout={plotLayout({ height: 300, barmode: "group", bargap: 0.3, hovermode: "closest",
              xaxis: { type: "date", tickformat: "%Y.%m", dtick: "M1", gridcolor: "rgba(128,140,150,0.15)" },
              yaxis: { title: { text: unit ? `${unit} / сар` : "сарын нийт" }, rangemode: "tozero", gridcolor: "rgba(128,140,150,0.15)" } })}
              style={{ width: "100%" }} useResizeHandler config={{ displayModeBar: false, responsive: true }} />
            <div className="table-wrap">
              <table>
                <thead><tr><th>Сар</th><th className="num">Таамаглал</th><th className="num">Бодит</th><th className="num">Зөрүү</th><th className="num">Сарын алдаа</th></tr></thead>
                <tbody>{t.by_month.map((m) => (
                  <tr key={m.month}><td>{monthLabel(m.month, true)}</td><td className="num">{fmt(m.forecast, 0)}</td><td className="num">{fmt(m.actual, 0)}</td>
                    <td className="num">{m.forecast - m.actual >= 0 ? "+" : "−"}{fmt(Math.abs(m.forecast - m.actual), 0)}</td><td className="num">{pct(m.wape)}</td></tr>))}
                </tbody>
              </table>
            </div>
          </div>

          <h2>Бараагаар</h2>
          <p className="small muted">Хамгийн их зөрсөн нь дээрээ. Мөрийг дарж сар бүрийг харна.</p>
          <div className="panel table-wrap">
            <table>
              <thead><tr><th>Бараа</th><th className="num">Таамаглал</th><th className="num">Бодит</th><th className="num">Зөрүү</th><th className="num">Сарын алдаа</th><th>Үнэлгээ</th><th>Арга</th></tr></thead>
              <tbody>{items.map((it) => {
                const s = it.score, gg = trackGrade(s.wape), isOpen = open === it.series_id;
                return [
                  <tr key={it.series_id} className="clickable" tabIndex={0} aria-expanded={isOpen}
                      onClick={() => setOpen(isOpen ? null : it.series_id)} onKeyDown={(ev) => ev.key === "Enter" && setOpen(isOpen ? null : it.series_id)}>
                    <td>{seriesLabel(it)}</td>
                    <td className="num">{fmt(s.forecast, 0)}</td><td className="num">{fmt(s.actual, 0)}</td>
                    <td className="num">{s.n ? `${s.forecast - s.actual >= 0 ? "+" : "−"}${fmt(Math.abs(s.forecast - s.actual), 0)}` : "—"}</td>
                    <td className="num">{pct(s.wape)}</td>
                    <td>{s.n ? <span className={`grade ${gg.tone}`}>{gg.label}</span> : <span className="muted small">бодит утга алга</span>}</td>
                    <td className="small">{MODEL_LABELS[it.model] || it.model}</td>
                  </tr>,
                  isOpen && (
                    <tr key={`${it.series_id}-d`}><td colSpan={7} style={{ background: "var(--paper)" }}>
                      <table>
                        <thead><tr><th>Сар</th><th className="num">Таамаглал</th><th className="num">Гараар зассан</th><th className="num">Бодит</th><th>Тайлбар</th></tr></thead>
                        <tbody>{it.months.map((m) => (
                          <tr key={m.month}><td>{monthLabel(m.month, true)}</td><td className="num">{fmt(m.forecast, 0)}</td>
                            <td className="num">{m.adjusted === null ? "—" : fmt(m.adjusted, 0)}</td>
                            <td className="num">{fmt(m.actual, 0)}</td><td className="small muted">{m.actual === null ? `Тооцоогүй: ${m.reason}` : ""}</td></tr>))}
                        </tbody>
                      </table>
                      <button className="quiet mini" style={{ marginTop: 8 }} onClick={() => go("forecast", { experiment: eid, series: it.series_id, h: horizon })}>Энэ барааны таамаглалыг нээх</button>
                    </td></tr>),
                ];
              })}</tbody>
            </table>
          </div>
          <p className="small muted">Сарын алдаа = нийт зөрүү ÷ нийт бодит {what}. Бодит утга тодорхойгүй сарыг (бүртгэлгүй, нөөц олон хоног тасарсан) тооцоогүй.</p>
        </>
      )}
    </>
  );
}
