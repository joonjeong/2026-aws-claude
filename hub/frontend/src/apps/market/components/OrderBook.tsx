import { useQuery } from "@tanstack/react-query";
import { fetchOrderBook, fmtNum, fmtVolume, OrderBookLevel } from "../api/client";

const REFETCH_MS = 45_000; // matches backend ORDERBOOK_TTL

function Ladder({ side, levels, maxVol }: {
  side: "ask" | "bid";
  levels: OrderBookLevel[];
  maxVol: number;
}) {
  return (
    <div className="ob-col">
      <div className={`ob-head ${side === "ask" ? "down" : "up"}`}>
        {side === "ask" ? "매도" : "매수"}
      </div>
      {levels.map((l) => (
        <div className="ob-row" key={`${side}-${l.price}`}>
          <div
            className={`ob-bar ${side}`}
            style={{ width: `${Math.max(2, (l.volume / maxVol) * 100)}%` }}
          />
          <span className={`ob-price ${side === "ask" ? "down" : "up"}`}>
            {fmtNum(l.price)}
          </span>
          <span className="ob-vol dim">{fmtVolume(l.volume)}</span>
        </div>
      ))}
    </div>
  );
}

export default function OrderBook({ symbol }: { symbol: string }) {
  const q = useQuery({
    queryKey: ["orderbook", symbol],
    queryFn: () => fetchOrderBook(symbol),
    refetchInterval: REFETCH_MS,
  });

  return (
    <div className="panel">
      <h3>
        호가 <span className="sim-badge">시뮬레이션</span>
      </h3>
      {q.isLoading && <div className="dim">호가 불러오는 중…</div>}
      {q.isError && <div className="error-note">호가를 불러오지 못했습니다.</div>}
      {q.data && (
        <>
          <div className="ob-grid">
            <Ladder
              side="ask"
              levels={q.data.asks}
              maxVol={Math.max(
                ...q.data.asks.map((l) => l.volume),
                ...q.data.bids.map((l) => l.volume),
              )}
            />
            <Ladder
              side="bid"
              levels={q.data.bids}
              maxVol={Math.max(
                ...q.data.asks.map((l) => l.volume),
                ...q.data.bids.map((l) => l.volume),
              )}
            />
          </div>
          <div className="ob-mid">현재가 {fmtNum(q.data.price)}</div>
        </>
      )}
    </div>
  );
}
