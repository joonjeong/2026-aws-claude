import { useQuery } from "@tanstack/react-query";
import type { AppDef } from "../apps/types";
import { toggleTheme } from "../theme";

interface Props {
  apps: AppDef[];
  navigate: (p: string) => void;
}

interface ModulesResp {
  modules: { id: string; title: string; tagline: string; icon: string; path: string }[];
}

async function fetchJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(String(r.status));
  return r.json() as Promise<T>;
}

export default function Launcher({ apps, navigate }: Props) {
  const modules = useQuery({
    queryKey: ["modules"],
    queryFn: () => fetchJson<ModulesResp>("/api/modules"),
    refetchInterval: 30_000,
  });
  const health = useQuery({
    queryKey: ["healthz"],
    queryFn: () => fetchJson<{ modules: Record<string, unknown> }>("/healthz"),
    refetchInterval: 30_000,
  });

  const backendEnabled = new Set(modules.data?.modules.map((m) => m.id) ?? []);

  function statusLine(id: string): string {
    const h = health.data?.modules?.[id];
    if (!h || typeof h !== "object") return "상태 정보 없음";
    const parts: string[] = [];
    for (const [k, v] of Object.entries(h as Record<string, unknown>)) {
      if (typeof v === "number") parts.push(`${k} ${v.toLocaleString()}`);
    }
    return parts.slice(0, 3).join(" · ") || "상태 정보 없음";
  }

  return (
    <div className="launcher">
      <header className="launcher-header">
        <h1>
          claude-lab hub<small>모듈을 선택하세요</small>
        </h1>
        <button className="shell-btn" onClick={() => toggleTheme()}>
          테마
        </button>
      </header>
      <main className="launcher-grid">
        {apps.length === 0 && (
          <div className="launcher-empty">이 빌드에 포함된 앱이 없습니다 (VITE_APPS 확인)</div>
        )}
        {apps.map((a) => {
          const enabled = modules.isPending || backendEnabled.has(a.id);
          return (
            <button
              key={a.id}
              className={`launcher-card${enabled ? "" : " disabled"}`}
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
