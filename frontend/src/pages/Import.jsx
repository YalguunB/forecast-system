import { useState } from "react";
import { api } from "../api.js";
import { go } from "../App.jsx";
import { ErrorNote, Intro, JobProgress, useLoad } from "../components.jsx";

const FIELD_LABELS = {
  txn_date: "Огноо", product_id: "Бүтээгдэхүүний код", product_name: "Бүтээгдэхүүний нэр", product_category: "Бүтээгдэхүүний ангилал", branch_id: "Салбарын код", qty: "Хэмжээ",
  unit: "Хэмжих нэгж", txn_id: "Гүйлгээний дугаар", amount: "Мөнгөн дүн", is_return: "Буцаалтын тэмдэг",
};
const AUX = [
  ["price_file", "Үнэ (date, product_id, branch_id, price, price_kind, known_at)"],
  ["calendar_file", "Салбарын календарь (date, branch_id, is_open)"],
  ["inventory_file", "Нөөцийн хүртээмж (date, product_id, branch_id, on_hand, available, reliability)"],
  ["promotion_file", "Урамшуулал (date_from, date_to, product_id, branch_id, known_at)"],
];

// UC-01: 3 алхамт хэлбэр — файл, зураглал, шалгалтын үр дүн
export default function Import() {
  const datasets = useLoad(() => api.get("/datasets"), []);
  const [step, setStep] = useState(1);
  const [ds, setDs] = useState("");
  const [newName, setNewName] = useState("");
  const [file, setFile] = useState(null);
  const [aux, setAux] = useState({});
  const [preview, setPreview] = useState(null);
  const [mapping, setMapping] = useState({});
  const [dateFormat, setDateFormat] = useState("%Y-%m-%d");
  const [conv, setConv] = useState("");
  const [defBranch, setDefBranch] = useState("ALL");
  const [defUnit, setDefUnit] = useState("ширхэг");
  const [err, setErr] = useState(null);
  const [job, setJob] = useState(null);
  const [dup, setDup] = useState(null);

  const toMapping = async () => {
    setErr(null);
    try {
      let id = ds;
      if (!id) {
        const d = await api.post("/datasets", { name: newName });
        id = String(d.id);
        setDs(id);
        datasets.reload();
      }
      const f = new FormData();
      f.append("file", file);
      const p = await api.upload(`/datasets/${id}/preview`, f);
      setPreview(p);
      setMapping(p.suggested_mapping);
      setDateFormat(p.suggested_date_format || "");
      setStep(2);
    } catch (x) { setErr(x); }
  };

  const submit = async (force = false) => {
    setErr(null);
    const f = new FormData();
    f.append("file", file);
    f.append("mapping", JSON.stringify(mapping));
    if (dateFormat) f.append("date_format", dateFormat);
    if (conv.trim()) f.append("unit_conversions", conv);
    if (!mapping.branch_id) f.append("default_branch", defBranch);
    if (!mapping.unit) f.append("default_unit", defUnit);
    f.append("force", force ? "true" : "false");
    for (const [k, v] of Object.entries(aux)) if (v) f.append(k, v);
    try {
      const r = await api.upload(`/datasets/${ds}/versions`, f);
      setDup(null);
      setJob(r);
      setStep(3);
    } catch (x) {
      if (x.code === "duplicate_checksum") setDup(x); else setErr(x);
    }
  };

  return (
    <>
      <h1>Өгөгдөл оруулах</h1>

      <ol className="ladder" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
        {["Файл сонгох", "Талбар зураглах", "Шалгалтын үр дүн"].map((t, i) => (
          <li key={t} className={step === i + 1 ? "current" : step > i + 1 ? "done" : ""}>{t}</li>
        ))}
      </ol>
      <ErrorNote error={err} />
      {err?.details?.missing && <p className="small">Файлын баганууд: {err.details.columns.join(", ")}</p>}

      {step === 1 && (
        <div className="panel">
          <div className="row">
            <div className="grow">
              <label htmlFor="ds">Өгөгдлийн багц</label>
              <select id="ds" value={ds} onChange={(e) => setDs(e.target.value)}>
                <option value="">— Шинэ багц үүсгэх —</option>
                {(datasets.data || []).map((d) => <option key={d.id} value={d.id}>{d.name} ({d.n_versions} хувилбар)</option>)}
              </select>
            </div>
            {!ds && (
              <div className="grow">
                <label htmlFor="nn">Шинэ багцын нэр</label>
                <input id="nn" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Жишээ: Төв дэлгүүр 2024–2026" />
              </div>
            )}
          </div>
          <label htmlFor="f" style={{ marginTop: "1rem" }}>Гүйлгээний файл (CSV эсвэл Excel)</label>
          <input id="f" type="file" accept=".csv,.xlsx,.xls" onChange={(e) => setFile(e.target.files[0])} />
          <button style={{ marginTop: "1rem" }} disabled={!file || (!ds && !newName.trim())} onClick={toMapping}>
            Талбар зураглах руу
          </button>
        </div>
      )}

      {step === 2 && preview && (
        <div className="panel">
          <h3>Талбарын зураглал</h3>
          <p className="small muted">Систем баганын нэрээр санал болгосон. Од (*) бүхий талбар заавал.</p>
          <div className="row">
            {[...preview.required, ...preview.optional].map((fld) => (
              <div key={fld} style={{ flex: "1 1 200px" }}>
                <label htmlFor={`m-${fld}`}>{FIELD_LABELS[fld]}{preview.required.includes(fld) ? " *" : ""}</label>
                <select id={`m-${fld}`} value={mapping[fld] || ""} onChange={(e) => setMapping({ ...mapping, [fld]: e.target.value || null })}>
                  <option value="">— байхгүй —</option>
                  {preview.columns.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
            ))}
          </div>
          {(!mapping.branch_id || !mapping.unit) && (
            <div className="row" style={{ marginTop: "1rem" }}>
              {!mapping.branch_id && (
                <div className="grow">
                  <label htmlFor="db">Салбар зураглаагүй — бүх мөрийн салбар</label>
                  <input id="db" value={defBranch} onChange={(e) => setDefBranch(e.target.value)} />
                </div>
              )}
              {!mapping.unit && (
                <div className="grow">
                  <label htmlFor="du">Нэгж зураглаагүй — бүх мөрийн нэгж</label>
                  <input id="du" value={defUnit} onChange={(e) => setDefUnit(e.target.value)} />
                </div>
              )}
            </div>
          )}
          <div className="row" style={{ marginTop: "1rem" }}>
            <div className="grow">
              <label htmlFor="df">Огнооны хэлбэр</label>
              <input id="df" value={dateFormat} onChange={(e) => setDateFormat(e.target.value)} placeholder="Хоосон бол автоматаар танина" />
            </div>
            <div className="grow">
              <label htmlFor="cv">Нэгжийн хөрвүүлэлт (JSON, заавал биш)</label>
              <input id="cv" value={conv} onChange={(e) => setConv(e.target.value)}
                     placeholder='[{"product_id":"P005","from":"хайрцаг","to":"ширхэг","factor":12}]' />
            </div>
          </div>
          <h3>Нэмэлт файл (заавал биш)</h3>
          <p className="small muted">Календарь ба нөөцийн файл өгвөл гүйлгээгүй өдрийг «хаалттай», «нөөцгүй» гэж ялгана; эс бөгөөс «тодорхойгүй» болно.</p>
          {AUX.map(([k, l]) => (
            <div key={k} style={{ marginBottom: "0.5rem" }}>
              <label htmlFor={k}>{l}</label>
              <input id={k} type="file" accept=".csv,.xlsx" onChange={(e) => setAux({ ...aux, [k]: e.target.files[0] })} />
            </div>
          ))}
          <h3>Эхний мөрүүд</h3>
          <div className="table-wrap">
            <table><thead><tr>{preview.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>{preview.rows.slice(0, 5).map((r, i) => <tr key={i}>{preview.columns.map((c) => <td key={c}>{r[c]}</td>)}</tr>)}</tbody>
            </table>
          </div>
          {dup && (
            <div className="notice warn">
              {dup.message}. Ижил файлыг дахин оруулах уу?{" "}
              <button className="warn" onClick={() => submit(true)}>Тийм, шинэ хувилбар болгох</button>
            </div>
          )}
          <div className="row" style={{ marginTop: "1rem" }}>
            <button className="quiet" onClick={() => setStep(1)}>Буцах</button>
            <button onClick={() => submit(false)}>Импортлох</button>
          </div>
        </div>
      )}

      {step === 3 && job && (
        <>
          <p>Хувилбар v{job.version_no} үүслээ. checksum: <code className="small">{job.sha256.slice(0, 16)}…</code></p>
          <JobProgress jobId={job.job_id} onDone={() => {}} />
          <button onClick={() => go("quality", { version: job.version_id })}>Чанарын тайлан харах</button>
        </>
      )}
    </>
  );
}
