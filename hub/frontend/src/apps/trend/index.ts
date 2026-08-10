import { lazy } from "react";
import type { AppDef } from "../types";

export const app: AppDef = {
  id: "trend",
  title: "Trend Radar",
  tagline: "유튜브 급상승 30 — rank delta·NEW·카테고리 점유율·AI 브리핑",
  icon: "📈",
  Component: lazy(() => import("./TrendApp")),
};
