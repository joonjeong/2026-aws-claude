import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchChart, fetchDetail, fmtNum, fmtVolume, StockDetail as Detail } from "../api/client";
import Delta from "./Delta";
import CandleChart from "./CandleChart";
import AIPanel from "./AIPanel";

const RANGES = ["1w", "1m", "3m", "1y"] as const;
type Range = (typeof RANGES)[number];
const RANGE_LABEL: Record<Range, string> = { "1w": "1W", "1m": "1M", "3m": "3M", "1y": "1Y" };

function StockHeader({ d }: { d: Detail }) {
  return (
    <div className="stock-header">
      <span className="name">
        {d.name} <span className="dim">({d.symbol})</span>
      </span>
      <span className="price">{fmtNum(d.price)}</span>
      <span className="delta">
        <Delta change={d.change} pct={d.change_pct} />
      </span>
      <span className="vol">
        거래량 {fmtVolume(d.volume)} · 기준일 {d.as_of}
      </span>
    </div>
  );
}

function ReturnsRow({ d }: { d: Detail }) {
  return (
    <div className="panel">
      <h3>기간 수익률</h3>
      <div className="returns-row">
        {RANGES.map((r) => {
          const v = d.returns[r];
          return (
            <div className="cell" key={r}>
              <div className="label">{RANGE_LABEL[r]}</div>
              <div className={`value ${v == null ? "dim" : v > 0 ? "up" : v < 0 ? "down" : "dim"}`}>
                {v == null ? "—" : `${v > 0 ? "+" : ""}${fmtNum(v)}%`}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Week52Bar({ d }: { d: Detail }) {
  const pct = Math.min(100, Math.max(0, d.week52.position * 100));
  return (
    <div className="panel">
      <h3>52주 범위</h3>
      <div className="w52-track">
        <div className="w52-marker" style={{ left: `${pct}%` }} />
      </div>
      <div className="w52-labels">
        <span>저 {fmtNum(d.week52.low)}</span>
        <span>현재 위치 {fmtNum(pct, 0)}%</span>
        <span>고 {fmtNum(d.week52.high)}</span>
      </div>
    </div>
  );
}

export default function StockDetail({
  symbol,
  onBack,
}: {
  symbol: string;
  onBack: () => void;
}) {
  const [range, setRange] = useState<Range>("3m");

  const detail = useQuery({
    queryKey: ["detail", symbol],
    queryFn: () => fetchDetail(symbol),
  });
  const chart = useQuery({
    queryKey: ["chart", symbol, range],
    queryFn: () => fetchChart(symbol, range),
  });

  return (
    <div>
      <button className="back-btn" onClick={onBack}>
        ← 대시보드
      </button>
      {detail.isLoading && <div className="dim">불러오는 중…</div>}
      {detail.isError && <div className="error-note">종목 정보를 불러오지 못했습니다.</div>}
      {detail.data && (
        <>
          <StockHeader d={detail.data} />
          <div className="panel">
            <div className="tabs">
              {RANGES.map((r) => (
                <button
                  key={r}
                  className={range === r ? "active" : ""}
                  onClick={() => setRange(r)}
                >
                  {RANGE_LABEL[r]}
                </button>
              ))}
            </div>
            {chart.isLoading && <div className="dim chart-box">차트 불러오는 중…</div>}
            {chart.isError && <div className="error-note">차트를 불러오지 못했습니다.</div>}
            {chart.data && <CandleChart candles={chart.data.candles} />}
          </div>
          <ReturnsRow d={detail.data} />
          <Week52Bar d={detail.data} />
          <AIPanel symbol={symbol} />
        </>
      )}
    </div>
  );
}
