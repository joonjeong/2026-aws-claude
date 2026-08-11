import { useQuery } from "@tanstack/react-query";
import {
  fetchContrailHealth,
  fetchQuakes,
  fetchWakeHealth,
  fmtNum,
  rel,
} from "./api";

interface Preset {
  id: string;
  label: string;
}

async function getPresets(url: string): Promise<Map<string, string>> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  const body = (await r.json()) as { presets: Preset[] };
  return new Map(body.presets.map((p) => [p.id, p.label]));
}

/* 지정학 이슈 모니터 — 항공(contrail)·물류(wake)·지진(quake) 3계열 요약.
   모듈별로 독립 쿼리라 한 계열이 죽어도 나머지는 계속 나온다. */
export default function GeoPanel({
  contrail,
  wake,
  quake,
  navigate,
}: {
  contrail: boolean;
  wake: boolean;
  quake: boolean;
  navigate: (p: string) => void;
}) {
  const air = useQuery({
    queryKey: ["dash-contrail"],
    queryFn: fetchContrailHealth,
    refetchInterval: 60_000,
    enabled: contrail,
  });
  const airPresets = useQuery({
    queryKey: ["dash-contrail-presets"],
    queryFn: () => getPresets("/api/contrail/preset"),
    staleTime: Infinity,
    enabled: contrail,
  });
  const sea = useQuery({
    queryKey: ["dash-wake"],
    queryFn: fetchWakeHealth,
    refetchInterval: 60_000,
    enabled: wake,
  });
  const seaPresets = useQuery({
    queryKey: ["dash-wake-presets"],
    queryFn: () => getPresets("/api/wake/preset"),
    staleTime: Infinity,
    enabled: wake,
  });
  const eq = useQuery({
    queryKey: ["dash-quake"],
    queryFn: fetchQuakes,
    refetchInterval: 60_000,
    enabled: quake,
  });

  const quakes = eq.data?.events.slice(0, 3) ?? [];

  return (
    <section className="panel">
      <button className="panel-title" onClick={() => navigate("/contrail")}>
        🌐 지정학 모니터 <span className="panel-arrow">→</span>
      </button>

      <div className="geo-row">
        <button className="geo-head" onClick={() => navigate("/contrail")}>
          ✈️ 항공 <span className="geo-status">{contrail ? air.data?.status ?? "…" : "모듈 비활성"}</span>
        </button>
        {contrail && air.data && (
          <>
            <div className="geo-main">
              전세계 추적 <b>{fmtNum(air.data.global_flights, 0)}</b>대
            </div>
            <div className="geo-sub">
              {Object.entries(air.data.region_flights).map(([pid, n]) => (
                <span key={pid}>
                  {airPresets.data?.get(pid) ?? pid} {fmtNum(n, 0)}
                </span>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="geo-row">
        <button className="geo-head" onClick={() => navigate("/wake")}>
          🚢 물류(해상) <span className="geo-status">{wake ? sea.data?.status ?? "…" : "모듈 비활성"}</span>
        </button>
        {wake && sea.data && (
          <div className="geo-main">
            {sea.data.status === "no_key" ? (
              <span className="dim">AIS 키 미설정 — 수집 대기</span>
            ) : (
              <>
                {seaPresets.data?.get(sea.data.preset) ?? sea.data.preset} 선박{" "}
                <b>{fmtNum(sea.data.vessels, 0)}</b>척
              </>
            )}
          </div>
        )}
      </div>

      <div className="geo-row">
        <button className="geo-head" onClick={() => navigate("/quake")}>
          🌍 지진 <span className="geo-status">{quake ? "24h · M4.5+" : "모듈 비활성"}</span>
        </button>
        {quake && eq.data && (
          <>
            <div className="geo-main">
              <b>{eq.data.stats.count}</b>건 · 최대 M{eq.data.stats.max_mag.toFixed(1)}
              {eq.data.stats.top_region && ` · ${eq.data.stats.top_region}`}
            </div>
            <ul className="geo-quakes">
              {quakes.map((e) => (
                <li key={e.id}>
                  <span className={`mag${e.mag >= 6 ? " strong" : ""}`}>
                    M{e.mag.toFixed(1)}
                  </span>
                  <span className="place">{e.place}</span>
                  <span className="when">{rel(e.time)}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  );
}
