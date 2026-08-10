import { lazy } from "react";
import type { AppDef } from "../types";

export const app: AppDef = {
  id: "news",
  title: "Newsroom Lens",
  tagline: "BBC·Guardian·NHK·연합뉴스·Al Jazeera — 5개 매체 관점 비교 뉴스룸",
  icon: "📰",
  Component: lazy(() => import("./NewsApp")),
};
