import { lazy } from "react";
import type { AppDef } from "../types";

export const app: AppDef = {
  id: "market",
  title: "Market Desk",
  tagline: "US·KR 시세 대시보드 — 캔들 차트와 AI 분석",
  icon: "📊",
  Component: lazy(() => import("./MarketApp")),
};
