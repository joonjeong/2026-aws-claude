import { useCallback, useEffect, useRef, useState } from "react";
import "./contrail.css";
import GeoCanvas, { project, bboxZoomK, type BBox } from "../../components/GeoCanvas";

const API = "/api/contrail";
const WORLD_REFRESH_MS = 60_000;
const REGION_REFRESH_MS = 30_000;

interface Flight {
  id: string;
  ts: number;
  lon: number;
  lat: number;
  callsign?: string | null;
  type?: string | null;   // 기종 코드 (adsb.lol `t`, 예: A359 — opensky 롤백 시 null)
  reg?: string | null;    // 등록부호 (adsb.lol `r`, 예: HL7771)
  alt_m: number | null;
  velocity_ms: number | null;
  track_deg: number | null;
  on_ground: boolean;
}

interface Trail { id: string; points: [number, number, number][] }
interface Preset { id: string; label: string; bbox: BBox }

interface GlobalResponse {
  flights?: Flight[];
  stats?: { count: number; airborne: number; top_type: string | null; last_fetch: number | null };
}
interface RegionResponse {
  flights?: Flight[];
  trails?: Trail[];
  preset?: string;
  stats?: { count: number; airborne: number };
}

/** 고도 색: 지상 회색, 저고도 주황 → 순항(10km+) 파랑 */
function altColor(f: Flight): string {
  if (f.on_ground) return "var(--muted)";
  const t = Math.min((f.alt_m ?? 0) / 11_000, 1);
  const hue = 30 + t * 190; // 주황(저고도) → 파랑(순항)
  return `hsl(${hue} 75% 55%)`;
}

export default function ContrailApp() {
  const [view, setView] = useState<string>("world"); // "world" | preset id
  const [presets, setPresets] = useState<Preset[]>([]);
  const [world, setWorld] = useState<GlobalResponse>({});
  const [region, setRegion] = useState<RegionResponse>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [historyPts, setHistoryPts] = useState<[number, number, number][]>([]);
  const [brief, setBrief] = useState<{ text?: string; loading?: boolean; error?: string }>({});
  const selectedRef = useRef<string | null>(null);

  const loadWorld = useCallback(async () => {
    try { setWorld(await (await fetch(`${API}/global`)).json()); } catch { /* retry next tick */ }
  }, []);
  // 모든 프리셋이 서버에서 상시 수집·저장되므로 전환은 조회 파라미터만 바꾼다
  const loadRegion = useCallback(async (id: string) => {
    try {
      setRegion(await (await fetch(`${API}/region?preset=${encodeURIComponent(id)}`)).json());
    } catch { /* retry next tick */ }
  }, []);

  useEffect(() => {
    fetch(`${API}/preset`).then((r) => r.json()).then((p) => setPresets(p.presets ?? [])).catch(() => {});
  }, []);

  useEffect(() => {
    loadWorld();
    const tw = setInterval(loadWorld, WORLD_REFRESH_MS);
    return () => clearInterval(tw);
  }, [loadWorld]);

  useEffect(() => {
    if (view === "world") return;
    loadRegion(view);
    const tr = setInterval(() => loadRegion(view), REGION_REFRESH_MS);
    return () => clearInterval(tr);
  }, [view, loadRegion]);

  const switchView = useCallback((id: string) => {
    setView(id);
    setSelected(null);
    selectedRef.current = null;
    setHistoryPts([]);
    setRegion({}); // 이전 지역 잔상 방지 — 다음 tick에 새 프리셋 데이터로 채워짐
  }, []);

  const selectFlight = useCallback(async (id: string) => {
    setSelected(id);
    selectedRef.current = id;
    try {
      const h = await (await fetch(`${API}/history?id=${encodeURIComponent(id)}&hours=24`)).json();
      if (selectedRef.current === id) setHistoryPts(h.points ?? []);
    } catch {
      if (selectedRef.current === id) setHistoryPts([]);
    }
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

  const isWorld = view === "world";
  const preset = presets.find((p) => p.id === view) ?? null;
  const bbox = preset?.bbox ?? null;
  const k = bboxZoomK(bbox);
  const flights = (isWorld ? world.flights : region.flights) ?? [];
  const gs = world.stats;

  return (
    <div className="wrap">
      <header className="head">
        <h1>✈️ Contrail Watch</h1>
        <nav className="presets">
          <button className={isWorld ? "on" : ""} onClick={() => switchView("world")}>🌍 전 세계</button>
          {presets.map((p) => (
            <button key={p.id} className={view === p.id ? "on" : ""}
                    onClick={() => switchView(p.id)}>{p.label}</button>
          ))}
        </nav>
      </header>

      {gs && (
        <div className="stats">
          <span>추적 <b>{gs.count}</b>대</span>
          <span>공중 <b>{gs.airborne}</b>대</span>
          <span>최다 기종 <b>{gs.top_type ?? "-"}</b></span>
          {!isWorld && region.stats && <span>지역 <b>{region.stats.count}</b>대</span>}
        </div>
      )}

      <GeoCanvas bbox={bbox} className="map">
        {!isWorld && (region.trails ?? []).map((t) => (
          <polyline key={t.id}
            points={t.points.map(([, lon, lat]) => project(lon, lat).join(",")).join(" ")}
            className={`trail${t.id === selected ? " selected" : ""}`}
            vectorEffect="non-scaling-stroke" />
        ))}
        {selected && historyPts.length > 1 && (
          <polyline
            points={historyPts.map(([, lon, lat]) => project(lon, lat).join(",")).join(" ")}
            className="trail history" vectorEffect="non-scaling-stroke" />
        )}
        {isWorld
          ? flights.map((f) => {
              const [x, y] = project(f.lon, f.lat);
              return <circle key={f.id} cx={x} cy={y} r={0.8} fill={altColor(f)} />;
            })
          : flights.map((f) => {
              const [x, y] = project(f.lon, f.lat);
              return (
                <g key={f.id}
                   transform={`translate(${x},${y}) rotate(${f.track_deg ?? 0}) scale(${1 / k})`}
                   className={`plane${f.id === selected ? " selected" : ""}`}
                   onClick={() => selectFlight(f.id)}>
                  <polygon points="0,-7 4.5,7 0,4 -4.5,7" fill={altColor(f)} />
                </g>
              );
            })}
      </GeoCanvas>

      <section className="brief">
        <button onClick={loadBrief} disabled={brief.loading}>
          {brief.loading ? "생성 중…" : "🤖 항공 브리핑"}
        </button>
        {brief.text && <p>{brief.text}</p>}
        {brief.error && <p className="error">{brief.error}</p>}
      </section>

      {!isWorld && (
        <table className="tbl">
          <thead><tr><th>콜사인</th><th>기종</th><th>고도</th><th>속도</th></tr></thead>
          <tbody>
            {flights.slice(0, 50).map((f) => (
              <tr key={f.id} className={f.id === selected ? "on" : ""}
                  onClick={() => selectFlight(f.id)}>
                <td title={f.reg ?? undefined}>{f.callsign ?? f.id}</td>
                <td>{f.type ?? "-"}</td>
                <td>{f.alt_m != null ? `${Math.round(f.alt_m)}m` : "-"}</td>
                <td>{f.velocity_ms != null ? `${Math.round(f.velocity_ms * 3.6)}km/h` : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
