import { useQuery } from "@tanstack/react-query";
import { arrow, deltaClass, fetchOverview, fmtNum } from "./api";

/* 최상단 지표 티커 — 11개 지표(원자재·환율·금리·크립토)를 오른쪽에서
   왼쪽으로 무한 스크롤. 트랙에 같은 목록을 2벌 넣고 -50%까지 이동시키면
   경계 없이 이어진다. hover 시 일시정지, reduced-motion 시 정적 스크롤. */
export default function TickerTape({ enabled }: { enabled: boolean }) {
  const overview = useQuery({
    queryKey: ["dash-overview"],
    queryFn: fetchOverview,
    refetchInterval: 45_000,
    enabled,
  });

  const items = overview.data?.indicators ?? [];
  if (!enabled || items.length === 0) {
    return (
      <div className="ticker-tape">
        <span className="ticker-empty">
          {enabled ? "지표 불러오는 중…" : "Market 모듈 비활성"}
        </span>
      </div>
    );
  }

  // 2벌 복제 — 트랙 폭의 정확히 절반이 한 사이클이 되어 이음새가 없다
  const track = [...items, ...items];
  return (
    <div className="ticker-tape" aria-label="시장 지표 티커">
      <div
        className="ticker-track"
        style={{ animationDuration: `${items.length * 4.5}s` }}
      >
        {track.map((it, i) => (
          <span className="ticker-item" key={`${it.symbol}-${i}`} aria-hidden={i >= items.length}>
            <span className="t-label">{it.name}</span>
            <span className="t-value">{fmtNum(it.price)}</span>
            <span className={`t-delta ${deltaClass(it.change_pct)}`}>
              {arrow(it.change_pct)}
              {fmtNum(Math.abs(it.change_pct))}%
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}
