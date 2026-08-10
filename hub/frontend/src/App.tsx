import { Suspense, useCallback, useEffect, useState } from "react";
import { APPS } from "virtual:apps";
import Launcher from "./launcher/Launcher";
import { toggleTheme } from "./theme";

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
  const [, rerender] = useState(0);

  const seg = path.split("/").filter(Boolean)[0] ?? "";
  const active = APPS.find((a) => a.id === seg);

  if (!active) {
    return <Launcher apps={APPS} navigate={navigate} />;
  }

  const C = active.Component;
  return (
    <div className={`app-shell app-${active.id}`}>
      <nav className="shell-bar">
        <button className="shell-btn" onClick={() => navigate("/")}>
          ← 런처
        </button>
        <span className="shell-title">
          {active.icon} {active.title}
        </span>
        <button
          className="shell-btn"
          onClick={() => {
            toggleTheme();
            rerender((n) => n + 1);
          }}
        >
          테마
        </button>
      </nav>
      <Suspense fallback={<div className="shell-loading">불러오는 중…</div>}>
        <C />
      </Suspense>
    </div>
  );
}
