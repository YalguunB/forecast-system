import { useEffect, useState } from "react";
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
import Admin from "./pages/Admin.jsx";

// n: менежерийн ажлын дарааллын дугаар (цэсэнд харагдана)
const SCREENS = [
  { path: "dashboard", title: "Нүүр", roles: null, el: Dashboard },
  { path: "import", n: 1, title: "Өгөгдөл оруулах", roles: ["manager"], el: Import },
  { path: "quality", n: 2, title: "Өгөгдөл шалгах", roles: ["executive", "manager"], el: Quality },
  { path: "experiments", n: 3, title: "Таамаглал гаргуулах", roles: ["manager"], el: Experiments },
  { path: "forecast", n: 4, title: "Бүтээгдэхүүний таамаглал", roles: ["executive", "manager"], el: Forecast },
  { path: "reports", title: "Тайлан", roles: ["executive", "manager"], el: Reports },
  { path: "compare", title: "Аргуудын харьцуулалт", roles: ["executive", "manager"], el: Compare },
  { path: "admin", title: "Хэрэглэгч ба эрх", roles: ["admin"], el: Admin },
];

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
  useEffect(() => {
    const on = () => { setRoute(parseHash()); setS(session.get()); };
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
      <nav className="rail" aria-label="Үндсэн цэс">
        <div className="brand">Таамаглалын систем<span>Сар, улирал, жилийн таамаглал</span></div>
        {visible.map((x) => (
          <a key={x.path} href={`#/${x.path}`} className={x === screen ? "active" : ""}
             aria-current={x === screen ? "page" : undefined}>
            {x.n && roles.includes("manager") ? <span className="step-n" aria-hidden="true">{x.n}</span> : null}{x.title}
          </a>
        ))}
        <div className="who">
          {s.user.full_name || s.user.username}
          <div>{roles.map((r) => ROLE_LABELS[r]).join(", ")}</div>
          {roles.includes("manager") && <div>Салбар: {branchText(s.user.branches)}</div>}
          <button onClick={() => { session.clear(); setS(null); go("login"); }}>Гарах</button>
        </div>
      </nav>
      <main><El params={route.params} user={s.user} /></main>
    </div>
  );
}
