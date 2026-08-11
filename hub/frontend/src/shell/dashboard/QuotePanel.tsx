import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { arrow, deltaClass, fetchQuotes, fmtNum } from "./api";

const fmtVolume = (n: number) =>
  n >= 1_000_000_000 ? `${(n / 1_000_000_000).toFixed(2)}B`
  : n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}M`
  : n >= 1_000 ? `${(n / 1_000).toFixed(1)}K`
  : String(n);

/* 마켓데스크 시세표 — 대시보드 가운데 하단. 행 클릭 시 Market Desk로 이동
   (앱 내 종목 선택은 MarketApp이 상태로 관리하므로 딥링크는 없다). */
export default function QuotePanel({
  enabled,
  navigate,
}: {
  enabled: boolean;
  navigate: (p: string) => void;
}) {
  const [tab, setTab] = useState<"us" | "kr">("us");
  const quotes = useQuery({
    queryKey: ["dash-quotes"],
    queryFn: fetchQuotes,
    refetchInterval: 45_000,
    enabled,
  });

  if (!enabled) return null;
  const rows = quotes.data?.[tab] ?? [];

  return (
    <section className="panel quote-panel">
      <div className="quote-head">
        <button className="panel-title" onClick={() => navigate("/market")}>
          📊 Market Desk <span className="panel-arrow">→</span>
        </button>
        <div className="quote-tabs">
          <button className={tab === "us" ? "active" : ""} onClick={() => setTab("us")}>
            US
          </button>
          <button className={tab === "kr" ? "active" : ""} onClick={() => setTab("kr")}>
            KR
          </button>
        </div>
      </div>
      {quotes.isLoading && <div className="panel-empty">시세 불러오는 중…</div>}
      {quotes.isError && <div className="panel-empty">시세 로딩 실패</div>}
      {quotes.data?.errors[tab] && (
        <div className="panel-empty">
          {tab.toUpperCase()} 시세 일부 실패: {quotes.data.errors[tab]}
        </div>
      )}
      {rows.length > 0 && (
        <div className="quote-scroll">
          <table className="dash-quote-table">
            <thead>
              <tr>
                <th>심볼</th>
                <th>종목</th>
                <th className="num">가격</th>
                <th className="num">등락</th>
                <th className="num">%</th>
                <th className="num">거래량</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.symbol} onClick={() => navigate("/market")}>
                  <td className="sym">{r.symbol}</td>
                  <td className="nm">{r.name}</td>
                  <td className="num">{fmtNum(r.price)}</td>
                  <td className={`num ${deltaClass(r.change)}`}>
                    {arrow(r.change)} {fmtNum(Math.abs(r.change))}
                  </td>
                  <td className={`num ${deltaClass(r.change_pct)}`}>
                    {r.change_pct > 0 ? "+" : ""}
                    {fmtNum(r.change_pct)}%
                  </td>
                  <td className="num dim">{fmtVolume(r.volume)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
