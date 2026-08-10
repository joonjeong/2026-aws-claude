import { lazy } from "react";
import type { AppDef } from "../types";

export const app: AppDef = {
  id: "quake",
  title: "Quake Watch",
  tagline: "전 세계 실시간 지진 모니터 — USGS 60초 수집",
  icon: "🌋",
  Component: lazy(() => import("./QuakeApp")),
};
