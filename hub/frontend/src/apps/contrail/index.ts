import { lazy } from "react";
import type { AppDef } from "../types";

export const app: AppDef = {
  id: "contrail",
  title: "Contrail Watch",
  tagline: "전 세계 항공 트래픽·관심지역 항적 — OpenSky",
  icon: "✈️",
  Component: lazy(() => import("./ContrailApp")),
};
