import { lazy } from "react";
import type { AppDef } from "../types";

export const app: AppDef = {
  id: "flashpoint",
  title: "Flashpoint Watch",
  tagline: "전 세계 분쟁·불안 이벤트 — GDELT 뉴스 보도 기반",
  icon: "⚡",
  Component: lazy(() => import("./FlashpointApp")),
};
