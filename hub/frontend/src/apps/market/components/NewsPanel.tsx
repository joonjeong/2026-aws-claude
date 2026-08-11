import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchNews, NewsItem } from "../api/client";
import { streamSse } from "../../../lib/sse";
import Markdown from "../../../lib/md";

type Phase = "idle" | "fetching" | "analyzing" | "done" | "disabled" | "error";

/** REAL Yahoo Finance RSS headlines + per-article AI analysis stream.
 * The analysis uses the same abort-able SSE reader pattern as AIPanel. */
export default function NewsPanel({ symbol }: { symbol: string }) {
  const news = useQuery({
    queryKey: ["news", symbol],
    queryFn: () => fetchNews(symbol),
  });

  const [activeLink, setActiveLink] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [text, setText] = useState("");
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    // reset per symbol; abort any in-flight stream
    abortRef.current?.abort();
    setActiveLink(null);
    setPhase("idle");
    setText("");
    setErrorStatus(null);
    return () => abortRef.current?.abort();
  }, [symbol]);

  async function analyze(item: NewsItem) {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setActiveLink(item.link);
    setText("");
    setErrorStatus(null);
    setPhase("fetching");

    try {
      const status = await streamSse(
        "/api/market/ai/articles",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: item.title, link: item.link }),
          signal: ctrl.signal,
        },
        {
          onPhase: (p) => setPhase(p as Phase),
          onDelta: (t) => setText((cur) => cur + t), // typewriter accumulation
          onFinal: (t) => {
            setText(t);
            setPhase("done");
          },
          onError: (s) => {
            setErrorStatus(s);
            setPhase("error");
          },
        },
      );
      if (status === 503) setPhase("disabled"); // Bedrock token unset
      else if (status !== 200) {
        setErrorStatus(status);
        setPhase("error");
      }
    } catch {
      if (!ctrl.signal.aborted) setPhase("error");
    }
  }

  const streaming = phase === "fetching" || phase === "analyzing";

  return (
    <div className="panel">
      <h3>관련 뉴스</h3>
      {news.isLoading && <div className="dim">뉴스 불러오는 중…</div>}
      {news.isError && <div className="error-note">뉴스를 불러오지 못했습니다.</div>}
      {news.data?.error && (
        <div className="error-note">뉴스 소스 오류: {news.data.error}</div>
      )}
      {news.data && !news.data.error && news.data.items.length === 0 && (
        <div className="dim">표시할 뉴스가 없습니다.</div>
      )}
      {news.data && news.data.items.length > 0 && (
        <ul className="news-list">
          {news.data.items.map((it) => (
            <li className="news-item" key={it.link}>
              <div className="news-main">
                <a href={it.link} target="_blank" rel="noopener noreferrer">
                  {it.title}
                </a>
                {it.published && <div className="news-date dim">{it.published}</div>}
              </div>
              <button
                className="analyze-btn"
                onClick={() => analyze(it)}
                disabled={streaming}
              >
                {streaming && activeLink === it.link ? "분석 중…" : "분석"}
              </button>
            </li>
          ))}
        </ul>
      )}
      {activeLink && (
        <div className="article-analysis">
          <div className="ai-head">
            <span className="dim">기사 AI 분석</span>
            {streaming && <span className="phase-badge">{phase}</span>}
          </div>
          {phase === "disabled" && (
            <div className="ai-note">
              AI 분석 비활성 — Bedrock 키(AWS_BEARER_TOKEN_BEDROCK)가 설정되지
              않았습니다.
            </div>
          )}
          {phase === "error" && (
            <div className="error-note">
              기사 분석 실패{errorStatus ? ` (HTTP ${errorStatus})` : ""}
            </div>
          )}
          {text && (
            <div className="ai-output">
              <Markdown text={text} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
