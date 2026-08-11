import { useCallback, useEffect, useState } from "react";
import "./flashpoint.css";
import GeoCanvas, { project, bboxZoomK, type BBox } from "../../components/GeoCanvas";

const API = "/api/flashpoint";
const REFRESH_MS = 60_000;
const HOURS_CHIPS = [6, 24, 72];

/* CAMEO 루트코드 → 한국어 라벨·위험도 색 (14 시위 → 20 대량폭력) */
const ROOT_LABELS: Record<string, string> = {
  "14": "시위", "15": "무력과시", "16": "관계축소",
  "17": "강압", "18": "폭행", "19": "교전", "20": "대량폭력",
};
const ROOT_COLORS: Record<string, string> = {
  "14": "#facc15", "15": "#fbbf24", "16": "#fb923c",
  "17": "#f97316", "18": "#ef4444", "19": "#dc2626", "20": "#991b1b",
};

interface FpEvent {
  event_id: number;
  ts: number;
  root?: string | null;
  code?: string | null;
  actor1?: string | null;
  actor2?: string | null;
  mentions?: number | null;
  country?: string | null;
  lat: number;
  lon: number;
  source_url?: string | null;
}
interface Preset { id: string; label: string; bbox: BBox }
interface EventsResponse {
  events?: FpEvent[];
  stats?: { count: number; by_root: Record<string, number>; top_country: string | null; last_fetch: number | null };
}

function fmtTime(ts: number): string {
  const d = new Date(ts * 1000);
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/* 마커 반지름 — 언급 수 log 스케일, 지역 확대 시 화면 크기 유지(1/k) */
function radius(e: FpEvent, k: number): number {
  const base = 0.9 + Math.min(Math.log10(1 + (e.mentions ?? 0)), 2) * 0.7;
  return k > 1 ? (base * 2.2) / k : base;
}

export default function FlashpointApp() {
  const [view, setView] = useState<string>("world"); // "world" | preset id
  const [presets, setPresets] = useState<Preset[]>([]);
  const [hours, setHours] = useState<number>(24);
  const [data, setData] = useState<EventsResponse>({});
  const [selected, setSelected] = useState<number | null>(null);
  const [brief, setBrief] = useState<{ text?: string; loading?: boolean; error?: string }>({});

  const load = useCallback(async (v: string, h: number) => {
    const q = v === "world" ? `hours=${h}` : `preset=${encodeURIComponent(v)}&hours=${h}`;
    try { setData(await (await fetch(`${API}/events?${q}`)).json()); } catch { /* retry next tick */ }
  }, []);

  useEffect(() => {
    fetch(`${API}/preset`).then((r) => r.json()).then((p) => setPresets(p.presets ?? [])).catch(() => {});
  }, []);

  useEffect(() => {
    load(view, hours);
    const t = setInterval(() => load(view, hours), REFRESH_MS);
    return () => clearInterval(t);
  }, [view, hours, load]);

  const switchView = useCallback((id: string) => {
    setView(id);
    setSelected(null);
    setData({});
  }, []);

  const loadBrief = useCallback(async () => {
    setBrief({ loading: true });
    try {
      const target = view === "world" ? "" : `?preset=${encodeURIComponent(view)}`;
      const r = await fetch(`${API}/brief${target}`, { method: "POST" });
      const b = await r.json();
      setBrief(r.ok ? { text: b.brief } : { error: b.error ?? "브리핑 실패" });
    } catch { setBrief({ error: "브리핑 요청 실패" }); }
  }, [view]);

  const preset = presets.find((p) => p.id === view) ?? null;
  const bbox = preset?.bbox ?? null;
  const k = bboxZoomK(bbox);
  const events = data.events ?? [];
  const s = data.stats;
  const topRoot = s && Object.entries(s.by_root ?? {}).sort((a, b) => b[1] - a[1])[0];

  return (
    <div className="wrap">
      <header className="head">
        <h1>⚡ Flashpoint Watch</h1>
        <nav className="presets">
          <button className={view === "world" ? "on" : ""} onClick={() => switchView("world")}>🌍 전 세계</button>
          {presets.map((p) => (
            <button key={p.id} className={view === p.id ? "on" : ""}
                    onClick={() => switchView(p.id)}>{p.label}</button>
          ))}
        </nav>
        <nav className="chips">
          {HOURS_CHIPS.map((h) => (
            <button key={h} className={hours === h ? "on" : ""} onClick={() => setHours(h)}>{h}h</button>
          ))}
        </nav>
      </header>

      <p className="notice">뉴스 보도 기반 자동 추출(GDELT) — 중복·오탐이 포함될 수 있습니다.</p>

      {s && (
        <div className="stats">
          <span>이벤트 <b>{s.count}</b>건</span>
          <span>최다 유형 <b>{topRoot ? `${ROOT_LABELS[topRoot[0]] ?? topRoot[0]} ${topRoot[1]}건` : "-"}</b></span>
          <span>최다 국가 <b>{s.top_country ?? "-"}</b></span>
        </div>
      )}

      <GeoCanvas bbox={bbox} className="map">
        {events.map((e) => {
          const [x, y] = project(e.lon, e.lat);
          return (
            <circle key={e.event_id} cx={x} cy={y} r={radius(e, k)}
              className={`event${e.event_id === selected ? " selected" : ""}`}
              fill={ROOT_COLORS[e.root ?? ""] ?? "#9ca3af"}
              onClick={() => setSelected(e.event_id === selected ? null : e.event_id)} />
          );
        })}
      </GeoCanvas>

      <section className="brief">
        <button onClick={loadBrief} disabled={brief.loading}>
          {brief.loading ? "생성 중…" : "🤖 정세 브리핑"}
        </button>
        {brief.text && <p>{brief.text}</p>}
        {brief.error && <p className="error">{brief.error}</p>}
      </section>

      <table className="tbl">
        <thead><tr><th>시각(UTC+9)</th><th>유형</th><th>행위자</th><th>국가</th><th>언급</th><th>출처</th></tr></thead>
        <tbody>
          {events.slice(0, 50).map((e) => (
            <tr key={e.event_id} className={e.event_id === selected ? "on" : ""}
                onClick={() => setSelected(e.event_id === selected ? null : e.event_id)}>
              <td>{fmtTime(e.ts)}</td>
              <td><span className="dot" style={{ background: ROOT_COLORS[e.root ?? ""] ?? "#9ca3af" }} />{ROOT_LABELS[e.root ?? ""] ?? e.root ?? "-"}</td>
              <td>{e.actor1 ?? "?"} → {e.actor2 ?? "?"}</td>
              <td>{e.country ?? "-"}</td>
              <td>{e.mentions ?? 0}</td>
              <td>{e.source_url?.startsWith("http")
                ? <a href={e.source_url} target="_blank" rel="noreferrer" onClick={(ev) => ev.stopPropagation()}>기사</a>
                : "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
