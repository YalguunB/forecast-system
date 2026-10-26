import { api } from "../api.js";
import { go } from "../App.jsx";
import { ErrorNote, Loading, useLoad } from "../components.jsx";
import { EXP_STEPS, JOB_STATUS, JOB_TYPE, VERSION_STATUS } from "../labels.js";

export default function Dashboard({ user }) {
  const can = (...r) => r.some((x) => user.roles.includes(x));
  const jobs = useLoad(() => api.get("/jobs?limit=15"), []);
  const versions = useLoad(() => api.get("/dataset-versions"), []);
  const exps = useLoad(() => (can("data_steward", "analyst", "manager", "researcher") ? api.get("/experiments") : Promise.resolve([])), []);
  const failed = (versions.data || []).filter((v) => v.status === "failed" && !v.archived_at);
  const ready = (exps.data || []).filter((e) => e.status === "test_done" && !e.archived_at);
  return (
    <>
      <h1>Сайн байна уу, {user.full_name || user.username}</h1>
      <p className="muted">Эндээс таны ажлын төлөв, анхаарах өгөгдлийг харна.</p>

      {failed.length > 0 && (
        <div className="notice warn">
          {failed.length} өгөгдлийн хувилбарт блоклох чанарын асуудал шийдэгдээгүй — таамаглалд ашиглагдахгүй.{" "}
          {can("data_steward") && <a href={`#/quality?version=${failed[0].id}`}>Асуудлыг шийдэх</a>}
        </div>
      )}

      {ready.length > 0 && (
        <>
          <h2>Ашиглахад бэлэн таамаглал</h2>
          <div className="panel table-wrap">
            <table>
              <thead><tr><th>Туршилт</th><th>Зорилт</th><th>Өгөгдөл</th><th></th></tr></thead>
              <tbody>{ready.map((e) => (
                <tr key={e.id}>
                  <td>#{e.id} {e.name}</td><td>{e.target_label}</td><td>{e.dataset} v{e.version_no}</td>
                  <td><button className="quiet" onClick={() => go("forecast", { experiment: e.id })}>Таамаглал харах</button></td>
                </tr>))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h2>Миний ажлууд</h2>
      <div className="panel table-wrap">
        <ErrorNote error={jobs.error} />
        {jobs.loading ? <Loading /> : jobs.data?.length ? (
          <table>
            <thead><tr><th>#</th><th>Төрөл</th><th>Төлөв</th><th>Үе шат</th><th>Эхэлсэн</th></tr></thead>
            <tbody>{jobs.data.map((j) => (
              <tr key={j.id}>
                <td>{j.id}</td><td>{JOB_TYPE[j.type] || j.type}</td>
                <td><span className={`badge ${j.status === "done" ? "ok" : j.status === "failed" ? "bad" : "info"}`}>{JOB_STATUS[j.status]}</span></td>
                <td className="small">{j.error ? j.error.split("\n")[0] : j.progress?.stage || ""}</td>
                <td className="small">{new Date(j.created_at).toLocaleString("mn-MN")}</td>
              </tr>))}
            </tbody>
          </table>
        ) : <p className="muted">Та одоогоор ажил эхлүүлээгүй байна.</p>}
      </div>

      {exps.data?.length > 0 && (
        <>
          <h2>Туршилтууд</h2>
          <div className="panel table-wrap">
            <table>
              <thead><tr><th>Туршилт</th><th>Зорилт</th><th>Төлөв</th></tr></thead>
              <tbody>{exps.data.slice(0, 10).map((e) => (
                <tr key={e.id}><td>#{e.id} {e.name}</td><td>{e.target_label}</td>
                  <td>{Object.fromEntries(EXP_STEPS)[e.status]}</td></tr>))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {versions.data?.length > 0 && (
        <p className="muted small">Өгөгдлийн хувилбар: {versions.data.length}, үүнээс шалгагдсан{" "}
          {versions.data.filter((v) => v.status === "validated").length}. Сүүлийнх: {versions.data[0].dataset} v{versions.data[0].version_no} ({VERSION_STATUS[versions.data[0].status]}).</p>
      )}
    </>
  );
}
