import { useState } from "react";
import Dashboard from "./components/Dashboard";
import StockDetail from "./components/StockDetail";
import "./market.css";

// State-based view switch (no router needed per design doc).
// QueryClientProvider is supplied by the shell root — do not add one here.
export default function MarketApp() {
  const [symbol, setSymbol] = useState<string | null>(null);

  return (
    <div className="market-root">
      <h1 className="app-title">
        Market <span>Desk</span>
      </h1>
      {symbol === null ? (
        <Dashboard onSelect={setSymbol} />
      ) : (
        <StockDetail symbol={symbol} onBack={() => setSymbol(null)} />
      )}
    </div>
  );
}
