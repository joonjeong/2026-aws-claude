import { useEffect, useRef, useState } from "react";

type Phase = "idle" | "fetching" | "analyzing" | "done" | "disabled" | "error";

/** Raw fetch + stream reader — deliberately NOT react-query: SSE deltas are
 * incremental, react-query caches completed results. Typewriter accumulation. */
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

    let res: Response;
    try {
      res = await fetch(`/api/market/ai/stocks/${encodeURIComponent(symbol)}`, {
        method: "POST",
        signal: ctrl.signal,
      });
    } catch {
      setPhase("error");
      return;
    }
    if (res.status === 503) {
      setPhase("disabled"); // Bedrock token unset — panel disabled
      return;
    }
    if (!res.ok || !res.body) {
      setErrorStatus(res.status);
      setPhase("error");
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const frames = buf.split("\n\n");
        buf = frames.pop() ?? "";
        for (const frame of frames) {
          let event = "message";
          let data = "";
          for (const line of frame.split("\n")) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line.startsWith("data:")) data += line.slice(5).trim();
          }
          if (!data) continue;
          const payload = JSON.parse(data);
          if (event === "phase") {
            setPhase(payload.phase as Phase);
          } else if (event === "delta") {
            setText((t) => t + payload.text); // typewriter accumulation
          } else if (event === "final") {
            setText(payload.text);
            setPhase("done");
          } else if (event === "error") {
            setErrorStatus(payload.status);
            setPhase("error");
          }
        }
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
      {text && <div className="ai-output">{text}</div>}
    </div>
  );
}
