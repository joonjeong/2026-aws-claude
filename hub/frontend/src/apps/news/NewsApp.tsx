import { useCallback, useEffect, useRef, useState } from "react";
import "./news.css";

/* ---------- API 계약 타입 ---------- */

interface Article {
  title: string;
  link: string;
  summary?: string | null;
  published?: string | null;
}

interface Source {
  id: string;
  name: string;
  count: number;
  last_fetch: string | null;
  last_error: string | null;
  articles: Article[];
}

interface ArticlesResponse {
  sources: Source[];
}

interface LensCluster {
  topic: string;
  summary: string;
  frames?: Record<string, string>;
  sources?: Record<string, number[]>;
}

interface LensResult {
  bucket: number | string;
  cached: boolean;
  overview: string;
  clusters?: LensCluster[];
}

/* ---------- helpers ---------- */

function rel(iso: string | null | undefined): string {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "방금 전";
  if (s < 3600) return `${Math.floor(s / 60)}분 전`;
  if (s < 86400) return `${Math.floor(s / 3600)}시간 전`;
  return `${Math.floor(s / 86400)}일 전`;
}

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

type View = "grid" | "lens";

/** 렌즈 패널 상태 — 원본 SPA의 #lensview innerHTML 상태와 1:1 대응.
 *  null: 아직 로드한 적 없음(빈 패널) / loading: "렌즈 분석 중…" /
 *  error: "렌즈 결과를 표시할 수 없습니다." / data: 결과 렌더 */
type LensView =
  | null
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "data"; lens: LensResult };

export default function NewsApp() {
  const [sources, setSources] = useState<Source[]>([]);
  const [view, setView] = useState<View>("grid");
  const [lensView, setLensView] = useState<LensView>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const lensLoading = useRef(false);

  /* ---------- articles: 최초 + 60초 주기 재조회 ---------- */
  const loadArticles = useCallback(async () => {
    try {
      const r = await fetch("/api/news/articles");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = (await r.json()) as ArticlesResponse;
      setSources(body.sources);
    } catch (e) {
      setBanner(`기사 목록을 불러오지 못했습니다: ${errMsg(e)}`);
    }
  }, []);

  useEffect(() => {
    void loadArticles();
    const t = window.setInterval(() => void loadArticles(), 60_000);
    return () => window.clearInterval(t);
  }, [loadArticles]);

  /* ---------- lens ---------- */
  const loadLens = useCallback(async () => {
    if (lensLoading.current) return;
    lensLoading.current = true;
    setLensView({ kind: "loading" });
    try {
      const r = await fetch("/api/news/lens", { method: "POST" });
      const body: unknown = await r.json().catch(() => ({}));
      if (!r.ok) {
        // 503 (키 없음) / 502 → 서버 메시지를 배너로
        const msg = (body as { message?: string }).message;
        setBanner(msg || `렌즈 오류 (HTTP ${r.status})`);
        setLensView({ kind: "error" });
        return;
      }
      setBanner(null);
      setLensView({ kind: "data", lens: body as LensResult });
    } catch (e) {
      // 원본과 동일: 네트워크 실패는 배너만 갱신, 패널은 그대로 둠
      setBanner(`렌즈 요청 실패: ${errMsg(e)}`);
    } finally {
      lensLoading.current = false;
    }
  }, []);

  /* ---------- view toggle ---------- */
  const toggleView = () => {
    const next: View = view === "grid" ? "lens" : "grid";
    setView(next);
    if (next === "lens") void loadLens();
    else setBanner(null);
  };

  return (
    <div className="news-root">
      <div className="news-toolbar">
        <span className="spacer" />
        <button className="primary" onClick={toggleView}>
          {view === "grid" ? "렌즈 보기" : "그리드 보기"}
        </button>
      </div>

      <div className="statusbar">
        {sources.map((s) => (
          <div key={s.id} className={`status${s.last_error ? " error" : ""}`}>
            <span className="name">{s.name}</span>
            <span className="meta">
              마지막 수집 {rel(s.last_fetch)} · {s.count}건
              {s.last_error ? " · 수집 실패" : ""}
            </span>
          </div>
        ))}
      </div>

      {banner !== null && <div className="banner">{banner}</div>}

      <main>
        {view === "grid" ? (
          <ArticleGrid sources={sources} />
        ) : (
          <LensPanel lensView={lensView} sources={sources} />
        )}
      </main>
    </div>
  );
}

/* ---------- 4열 카드 그리드 ---------- */

function ArticleGrid({ sources }: { sources: Source[] }) {
  return (
    <div className="grid">
      {sources.map((s) => (
        <section key={s.id} className="col">
          <h2>{s.name}</h2>
          {s.articles.length === 0 ? (
            <div className="card">아직 수집된 기사가 없습니다.</div>
          ) : (
            s.articles.map((a, i) => (
              <article key={i} className="card">
                <a
                  className="headline"
                  href={a.link}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {a.title}
                </a>
                {a.summary ? <div className="summary">{a.summary}</div> : null}
                <div className="time">
                  {rel(a.published)} ·{" "}
                  <a href={a.link} target="_blank" rel="noopener noreferrer">
                    원문 보기
                  </a>
                </div>
              </article>
            ))
          )}
        </section>
      ))}
    </div>
  );
}

/* ---------- 렌즈 클러스터 뷰 ---------- */

function LensPanel({
  lensView,
  sources,
}: {
  lensView: LensView;
  sources: Source[];
}) {
  if (lensView === null) return <div className="lensview" />;
  if (lensView.kind === "loading")
    return (
      <div className="lensview">
        <div className="overview">렌즈 분석 중…</div>
      </div>
    );
  if (lensView.kind === "error")
    return (
      <div className="lensview">
        <div className="overview">렌즈 결과를 표시할 수 없습니다.</div>
      </div>
    );

  const L = lensView.lens;
  return (
    <div className="lensview">
      <div className="cachemeta">
        10분 버킷 #{L.bucket} · {L.cached ? "캐시된 결과" : "새로 생성됨"}
      </div>
      <div className="overview">
        <strong>오늘의 미디어 지형</strong>
        <br />
        {L.overview}
      </div>
      {(L.clusters ?? []).map((c, ci) => (
        <section key={ci} className="cluster">
          <h3>{c.topic}</h3>
          <div className="common">{c.summary}</div>
          <div className="frames">
            {sources.map((s) => (
              <OutletFrame key={s.id} source={s} cluster={c} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function OutletFrame({
  source,
  cluster,
}: {
  source: Source;
  cluster: LensCluster;
}) {
  const frame = (cluster.frames ?? {})[source.id] || "미보도";
  const missing = frame === "미보도";
  const idxs = (cluster.sources ?? {})[source.id] ?? [];
  const chips = idxs
    .map((i) => {
      const a = source.articles[i];
      return a ? (
        <a
          key={i}
          href={a.link}
          target="_blank"
          rel="noopener noreferrer"
          title={a.title}
        >
          {a.title.slice(0, 28)}…
        </a>
      ) : null;
    })
    .filter((c): c is NonNullable<typeof c> => c !== null);

  return (
    <div className={`frame${missing ? " missing" : ""}`}>
      <div className="outlet">{source.name}</div>
      <div>{frame}</div>
      {chips.length > 0 && <div className="chips">{chips}</div>}
    </div>
  );
}
