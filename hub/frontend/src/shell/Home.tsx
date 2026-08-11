import { useModules } from "./useModules";
import TickerTape from "./dashboard/TickerTape";
import IndexStrip from "./dashboard/IndexStrip";
import AISummaryPanel from "./dashboard/AISummaryPanel";
import QuotePanel from "./dashboard/QuotePanel";
import NewsPanel from "./dashboard/NewsPanel";
import TrendPanel from "./dashboard/TrendPanel";
import GeoPanel from "./dashboard/GeoPanel";

interface Props {
  navigate: (p: string) => void;
}

/* 통합 모니터링 대시보드 — 증시 지표(티커+지수), 지정학 이슈(항공·물류·지진),
   트렌드·뉴스를 한 화면에서 모니터링. 각 패널 제목은 해당 앱으로 이동한다. */
export default function Home({ navigate }: Props) {
  // 엄격 판정(isEnabledStrict): 모듈 목록 확정 전에 fetch가 나가
  // 비활성 모듈에 404 재시도 버스트가 생기는 것을 막는다.
  const { isEnabledStrict, ready } = useModules();

  if (!ready) return <div className="shell-loading">모듈 확인 중…</div>;

  return (
    <div className="dash">
      <TickerTape enabled={isEnabledStrict("market")} />
      <div className="dash-body">
        {/* 가운데 — 지수 스파크라인 / AI 시황 요약 / 마켓데스크 시세표 */}
        <div className="dash-main">
          <IndexStrip enabled={isEnabledStrict("market")} navigate={navigate} />
          <AISummaryPanel enabled={isEnabledStrict("market")} />
          <QuotePanel enabled={isEnabledStrict("market")} navigate={navigate} />
        </div>
        {/* 우측 레일 — 지정학 → 뉴스룸 → 트렌드 */}
        <aside className="dash-side">
          <GeoPanel
            contrail={isEnabledStrict("contrail")}
            wake={isEnabledStrict("wake")}
            quake={isEnabledStrict("quake")}
            navigate={navigate}
          />
          <NewsPanel enabled={isEnabledStrict("news")} navigate={navigate} />
          <TrendPanel enabled={isEnabledStrict("trend")} navigate={navigate} />
        </aside>
      </div>
    </div>
  );
}
