import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./wake.css";
import GeoCanvas, { project, bboxZoomK, type BBox } from "../../components/GeoCanvas";

const API = "/api/wake";
const REFRESH_MS = 15_000;

/* ---------- API types ---------- */

interface Vessel {
  id: string;
  ts: number;
  lon: number;
  lat: number;
  sog_kn: number | null;
  cog_deg: number | null;
  heading_deg: number | null;
  name?: string | null;
  ship_type?: string | null;
}

interface Trail { id: string; points: [number, number, number][] } // [ts, lon, lat]

interface Preset { id: string; label: string; bbox: BBox }

interface RegionResponse {
  vessels?: Vessel[];
  trails?: Trail[];
  preset?: string;
  status?: string;
  stats?: { count: number; moving: number; top_type: string | null; max_sog: number };
}

const SHIP_TYPES = ["화물", "탱커", "여객", "어선", "기타"] as const;

/** 속력 색: 정박(<0.5kn) 회색 → 20kn+ 주황 */
function speedColor(sog: number | null): string {
  if (sog == null || sog < 0.5) return "var(--muted)";
  const t = Math.min(sog / 20, 1);
  const hue = 210 - t * 180; // 파랑(느림) → 주황(빠름)
  return `hsl(${hue} 80% 55%)`;
}

function VesselMarker(props: { v: Vessel; k: number; selected: boolean; onClick: () => void }) {
  const { v, k, selected, onClick } = props;
  const [x, y] = project(v.lon, v.lat);
  const rot = v.heading_deg ?? v.cog_deg ?? 0;
  const s = 1 / k;
  return (
    <g
      transform={`translate(${x},${y}) rotate(${rot}) scale(${s})`}
      className={`vessel${selected ? " selected" : ""}`}
      onClick={onClick}
    >
      <polygon points="0,-7 4.5,7 -4.5,7" fill={speedColor(v.sog_kn)} />
    </g>
  );
}

export default function WakeApp() {
  const [data, setData] = useState<RegionResponse>({});
  const [presets, setPresets] = useState<Preset[]>([]);
  const [active, setActive] = useState<string>("kr");
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [historyPts, setHistoryPts] = useState<[number, number, number][]>([]);
  const [brief, setBrief] = useState<{ text?: string; loading?: boolean; error?: string }>({});
  const selectedRef = useRef<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = (await (await fetch(`${API}/region`)).json()) as RegionResponse;
      setData(r);
      if (r.preset) setActive(r.preset);
    } catch { /* 다음 주기 재시도 */ }
  }, []);

  useEffect(() => {
    fetch(`${API}/preset`).then((r) => r.json()).then((p) => {
      setPresets(p.presets ?? []);
      setActive(p.active ?? "kr");
    }).catch(() => {});
    load();
    const t = setInterval(load, REFRESH_MS);
    return () => clearInterval(t);
  }, [load]);

  const switchPreset = useCallback(async (id: string) => {
    setActive(id);
    setSelected(null);
    selectedRef.current = null;
    setHistoryPts([]);
    await fetch(`${API}/preset`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ id }),
    }).catch(() => {});
    load();
  }, [load]);

  const selectVessel = useCallback(async (id: string) => {
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
      const r = await fetch(`${API}/brief`, { method: "POST" });
      const b = await r.json();
      setBrief(r.ok ? { text: b.brief } : { error: b.error ?? "브리핑 실패" });
    } catch { setBrief({ error: "브리핑 요청 실패" }); }
  }, []);

  const preset = presets.find((p) => p.id === active) ?? null;
  const bbox = preset?.bbox ?? null;
  const k = bboxZoomK(bbox);

  const vessels = useMemo(() => {
    const all = data.vessels ?? [];
    return typeFilter ? all.filter((v) => (v.ship_type ?? "기타") === typeFilter) : all;
  }, [data.vessels, typeFilter]);
  const shown = new Set(vessels.map((v) => v.id));
  const stats = data.stats;

  return (
    <div className="wrap">
      <header className="head">
        <h1>🌊 Wake Watch</h1>
        <nav className="presets">
          {presets.map((p) => (
            <button
              key={p.id}
              className={p.id === active ? "on" : ""}
              onClick={() => switchPreset(p.id)}
            >{p.label}</button>
          ))}
        </nav>
      </header>

      {data.status === "no_key" && (
        <p className="notice">WAKE_AIS_KEY가 설정되지 않아 수집이 비활성 상태입니다.</p>
      )}

      {stats && (
        <div className="stats">
          <span>선박 <b>{stats.count}</b>척</span>
          <span>이동 중 <b>{stats.moving}</b>척</span>
          <span>최다 선종 <b>{stats.top_type ?? "-"}</b></span>
          <span>최고 속력 <b>{stats.max_sog?.toFixed?.(1) ?? 0}</b>kn</span>
        </div>
      )}

      <div className="chips">
        <button className={!typeFilter ? "on" : ""} onClick={() => setTypeFilter(null)}>전체</button>
        {SHIP_TYPES.map((t) => (
          <button key={t} className={typeFilter === t ? "on" : ""}
                  onClick={() => setTypeFilter(typeFilter === t ? null : t)}>{t}</button>
        ))}
      </div>

      <GeoCanvas bbox={bbox} className="map">
        {(data.trails ?? []).filter((t) => shown.has(t.id)).map((t) => (
          <polyline
            key={t.id}
            points={t.points.map(([, lon, lat]) => project(lon, lat).join(",")).join(" ")}
            className={`trail${t.id === selected ? " selected" : ""}`}
            vectorEffect="non-scaling-stroke"
          />
        ))}
        {selected && historyPts.length > 1 && (
          <polyline
            points={historyPts.map(([, lon, lat]) => project(lon, lat).join(",")).join(" ")}
            className="trail history"
            vectorEffect="non-scaling-stroke"
          />
        )}
        {vessels.map((v) => (
          <VesselMarker key={v.id} v={v} k={k}
                        selected={v.id === selected}
                        onClick={() => selectVessel(v.id)} />
        ))}
      </GeoCanvas>

      <section className="brief">
        <button onClick={loadBrief} disabled={brief.loading}>
          {brief.loading ? "생성 중…" : "🤖 해역 브리핑"}
        </button>
        {brief.text && <p>{brief.text}</p>}
        {brief.error && <p className="error">{brief.error}</p>}
      </section>

      <table className="tbl">
        <thead><tr><th>선명</th><th>MMSI</th><th>선종</th><th>속력</th><th>침로</th></tr></thead>
        <tbody>
          {vessels.slice(0, 50).map((v) => (
            <tr key={v.id} className={v.id === selected ? "on" : ""}
                onClick={() => selectVessel(v.id)}>
              <td>{v.name ?? "-"}</td>
              <td>{v.id}</td>
              <td>{v.ship_type ?? "기타"}</td>
              <td>{v.sog_kn?.toFixed?.(1) ?? "-"}kn</td>
              <td>{v.cog_deg != null ? `${Math.round(v.cog_deg)}°` : "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
