import { useEffect, useState } from "react";
import { session } from "./api.js";
import { ROLE_LABELS } from "./labels.js";
import Login from "./pages/Login.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Import from "./pages/Import.jsx";
import Quality from "./pages/Quality.jsx";
import Experiments from "./pages/Experiments.jsx";
import Forecast from "./pages/Forecast.jsx";
import Compare from "./pages/Compare.jsx";
import Admin from "./pages/Admin.jsx";

// Хүснэгт 4.10-ын долоон дэлгэц; цэс эрхийн дагуу (Хүснэгт 4.11)
const SCREENS = [
  { path: "dashboard", title: "Самбар", roles: null, el: Dashboard },
  { path: "import", title: "Импорт", roles: ["data_steward"], el: Import },
  { path: "quality", title: "Чанарын шалгалт", roles: ["data_steward", "analyst", "researcher", "admin"], el: Quality },
  { path: "forecast", title: "Таамаглал", roles: ["data_steward", "analyst", "manager", "researcher"], el: Forecast },
  { path: "compare", title: "Загвар харьцуулалт", roles: ["data_steward", "analyst", "manager", "researcher"], el: Compare },
  { path: "experiments", title: "Туршилт", roles: ["researcher"], el: Experiments },
  { path: "admin", title: "Удирдлага", roles: ["admin"], el: Admin },
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
        <div className="brand">Таамаглалын систем<span>Бүтээгдэхүүн–салбар–өдөр</span></div>
        {visible.map((x) => (
          <a key={x.path} href={`#/${x.path}`} className={x === screen ? "active" : ""}
             aria-current={x === screen ? "page" : undefined}>{x.title}</a>
        ))}
        <div className="who">
          {s.user.full_name || s.user.username}
          <div>{roles.map((r) => ROLE_LABELS[r]).join(", ")}</div>
          <button onClick={() => { session.clear(); setS(null); go("login"); }}>Гарах</button>
        </div>
      </nav>
      <main><El params={route.params} user={s.user} /></main>
    </div>
  );
}
