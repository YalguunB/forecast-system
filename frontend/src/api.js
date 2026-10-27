// API клиент. Токеныг sessionStorage-д хадгална; алдааг {code, message, details}-ээр шиднэ.
const BASE = "/api/v1";

export const session = {
  get() {
    try { return JSON.parse(sessionStorage.getItem("fc_session") || "null"); } catch { return null; }
  },
  set(s) { try { sessionStorage.setItem("fc_session", JSON.stringify(s)); } catch { /* хувийн цонх */ } },
  clear() { try { sessionStorage.removeItem("fc_session"); } catch { /* */ } },
};

const STATUS_TEXT = {
  0: "Сервертэй холбогдож чадсангүй. API ажиллаж байгаа эсэхийг шалгана уу.",
  401: "Нэвтрэх хугацаа дууссан. Дахин нэвтэрнэ үү.",
  403: "Танд энэ үйлдлийг хийх эрх алга. Админд хандана уу.",
  404: "Хайсан зүйл олдсонгүй. Хэрэв шинэ хуудас бол API-г дахин эхлүүлсэн эсэхээ шалгана уу.",
  409: "Энэ үйлдлийг одоогийн төлөвт хийх боломжгүй.",
  413: "Файл хэт том байна.",
  422: "Оруулсан мэдээлэл буруу байна. Талбаруудыг шалгана уу.",
  500: "Серверт алдаа гарлаа. API-ийн терминал дээрх алдааг харна уу.",
};

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.message || STATUS_TEXT[status] || `Алдаа гарлаа (код ${status})`);
    this.status = status;
    this.code = body?.code;
    this.details = body?.details;
  }
}

async function request(method, path, { json, form, raw } = {}) {
  const s = session.get();
  const headers = {};
  if (s?.token) headers.Authorization = `Bearer ${s.token}`;
  let body;
  if (json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  if (form) body = form;
  let res;
  try {
    res = await fetch(BASE + path, { method, headers, body });
  } catch {
    throw new ApiError(0, {});
  }
  if (res.status === 401 && s) { session.clear(); window.location.hash = "#/login"; }
  if (raw) {
    if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => ({})));
    return res;
  }
  const data = res.status === 204 ? null : await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export const api = {
  get: (p) => request("GET", p),
  post: (p, json) => request("POST", p, { json }),
  put: (p, json) => request("PUT", p, { json }),
  patch: (p, json) => request("PATCH", p, { json }),
  upload: (p, form) => request("POST", p, { form }),
  async download(p, filename) {
    const res = await request("GET", p, { raw: true });
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  },
  async login(username, password) {
    const form = new URLSearchParams({ username, password });
    const res = await fetch(BASE + "/auth/token", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new ApiError(res.status, data);
    session.set({ token: data.access_token, user: data.user });
    return data.user;
  },
};

// Ажлыг дуустал асууна (FR-M5)
export async function waitJob(id, onProgress) {
  for (;;) {
    const j = await api.get(`/jobs/${id}`);
    onProgress?.(j);
    if (["done", "failed", "cancelled"].includes(j.status)) return j;
    await new Promise((r) => setTimeout(r, 1500));
  }
}
