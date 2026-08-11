import { lazy } from "react";
import type { AppDef } from "../types";

export const app: AppDef = {
  id: "wake",
  title: "Wake Watch",
  tagline: "관심 해역 선박 항적 — AIS 실시간 스트림",
  icon: "🌊",
  Component: lazy(() => import("./WakeApp")),
};
