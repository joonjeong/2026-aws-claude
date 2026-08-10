import type { AppDef } from "../apps/types";
import { useModules } from "./useModules";

interface Props {
  apps: AppDef[];
  navigate: (p: string) => void;
}

export default function Home({ apps, navigate }: Props) {
  const { isEnabled, statusLine } = useModules();

  return (
    <div className="home">
      <header className="home-header">
        <h1>
          claude-lab<small>시스템 개요</small>
        </h1>
      </header>
      <main className="home-grid">
        {apps.length === 0 && (
          <div className="home-empty">이 빌드에 포함된 앱이 없습니다 (VITE_APPS 확인)</div>
        )}
        {apps.map((a) => {
          const enabled = isEnabled(a.id);
          return (
            <button
              key={a.id}
              className={`home-card${enabled ? "" : " disabled"}`}
              onClick={() => enabled && navigate(`/${a.id}`)}
              disabled={!enabled}
            >
              <div className="card-icon">{a.icon}</div>
              <div className="card-title">{a.title}</div>
              <div className="card-tagline">{a.tagline}</div>
              <div className="card-status">
                <span className={`dot${enabled ? "" : " off"}`} />
                <span>{enabled ? statusLine(a.id) : "백엔드 모듈 비활성 (ENABLED_MODULES)"}</span>
              </div>
            </button>
          );
        })}
      </main>
    </div>
  );
}
