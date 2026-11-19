import { Fragment, useEffect, useState } from "react";
import { session } from "./api.js";
import { ROLE_LABELS, branchText } from "./labels.js";
import Login from "./pages/Login.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Import from "./pages/Import.jsx";
import Quality from "./pages/Quality.jsx";
import Experiments from "./pages/Experiments.jsx";
import Forecast from "./pages/Forecast.jsx";
import Compare from "./pages/Compare.jsx";
import Reports from "./pages/Reports.jsx";
import Tracking from "./pages/Tracking.jsx";
import Admin from "./pages/Admin.jsx";

// n: менежерийн ажлын дарааллын дугаар (цэсэнд харагдана)
const SCREENS = [
  { path: "dashboard", title: "Нүүр", roles: null, el: Dashboard },
  { path: "import", n: 1, title: "Өгөгдөл оруулах", roles: ["manager"], el: Import },
  { path: "quality", n: 2, title: "Өгөгдөл шалгах", roles: ["executive", "manager"], el: Quality },
  { path: "experiments", n: 3, title: "Таамаглах", roles: ["manager"], el: Experiments },
  { path: "forecast", n: 4, title: "Барааны таамаглал", roles: ["executive", "manager"], el: Forecast },
  { path: "reports", title: "Тайлан", roles: ["executive", "manager"], el: Reports },
  { path: "tracking", title: "Гүйцэтгэл", roles: ["executive", "manager"], el: Tracking },
  { path: "compare", title: "Аргуудын харьцуулалт", short: "Аргууд", roles: ["executive", "manager"], el: Compare },
  { path: "admin", title: "Хэрэглэгч ба эрх", roles: ["admin"], el: Admin },
];

// Үсгээр эхэлсэн эхний хоёр үгийн эхний үсэг («Болормаа (менежер)» → «БМ», хаалт, тэмдэгтийг алгасна)
const initials = (n) => n.split(/\s+/).map((w) => w.replace(/[^\p{L}]/gu, "")).filter(Boolean).slice(0, 2)
  .map((w) => w[0].toUpperCase()).join("") || "?";

// Тэмдэг: өсөх гурван багана, сүүлийнх нь таамаглал (тасархай)
export function Mark() {
  return (
    <span className="mark" aria-hidden="true">
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <rect x="1.5" y="9" width="3" height="5.5" rx="1" fill="currentColor" />
        <rect x="6.5" y="5.5" width="3" height="9" rx="1" fill="currentColor" />
        <rect x="11.5" y="2" width="3" height="12.5" rx="1" stroke="currentColor" strokeWidth="1.2" strokeDasharray="2 1.6" />
      </svg>
    </span>
  );
}

function parseHash() {
  const [path, query = ""] = window.location.hash.replace(/^#\/?/, "").split("?");
  return { path: path || "dashboard", params: Object.fromEntries(new URLSearchParams(query)) };
}

export function go(path, params = {}) {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null)).toString();
  window.location.hash = `#/${path}${q ? `?${q}` : ""}`;
}

export default function App() {
  const [route, setRoute] = useState(parseHash());
  const [s, setS] = useState(session.get());
  const [menu, setMenu] = useState(false);          // утсан дээрх эвхдэг цэс
  useEffect(() => {
    const on = () => { setRoute(parseHash()); setS(session.get()); setMenu(false); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  if (!s?.token || route.path === "login") return <Login onLogin={() => { setS(session.get()); go("dashboard"); }} />;
  const roles = s.user.roles;
  const visible = SCREENS.filter((x) => !x.roles || x.roles.some((r) => roles.includes(r)));
  const screen = visible.find((x) => x.path === route.path) || visible[0];
  const El = screen.el;
  return (
    <div className="shell">
      <header className={`topbar${menu ? " open" : ""}`}>
        <a className="brand" href="#/dashboard"><Mark />Таамаглал</a>
        <button className="quiet menu-btn" aria-expanded={menu} aria-controls="main-nav" onClick={() => setMenu(!menu)}>
          {menu ? "Хаах" : `Цэс · ${screen.short || screen.title}`}
        </button>
        <nav className="nav" id="main-nav" aria-label="Үндсэн цэс">
          {visible.map((x, i) => (
            <Fragment key={x.path}>
              {/* Менежерийн 4 алхмын дараа бусад хуудсыг зураасаар тусгаарлана */}
              {i > 0 && !x.n && visible[i - 1].n && <span className="sep" aria-hidden="true" />}
              <a href={`#/${x.path}`} className={x === screen ? "active" : ""} aria-current={x === screen ? "page" : undefined}>
                {x.n && roles.includes("manager") ? <span className="step-n" aria-hidden="true">{x.n}</span> : null}{x.short || x.title}
              </a>
            </Fragment>
          ))}
        </nav>
        <div className="who">
          <span className="avatar" title={`${s.user.full_name || s.user.username} · ${roles.map((r) => ROLE_LABELS[r]).join(", ")}`} aria-hidden="true">{initials(s.user.full_name || s.user.username)}</span>
          <span className="id">
            <b>{s.user.full_name || s.user.username}</b>
            <span>{roles.map((r) => ROLE_LABELS[r]).join(", ")}{roles.includes("manager") ? `, ${branchText(s.user.branches).toLowerCase()}` : ""}</span>
          </span>
          <button onClick={() => { session.clear(); setS(null); go("login"); }}>Гарах</button>
        </div>
      </header>
      <main><El params={route.params} user={s.user} /></main>
    </div>
  );
}
