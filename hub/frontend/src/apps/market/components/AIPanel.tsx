import { useEffect, useRef, useState } from "react";
import { streamSse } from "../api/sse";
import Markdown from "./md";

type Phase = "idle" | "fetching" | "analyzing" | "done" | "disabled" | "error";

/** Stock AI analysis — abort-able SSE reader (shared api/sse.ts helper);
 * accumulated text is re-rendered through the markdown module on every
 * delta, keeping the typewriter feel with formatted output. */
export default function AIPanel({ symbol }: { symbol: string }) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [text, setText] = useState("");
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    // reset per symbol; abort any in-flight stream
    abortRef.current?.abort();
    setPhase("idle");
    setText("");
    setErrorStatus(null);
    return () => abortRef.current?.abort();
  }, [symbol]);

  async function run() {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setText("");
    setErrorStatus(null);
    setPhase("fetching");

    try {
      const status = await streamSse(
        `/api/market/ai/stocks/${encodeURIComponent(symbol)}`,
        { method: "POST", signal: ctrl.signal },
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
      <h3>AI 분석</h3>
      <div className="ai-head">
        <button
          className="ai-btn"
          onClick={run}
          disabled={streaming || phase === "disabled"}
        >
          {streaming ? "분석 중…" : "AI 분석 실행"}
        </button>
        {streaming && <span className="phase-badge">{phase}</span>}
      </div>
      {phase === "disabled" && (
        <div className="ai-note">
          AI 분석 비활성 — Bedrock 키(AWS_BEARER_TOKEN_BEDROCK)가 설정되지 않았습니다.
        </div>
      )}
      {phase === "error" && (
        <div className="error-note">
          AI 분석 실패{errorStatus ? ` (HTTP ${errorStatus})` : ""}
        </div>
      )}
      {text && (
        <div className="ai-output">
          <Markdown text={text} />
        </div>
      )}
    </div>
  );
}
