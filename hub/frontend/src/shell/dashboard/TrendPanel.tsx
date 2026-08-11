import { useQuery } from "@tanstack/react-query";
import { fetchTrending, fmtCompact, rel } from "./api";

const TOP_N = 6;

/* 트렌드 레이더 요약 — 최신 스냅샷 상위 랭크만. 스탯은 풀 스냅샷 기준. */
export default function TrendPanel({
  enabled,
  navigate,
}: {
  enabled: boolean;
  navigate: (p: string) => void;
}) {
  const trending = useQuery({
    queryKey: ["dash-trending"],
    queryFn: fetchTrending,
    refetchInterval: 60_000,
    enabled,
  });

  const items = trending.data?.items.slice(0, TOP_N) ?? [];
  const stats = trending.data?.stats;

  return (
    <section className="panel">
      <button className="panel-title" onClick={() => navigate("/trend")}>
        📈 Trend Radar <span className="panel-arrow">→</span>
      </button>
      {!enabled && <div className="panel-empty">Trend 모듈 비활성</div>}
      {enabled && trending.isLoading && <div className="panel-empty">불러오는 중…</div>}
      {enabled && trending.data && items.length === 0 && (
        <div className="panel-empty">아직 수집된 스냅샷이 없습니다</div>
      )}
      {items.length > 0 && (
        <>
          <ol className="trend-list">
            {items.map((it) => (
              <li key={it.video_id}>
                <span className="rank">{it.rank}</span>
                <span className="t-body">
                  <span className="t-title">{it.title}</span>
                  <span className="t-meta">
                    {it.channel}
                    {it.view_count != null && ` · ${fmtCompact(it.view_count)}회`}
                    {it.is_new && <em className="badge-new">NEW</em>}
                  </span>
                </span>
              </li>
            ))}
          </ol>
          <footer className="panel-foot">
            {stats?.top_category && <>인기 카테고리 {stats.top_category} · </>}
            {trending.data?.captured_at && `스냅샷 ${rel(trending.data.captured_at)}`}
          </footer>
        </>
      )}
    </section>
  );
}
