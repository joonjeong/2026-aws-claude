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

export interface Quotes {
  us: QuoteRow[];
  kr: QuoteRow[];
  errors: Record<string, string | null>;
}

export interface StockDetail {
  symbol: string;
  name: string;
  market: "US" | "KR";
  price: number;
  change: number;
  change_pct: number;
  volume: number;
  returns: Record<"1w" | "1m" | "3m" | "1y", number | null>;
  week52: { high: number; low: number; position: number };
  as_of: string;
}

export interface Candle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface ChartData {
  symbol: string;
  range: string;
  candles: Candle[];
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} -> ${res.status}`);
  return res.json() as Promise<T>;
}

export const fetchOverview = () => getJson<Overview>("/api/market/overview");
export const fetchQuotes = () => getJson<Quotes>("/api/market/quotes");
export const fetchDetail = (symbol: string) =>
  getJson<StockDetail>(`/api/market/stocks/${encodeURIComponent(symbol)}`);
export const fetchChart = (symbol: string, range: string) =>
  getJson<ChartData>(`/api/market/stocks/${encodeURIComponent(symbol)}/chart?range=${range}`);

export const fmtNum = (n: number, digits = 2) =>
  n.toLocaleString(undefined, { maximumFractionDigits: digits });
export const fmtVolume = (n: number) =>
  n >= 1_000_000_000 ? `${(n / 1_000_000_000).toFixed(2)}B`
  : n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}M`
  : n >= 1_000 ? `${(n / 1_000).toFixed(1)}K`
  : String(n);
