import type { ComponentType, LazyExoticComponent } from "react";

export interface AppDef {
  id: string;
  title: string;
  tagline: string;
  icon: string;
  Component: LazyExoticComponent<ComponentType>;
}
