/* 홈 대시보드 전용 API 클라이언트 — 셸 소유.
   앱 번들(virtual:apps)은 조건부 포함이므로 apps/* 의 클라이언트를 import하지
   않고 셸이 계약 타입을 직접 소유한다 (useModules와 같은 원칙). */

export interface QuoteRow {
  symbol: string;
  name: string;
  price: number;
  change: number;
  change_pct: number;
  volume: number;
  market?: string;
}

export interface Overview {
  indices: QuoteRow[];
  indicators: QuoteRow[];
  errors: Record<string, string | null>;
}

export interface SparkIndex {
  symbol: string;
  name: string;
  market: string;
  points: [string, number][]; // [date, close] — 최근 1개월 일봉 종가
}

export interface ContrailHealth {
  status: string;
  global_flights: number;
  region_flights: Record<string, number>;
}

export interface WakeHealth {
  status: string; // ok | degraded | no_key
  vessels: number;
  preset: string;
}

export interface QuakeEvent {
  id: string;
  mag: number;
  place: string;
  time: number; // epoch ms
}

export interface QuakeResponse {
  events: QuakeEvent[];
  stats: { count: number; max_mag: number; top_region: string | null };
}

export interface TrendItem {
  video_id: string;
  title: string;
  channel: string;
  rank: number;
  view_count: number | null;
  is_new: boolean;
  category_name: string;
}

export interface TrendingResponse {
  captured_at: string | null;
  items: TrendItem[];
  stats: { total_views: number | null; top_category: string | null; exited: number | null };
}

export interface NewsArticle {
  title: string;
  link: string;
  published?: string | null;
}

export interface NewsSource {
  id: string;
  name: string;
  lang: string;
  articles: NewsArticle[];
}

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json() as Promise<T>;
}

export interface Quotes {
  us: QuoteRow[];
  kr: QuoteRow[];
  errors: Record<string, string | null>;
}

export const fetchOverview = () => getJson<Overview>("/api/market/overview");
export const fetchQuotes = () => getJson<Quotes>("/api/market/quotes");
export const fetchSpark = () =>
  getJson<{ indices: SparkIndex[] }>("/api/market/indices/spark");
export const fetchContrailHealth = () =>
  getJson<ContrailHealth>("/api/contrail/healthz");
export const fetchWakeHealth = () => getJson<WakeHealth>("/api/wake/healthz");
export const fetchQuakes = () =>
  getJson<QuakeResponse>("/api/quake/quakes?hours=24&min_mag=4.5");
export const fetchTrending = () => getJson<TrendingResponse>("/api/trend/trending");
export const fetchArticles = () =>
  getJson<{ sources: NewsSource[] }>("/api/news/articles");

/* ---------- 표시 헬퍼 ---------- */

export const fmtNum = (n: number, digits = 2) =>
  n.toLocaleString(undefined, { maximumFractionDigits: digits });

export const fmtCompact = (n: number) =>
  n >= 1_0000_0000 ? `${(n / 1_0000_0000).toFixed(1)}억`
  : n >= 1_0000 ? `${(n / 1_0000).toFixed(1)}만`
  : String(n);

export const deltaClass = (v: number) => (v > 0 ? "up" : v < 0 ? "down" : "flat");
export const arrow = (v: number) => (v > 0 ? "▲" : v < 0 ? "▼" : "―");

export function rel(msOrIso: number | string | null | undefined): string {
  if (msOrIso == null) return "—";
  const t = typeof msOrIso === "number" ? msOrIso : new Date(msOrIso).getTime();
  const s = (Date.now() - t) / 1000;
  if (s < 60) return "방금 전";
  if (s < 3600) return `${Math.floor(s / 60)}분 전`;
  if (s < 86400) return `${Math.floor(s / 3600)}시간 전`;
  return `${Math.floor(s / 86400)}일 전`;
}
