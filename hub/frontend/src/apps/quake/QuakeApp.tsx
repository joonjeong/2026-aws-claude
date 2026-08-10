import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./quake.css";
import { GRChart, HourHistogram } from "./charts";
import { PLATE_BOUNDARIES } from "./plates";
import {
  MAP_W as W,
  MAP_H as H,
  PRESETS,
  findPreset,
  inPreset,
  presetViewBox,
  presetZoomK,
  type Preset,
  type PresetId,
} from "./presets";

const API = "/api/quake";

/* 시간 창 (시간 단위) — localStorage `quake-hours`에 유지 */
type HoursWindow = 6 | 24;
const DEFAULT_HOURS: HoursWindow = 24;
const HOURS_OPTIONS: ReadonlyArray<HoursWindow> = [6, 24];

/** USGS 이벤트 상세 페이지 */
const usgsUrl = (id: string): string =>
  `https://earthquake.usgs.gov/earthquakes/eventpage/${encodeURIComponent(id)}`;

/* ---------- API types ---------- */

interface QuakeEvent {
  id: string;
  mag: number;
  place: string;
  time: number; // epoch ms
  lon: number;
  lat: number;
  depth_km: number;
}

interface QuakesResponse {
  events?: QuakeEvent[];
  stats?: { last_fetch?: number | null }; // epoch seconds
  new_ids?: string[]; // 마지막 수집 사이클에 새로 들어온 이벤트 id
}

interface BriefResponse {
  brief?: string;
  cached?: boolean;
  error?: string;
  detail?: string;
}

/* ---------- simple hardcoded continent outlines (lon,lat polylines) ---------- */

const CONTINENTS: ReadonlyArray<ReadonlyArray<readonly [number, number]>> = [
  // North America
  [[-168, 66], [-160, 70], [-140, 70], [-125, 72], [-110, 73], [-95, 72], [-80, 70], [-70, 62], [-55, 50],
   [-67, 45], [-75, 38], [-81, 31], [-80, 25], [-88, 30], [-97, 27], [-97, 22], [-105, 20], [-95, 16], [-83, 9],
   [-79, 8], [-85, 12], [-92, 15], [-105, 22], [-112, 28], [-117, 33], [-122, 38], [-124, 45], [-128, 52],
   [-132, 57], [-152, 60], [-165, 60], [-168, 66]],
  // Greenland
  [[-45, 60], [-53, 66], [-56, 71], [-61, 76], [-45, 82], [-30, 83], [-20, 80], [-22, 70], [-32, 66], [-40, 60], [-45, 60]],
  // South America
  [[-79, 8], [-75, 10], [-71, 12], [-63, 10], [-52, 4], [-45, -2], [-35, -8], [-39, -15], [-48, -25], [-53, -34],
   [-58, -39], [-65, -41], [-65, -47], [-68, -52], [-70, -54], [-73, -50], [-71, -42], [-71, -33], [-70, -25],
   [-75, -15], [-81, -6], [-80, 0], [-79, 8]],
  // Africa
  [[-6, 35], [10, 37], [20, 32], [32, 31], [43, 11], [51, 12], [48, 5], [40, -3], [35, -15], [33, -26], [27, -34],
   [20, -35], [15, -27], [12, -18], [9, -1], [8, 4], [-8, 4], [-17, 15], [-17, 21], [-10, 30], [-6, 35]],
  // Eurasia
  [[-9, 38], [-9, 43], [-2, 44], [0, 49], [4, 52], [8, 55], [10, 59], [5, 62], [15, 69], [25, 71], [35, 69],
   [45, 68], [60, 69], [75, 73], [95, 76], [110, 74], [130, 72], [150, 70], [160, 70], [170, 66], [178, 65],
   [170, 60], [160, 60], [156, 51], [142, 53], [135, 44], [130, 42], [122, 39], [122, 30], [110, 20], [109, 12],
   [103, 1], [98, 8], [91, 22], [87, 21], [80, 15], [77, 8], [73, 20], [67, 24], [57, 25], [52, 24], [48, 30],
   [56, 26], [58, 22], [52, 16], [43, 12], [35, 28], [36, 36], [30, 36], [26, 40], [20, 40], [15, 38], [12, 44],
   [5, 43], [-2, 36], [-9, 38]],
  // Australia
  [[114, -22], [122, -17], [131, -12], [137, -12], [141, -13], [143, -11], [146, -19], [150, -23], [153, -28],
   [150, -37], [144, -38], [140, -38], [135, -35], [129, -32], [124, -33], [115, -34], [113, -26], [114, -22]],
  // Antarctica (open coastline)
  [[-180, -72], [-150, -75], [-100, -73], [-60, -70], [-45, -75], [0, -70], [50, -68], [90, -67], [140, -67], [180, -72]],
];

/* equirectangular projection: x=(lon+180)/360*W, y=(90-lat)/180*H */
const px = (lon: number): number => ((lon + 180) / 360) * W;
const py = (lat: number): number => ((90 - lat) / 180) * H;

const toPoints = (line: ReadonlyArray<readonly [number, number]>): string =>
  line.map(([lon, lat]) => `${px(lon).toFixed(1)},${py(lat).toFixed(1)}`).join(" ");

const CONTINENT_POINTS: string[] = CONTINENTS.map(toPoints);
const PLATE_POINTS: Array<{ name: string; points: string }> = PLATE_BOUNDARIES.map((b) => ({
  name: b.name,
  points: toPoints(b.points),
}));

/* ---------- depth color: lerp #ff8c42 (0km) -> #7c3aed (300km+) ---------- */
function depthColor(depthKm: number): string {
  const t = Math.max(0, Math.min(1, depthKm / 300));
  const a = [255, 140, 66];
  const b = [124, 58, 237];
  const c = a.map((v, i) => Math.round(v + (b[i] - v) * t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

/* ---------- helpers ---------- */

const fmtKST = (ms: number | null | undefined): string =>
  ms
    ? new Date(ms).toLocaleString("ko-KR", {
        timeZone: "Asia/Seoul",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : "–";

function topRegion(events: QuakeEvent[]): string | null {
  const counts: Record<string, number> = {};
  for (const e of events) {
    const p = e.place || "unknown";
    const i = p.lastIndexOf(",");
    const r = (i >= 0 ? p.slice(i + 1) : p).trim() || p;
    counts[r] = (counts[r] ?? 0) + 1;
  }
  let best: string | null = null;
  let n = 0;
  for (const [r, c] of Object.entries(counts)) {
    if (c > n) {
      best = r;
      n = c;
    }
  }
  return best;
}

function storageGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function storageSet(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* private mode 등 — 저장 실패는 무시 */
  }
}

/* ---------- sub-components ---------- */

function Toolbar(props: {
  preset: Preset;
  onPreset: (id: PresetId) => void;
  hours: HoursWindow;
  onHours: (h: HoursWindow) => void;
  showPlates: boolean;
  onTogglePlates: () => void;
  hasLoaded: boolean;
  newCount: number;
}) {
  const { preset, onPreset, hours, onHours, showPlates, onTogglePlates, hasLoaded, newCount } = props;
  return (
    <div className="card toolbar">
      <div className="presets" role="group" aria-label="지역 프리셋">
        {PRESETS.map((p) => (
          <button
            key={p.id}
            className={p.id === preset.id ? "on" : undefined}
            aria-pressed={p.id === preset.id}
            onClick={() => onPreset(p.id)}
          >
            {p.label}
          </button>
        ))}
      </div>
      <span className="sep" />
      <div className="presets" role="group" aria-label="시간 창">
        {HOURS_OPTIONS.map((h) => (
          <button
            key={h}
            className={h === hours ? "on" : undefined}
            aria-pressed={h === hours}
            onClick={() => onHours(h)}
          >
            {h}시간
          </button>
        ))}
      </div>
      <span className="sep" />
      <button className={showPlates ? "on" : undefined} aria-pressed={showPlates} onClick={onTogglePlates}>
        판 경계
      </button>
      <span className="newcount">
        이번 사이클 신규 <b>{hasLoaded ? newCount : "–"}</b>건
      </span>
    </div>
  );
}

function StatsBar(props: {
  hasLoaded: boolean;
  loadFailed: boolean;
  events: QuakeEvent[];
  lastFetch: number | null;
  hours: HoursWindow;
}) {
  const { hasLoaded, loadFailed, events, lastFetch, hours } = props;
  const count = hasLoaded ? String(events.length) : "–";
  const max =
    hasLoaded && events.length
      ? "M " + Math.max(...events.map((e) => e.mag)).toFixed(1)
      : "–";
  const region = (hasLoaded ? topRegion(events) : null) ?? "–";
  const fetched = loadFailed ? "수집 실패" : lastFetch ? fmtKST(lastFetch * 1000) : "–";
  return (
    <div className="stats">
      <div className="stat">
        <div className="label">{hours}시간 건수</div>
        <div className="value">{count}</div>
      </div>
      <div className="stat">
        <div className="label">최대 규모</div>
        <div className="value">{max}</div>
      </div>
      <div className="stat">
        <div className="label">최다 지역</div>
        <div className="value small">{region}</div>
      </div>
      <div className="stat">
        <div className="label">마지막 수집 (KST)</div>
        <div className="value small">{fetched}</div>
      </div>
    </div>
  );
}

function WorldMap(props: {
  events: QuakeEvent[];
  now: number;
  preset: Preset;
  showPlates: boolean;
  newIds: ReadonlySet<string>;
}) {
  const { events, now, preset, showPlates, newIds } = props;
  const zoomK = presetZoomK(preset); // 줌해도 화면상 원 크기 유지
  return (
    <div className="card">
      <div className="map-box">
        <svg
          className="worldmap"
          viewBox={presetViewBox(preset)}
          xmlns="http://www.w3.org/2000/svg"
          role="img"
          aria-label="세계 지진 지도"
        >
          <g>
            {CONTINENT_POINTS.map((points, i) => (
              <polyline key={i} className="continent" points={points} />
            ))}
          </g>
          {showPlates && (
            <g>
              {PLATE_POINTS.map((b) => (
                <polyline key={b.name} className="plate" points={b.points}>
                  <title>{b.name}</title>
                </polyline>
              ))}
            </g>
          )}
          <g>
            {[...events].reverse().map((e) => {
              // draw newest last (on top)
              const cx = px(e.lon).toFixed(1);
              const cy = py(e.lat).toFixed(1);
              const r = Math.max(1.5, e.mag * 2.2) * zoomK; // radius = mag * 2.2px (줌 보정)
              return (
                <g key={e.id}>
                  {now - e.time < 3600_000 && (
                    // pulse ring for < 1h old
                    <circle className="pulse" cx={cx} cy={cy} r={r} />
                  )}
                  {/* SVG 앵커 — 진앙 클릭 시 USGS 이벤트 페이지 (새 탭) */}
                  <a href={usgsUrl(e.id)} target="_blank" rel="noopener noreferrer">
                    <circle
                      className={newIds.has(e.id) ? "epi newhl" : "epi"}
                      cx={cx}
                      cy={cy}
                      r={r}
                      fill={depthColor(e.depth_km)}
                    >
                      <title>{`M${e.mag} ${e.place} · 깊이 ${e.depth_km}km · ${fmtKST(e.time)} — 클릭하면 USGS 상세`}</title>
                    </circle>
                  </a>
                </g>
              );
            })}
          </g>
        </svg>
      </div>
      <div className="legend">
        <span>깊이</span>
        <span>0km</span>
        <span className="bar" />
        <span>300km+</span>
        <span className="note">원 크기 = 규모 · 링 = 최근 1시간{showPlates ? " · 점선 = 판 경계" : ""}</span>
      </div>
    </div>
  );
}

/* ---------- 깊이 단면: x = 경도(프리셋 범위), y = 깊이 로그 스케일 ---------- */

const SEC_W = 1000;
const SEC_H = 260;
const SEC_TOP = 12;
const SEC_BOTTOM = 28;
const SEC_LEFT = 52;
const SEC_RIGHT = 12;
const SEC_PLOT_W = SEC_W - SEC_LEFT - SEC_RIGHT;
const SEC_PLOT_H = SEC_H - SEC_TOP - SEC_BOTTOM;
const DEPTH_MAX = 700;
const DEPTH_TICKS = [0, 10, 70, 300, 700];

/** 깊이 -> y (로그 스케일, [1,700]km로 클램프) */
function depthY(depthKm: number): number {
  const d = Math.max(1, Math.min(DEPTH_MAX, depthKm));
  return SEC_TOP + (Math.log10(d) / Math.log10(DEPTH_MAX)) * SEC_PLOT_H;
}

function DepthSection({ events, preset }: { events: QuakeEvent[]; preset: Preset }) {
  const [lonA, lonB] = preset.viewLon;
  const lonX = (lon: number): number => SEC_LEFT + ((lon - lonA) / (lonB - lonA)) * SEC_PLOT_W;
  return (
    <div className="card">
      <h2>깊이 단면 — 경도 × 깊이 (로그 스케일)</h2>
      <div className="section-box">
        <svg
          className="depthsection"
          viewBox={`0 0 ${SEC_W} ${SEC_H}`}
          xmlns="http://www.w3.org/2000/svg"
          role="img"
          aria-label="경도-깊이 단면도"
        >
          <rect className="section-frame" x={SEC_LEFT} y={SEC_TOP} width={SEC_PLOT_W} height={SEC_PLOT_H} />
          {DEPTH_TICKS.map((d) => {
            const y = depthY(Math.max(1, d));
            return (
              <g key={d}>
                <line className="gridline" x1={SEC_LEFT} x2={SEC_LEFT + SEC_PLOT_W} y1={y} y2={y} />
                <text className="axis" x={SEC_LEFT - 7} y={y + 4} textAnchor="end">
                  {d === DEPTH_MAX ? `${d} km` : String(d)}
                </text>
              </g>
            );
          })}
          <text className="axis" x={SEC_LEFT} y={SEC_H - 8} textAnchor="start">{`${lonA}°`}</text>
          <text className="axis" x={SEC_LEFT + SEC_PLOT_W} y={SEC_H - 8} textAnchor="end">{`${lonB}°`}</text>
          <g>
            {[...events].reverse().map((e) => (
              <circle
                key={e.id}
                className="epi"
                cx={lonX(e.lon).toFixed(1)}
                cy={depthY(e.depth_km).toFixed(1)}
                r={Math.max(1.5, e.mag * 1.8)}
                fill={depthColor(e.depth_km)}
              >
                <title>{`M${e.mag} ${e.place} · 깊이 ${e.depth_km}km`}</title>
              </circle>
            ))}
          </g>
        </svg>
      </div>
      <div className="legend">
        <span className="note">
          가로 = 경도 · 세로 = 깊이(로그) — 해구에서 대륙 쪽으로 갈수록 깊어지는 섭입대 경사가 드러납니다
        </span>
      </div>
    </div>
  );
}

function MagFilter({ minMag, onChange }: { minMag: number; onChange: (v: number) => void }) {
  return (
    <div className="card">
      <div className="filter">
        <span className="filter-label">규모 필터</span>
        <input
          type="range"
          min="2.5"
          max="6.0"
          step="0.1"
          value={minMag}
          onChange={(e) => onChange(parseFloat(e.target.value))}
        />
        <span className="val">
          M <span>{minMag.toFixed(1)}</span>+
        </span>
      </div>
    </div>
  );
}

type BriefState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "done"; text: string; cached: boolean };

function BriefCard() {
  const [brief, setBrief] = useState<BriefState>({ kind: "idle" });

  const generate = async (): Promise<void> => {
    setBrief({ kind: "loading" });
    try {
      const res = await fetch(`${API}/brief`, { method: "POST" });
      const data: BriefResponse = await res.json().catch(() => ({}) as BriefResponse);
      if (res.status === 503) {
        setBrief({
          kind: "error",
          message: `${data.error ?? "브리핑을 사용할 수 없습니다"} — ${data.detail ?? ""}`,
        });
      } else if (!res.ok) {
        setBrief({ kind: "error", message: `브리핑 생성 실패 (${res.status})` });
      } else {
        setBrief({ kind: "done", text: data.brief ?? "", cached: Boolean(data.cached) });
      }
    } catch {
      setBrief({ kind: "error", message: "브리핑 요청 중 오류가 발생했습니다" });
    }
  };

  return (
    <div className="card">
      <h2>
        AI 브리핑
        {brief.kind === "done" && (
          <span className="badge">{brief.cached ? "캐시됨 (10분 버킷)" : "새로 생성"}</span>
        )}
      </h2>
      <button onClick={() => void generate()} disabled={brief.kind === "loading"}>
        지난 24시간 브리핑 생성
      </button>
      <div className={brief.kind === "error" ? "brief-out err" : "brief-out"}>
        {brief.kind === "loading"
          ? "생성 중…"
          : brief.kind === "error"
            ? brief.message
            : brief.kind === "done"
              ? brief.text
              : ""}
      </div>
    </div>
  );
}

function EventTable(props: {
  hasLoaded: boolean;
  events: QuakeEvent[];
  newIds: ReadonlySet<string>;
}) {
  const { hasLoaded, events, newIds } = props;
  return (
    <div className="card">
      <h2>최근 이벤트</h2>
      <div className="table-box">
        <table>
          <thead>
            <tr>
              <th>시각 (KST)</th>
              <th>규모</th>
              <th>지역</th>
              <th>깊이</th>
            </tr>
          </thead>
          <tbody>
            {!hasLoaded ? (
              <tr>
                <td colSpan={4} className="dim">
                  불러오는 중…
                </td>
              </tr>
            ) : events.length === 0 ? (
              <tr>
                <td colSpan={4} className="dim">
                  조건에 맞는 이벤트가 없습니다
                </td>
              </tr>
            ) : (
              events.slice(0, 100).map((e) => {
                const isNew = newIds.has(e.id);
                return (
                  <tr key={e.id} className={isNew ? "rownew" : undefined}>
                    <td className="num">{fmtKST(e.time)}</td>
                    <td className="num">
                      <span className="magchip" style={{ background: depthColor(e.depth_km) }}>
                        M {e.mag.toFixed(1)}
                      </span>
                    </td>
                    <td className="place">
                      {isNew && <span className="newbadge">NEW</span>}
                      <a
                        href={usgsUrl(e.id)}
                        target="_blank"
                        rel="noopener noreferrer"
                        title="USGS 이벤트 페이지 (새 탭)"
                      >
                        {e.place}
                      </a>
                    </td>
                    <td className="num">{e.depth_km.toFixed(1)} km</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ---------- app ---------- */

export default function QuakeApp() {
  const [allEvents, setAllEvents] = useState<QuakeEvent[]>([]);
  const [lastFetch, setLastFetch] = useState<number | null>(null);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [minMag, setMinMag] = useState(2.5);
  const [hours, setHours] = useState<HoursWindow>(() =>
    storageGet("quake-hours") === "6" ? 6 : DEFAULT_HOURS,
  );
  const [presetId, setPresetId] = useState<PresetId>(() => findPreset(storageGet("quake-preset")).id);
  const [showPlates, setShowPlates] = useState<boolean>(() => storageGet("quake-plates") === "1");
  const [serverNewIds, setServerNewIds] = useState<string[]>([]);
  // 직전 응답과의 diff로 얻은 "이번에 새로 나타난" id — 하이라이트/NEW 배지용
  const [clientNewIds, setClientNewIds] = useState<ReadonlySet<string>>(() => new Set());
  const prevIdsRef = useRef<Set<string> | null>(null);

  const load = useCallback(async (): Promise<void> => {
    try {
      const res = await fetch(`${API}/quakes?hours=${hours}&min_mag=2.5`);
      if (!res.ok) throw new Error(String(res.status));
      const data = (await res.json()) as QuakesResponse;
      const evts = data.events ?? [];
      const prev = prevIdsRef.current;
      if (prev) {
        // 첫 로드는 비교 대상이 없으므로 하이라이트 없음
        setClientNewIds(new Set(evts.filter((e) => !prev.has(e.id)).map((e) => e.id)));
      }
      prevIdsRef.current = new Set(evts.map((e) => e.id));
      setAllEvents(evts);
      setServerNewIds(data.new_ids ?? []);
      setLastFetch(data.stats?.last_fetch ?? null);
      setHasLoaded(true);
      setLoadFailed(false);
    } catch {
      setLoadFailed(true);
    }
  }, [hours]);

  // fetch now + every 60s — hours가 바뀌면 load 정체성이 바뀌어 즉시 재요청 + 인터벌 재설정
  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(), 60_000);
    return () => window.clearInterval(id);
  }, [load]);

  const selectHours = useCallback((h: HoursWindow): void => {
    setHours((prev) => {
      if (h === prev) return prev;
      // 창 전환으로 "나타난" 이벤트는 신규가 아니므로 diff 기준을 초기화한다
      prevIdsRef.current = null;
      setClientNewIds(new Set());
      storageSet("quake-hours", String(h));
      return h;
    });
  }, []);

  const selectPreset = useCallback((id: PresetId): void => {
    setPresetId(id);
    storageSet("quake-preset", id);
  }, []);

  const togglePlates = useCallback((): void => {
    setShowPlates((v) => {
      storageSet("quake-plates", v ? "0" : "1");
      return !v;
    });
  }, []);

  const preset = findPreset(presetId);

  // client-side filter (규모 + 프리셋 bbox) — map, section, table, stats all derive from this
  const events = useMemo(
    () => allEvents.filter((e) => e.mag >= minMag && inPreset(e.lon, e.lat, preset)),
    [allEvents, minMag, preset],
  );
  const now = Date.now();

  return (
    <div className="wrap">
      <Toolbar
        preset={preset}
        onPreset={selectPreset}
        hours={hours}
        onHours={selectHours}
        showPlates={showPlates}
        onTogglePlates={togglePlates}
        hasLoaded={hasLoaded}
        newCount={serverNewIds.length}
      />
      <StatsBar
        hasLoaded={hasLoaded}
        loadFailed={loadFailed}
        events={events}
        lastFetch={lastFetch}
        hours={hours}
      />
      <WorldMap events={events} now={now} preset={preset} showPlates={showPlates} newIds={clientNewIds} />
      <DepthSection events={events} preset={preset} />
      <MagFilter minMag={minMag} onChange={setMinMag} />
      <div className="charts-row">
        <div className="card">
          <h2>시간별 발생 빈도 — 최근 {hours}시간 (KST)</h2>
          <HourHistogram events={events} hours={hours} now={now} />
        </div>
        <div className="card">
          <h2>규모-빈도 분포 — 구텐베르크-리히터</h2>
          <GRChart events={events} minMag={minMag} />
        </div>
      </div>
      <BriefCard />
      <EventTable hasLoaded={hasLoaded} events={events} newIds={clientNewIds} />
    </div>
  );
}
