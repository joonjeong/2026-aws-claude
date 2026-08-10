/* 보너스 차트 — 시간 히스토그램 + 구텐베르크-리히터 규모-빈도 분포.
   둘 다 QuakeApp의 filtered events(프리셋 bbox + 규모 슬라이더 적용)에서 파생되는
   순수 클라이언트 사이드 SVG (외부 라이브러리 없음). */

/** 차트가 필요로 하는 최소 이벤트 형태 — QuakeApp의 QuakeEvent가 구조적으로 호환된다 */
export interface ChartEvent {
  id: string;
  mag: number;
  time: number; // epoch ms
}

const HOUR_MS = 3600_000;

/** epoch ms -> KST 시(0-23) */
function kstHour(ms: number): number {
  const h = parseInt(
    new Date(ms).toLocaleString("en-US", {
      timeZone: "Asia/Seoul",
      hour: "2-digit",
      hour12: false,
    }),
    10,
  );
  return Number.isFinite(h) ? h % 24 : 0;
}

/* ---------- 시간 히스토그램: 선택한 창을 1시간 버킷으로 나눈 발생 건수 ---------- */

const HG_W = 480;
const HG_H = 200;
const HG_TOP = 16;
const HG_BOTTOM = 26;
const HG_LEFT = 34;
const HG_RIGHT = 10;
const HG_PLOT_W = HG_W - HG_LEFT - HG_RIGHT;
const HG_PLOT_H = HG_H - HG_TOP - HG_BOTTOM;

export function HourHistogram({
  events,
  hours,
  now,
}: {
  events: ChartEvent[];
  hours: 6 | 24;
  now: number;
}) {
  const start = now - hours * HOUR_MS;
  const counts: number[] = new Array<number>(hours).fill(0);
  const maxMags: number[] = new Array<number>(hours).fill(0);
  for (const e of events) {
    const i = Math.floor((e.time - start) / HOUR_MS);
    if (i >= 0 && i < hours) {
      counts[i] += 1;
      if (e.mag > maxMags[i]) maxMags[i] = e.mag;
    }
  }
  const maxCount = Math.max(1, ...counts);
  const bw = HG_PLOT_W / hours;
  const labelEvery = hours === 6 ? 1 : 4; // 6h → 매 시간, 24h → 4시간 간격
  const baseY = HG_TOP + HG_PLOT_H;

  return (
    <>
      <div className="chart-box">
        <svg
          className="qchart"
          viewBox={`0 0 ${HG_W} ${HG_H}`}
          xmlns="http://www.w3.org/2000/svg"
          role="img"
          aria-label={`최근 ${hours}시간 시간별 지진 발생 건수 히스토그램`}
        >
          {/* 최대치 기준선 */}
          <line className="gridline" x1={HG_LEFT} x2={HG_LEFT + HG_PLOT_W} y1={HG_TOP} y2={HG_TOP} />
          <text className="axis" x={HG_LEFT - 6} y={HG_TOP + 4} textAnchor="end">
            {maxCount}
          </text>
          <text className="axis" x={HG_LEFT - 6} y={baseY + 4} textAnchor="end">
            0
          </text>
          {/* 기준선(x축) */}
          <line className="baseline" x1={HG_LEFT} x2={HG_LEFT + HG_PLOT_W} y1={baseY} y2={baseY} />
          {counts.map((c, i) => {
            const x = HG_LEFT + i * bw;
            const h = (c / maxCount) * HG_PLOT_H;
            const h0 = kstHour(start + i * HOUR_MS);
            return (
              <g key={i}>
                <rect
                  className="bar"
                  x={(x + bw * 0.12).toFixed(1)}
                  y={(baseY - h).toFixed(1)}
                  width={(bw * 0.76).toFixed(1)}
                  height={h.toFixed(1)}
                >
                  <title>
                    {`${h0}시~${(h0 + 1) % 24}시: ${c}건${c > 0 ? ` · 최대 M${maxMags[i].toFixed(1)}` : ""}`}
                  </title>
                </rect>
                {i % labelEvery === 0 && (
                  <text className="axis" x={(x + bw / 2).toFixed(1)} y={HG_H - 8} textAnchor="middle">
                    {`${h0}시`}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      <div className="legend">
        <span className="note">가로 = 시각(KST) · 세로 = 시간당 건수 (오래된 시간이 왼쪽) — 막대에 마우스를 올리면 건수 표시</span>
      </div>
    </>
  );
}

/* ---------- 구텐베르크-리히터: x = 규모, y = log10(누적 빈도 N≥M) ---------- */

const GR_W = 480;
const GR_H = 200;
const GR_TOP = 16;
const GR_BOTTOM = 30;
const GR_LEFT = 44;
const GR_RIGHT = 14;
const GR_PLOT_W = GR_W - GR_LEFT - GR_RIGHT;
const GR_PLOT_H = GR_H - GR_TOP - GR_BOTTOM;

const GR_MIN_SAMPLE = 10;

interface GRPoint {
  m: number;
  n: number; // 누적 건수 N≥M
  logN: number;
}

/** 최소제곱 직선 적합: y = a + s·x → 반환 [s, a], 분산 0이면 null */
function leastSquares(pts: ReadonlyArray<readonly [number, number]>): [number, number] | null {
  const k = pts.length;
  if (k < 2) return null;
  let sx = 0;
  let sy = 0;
  let sxx = 0;
  let sxy = 0;
  for (const [x, y] of pts) {
    sx += x;
    sy += y;
    sxx += x * x;
    sxy += x * y;
  }
  const den = k * sxx - sx * sx;
  if (Math.abs(den) < 1e-12) return null;
  const s = (k * sxy - sx * sy) / den;
  const a = (sy - s * sx) / k;
  return [s, a];
}

export function GRChart({ events, minMag }: { events: ChartEvent[]; minMag: number }) {
  const n = events.length;
  if (n < GR_MIN_SAMPLE) {
    return (
      <div className="chart-notice">
        표본이 부족합니다 (N = {n} &lt; {GR_MIN_SAMPLE}건) — 현재 필터 조건에서는 의미 있는 b값을
        추정할 수 없습니다. 규모 슬라이더를 낮추거나 더 넓은 지역·긴 시간 창을 선택해 보세요.
      </div>
    );
  }

  const mags = events.map((e) => e.mag);
  const maxMag = Math.max(...mags);
  const m0 = Math.round(minMag * 10) / 10;

  // 0.1 간격 규모 빈: 슬라이더 최소값부터 관측 최대 규모까지, 누적 N≥M
  const points: GRPoint[] = [];
  for (let i = 0; ; i++) {
    const m = Math.round((m0 + i * 0.1) * 10) / 10;
    if (m > maxMag + 1e-9) break;
    const c = mags.reduce((acc, v) => (v >= m - 1e-9 ? acc + 1 : acc), 0);
    if (c > 0) points.push({ m, n: c, logN: Math.log10(c) });
  }

  // 선형 구간 선택 — 카탈로그는 작은 규모에서 불완전해(관측 누락) 저규모 쪽이 휘어진다.
  // 적합도 탐색(Wiemer-Wyss GFT 방식 단순화): 완전성 규모 후보 Mc를 낮은 쪽부터 훑으며
  // "Mc 이상 & 누적 N≥3"인 점들로 최소제곱 적합 → R²가 처음 0.95를 넘는 가장 낮은 Mc 채택.
  // 어느 후보도 못 넘으면 R² 최대 후보, 그마저 없으면 전체 점으로 폴백.
  const significant = points.filter((p) => p.n >= 3);
  let fitPts: GRPoint[] = significant.length >= 2 ? significant : points;
  let fit = leastSquares(fitPts.map((p) => [p.m, p.logN] as const));
  let bestR2 = -Infinity;
  for (let s = 0; s + 4 <= significant.length; s++) {
    const cand = significant.slice(s); // Mc = significant[s].m 이상
    const ls = leastSquares(cand.map((p) => [p.m, p.logN] as const));
    if (!ls || ls[0] >= 0) continue;
    const mean = cand.reduce((a, p) => a + p.logN, 0) / cand.length;
    const ssTot = cand.reduce((a, p) => a + (p.logN - mean) ** 2, 0);
    const ssRes = cand.reduce((a, p) => a + (p.logN - (ls[1] + ls[0] * p.m)) ** 2, 0);
    const r2 = ssTot > 1e-12 ? 1 - ssRes / ssTot : 0;
    if (r2 > bestR2) {
      bestR2 = r2;
      fitPts = cand;
      fit = ls;
    }
    if (r2 >= 0.95) break; // 조건을 만족하는 가장 낮은 Mc에서 정지
  }
  const b = fit && fit[0] < 0 ? -fit[0] : null;

  const xMin = m0;
  const xMax = Math.max(maxMag, m0 + 0.5);
  const yMax = Math.max(1, Math.ceil(Math.log10(n)));
  const gx = (m: number): number => GR_LEFT + ((m - xMin) / (xMax - xMin)) * GR_PLOT_W;
  const gy = (logN: number): number => GR_TOP + (1 - logN / yMax) * GR_PLOT_H;

  // x축 눈금: 0.5 간격
  const xTicks: number[] = [];
  for (let m = Math.ceil(xMin * 2) / 2; m <= xMax + 1e-9; m += 0.5) {
    xTicks.push(Math.round(m * 10) / 10);
  }

  // 적합선은 실제로 적합에 쓰인 규모 구간 위에만 그린다
  const fitLine =
    fit && b !== null && fitPts.length >= 2
      ? {
          x1: gx(fitPts[0].m),
          y1: gy(Math.min(yMax, Math.max(0, fit[1] + fit[0] * fitPts[0].m))),
          x2: gx(fitPts[fitPts.length - 1].m),
          y2: gy(Math.min(yMax, Math.max(0, fit[1] + fit[0] * fitPts[fitPts.length - 1].m))),
        }
      : null;

  return (
    <>
      <div className="chart-box">
        <svg
          className="qchart"
          viewBox={`0 0 ${GR_W} ${GR_H}`}
          xmlns="http://www.w3.org/2000/svg"
          role="img"
          aria-label="구텐베르크-리히터 규모-빈도 분포"
        >
          {/* y축 눈금: 10^k */}
          {Array.from({ length: yMax + 1 }, (_, k) => (
            <g key={k}>
              <line
                className="gridline"
                x1={GR_LEFT}
                x2={GR_LEFT + GR_PLOT_W}
                y1={gy(k)}
                y2={gy(k)}
              />
              <text className="axis" x={GR_LEFT - 6} y={gy(k) + 4} textAnchor="end">
                {10 ** k}
              </text>
            </g>
          ))}
          {/* x축 눈금 */}
          {xTicks.map((m) => (
            <text key={m} className="axis" x={gx(m).toFixed(1)} y={GR_H - 8} textAnchor="middle">
              {`M${m.toFixed(1)}`}
            </text>
          ))}
          <line
            className="baseline"
            x1={GR_LEFT}
            x2={GR_LEFT + GR_PLOT_W}
            y1={GR_TOP + GR_PLOT_H}
            y2={GR_TOP + GR_PLOT_H}
          />
          {fitLine && (
            <line className="grfit" x1={fitLine.x1} y1={fitLine.y1} x2={fitLine.x2} y2={fitLine.y2} />
          )}
          {points.map((p) => (
            <circle key={p.m} className="grpoint" cx={gx(p.m).toFixed(1)} cy={gy(p.logN).toFixed(1)} r={3}>
              <title>{`M${p.m.toFixed(1)} 이상: ${p.n}건`}</title>
            </circle>
          ))}
          {b !== null && (
            <text className="grb" x={GR_LEFT + GR_PLOT_W - 6} y={GR_TOP + 14} textAnchor="end">
              {`b ≈ ${b.toFixed(2)}`}
            </text>
          )}
        </svg>
      </div>
      <div className="legend">
        <span className="note">
          {b !== null
            ? `구텐베르크-리히터: 규모가 1 커지면 빈도는 ~10^b분의 1 (b ≈ ${b.toFixed(2)}) · 점 = 누적 빈도 N≥M`
            : "선형 구간이 짧아 b값을 추정할 수 없습니다 · 점 = 누적 빈도 N≥M"}
        </span>
      </div>
    </>
  );
}
