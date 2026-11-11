// Монгол нэршил ба өдрийн төлвийн өнгө (өнгө дангаараа утга тээхгүй — үргэлж шошготой, FR-F3)
// code: календарт өнгөнөөс гадна харагдах үсэг; note: энгийн тайлбар
export const STATES = {
  sold: { label: "Зарагдсан", color: "#3E7D5A", code: "Б", note: "таамаглалд орно" },
  open_no_sale: { label: "Нээлттэй, зараагүй", color: "#9DB8A6", code: "0", note: "жинхэнэ 0" },
  stockout: { label: "Нөөцгүй", color: "#B5483B", code: "Н", note: "бараа байгаагүй" },
  sold_out: { label: "Дууссан", color: "#D9822B", code: "Д", note: "өдөртөө зарагдаж дууссан" },
  stockout_est: { label: "Нөөцгүй бололтой", color: "#D98C80", code: "н", note: "удаан хугацаанд зарагдаагүй" },
  closed: { label: "Хаалттай", color: "#6B7780", code: "Х", note: "дэлгүүр хаалттай" },
  missing: { label: "Бүртгэлгүй", color: "#C9A227", code: "?", note: "борлуулалт бүртгэгдээгүй" },
  unknown: { label: "Тодорхойгүй", color: "#C8CFD4", code: "~", note: "шалтгаан мэдэгдэхгүй" },
};

export const ROLE_LABELS = {
  executive: "Удирдлага",
  manager: "Менежер",
  admin: "Админ",
};
export const ROLE_DESC = {
  executive: "Бүх салбарын таамаглал, тайланг харж татна.",
  manager: "Өгөгдөл оруулж, шалгаж, таамаглал гаргуулна.",
  admin: "Хэрэглэгч, эрх, салбарыг тохируулна.",
};
export const branchText = (b) => (!b || !b.length ? "оноогоогүй" : b.includes("*") ? "Бүх салбар" : b.join(", "));

export const EXP_STEPS = [
  ["draft", "Үүсгэсэн"],
  ["validating", "Туршиж байна"],
  ["validation_done", "Арга сонгогдсон"],
  ["locked", "Батлагдсан"],
  ["test_done", "Бэлэн"],
];

export const VERSION_STATUS = { imported: "Шалгаж байна", validated: "Бэлэн", failed: "Алдаатай" };
export const JOB_STATUS = { queued: "Дараалалд", running: "Ажиллаж байна", done: "Дууссан", failed: "Бүтэлгүй", cancelled: "Цуцлагдсан" };
export const JOB_TYPE = { import: "Файл оруулах", regrid: "Засвар хэрэгжүүлэх", validate: "Аргуудыг турших", test: "Таамаглал гаргах" };
export const SEVERITY = { blocking: "Заавал засах", warning: "Анхааруулга", info: "Мэдээлэл" };
export const SEVERITY_NOTE = { blocking: "Засахгүй бол ашиглахгүй", warning: "Шийдвэр хэрэгтэй", info: "Зөвхөн мэдээлэл" };
export const ACTIONS = { open: "Шийдээгүй", accepted: "Зөвшөөрсөн", corrected: "Зассан", excluded: "Хассан" };
// Менежерт харагдах аргын нэр — энгийн монголоор (техник нэр MODEL_PLAIN[m].short-д)
export const MODEL_LABELS = { ma: "3 сарын дундаж", naive: "Өнгөрсөн сар", snaive: "Өнгөрсөн оны мөн сар", ets: "Чиг хандлага, улирал", sarima: "Улирлын загвар", croston: "Ховор барааны арга", sba: "Ховор барааны арга (засвартай)" };
// "ets {\"trend\": \"add\"}" хэлбэрийн шошгоос энгийн нэр
export const runName = (lbl) => {
  const [m, ...rest] = String(lbl).split(" ");
  return (MODEL_LABELS[m] || m) + (m === "ets" && rest.join(" ").includes("trend") ? " (өсөлттэй)" : "");
};

// Таамаглалын хугацаа (диплом FR-04): сар, улирал, жил = 1, 3, 12 сар
export const HORIZONS = [[1, "Сар"], [3, "Улирал"], [12, "Жил"]];
export const PERIOD = { 1: "Сар", 3: "Улирал", 12: "Жил" };
// Харьяалахын тийн ялгал: «Улиралын», «Жилын» гэж бичихгүй
export const PERIOD_OF = { 1: "Сарын", 3: "Улирлын", 12: "Жилийн" };
export const PERIOD_LONG = { 1: "ирэх сар", 3: "ирэх 3 сар", 12: "ирэх 12 сар" };
const MONTHS = ["1-р сар", "2-р сар", "3-р сар", "4-р сар", "5-р сар", "6-р сар", "7-р сар", "8-р сар", "9-р сар", "10-р сар", "11-р сар", "12-р сар"];
export const monthName = (m) => MONTHS[m - 1];
// "2026-10-01" → "2026 оны 10-р сар" (long) эсвэл "2026.10" (short)
export const monthLabel = (iso, long = false) => {
  if (!iso) return "";
  const [y, m] = String(iso).split("-").map(Number);
  return long ? `${y} оны ${MONTHS[m - 1]}` : `${y}.${String(m).padStart(2, "0")}`;
};

// Бүтээгдэхүүнийг нэрээр нь харуулна (нэр байхгүй бол код); салбар «ALL» бол нуух
export const productLabel = (s) => (s?.product_name ? s.product_name : s?.product_id ?? "");
export const seriesLabel = (s) => productLabel(s) + (s?.branch_id && s.branch_id !== "ALL" ? ` / ${s.branch_id}` : "");

export const fmt = (v, d = 2) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : Number(v).toLocaleString("mn-MN", { maximumFractionDigits: d });
export const pct = (v) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(0)}%`);

// ---------------------------------------------------------------------------
// Энгийн хэллэг: хэрэглэгчид мэргэжлийн нэр томьёог тайлбарлах (Тусламж хуудас, «?» тэмдэг)
// ---------------------------------------------------------------------------
export const MODEL_PLAIN = {
  ma: { name: "3 сарын дундаж", short: "Гулсах дундаж", desc: "Сүүлийн 3 сарын дундаж. Бусад аргыг үүнтэй харьцуулна." },
  naive: { name: "Өнгөрсөн сар", short: "Naive", desc: "Ирэх сар өнгөрсөн сартай адил гэж үзнэ." },
  snaive: { name: "Өнгөрсөн оны мөн сар", short: "Seasonal naive", desc: "Ирэх сар өнгөрсөн оны мөн сартай адил гэж үзнэ." },
  ets: { name: "Чиг хандлага, улирал", short: "ETS", desc: "Сүүлийн саруудад илүү жин өгч, өсөлт ба улирлыг тооцно." },
  sarima: { name: "Улирлын загвар", short: "SARIMA", desc: "Өмнөх сарууд болон өнгөрсөн оны мөн сараас тооцно. 3-аас дээш жилийн өгөгдөл хэрэгтэй." },
  croston: { name: "Ховор барааны арга", short: "Croston", desc: "Сар бүр зарагддаггүй бараанд зориулсан." },
  sba: { name: "Ховор барааны арга (засвартай)", short: "SBA", desc: "Croston аргын хэт өндөр таамаглахаас сэргийлсэн хувилбар." },
};
export const modelName = (m) => (MODEL_PLAIN[m] ? `${MODEL_PLAIN[m].name} (${MODEL_PLAIN[m].short})` : m);

export const GLOSSARY = {
  WAPE: { term: "Сарын алдаа", desc: "Таамаглал бодитоос хэдэн хувиар зөрсөн бэ. 20% гэвэл 100 ширхэг зарагдах сард 20 орчим ширхэгээр зөрнө." },
  SUM_APE: { term: "Нийт дүнгийн алдаа", desc: "Улирал эсвэл жилийн нийт дүн хэдэн хувиар зөрсөн бэ. Сар бүрийн зөрүү бие биенээ нөхдөг тул сарынхаас бага гардаг." },
  MASE: { term: "MASE", desc: "1-ээс бага бол «өнгөрсөн оны мөн сар» аргаас сайн." },
  MAE: { term: "Дундаж зөрүү", desc: "Сард дунджаар хэдэн ширхэгээр зөрсөн бэ." },
  RMSE: { term: "RMSE", desc: "Том зөрүүг илүү хүндээр тооцсон дундаж." },
  Bias: { term: "Хазайлт", desc: "Эерэг бол илүү, сөрөг бол дутуу таамагласан." },
  SUM_AE: { term: "Нийт дүнгийн зөрүү", desc: "Хугацааны нийт дүн хэдэн ширхэгээр зөрсөн бэ." },
  COVERAGE: { term: "Хүрээнд багтсан", desc: "Бодит борлуулалт 80%-ийн хүрээнд хэдэн удаа багтсан бэ. 80% орчим байвал зөв." },
  horizon: { term: "Хугацаа", desc: "Ирэх сар, ирэх 3 сар эсвэл ирэх 12 сар." },
  origin: { term: "Сүүлийн бүтэн сар", desc: "Таамаглал энэ сар хүртэлх өгөгдөлд үндэслэсэн." },
  interval: { term: "80%-ийн хүрээ", desc: "Бодит борлуулалт 10 удаагийн 8-д нь энэ хүрээнд багтана." },
  validation: { term: "Туршилт", desc: "Бүх аргыг өмнөх саруудад туршиж, хамгийн бага алдсаныг сонгоно." },
  test: { term: "Эцсийн шалгалт", desc: "Сонгосон аргыг өмнө нь ашиглаагүй саруудад нэг удаа шалгана." },
  lock: { term: "Батлах", desc: "Батласны дараа сонголтыг өөрчлөхгүй. Ингэснээр шалгалтын дүн бодитой гарна." },
  baseline: { term: "Энгийн арга", desc: "Сүүлийн 3 сарын дундаж. Бусад арга үүнээс сайн байж л ашиглагдана." },
  class: { term: "Борлуулалтын төрөл", desc: "Тогтвортой: сар бүр жигд. Хэлбэлзэлтэй: сар бүр, гэхдээ тогтворгүй. Тасалдалтай: зарим сард зарагддаггүй. Бөөгнөрсөн: ховор, их хэмжээгээр." },
  day_state: { term: "Өдрийн төлөв", desc: "Борлуулалтгүй өдөр бүрд шалтгаан оноодог: хаалттай, нөөцгүй, бүртгэлгүй гэх мэт." },
  category: { term: "Ангилал", desc: "Файлын ангиллын баганаас авсан." },
  sales_vs_demand: { term: "Борлуулалт ба эрэлт", desc: "Борлуулалт нь зарагдсан тоо. Эрэлт нь бараа хүрэлцээтэй байсан бол зарагдах байсан тоо. Нөөцийн файл байвал илүү нарийн тооцно." },
};

// Дүрэм бүрт систем юу хийдэг вэ (Хүснэгт 3.9)
export const RULE_SYSTEM_DID = {
  "DQ-01": "Мөрийг түр хассан",
  "DQ-02": "Мөрийг тусад нь хадгалсан",
  "DQ-03": "Таны шийдвэрийг хүлээж байна",
  "DQ-04": "Нэгж хөрвүүлэх хүртэл зогсоосон",
  "DQ-05": "Борлуулалтаас хассан",
  "DQ-06": "Тэмдэглэсэн, өөрчлөөгүй",
  "DQ-07": "Таны шийдвэрийг хүлээж байна",
  "DQ-08": "Өдөр бүрд шалтгаан оноосон",
  "DQ-09": "Тусад нь харуулна",
  "DQ-10": "Таамаглалд ашиглахгүй",
  "DQ-11": "Борлуулалтад тооцоогүй",
};
export const RULE_PLAIN = {
  "DQ-01": "Хоосон эсвэл буруу хэмжээ",
  "DQ-02": "Буруу огноо",
  "DQ-03": "Давхардсан мөр",
  "DQ-04": "Өөр өөр нэгж",
  "DQ-05": "Буцаалт",
  "DQ-06": "Хэт өндөр утга",
  "DQ-07": "Код солигдсон байж магадгүй",
  "DQ-08": "Борлуулалтгүй өдөр",
  "DQ-09": "Түүх богино",
  "DQ-10": "Үнийн огноо зөрүүтэй",
  "DQ-11": "Цуцлагдсан, буцаагдсан захиалга",
};

// Сарын WAPE-ээс ойлгомжтой үнэлгээ; суурь аргатай харьцуулалт өгвөл түүнийг ч тооцно
export function accuracyLevel(wape, baseline) {
  if (wape === null || wape === undefined) return { label: "Тодорхойгүй", tone: "", text: "Шалгах өгөгдөл хүрэлцээгүй." };
  const better = baseline === null || baseline === undefined || wape < baseline;
  const w = `Сарын алдаа ${(wape * 100).toFixed(0)}%.`;
  if (wape < 0.2 && better) return { label: "Сайн", tone: "ok", text: w };
  if (wape < 0.4 && better) return { label: "Дунд", tone: "warn", text: `${w} Ерөнхий чиг хандлагыг харахад тохиромжтой.` };
  if (!better) return { label: "Энгийн аргаас муу", tone: "warn", text: `${w} Энгийн арга ${(baseline * 100).toFixed(0)}%. Болгоомжтой ашиглана уу.` };
  return { label: "Сул", tone: "bad", text: `${w} Алдаа өндөр.` };
}

// Үүрэг бүрийн эрх — backend-ийн core.PERMISSIONS-тэй ижил (Хүснэгт 4.11)
export const PERMISSION_ROWS = [
  ["Өгөгдөл оруулах, алдаа засах", ["manager"]],
  ["Өгөгдлийн шалгалтын тайлан харах", ["executive", "manager"]],
  ["Таамаглал гаргуулах", ["manager"]],
  ["Таамаглал, тайлан харах", ["executive", "manager"]],
  ["Таамаглалыг гараар засах", ["manager"]],
  ["Excel, CSV татах", ["executive", "manager"]],
  ["Хэрэглэгч, архив, бүртгэл", ["admin"]],
];

// Үйлдлийн бүртгэлийн нэр
export const AUDIT_ACTIONS = {
  login: "Нэвтэрсэн", create: "Үүсгэсэн", edit: "Өөрчилсөн", archive: "Архивласан", cancel: "Ажил цуцалсан",
  import_start: "Өгөгдөл оруулж эхэлсэн", import_done: "Өгөгдөл оруулж дууссан",
  resolve_issue: "Өгөгдлийн асуудал шийдсэн", resolve_issues_bulk: "Олон асуудлыг нэг дор шийдсэн",
  apply_decisions: "Засвар хэрэгжүүлсэн", regrid_done: "Засвар хэрэгжсэн",
  edit_protocol: "Тохиргоо өөрчилсөн", lock_protocol_start_validation: "Аргуудыг туршиж эхэлсэн",
  validation_done: "Арга сонгогдсон", lock_selection: "Сонголтыг баталсан",
  start_test: "Эцсийн шалгалт эхэлсэн", test_done: "Таамаглал бэлэн болсон",
  export_report: "Дэлгэрэнгүй тайлан татсан", export_forecasts: "Таамаглал татсан", export_summary: "Тайлан татсан",
};
export const OBJECT_LABELS = {
  app_user: "хэрэглэгч", dataset: "багц", dataset_version: "файл", experiment: "таамаглал",
  forecast_adjustment: "гараар засвар", data_quality_issue: "өгөгдлийн асуудал", job: "ажил",
};

// Хассан шалтгааныг энгийн болгох: "бүтэн сар 6 < 24" → "түүх богино: 6 сар (24 сар хэрэгтэй)"
export function plainExclude(reason) {
  const r = String(reason || "");
  const m = r.match(/бүтэн сар (\d+) < (\d+)/);
  if (m) return `түүх богино: ${m[1]} сар (${m[2]} сар хэрэгтэй)`;
  if (r.startsWith("дэд багцад")) return "барааны дээд тоонд багтаагүй";
  return r;
}
