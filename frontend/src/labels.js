// Монгол нэршил ба өдрийн төлвийн өнгө (өнгө дангаараа утга тээхгүй — үргэлж шошготой, FR-F3)
export const STATES = {
  sold: { label: "Борлуулалттай", color: "#3E7D5A" },
  open_no_sale: { label: "Нээлттэй, борлуулалтгүй", color: "#9DB8A6" },
  stockout: { label: "Нөөцгүй", color: "#B5483B" },
  closed: { label: "Хаалттай", color: "#6B7780" },
  missing: { label: "Бүртгэл дутуу", color: "#C9A227" },
  unknown: { label: "Тодорхойгүй", color: "#C8CFD4" },
};

export const ROLE_LABELS = {
  data_steward: "Өгөгдлийн хариуцагч",
  analyst: "Шинжээч",
  manager: "Менежер",
  researcher: "Судлаач",
  admin: "Админ",
};

export const EXP_STEPS = [
  ["draft", "Ноорог"],
  ["validating", "Validation ажиллаж байна"],
  ["validation_done", "Validation дууссан"],
  ["locked", "Сонголт түгжигдсэн"],
  ["test_done", "Тест дууссан"],
];

export const VERSION_STATUS = { imported: "Импортлогдсон", validated: "Шалгагдсан", failed: "Шалгалт бүтэлгүй" };
export const JOB_STATUS = { queued: "Дараалалд", running: "Ажиллаж байна", done: "Дууссан", failed: "Бүтэлгүй", cancelled: "Цуцлагдсан" };
export const JOB_TYPE = { import: "Импорт", regrid: "Шийдвэр хэрэглэх", validate: "Validation", test: "Эцсийн тест" };
export const SEVERITY = { blocking: "Блоклох", warning: "Анхааруулга", info: "Мэдээлэл" };
export const ACTIONS = { open: "Нээлттэй", accepted: "Хүлээн зөвшөөрсөн", corrected: "Залруулсан", excluded: "Хассан" };
export const MODEL_LABELS = { naive: "Naive", snaive: "Seasonal naive", ets: "ETS", croston: "Croston", sba: "SBA" };

export const fmt = (v, d = 2) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : Number(v).toLocaleString("mn-MN", { maximumFractionDigits: d });
export const pct = (v) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(0)}%`);
