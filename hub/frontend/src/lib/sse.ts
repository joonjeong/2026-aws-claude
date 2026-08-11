/** Shared abort-able SSE reader for the AI streams (market 앱 + 셸 대시보드).
 *
 * Deliberately NOT react-query: SSE deltas are incremental, react-query
 * caches completed results. Used by market AIPanel/NewsPanel and the home
 * dashboard AI summary — same frame parsing as the original AIPanel reader.
 */
export interface SseHandlers {
  onPhase?: (phase: string) => void;
  onDelta?: (text: string) => void;
  onFinal?: (text: string) => void;
  onError?: (status: number | null) => void;
}

/** POST `url` and stream SSE frames into `handlers`.
 * Returns the HTTP status (stream is only read on 2xx). Network errors and
 * aborts propagate as exceptions — the caller checks `signal.aborted`. */
export async function streamSse(
  url: string,
  init: RequestInit,
  handlers: SseHandlers,
): Promise<number> {
  const res = await fetch(url, init);
  if (!res.ok || !res.body) return res.status;

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
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
      if (event === "phase") handlers.onPhase?.(payload.phase as string);
      else if (event === "delta") handlers.onDelta?.(payload.text as string);
      else if (event === "final") handlers.onFinal?.(payload.text as string);
      else if (event === "error") handlers.onError?.(payload.status ?? null);
    }
  }
  return res.status;
}
