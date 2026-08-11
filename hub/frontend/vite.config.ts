import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

const ALL_APPS = ["quake", "news", "trend", "market", "contrail", "wake", "flashpoint"];

/** virtual:apps — VITE_APPS(쉼표 구분)로 선택된 앱만 정적 import하는
 *  레지스트리를 생성한다. 미선택 앱은 import 그래프에서 빠져 번들에 포함되지 않는다. */
function appsPlugin(): Plugin {
  const raw = process.env.VITE_APPS ?? ALL_APPS.join(",");
  const apps = raw
    .split(",")
    .map((s) => s.trim())
    .filter((s) => ALL_APPS.includes(s));
  const VIRTUAL_ID = "virtual:apps";
  const RESOLVED_ID = "\0" + VIRTUAL_ID;
  return {
    name: "hub-apps-registry",
    resolveId(id) {
      if (id === VIRTUAL_ID) return RESOLVED_ID;
    },
    load(id) {
      if (id !== RESOLVED_ID) return;
      return [
        ...apps.map((a) => `import { app as ${a} } from "/src/apps/${a}/index";`),
        `export const APPS = [${apps.join(", ")}];`,
      ].join("\n");
    },
  };
}

export default defineConfig({
  plugins: [appsPlugin(), react()],
  base: "/",
  build: {
    outDir: "../backend/static/app",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": process.env.VITE_API_TARGET ?? "http://localhost:8000",
      "/healthz": process.env.VITE_API_TARGET ?? "http://localhost:8000",
    },
  },
});
