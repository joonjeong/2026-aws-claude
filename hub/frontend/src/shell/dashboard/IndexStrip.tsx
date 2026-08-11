import { useQuery } from "@tanstack/react-query";
import {
  arrow,
  deltaClass,
  fetchOverview,
  fetchSpark,
  fmtNum,
  SparkIndex,
} from "./api";

/* 지수 스파크라인 — 단일 시리즈라 범례 없이 극성(상승/하락)만 색으로 표현.
   기존 테마 토큰 --up/--down을 그대로 쓴다 (마켓 앱과 같은 규약). */
function Sparkline({ points }: { points: [string, number][] }) {
  const W = 120;
  const H = 34;
  const values = points.map(([, v]) => v);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = points.length > 1 ? W / (points.length - 1) : W;
  const xy = values.map(
    (v, i) => [i * step, H - 3 - ((v - min) / span) * (H - 6)] as const,
  );
  const d = xy.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const upMonth = values[values.length - 1] >= values[0];
  const color = upMonth ? "var(--up)" : "var(--down)";
  const last = xy[xy.length - 1];
  return (
    <svg
      className="sparkline"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={`최근 1개월 추이 ${upMonth ? "상승" : "하락"}`}
    >
      <path d={d} fill="none" stroke={color} strokeWidth="2"
        strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      {last && <circle cx={last[0]} cy={last[1]} r="2.5" fill={color} />}
    </svg>
  );
}

function monthReturn(points: [string, number][]): number | null {
  if (points.length < 2) return null;
  const first = points[0][1];
  const lastV = points[points.length - 1][1];
  return first ? ((lastV - first) / first) * 100 : null;
}

export default function IndexStrip({
  enabled,
  navigate,
}: {
  enabled: boolean;
  navigate: (p: string) => void;
}) {
  const overview = useQuery({
    queryKey: ["dash-overview"],
    queryFn: fetchOverview,
    refetchInterval: 45_000,
    enabled,
  });
  const spark = useQuery({
    queryKey: ["dash-spark"],
    queryFn: fetchSpark,
    refetchInterval: 15 * 60_000,
    enabled,
  });

  if (!enabled) return null;
  const indices = overview.data?.indices ?? [];
  const sparkBySymbol = new Map<string, SparkIndex>(
    (spark.data?.indices ?? []).map((s) => [s.symbol, s]),
  );
  if (indices.length === 0)
    return <div className="index-strip dim">지수 불러오는 중…</div>;

  return (
    <div className="index-strip">
      {indices.map((ix) => {
        const sp = sparkBySymbol.get(ix.symbol);
        const m = sp ? monthReturn(sp.points) : null;
        return (
          <button
            key={ix.symbol}
            className="index-tile"
            onClick={() => navigate("/market")}
            title={`${ix.name} — Market Desk 열기`}
          >
            <div className="ix-head">
              <span className="ix-name">{ix.name}</span>
              <span className="ix-market">{ix.market}</span>
            </div>
            <div className="ix-price">{fmtNum(ix.price)}</div>
            <div className={`ix-delta ${deltaClass(ix.change_pct)}`}>
              {arrow(ix.change_pct)} {fmtNum(Math.abs(ix.change))} (
              {fmtNum(Math.abs(ix.change_pct))}%)
            </div>
            {sp ? (
              <>
                <Sparkline points={sp.points} />
                {m !== null && (
                  <div className={`ix-month ${deltaClass(m)}`}>
                    1개월 {m > 0 ? "+" : ""}
                    {fmtNum(m)}%
                  </div>
                )}
              </>
            ) : (
              <div className="sparkline-empty">1개월 추이 로딩…</div>
            )}
          </button>
        );
      })}
    </div>
  );
}
