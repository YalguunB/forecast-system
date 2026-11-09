import { useState } from "react";
import { api } from "../api.js";
import { go } from "../App.jsx";
import { ErrorNote, Intro, JobProgress, useLoad } from "../components.jsx";

const FIELD_LABELS = {
  txn_date: "Огноо", product_id: "Бүтээгдэхүүний код", product_name: "Бүтээгдэхүүний нэр", product_category: "Бүтээгдэхүүний ангилал", branch_id: "Салбарын код", qty: "Хэмжээ",
  unit: "Хэмжих нэгж", txn_id: "Гүйлгээний дугаар", amount: "Мөнгөн дүн", is_return: "Буцаалтын тэмдэг",
};
// [талбар, гарчиг, юунд хэрэгтэй, файлын баганууд]
const AUX = [
  ["calendar_file", "Салбарын хуанли", "Хаалттай өдрийг «зараагүй» гэж андуурахгүй", "date, branch_id, is_open"],
  ["inventory_file", "Нөөцийн үлдэгдэл", "Бараа дууссан өдрийг ялгана", "date, product_id, branch_id, on_hand, available, reliability"],
  ["price_file", "Үнэ", "Үнийн өөрчлөлтийг тооцно", "date, product_id, branch_id, price, price_kind, known_at"],
  ["promotion_file", "Урамшуулал", "Урамшууллын үеийн өсөлтийг тооцно", "date_from, date_to, product_id, branch_id, known_at"],
];
const DATE_FORMATS = [
  ["", "Автоматаар таних"], ["%Y-%m-%d", "2024-01-31"], ["%Y/%m/%d", "2024/01/31"], ["%Y.%m.%d", "2024.01.31"],
  ["%d/%m/%Y", "31/01/2024"], ["%m/%d/%Y", "01/31/2024"], ["%d.%m.%Y", "31.01.2024"],
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
  const [conv, setConv] = useState([]);   // [{product_id, from, to, factor}]
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
    const cv = conv.filter((c) => c.product_id && c.from && c.to && Number(c.factor) > 0).map((c) => ({ ...c, factor: Number(c.factor) }));
    if (cv.length) f.append("unit_conversions", JSON.stringify(cv));
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
      <p className="muted">Борлуулалтын файлаа оруулахад систем баганыг өөрөө таньж, та зөвхөн шалгаж батална.</p>

      <ol className="ladder" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
        {["Файл сонгох", "Багана тааруулах", "Шалгалт"].map((t, i) => (
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
            Үргэлжлүүлэх
          </button>
        </div>
      )}

      {step === 2 && preview && (
        <div className="panel">
          <h3>Таны файлын багана → системийн талбар</h3>
          <MappingTable preview={preview} mapping={mapping} setMapping={setMapping} />
          {(!mapping.branch_id || !mapping.unit) && (
            <div className="row" style={{ marginTop: "1rem" }}>
              {!mapping.branch_id && (
                <div className="grow">
                  <label htmlFor="db">Салбарын багана алга — бүх мөрийг аль салбарт тооцох вэ?</label>
                  <input id="db" value={defBranch} onChange={(e) => setDefBranch(e.target.value)} />
                </div>
              )}
              {!mapping.unit && (
                <div className="grow">
                  <label htmlFor="du">Нэгжийн багана алга — бүх мөрийн нэгж</label>
                  <input id="du" value={defUnit} onChange={(e) => setDefUnit(e.target.value)} />
                </div>
              )}
            </div>
          )}
          <div className="row" style={{ marginTop: "1rem" }}>
            <div className="grow">
              <label htmlFor="df">Огноог хэрхэн бичсэн бэ</label>
              <select id="df" value={DATE_FORMATS.some(([k]) => k === dateFormat) ? dateFormat : ""} onChange={(e) => setDateFormat(e.target.value)}>
                {DATE_FORMATS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
              {preview.rows[0] && mapping.txn_date && <p className="small muted" style={{ margin: "0.25rem 0 0" }}>Таны файлын эхний огноо: <b>{String(preview.rows[0][mapping.txn_date])}</b></p>}
            </div>
            <div className="grow" />
          </div>
          <UnitConversions conv={conv} setConv={setConv} />
          <h3>Нэмэлт мэдээлэл <span className="muted small" style={{ fontWeight: 400 }}>· заавал биш, таамаглалыг сайжруулна</span></h3>
          <div className="grp-cards">
            {AUX.map(([k, l, why, cols]) => (
              <div key={k}>
                <label htmlFor={k} style={{ color: "var(--ink)", fontWeight: 600, marginBottom: 0 }}>{l}</label>
                <span className="muted">{why}</span>
                <input id={k} type="file" accept=".csv,.xlsx" onChange={(e) => setAux({ ...aux, [k]: e.target.files[0] })} />
                <span className="facts-tech">Баганууд: {cols}</span>
              </div>
            ))}
          </div>
          <details style={{ marginTop: "1rem" }}>
          <summary className="small">Файлын эхний 5 мөрийг харах</summary>
          <div className="table-wrap">
            <table><thead><tr>{preview.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>{preview.rows.slice(0, 5).map((r, i) => <tr key={i}>{preview.columns.map((c) => <td key={c}>{r[c]}</td>)}</tr>)}</tbody>
            </table>
          </div>
          </details>
          {dup && (
            <div className="notice warn">
              {dup.message}. Ижил файлыг дахин оруулах уу?{" "}
              <button className="warn" onClick={() => submit(true)}>Тийм, шинэ хувилбар болгох</button>
            </div>
          )}
          <div className="row" style={{ marginTop: "1rem" }}>
            <button className="quiet" onClick={() => setStep(1)}>Буцах</button>
            <button onClick={() => submit(false)} disabled={preview.required.some((x) => !mapping[x] && !["branch_id", "unit"].includes(x))}>Оруулж шалгах</button>
            <span className="small muted" style={{ alignSelf: "center" }}>Таны файл өөрчлөгдөхгүй хуулбар болж хадгалагдана — дараа засвар хийсэн ч анхны утга үлдэнэ.</span>
          </div>
        </div>
      )}

      {step === 3 && job && (
        <>
          <p>Файл хадгалагдлаа (хувилбар {job.version_no}). Систем одоо алдаа шалгаж байна — дуусмагц үр дүнг харна уу.</p>
          <JobProgress jobId={job.job_id} onDone={() => {}} />
          <button onClick={() => go("quality", { version: job.version_id })}>Шалгалтын үр дүн харах</button>
          <p className="small muted">Мөшгих код: <code>{job.sha256.slice(0, 16)}…</code></p>
        </>
      )}
    </>
  );
}

// Системийн талбар бүрд: таны баганыг сонгох, эхний мөрийн жишээ утга, төлөв
function MappingTable({ preview, mapping, setMapping }) {
  const req = new Set(preview.required);
  const fields = [...preview.required, ...preview.optional];
  const sample = preview.rows[0] || {};
  const nOk = preview.required.filter((f) => mapping[f]).length;
  const optionalDefault = (f) => ["branch_id", "unit"].includes(f);
  return (
    <>
      <p className="small muted">Заавал {preview.required.length} талбараас {nOk}-ийг таньсан. Шар тэмдэгтэйг шалгахад хангалттай.</p>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Системд хэрэгтэй</th><th>Таны файлын багана</th><th>Эхний мөрийн утга</th><th>Төлөв</th></tr></thead>
          <tbody>{fields.map((fld) => {
            const col = mapping[fld];
            const st = col ? ["ok", "Таньсан"] : req.has(fld) && !optionalDefault(fld) ? ["bad", "Сонгоно уу"] : req.has(fld) ? ["warn", "Доор нэг утга өгнө"] : ["", "Заавал биш"];
            return (
              <tr key={fld} style={st[0] === "bad" || st[0] === "warn" ? { background: "var(--saffron-soft)" } : null}>
                <td><b>{FIELD_LABELS[fld]}</b>{req.has(fld) ? <span className="muted small"> · заавал</span> : null}</td>
                <td style={{ minWidth: 200 }}>
                  <select aria-label={`${FIELD_LABELS[fld]}: багана`} value={col || ""} onChange={(e) => setMapping({ ...mapping, [fld]: e.target.value || null })}>
                    <option value="">— байхгүй —</option>
                    {preview.columns.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </td>
                <td className="small">{col && sample[col] !== undefined && sample[col] !== null ? <code>{String(sample[col])}</code> : <span className="muted">—</span>}</td>
                <td><span className={`badge ${st[0]}`}>{st[1]}</span></td>
              </tr>);
          })}</tbody>
        </table>
      </div>
    </>
  );
}

// Нэг барааг өөр өөр нэгжээр бичсэн бол: «1 хайрцаг = 12 ширхэг»
function UnitConversions({ conv, setConv }) {
  const set = (i, patch) => setConv(conv.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  return (
    <details style={{ marginTop: "1rem" }} open={conv.length > 0}>
      <summary className="small">Нэгж хөрвүүлэх (жишээ нь 1 хайрцаг = 12 ширхэг) — заавал биш</summary>
      <p className="small muted">Нэг барааг «хайрцаг», «ширхэг» гэж холиод бичсэн бол энд заана. Эс бөгөөс шалгалт энэ барааг «Заавал засах» гэж тэмдэглэнэ.</p>
      {conv.map((c, i) => (
        <div className="row" key={i} style={{ marginBottom: 6, alignItems: "flex-end" }}>
          <div style={{ flex: "1 1 140px" }}><label htmlFor={`cp${i}`}>Барааны код</label><input id={`cp${i}`} value={c.product_id} onChange={(e) => set(i, { product_id: e.target.value })} /></div>
          <div style={{ flex: "0 1 90px" }}><label htmlFor={`cf${i}`}>1</label><input id={`cf${i}`} value={c.from} placeholder="хайрцаг" onChange={(e) => set(i, { from: e.target.value })} /></div>
          <div style={{ flex: "0 1 90px" }}><label htmlFor={`cx${i}`}>=</label><input id={`cx${i}`} type="number" min="0" step="any" value={c.factor} placeholder="12" onChange={(e) => set(i, { factor: e.target.value })} /></div>
          <div style={{ flex: "0 1 110px" }}><label htmlFor={`ct${i}`}>нэгж</label><input id={`ct${i}`} value={c.to} placeholder="ширхэг" onChange={(e) => set(i, { to: e.target.value })} /></div>
          <button className="quiet" onClick={() => setConv(conv.filter((_, j) => j !== i))}>Хасах</button>
        </div>
      ))}
      <button className="quiet" onClick={() => setConv([...conv, { product_id: "", from: "", to: "", factor: "" }])}>+ Хөрвүүлэлт нэмэх</button>
    </details>
  );
}
