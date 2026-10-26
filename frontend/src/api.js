// API клиент. Токеныг sessionStorage-д хадгална; алдааг {code, message, details}-ээр шиднэ.
const BASE = "/api/v1";

export const session = {
  get() {
    try { return JSON.parse(sessionStorage.getItem("fc_session") || "null"); } catch { return null; }
  },
  set(s) { try { sessionStorage.setItem("fc_session", JSON.stringify(s)); } catch { /* хувийн цонх */ } },
  clear() { try { sessionStorage.removeItem("fc_session"); } catch { /* */ } },
};

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.message || `HTTP ${status}`);
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
  const res = await fetch(BASE + path, { method, headers, body });
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
