import { useQuery } from "@tanstack/react-query";
import { fetchArticles, rel } from "./api";

const TOP_N = 8;

/* 뉴스 요약 — 15개 매체의 최신 기사를 시간순으로 평탄화해 상위 N건.
   published가 없는 기사는 뒤로 보낸다 (매체 RSS별 편차 흡수). */
export default function NewsPanel({
  enabled,
  navigate,
}: {
  enabled: boolean;
  navigate: (p: string) => void;
}) {
  const articles = useQuery({
    queryKey: ["dash-articles"],
    queryFn: fetchArticles,
    refetchInterval: 120_000,
    enabled,
  });

  const flat = (articles.data?.sources ?? [])
    .flatMap((s) => s.articles.map((a) => ({ ...a, source: s.name })))
    // RSS 링크는 외부 입력 — http(s) 외 스킴(javascript: 등)은 렌더하지 않는다
    .filter((a) => /^https?:\/\//i.test(a.link))
    .sort((a, b) => {
      const ta = a.published ? new Date(a.published).getTime() : 0;
      const tb = b.published ? new Date(b.published).getTime() : 0;
      return tb - ta;
    })
    .slice(0, TOP_N);

  return (
    <section className="panel">
      <button className="panel-title" onClick={() => navigate("/news")}>
        📰 Newsroom Lens <span className="panel-arrow">→</span>
      </button>
      {!enabled && <div className="panel-empty">News 모듈 비활성</div>}
      {enabled && articles.isLoading && <div className="panel-empty">불러오는 중…</div>}
      {enabled && articles.data && flat.length === 0 && (
        <div className="panel-empty">수집된 기사가 없습니다</div>
      )}
      <ul className="news-list">
        {flat.map((a) => (
          <li key={a.link}>
            <a href={a.link} target="_blank" rel="noreferrer noopener">
              <span className="n-title">{a.title}</span>
              <span className="n-meta">
                {a.source}
                {a.published && ` · ${rel(a.published)}`}
              </span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}
