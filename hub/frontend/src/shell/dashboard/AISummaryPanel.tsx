import { useCallback, useEffect, useRef, useState } from "react";
import { streamSse } from "../../lib/sse";
import Markdown from "../../lib/md";

const BUCKET_MS = 5 * 60_000; // 서버 버킷(MARKET_SUMMARY_BUCKET)과 동기

type Phase = "idle" | "fetching" | "analyzing" | "cached" | "done" | "disabled" | "error";

/* AI 시황 요약 — 스파크라인과 시세표 사이. 마운트 시 1회 + 5분(버킷)마다
   자동 갱신, refresh 버튼은 수동 재요청. 같은 버킷의 재요청은 서버가
   캐시를 즉시 final로 재생하므로 Bedrock 중복 호출이 없다. */
export default function AISummaryPanel({ enabled }: { enabled: boolean }) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [text, setText] = useState("");
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const run = useCallback(async () => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setText("");
    setErrorStatus(null);
    setPhase("fetching");

    try {
      const status = await streamSse(
        "/api/market/ai/market",
        { method: "POST", signal: ctrl.signal },
        {
          onPhase: (p) => setPhase(p as Phase),
          onDelta: (t) => setText((cur) => cur + t), // 타자기 느낌의 점진 렌더
          onFinal: (t) => {
            setText(t);
            setPhase("done");
            setUpdatedAt(new Date());
          },
          onError: (s) => {
            setErrorStatus(s);
            setPhase("error");
          },
        },
      );
      if (status === 503) setPhase("disabled"); // Bedrock 토큰 미설정
      else if (status !== 200) {
        setErrorStatus(status);
        setPhase("error");
      }
    } catch {
      if (!ctrl.signal.aborted) setPhase("error");
    }
  }, []);

  // 마운트 시 1회 + 다음 버킷 경계에 맞춰 5분 주기 자동 갱신
  useEffect(() => {
    if (!enabled) return;
    run();
    let interval: ReturnType<typeof setInterval> | undefined;
    const untilNextBucket = BUCKET_MS - (Date.now() % BUCKET_MS) + 2_000;
    const align = setTimeout(() => {
      run();
      interval = setInterval(run, BUCKET_MS);
    }, untilNextBucket);
    return () => {
      clearTimeout(align);
      if (interval) clearInterval(interval);
      abortRef.current?.abort();
    };
  }, [enabled, run]);

  if (!enabled) return null;
  const streaming = phase === "fetching" || phase === "analyzing" || phase === "cached";

  return (
    <section className="panel ai-summary">
      <div className="quote-head">
        <span className="panel-title as-label">🤖 AI 시황 요약</span>
        <div className="ai-sum-meta">
          {updatedAt && !streaming && (
            <span className="ai-sum-time">
              {updatedAt.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })} 기준
            </span>
          )}
          {streaming && <span className="ai-sum-time">{phase === "cached" ? "캐시 로딩" : "요약 중…"}</span>}
          <button
            className="ai-sum-refresh"
            onClick={run}
            disabled={streaming || phase === "disabled"}
            title="시황 요약 새로고침 (5분 버킷)"
          >
            ⟳ refresh
          </button>
        </div>
      </div>
      {phase === "disabled" && (
        <div className="panel-empty">
          AI 요약 비활성 — 서버에 AWS_BEARER_TOKEN_BEDROCK이 설정되지 않았습니다.
        </div>
      )}
      {phase === "error" && (
        <div className="panel-empty">
          요약 실패{errorStatus ? ` (HTTP ${errorStatus})` : ""} — refresh로 재시도
        </div>
      )}
      {text ? (
        <div className="ai-sum-body">
          <Markdown text={text} />
        </div>
      ) : (
        streaming && <div className="panel-empty">시황 데이터를 모으는 중…</div>
      )}
    </section>
  );
}
