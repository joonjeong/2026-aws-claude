import { useEffect, useRef } from "react";
import {
  createChart,
  CandlestickSeries,
  ColorType,
  IChartApi,
  UTCTimestamp,
} from "lightweight-charts";
import { Candle } from "../api/client";

const UP = "#22c55e";
const DOWN = "#ef4444";

export default function CandleChart({ candles }: { candles: Candle[] }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;

    const chart = createChart(box, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#7f8db3",
      },
      grid: {
        vertLines: { color: "#1a2547" },
        horzLines: { color: "#1a2547" },
      },
      timeScale: { borderColor: "#223058" },
      rightPriceScale: { borderColor: "#223058" },
      autoSize: true,
    });
    chartRef.current = chart;

    const series = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      wickUpColor: UP,
      wickDownColor: DOWN,
      borderVisible: false,
    });
    series.setData(
      candles.map((c) => ({
        // "YYYY-MM-DD" business-day strings are accepted directly
        time: c.time as unknown as UTCTimestamp,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })),
    );
    chart.timeScale().fitContent();

    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [candles]);

  return <div className="chart-box" ref={boxRef} />;
}
