import { toggleTheme } from "../theme";
import { useModules } from "./useModules";

export interface MenuItem {
  id: string;
  title: string;
  icon: string;
  /** virtual:apps 레지스트리 밖의 셸 정적 메뉴 (예: Laboratory) — 백엔드 활성 검사 제외 */
  static?: boolean;
}

interface Props {
  items: MenuItem[];
  activeId: string;
  navigate: (p: string) => void;
}

export default function Sidebar({ items, activeId, navigate }: Props) {
  const { isEnabled } = useModules();

  return (
    <aside className="sidebar">
      <button className="sidebar-brand" onClick={() => navigate("/")} title="시스템 홈">
        <span className="brand-icon">◆</span>
        <span className="brand-name">claude-lab</span>
      </button>
      <nav className="sidebar-nav">
        {items.map((it) => {
          const enabled = it.static || isEnabled(it.id);
          return (
            <button
              key={it.id}
              className={`nav-item${activeId === it.id ? " active" : ""}${enabled ? "" : " disabled"}`}
              onClick={() => enabled && navigate(`/${it.id}`)}
              disabled={!enabled}
              title={it.title}
            >
              <span className="nav-icon">{it.icon}</span>
              <span className="nav-label">{it.title}</span>
            </button>
          );
        })}
      </nav>
      <footer className="sidebar-foot">
        <button className="nav-item" onClick={() => toggleTheme()} title="테마 전환">
          <span className="nav-icon">◐</span>
          <span className="nav-label">테마</span>
        </button>
      </footer>
    </aside>
  );
}
