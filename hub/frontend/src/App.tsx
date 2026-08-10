import { Suspense, useCallback, useEffect, useState } from "react";
import { APPS } from "virtual:apps";
import type { AppDef } from "./apps/types";
import Sidebar, { type MenuItem } from "./shell/Sidebar";
import Home from "./shell/Home";
import Laboratory from "./shell/Laboratory";

/* 사이드바 메뉴 순서 — virtual:apps 등록 순서와 무관하게 셸이 소유 */
const MENU_ORDER = ["market", "news", "trend", "quake"];
const orderedApps = MENU_ORDER.map((id) => APPS.find((a) => a.id === id)).filter(
  (a): a is AppDef => Boolean(a),
);

const MENU_ITEMS: MenuItem[] = [
  ...orderedApps.map(({ id, title, icon }) => ({ id, title, icon })),
  { id: "lab", title: "Laboratory", icon: "🧪", static: true },
];

function usePath(): [string, (p: string) => void] {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const navigate = useCallback((p: string) => {
    window.history.pushState(null, "", p);
    setPath(p);
  }, []);
  return [path, navigate];
}

export default function App() {
  const [path, navigate] = usePath();

  const seg = path.split("/").filter(Boolean)[0] ?? "";
  const active = APPS.find((a) => a.id === seg);

  return (
    <div className="shell">
      <Sidebar items={MENU_ITEMS} activeId={seg} navigate={navigate} />
      <main className={`shell-content${active ? ` app-${active.id}` : ""}`}>
        {active ? (
          <Suspense fallback={<div className="shell-loading">불러오는 중…</div>}>
            <active.Component />
          </Suspense>
        ) : seg === "lab" ? (
          <Laboratory />
        ) : (
          /* 알 수 없는 경로는 홈으로 폴백 */
          <Home apps={orderedApps} navigate={navigate} />
        )}
      </main>
    </div>
  );
}
