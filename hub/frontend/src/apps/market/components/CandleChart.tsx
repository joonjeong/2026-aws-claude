import { useEffect, useRef } from "react";
import {
  createChart,
  CandlestickSeries,
  ColorType,
  IChartApi,
  UTCTimestamp,
} from "lightweight-charts";
import { Candle } from "../api/client";

/** lightweight-charts colors are JS-side — they can't consume CSS variables,
 * so we keep a palette per theme and re-apply on <html data-theme> changes
 * (the SHELL owns the toggle; we only react via a MutationObserver). */
const PALETTES = {
  dark: {
    text: "#7f8db3",
    grid: "#1a2547",
    border: "#223058",
    up: "#22c55e",
    down: "#ef4444",
  },
  light: {
    text: "#5d6a8c",
    grid: "#e5eaf6",
    border: "#c9d4ea",
    up: "#16a34a",
    down: "#dc2626",
  },
} as const;

function currentPalette() {
  const theme = document.documentElement.dataset.theme;
  return theme === "light" ? PALETTES.light : PALETTES.dark;
}

export default function CandleChart({ candles }: { candles: Candle[] }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;

    const chart = createChart(box, {
      layout: { background: { type: ColorType.Solid, color: "transparent" } },
      autoSize: true,
    });
    chartRef.current = chart;

    const series = chart.addSeries(CandlestickSeries, { borderVisible: false });
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

    const applyTheme = () => {
      const p = currentPalette();
      chart.applyOptions({
        layout: {
          background: { type: ColorType.Solid, color: "transparent" },
          textColor: p.text,
        },
        grid: {
          vertLines: { color: p.grid },
          horzLines: { color: p.grid },
        },
        timeScale: { borderColor: p.border },
        rightPriceScale: { borderColor: p.border },
      });
      series.applyOptions({
        upColor: p.up,
        downColor: p.down,
        wickUpColor: p.up,
        wickDownColor: p.down,
      });
    };
    applyTheme();

    const observer = new MutationObserver(applyTheme);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [candles]);

  return <div className="chart-box" ref={boxRef} />;
}
