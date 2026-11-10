import { useEffect, useState } from "react";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-dist-min";
import { api, waitJob } from "./api.js";
import { GLOSSARY, JOB_STATUS, STATES } from "./labels.js";

export const Plot = createPlotlyComponent(Plotly);

export function useLoad(fn, deps) {
  const [state, set] = useState({ data: null, error: null, loading: true });
  const reload = () => {
    set((s) => ({ ...s, loading: true }));
    fn().then((data) => set({ data, error: null, loading: false }))
      .catch((error) => set({ data: null, error, loading: false }));
  };
  useEffect(reload, deps); // eslint-disable-line react-hooks/exhaustive-deps
  return { ...state, reload };
}

export function ErrorNote({ error }) {
  if (!error) return null;
  return <div className="notice bad" role="alert">{error.message}</div>;
}

export function Loading({ what = "Ачаалж байна" }) {
  return <p className="muted">{what}…</p>;
}

// Асинхрон ажлын ахиц ба цуцлах товч (FR-M5)
export function JobProgress({ jobId, onDone }) {
  const [job, setJob] = useState(null);
  useEffect(() => {
    let alive = true;
    waitJob(jobId, (j) => alive && setJob(j)).then((j) => alive && onDone?.(j));
    return () => { alive = false; };
  }, [jobId]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!job) return <p className="muted small">Эхэлж байна…</p>;
  const running = ["queued", "running"].includes(job.status);
  return (
    <div className="panel" aria-live="polite">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <b>{JOB_STATUS[job.status]}</b>
          {job.progress?.stage ? <span className="muted"> · {job.progress.stage}</span> : null}
        </div>
        {running && (
          <button className="quiet" onClick={() => api.post(`/jobs/${job.id}/cancel`)}>Цуцлах</button>
        )}
      </div>
      {job.percent !== null && job.percent !== undefined && (
        <div className="progress"><div style={{ width: `${job.percent}%` }} /></div>
      )}
      {job.error && <div className="notice bad small">{job.error.split("\n")[0]}</div>}
    </div>
  );
}

export function StateLegend({ states }) {
  const keys = states ? Object.keys(STATES).filter((k) => states.includes(k)) : Object.keys(STATES);
  return (
    <div className="legend">
      {keys.map((k) => <span key={k}><i style={{ background: STATES[k].color }} />{STATES[k].label}</span>)}
    </div>
  );
}

export const plotLayout = (extra = {}) => ({
  margin: { l: 48, r: 12, t: 8, b: 36 },
  paper_bgcolor: "rgba(0,0,0,0)",
  plot_bgcolor: "rgba(0,0,0,0)",
  font: { family: "Golos Text, system-ui", size: 12, color: getComputedStyle(document.documentElement).getPropertyValue("--ink-2") || "#4a5a63" },
  xaxis: { gridcolor: "rgba(128,140,150,0.15)", zeroline: false },
  yaxis: { gridcolor: "rgba(128,140,150,0.15)", zeroline: false, rangemode: "tozero" },
  legend: { orientation: "h", y: -0.18 },
  hovermode: "x unified",
  ...extra,
});

// «?» тэмдэг: дарахад/хулгана барихад нэр томьёоны тайлбар гарна
export function Help({ k, text }) {
  const g = k ? GLOSSARY[k] : null;
  const body = text || g?.desc;
  if (!body) return null;
  return (
    <span className="help" tabIndex={0} role="button" aria-label={`${g?.term || "Тайлбар"}: ${body}`}>
      ?
      <span className="help-pop" role="tooltip">{g?.term && <b>{g.term}. </b>}{body}</span>
    </span>
  );
}

// Дэлгэц бүрийн дээд талд: энэ хуудас юуны тулд вэ, юу хийх вэ
export function Intro({ children }) {
  return <div className="intro">{children}</div>;
}
