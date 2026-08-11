import { useQuery } from "@tanstack/react-query";

interface ModulesResp {
  modules: { id: string; title: string; tagline: string; icon: string; path: string }[];
}

async function fetchJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(String(r.status));
  return r.json() as Promise<T>;
}

/** 백엔드 모듈 활성 여부·헬스 상태 폴링. Sidebar와 Home이 공유하며
 *  React Query가 같은 queryKey의 요청을 중복 제거한다. */
export function useModules() {
  const modules = useQuery({
    queryKey: ["modules"],
    queryFn: () => fetchJson<ModulesResp>("/api/modules"),
    refetchInterval: 30_000,
  });
  const health = useQuery({
    queryKey: ["healthz"],
    queryFn: () => fetchJson<{ modules: Record<string, unknown> }>("/healthz"),
    refetchInterval: 30_000,
  });

  const backendEnabled = new Set(modules.data?.modules.map((m) => m.id) ?? []);

  /** 낙관적 판정 — 모듈 목록 로딩 중엔 true (사이드바 깜빡임 방지용). */
  function isEnabled(id: string): boolean {
    return modules.isPending || backendEnabled.has(id);
  }

  /** 엄격 판정 — 목록이 확정된 뒤에만 true. 대시보드 패널의 fetch 게이트용
   *  (낙관 판정을 쓰면 비활성 모듈에 404 재시도 버스트가 생긴다). */
  function isEnabledStrict(id: string): boolean {
    return backendEnabled.has(id);
  }

  function statusLine(id: string): string {
    const h = health.data?.modules?.[id];
    if (!h || typeof h !== "object") return "상태 정보 없음";
    const parts: string[] = [];
    for (const [k, v] of Object.entries(h as Record<string, unknown>)) {
      if (typeof v === "number") parts.push(`${k} ${v.toLocaleString()}`);
    }
    return parts.slice(0, 3).join(" · ") || "상태 정보 없음";
  }

  /** 모듈 목록 1차 로딩 완료 여부 — false 동안 대시보드는 로딩 표시. */
  const ready = !modules.isPending;

  return { isEnabled, isEnabledStrict, ready, statusLine };
}
