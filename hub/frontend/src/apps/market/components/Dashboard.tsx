import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchOverview, fetchQuotes, fmtNum, fmtVolume, QuoteRow } from "../api/client";
import Delta, { deltaClass, arrow } from "./Delta";

const REFETCH_MS = 45_000;

function IndicatorBar({ items }: { items: QuoteRow[] }) {
  return (
    <div className="indicator-bar">
      {items.map((it) => (
        <div className="item" key={it.symbol}>
          <span className="label">{it.name}</span>
          <span className="value">{fmtNum(it.price)}</span>
          <span className={deltaClass(it.change_pct)}>
            {arrow(it.change_pct)}
            {fmtNum(Math.abs(it.change_pct))}%
          </span>
        </div>
      ))}
    </div>
  );
}

function IndexCards({ items }: { items: QuoteRow[] }) {
  return (
    <div className="index-cards">
      {items.map((ix) => (
        <div className="index-card" key={ix.symbol}>
          <div className="name">{ix.name}</div>
          <div className="price">{fmtNum(ix.price)}</div>
          <div className={`delta ${deltaClass(ix.change_pct)}`}>
            <Delta change={ix.change} pct={ix.change_pct} />
          </div>
        </div>
      ))}
    </div>
  );
}

function QuoteTable({
  rows,
  onSelect,
}: {
  rows: QuoteRow[];
  onSelect: (symbol: string) => void;
}) {
  return (
    <div className="quote-table-wrap">
      <table className="quote-table">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Name</th>
            <th className="num">Price</th>
            <th className="num">Change</th>
            <th className="num">%</th>
            <th className="num">Volume</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.symbol} onClick={() => onSelect(r.symbol)}>
              <td className="sym">{r.symbol}</td>
              <td>{r.name}</td>
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
  );
}

export default function Dashboard({ onSelect }: { onSelect: (s: string) => void }) {
  const [tab, setTab] = useState<"us" | "kr">("us");

  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: fetchOverview,
    refetchInterval: REFETCH_MS,
  });
  const quotes = useQuery({
    queryKey: ["quotes"],
    queryFn: fetchQuotes,
    refetchInterval: REFETCH_MS,
  });

  return (
    <div>
      {overview.isLoading && <div className="dim">지표 불러오는 중…</div>}
      {overview.data && (
        <>
          <IndicatorBar items={overview.data.indicators} />
          <IndexCards items={overview.data.indices} />
        </>
      )}
      <div className="tabs">
        <button className={tab === "us" ? "active" : ""} onClick={() => setTab("us")}>
          US
        </button>
        <button className={tab === "kr" ? "active" : ""} onClick={() => setTab("kr")}>
          KR
        </button>
      </div>
      {quotes.isLoading && <div className="dim">시세 불러오는 중…</div>}
      {quotes.isError && <div className="error-note">시세 로딩 실패</div>}
      {quotes.data && (
        <>
          {quotes.data.errors[tab] && (
            <div className="error-note">
              {tab.toUpperCase()} 시세 일부 실패: {quotes.data.errors[tab]}
            </div>
          )}
          <QuoteTable rows={quotes.data[tab]} onSelect={onSelect} />
        </>
      )}
    </div>
  );
}
