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
  /** 보너스 C — 매체별 논조 온도(-2..+2). 미보도 매체는 키 자체가 없다. */
  tones?: Record<string, number>;
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

/* ---------- 보너스 B: 키워드 핀 (localStorage 영속) ---------- */

const PINS_KEY = "news-pins";
const PINS_FILTER_KEY = "news-pins-filter";

function loadPins(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(PINS_KEY) ?? "[]");
    return Array.isArray(raw) ? raw.filter((p) => typeof p === "string") : [];
  } catch {
    return [];
  }
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function matchesPins(a: Article, pins: string[]): boolean {
  const hay = `${a.title} ${a.summary ?? ""}`.toLowerCase();
  return pins.some((p) => hay.includes(p.toLowerCase()));
}

/** 핀 키워드를 대소문자 무시로 <mark> 하이라이트. */
function Highlight({ text, pins }: { text: string; pins: string[] }) {
  if (!text || pins.length === 0) return <>{text}</>;
  const re = new RegExp(`(${pins.map(escapeRegExp).join("|")})`, "gi");
  const lower = new Set(pins.map((p) => p.toLowerCase()));
  return (
    <>
      {text.split(re).map((part, i) =>
        lower.has(part.toLowerCase()) ? <mark key={i}>{part}</mark> : part,
      )}
    </>
  );
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

  /* 보너스 B: 핀 상태 */
  const [pins, setPins] = useState<string[]>(loadPins);
  const [pinInput, setPinInput] = useState("");
  const [pinFilter, setPinFilter] = useState<boolean>(
    () => localStorage.getItem(PINS_FILTER_KEY) === "1",
  );

  const savePins = (next: string[]) => {
    setPins(next);
    localStorage.setItem(PINS_KEY, JSON.stringify(next));
  };

  const addPin = () => {
    const kw = pinInput.trim();
    setPinInput("");
    if (!kw) return;
    if (pins.some((p) => p.toLowerCase() === kw.toLowerCase())) return;
    savePins([...pins, kw]);
  };

  const removePin = (kw: string) => savePins(pins.filter((p) => p !== kw));

  const togglePinFilter = () => {
    setPinFilter((on) => {
      localStorage.setItem(PINS_FILTER_KEY, on ? "0" : "1");
      return !on;
    });
  };

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
        <div className="pinbox">
          <input
            value={pinInput}
            onChange={(e) => setPinInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") addPin();
            }}
            placeholder="키워드 핀 추가"
            aria-label="키워드 핀 추가"
          />
          <button onClick={addPin}>핀</button>
          {pins.map((p) => (
            <span key={p} className="pin">
              {p}
              <button
                className="pin-x"
                onClick={() => removePin(p)}
                aria-label={`${p} 핀 제거`}
              >
                ×
              </button>
            </span>
          ))}
          {pins.length > 0 && (
            <label className="pinfilter">
              <input
                type="checkbox"
                checked={pinFilter}
                onChange={togglePinFilter}
              />
              핀만 보기
            </label>
          )}
        </div>
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
          <ArticleGrid sources={sources} pins={pins} pinFilter={pinFilter} />
        ) : (
          <LensPanel lensView={lensView} sources={sources} />
        )}
      </main>
    </div>
  );
}

/* ---------- 카드 그리드 (소스 수에 따라 자동 확장) ---------- */

function ArticleGrid({
  sources,
  pins,
  pinFilter,
}: {
  sources: Source[];
  pins: string[];
  pinFilter: boolean;
}) {
  const filtering = pinFilter && pins.length > 0;
  return (
    <div className="grid">
      {sources.map((s) => {
        const shown = filtering
          ? s.articles.filter((a) => matchesPins(a, pins))
          : s.articles;
        return (
          <section key={s.id} className="col">
            <h2>{s.name}</h2>
            {shown.length === 0 ? (
              <div className="card">
                {filtering && s.articles.length > 0
                  ? "핀 키워드와 일치하는 기사가 없습니다."
                  : "아직 수집된 기사가 없습니다."}
              </div>
            ) : (
              shown.map((a, i) => (
                <article key={i} className="card">
                  <a
                    className="headline"
                    href={a.link}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <Highlight text={a.title} pins={pins} />
                  </a>
                  {a.summary ? (
                    <div className="summary">
                      <Highlight text={a.summary} pins={pins} />
                    </div>
                  ) : null}
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
        );
      })}
    </div>
  );
}

/* ---------- 보너스 C: 논조 온도 바 (-2..+2) ---------- */

function ToneBar({ tone }: { tone: number }) {
  const t = Math.max(-2, Math.min(2, Math.round(tone)));
  const pct = ((t + 2) / 4) * 100;
  const label = t > 0 ? `+${t}` : `${t}`;
  return (
    <div className="tonebar" title={`논조 온도 ${label} (-2 비판 ~ +2 옹호)`}>
      <div className="tonetrack">
        <div className="tonedot" style={{ left: `${pct}%` }} />
      </div>
      <span className={`tonelabel${t < 0 ? " neg" : t > 0 ? " pos" : ""}`}>
        {label}
      </span>
    </div>
  );
}

/* ---------- 보너스 D: 브리핑 복사 (Slack 친화 플레인텍스트) ---------- */

function buildBriefing(lens: LensResult, sources: Source[]): string {
  const byId = new Map(sources.map((s) => [s.id, s]));
  const lines: string[] = [
    `*뉴스룸 렌즈 브리핑* — 10분 버킷 #${lens.bucket}`,
    "",
    lens.overview,
  ];
  (lens.clusters ?? []).forEach((c, i) => {
    lines.push("", `*${i + 1}. ${c.topic}*`, c.summary);
    for (const s of sources) {
      const frame = (c.frames ?? {})[s.id] || "미보도";
      const tone = (c.tones ?? {})[s.id];
      const toneTag =
        frame !== "미보도" && typeof tone === "number"
          ? ` (논조 ${tone > 0 ? `+${tone}` : tone})`
          : "";
      lines.push(`• ${s.name}${toneTag}: ${frame}`);
    }
    const links: string[] = [];
    for (const [sid, idxs] of Object.entries(c.sources ?? {})) {
      const src = byId.get(sid);
      if (!src) continue;
      for (const idx of idxs) {
        const a = src.articles[idx];
        if (a) links.push(`  - ${a.title} — ${a.link}`);
      }
    }
    if (links.length > 0) lines.push("근거:", ...links);
  });
  return lines.join("\n");
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // clipboard API가 막힌 환경(비보안 컨텍스트 등) 폴백
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  }
}

/* ---------- 렌즈 클러스터 뷰 ---------- */

function LensPanel({
  lensView,
  sources,
}: {
  lensView: LensView;
  sources: Source[];
}) {
  const [copied, setCopied] = useState(false);

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
  const copyBriefing = async () => {
    if (await copyText(buildBriefing(L, sources))) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="lensview">
      <div className="lenshead">
        <div className="cachemeta">
          10분 버킷 #{L.bucket} · {L.cached ? "캐시된 결과" : "새로 생성됨"}
        </div>
        <button onClick={() => void copyBriefing()} disabled={copied}>
          {copied ? "복사됨 ✓" : "브리핑 복사"}
        </button>
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
  const tone = (cluster.tones ?? {})[source.id];
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
      {!missing && typeof tone === "number" && <ToneBar tone={tone} />}
      {chips.length > 0 && <div className="chips">{chips}</div>}
    </div>
  );
}
