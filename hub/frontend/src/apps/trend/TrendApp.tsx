/* Trend Radar — 바닐라 SPA(hub/frontend/trend/index.html) 1:1 동작 포트.
   테마 토글은 셸이 소유하므로 제외. 카테고리 칩 필터는 셸 계약에 따라
   클라이언트 필터(스탯은 항상 풀 스냅샷 기준 — 서버도 pre-filter로 계산). */
import { useCallback, useEffect, useState } from "react";
import "./trend.css";

/* ---------- API response types ---------- */

interface CollectorStatus {
  name?: string;
  last_success?: string | null;
  last_error?: string | null;
  cycles?: number;
  consecutive_failures?: number;
}

interface TrendStats {
  total_views: number | null;
  channel_count: number | null;
  top_category: string | null;
  exited: number | null;
}

interface TrendItem {
  video_id: string;
  title: string;
  channel: string;
  category_id: string;
  thumbnail: string;
  view_count: number | null;
  like_count: number | null;
  published_at?: string;
  rank: number;
  delta: number | null; // null = NEW (이전 스냅샷에 없음)
  is_new: boolean;
  category_name: string;
}

interface TrendingResponse {
  captured_at: string | null;
  items: TrendItem[];
  stats: TrendStats;
  collector: CollectorStatus;
}

interface TrendsPoint {
  bucket_ts: number;
  shares: Record<string, number>;
  entered: number;
  exited: number;
}

interface TrendsResponse {
  points: TrendsPoint[];
}

interface BriefResponse {
  brief?: string;
  cached?: boolean;
  bucket?: number;
  error?: string;
  message?: string;
}

type BriefState =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "done"; text: string; meta: string }
  | { phase: "error"; message: string };

/* ---------- constants (바닐라 원문 그대로) ---------- */

const CATEGORIES: ReadonlyArray<readonly [string, string]> = [
  ["10", "Music"], ["20", "Gaming"], ["24", "Entertainment"], ["25", "News & Politics"],
  ["17", "Sports"], ["1", "Film & Animation"], ["28", "Science & Tech"], ["23", "Comedy"],
];
const PALETTE = [
  "var(--trend-c1)", "var(--trend-c2)", "var(--trend-c3)", "var(--trend-c4)",
  "var(--trend-c5)", "var(--trend-c6)", "var(--trend-c7)", "var(--trend-c8)",
  "var(--trend-c9)",
];
const POLL_MS = 60000;

/* ---------- helpers ---------- */

function fmtNum(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1e8) return (n / 1e8).toFixed(1) + "억";
  if (n >= 1e4) return (n / 1e4).toFixed(1) + "만";
  return n.toLocaleString("ko-KR");
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("ko-KR", { hour12: false });
}

/* ---------- card ---------- */

function DeltaBadge({ item }: { item: TrendItem }) {
  if (item.is_new) return <span className="badge new">NEW</span>;
  if (item.delta == null) return null;
  if (item.delta > 0) return <span className="badge up">▲{item.delta}</span>;
  if (item.delta < 0) return <span className="badge down">▼{-item.delta}</span>;
  return <span className="badge same">−</span>;
}

function VideoCard({ item }: { item: TrendItem }) {
  return (
    <a
      className="card"
      href={"https://www.youtube.com/watch?v=" + encodeURIComponent(item.video_id)}
      target="_blank"
      rel="noopener noreferrer"
    >
      <div className="thumbbox">
        <img
          src={item.thumbnail}
          alt=""
          loading="lazy"
          onError={(e) => { e.currentTarget.style.display = "none"; }}
        />
        <span className="rank">{item.rank}</span>
        <span className="badges"><DeltaBadge item={item} /></span>
      </div>
      <div className="meta">
        <p className="title">{item.title}</p>
        <div className="channel">{item.channel}</div>
        <div className="counts">
          조회수 {fmtNum(item.view_count)} · 좋아요 {fmtNum(item.like_count)}
        </div>
        <span className="cat">{item.category_name}</span>
      </div>
    </a>
  );
}

/* ---------- time series: inline SVG stacked bars ---------- */

function StackedBars({ points }: { points: TrendsPoint[] }) {
  if (!points.length) {
    return (
      <>
        <div className="chart-svg-box"><div className="empty">데이터 없음</div></div>
        <div className="legend" />
      </>
    );
  }
  // stable color per category name across all points
  const names: string[] = [];
  for (const p of points) {
    for (const name of Object.keys(p.shares)) {
      if (!names.includes(name)) names.push(name);
    }
  }
  const color = (name: string): string =>
    PALETTE[names.indexOf(name) % PALETTE.length];

  const H = 220, PAD = 28, barW = 26, gap = 10;
  const W = Math.max(320, PAD * 2 + points.length * (barW + gap));

  return (
    <>
      <div className="chart-svg-box">
        <svg width={W} height={H + 42} role="img" aria-label="카테고리 점유율 누적 막대">
          {points.map((p, i) => {
            const x = PAD + i * (barW + gap);
            let y = H + 10;
            const rects = names.flatMap((name) => {
              const share = p.shares[name] || 0;
              if (!share) return [];
              const h = share * H;
              y -= h;
              return [
                <rect
                  key={name}
                  x={x}
                  y={y.toFixed(1)}
                  width={barW}
                  height={Math.max(h - 1, 0.5).toFixed(1)}
                  rx={1.5}
                  fill={color(name)}
                >
                  <title>{`${name} ${(share * 100).toFixed(0)}%`}</title>
                </rect>,
              ];
            });
            const t = new Date(p.bucket_ts * 1000);
            const label =
              String(t.getHours()).padStart(2, "0") + ":" +
              String(t.getMinutes()).padStart(2, "0");
            return (
              <g key={p.bucket_ts}>
                {rects}
                <text
                  x={x + barW / 2} y={H + 24}
                  textAnchor="middle" fontSize={10} fill="var(--muted)"
                >
                  {label}
                </text>
                <text
                  x={x + barW / 2} y={H + 38}
                  textAnchor="middle" fontSize={9} fill="var(--muted)"
                >
                  {`+${p.entered}/-${p.exited}`}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <div className="legend">
        {names.map((n) => (
          <span className="key" key={n}>
            <span className="sw" style={{ background: color(n) }} />
            {n}
          </span>
        ))}
        <span className="key">막대 아래 +진입/-이탈</span>
      </div>
    </>
  );
}

/* ---------- app ---------- */

export default function TrendApp() {
  const [tick, setTick] = useState(0);
  const [category, setCategory] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<TrendingResponse | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const [hours, setHours] = useState("1");
  const [points, setPoints] = useState<TrendsPoint[]>([]);
  const [brief, setBrief] = useState<BriefState>({ phase: "idle" });

  const refreshAll = useCallback(() => setTick((t) => t + 1), []);

  // auto refresh (our API only)
  useEffect(() => {
    const id = window.setInterval(refreshAll, POLL_MS);
    return () => window.clearInterval(id);
  }, [refreshAll]);

  // trending — 항상 풀 스냅샷을 받고 칩 필터는 클라이언트에서 적용
  useEffect(() => {
    let cancelled = false;
    (async () => {
      let data: TrendingResponse;
      try {
        data = (await (await fetch("/api/trend/trending")).json()) as TrendingResponse;
      } catch {
        if (!cancelled) setBanner("API 요청에 실패했습니다.");
        return;
      }
      if (cancelled) return;
      setSnapshot(data);
      const c = data.collector ?? {};
      if (!data.items.length && (c.consecutive_failures ?? 0) > 0) {
        setBanner(
          "수집 실패 상태입니다 (" + (c.last_error || "원인 미상") +
          ") — 데이터가 비어 있습니다."
        );
      } else {
        setBanner(null);
      }
    })();
    return () => { cancelled = true; };
  }, [tick]);

  // time series
  useEffect(() => {
    let cancelled = false;
    (async () => {
      let data: TrendsResponse;
      try {
        data = (await (await fetch("/api/trend/trends?hours=" + hours)).json()) as TrendsResponse;
      } catch {
        return; // 바닐라와 동일: 실패 시 기존 차트 유지
      }
      if (!cancelled) setPoints(data.points ?? []);
    })();
    return () => { cancelled = true; };
  }, [tick, hours]);

  const loadBrief = useCallback(async (mode: "now" | "daily") => {
    setBrief({ phase: "loading" });
    try {
      const resp = await fetch("/api/trend/brief?mode=" + mode, { method: "POST" });
      const data = (await resp.json()) as BriefResponse;
      if (!resp.ok) {
        setBrief({
          phase: "error",
          message: data.message || "브리핑 실패 (HTTP " + resp.status + ")",
        });
        return;
      }
      setBrief({
        phase: "done",
        text: data.brief ?? "",
        meta:
          "모드 " + mode + " · " + (data.cached ? "캐시된 결과" : "새로 생성") +
          " · 버킷 " + data.bucket,
      });
    } catch {
      setBrief({ phase: "error", message: "브리핑 요청에 실패했습니다." });
    }
  }, []);

  const items = snapshot?.items ?? [];
  const visibleItems =
    category === null ? items : items.filter((it) => it.category_id === category);
  const stats = snapshot?.stats;

  return (
    <div className="wrap">
      <header className="trend-header">
        <h1>
          Trend Radar <span className="dot">●</span> <small>유튜브 급상승 KR</small>
        </h1>
        <span className="captured">마지막 수집: {fmtTime(snapshot?.captured_at)}</span>
        <div className="spacer" />
        <button className="t-btn" onClick={refreshAll}>새로고침</button>
      </header>

      {banner !== null && <div className="banner">{banner}</div>}

      <div className="stats">
        <div className="stat">
          <div className="label">합산 조회수</div>
          <div className="value">{fmtNum(stats?.total_views)}</div>
        </div>
        <div className="stat">
          <div className="label">채널 수</div>
          <div className="value">{stats?.channel_count ?? "—"}</div>
        </div>
        <div className="stat">
          <div className="label">최다 카테고리</div>
          <div className="value">{stats?.top_category ?? "—"}</div>
        </div>
        <div className="stat">
          <div className="label">이탈 수</div>
          <div className="value">{stats?.exited ?? "—"}</div>
        </div>
      </div>

      <div className="chips">
        <span
          className={"chip" + (category === null ? " on" : "")}
          onClick={() => setCategory(null)}
        >
          전체
        </span>
        {CATEGORIES.map(([id, label]) => (
          <span
            key={id}
            className={"chip" + (category === id ? " on" : "")}
            onClick={() => setCategory(id)}
          >
            {label}
          </span>
        ))}
      </div>

      <div className="grid">
        {snapshot === null ? (
          <div className="empty">불러오는 중…</div>
        ) : !visibleItems.length ? (
          <div className="empty">표시할 항목이 없습니다.</div>
        ) : (
          visibleItems.map((it) => <VideoCard key={it.video_id} item={it} />)
        )}
      </div>

      <section className="panel">
        <h2>
          카테고리 점유율 추이
          <select
            className="t-select"
            value={hours}
            onChange={(e) => setHours(e.target.value)}
          >
            <option value="1">최근 1시간</option>
            <option value="3">최근 3시간</option>
            <option value="6">최근 6시간</option>
            <option value="24">최근 24시간</option>
          </select>
        </h2>
        <StackedBars points={points} />
      </section>

      <section className="panel">
        <h2>
          AI 브리핑
          <button className="t-btn" onClick={() => void loadBrief("now")}>지금 브리핑</button>
          <button className="t-btn" onClick={() => void loadBrief("daily")}>데일리 브리핑</button>
        </h2>
        <div className={"brief-out" + (brief.phase === "error" ? " err" : "")}>
          {brief.phase === "idle" && "버튼을 눌러 브리핑을 생성하세요."}
          {brief.phase === "loading" && "브리핑 생성 중…"}
          {brief.phase === "done" && brief.text}
          {brief.phase === "error" && brief.message}
        </div>
        <div className="brief-meta">{brief.phase === "done" ? brief.meta : ""}</div>
      </section>
    </div>
  );
}
