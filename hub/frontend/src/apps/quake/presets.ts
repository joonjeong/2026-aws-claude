/* 지역 프리셋 — lon/lat 경계 상자 필터 + SVG viewBox 줌.
   환태평양(ring)은 날짜변경선을 넘으므로 필터는 경도 두 구간의 합집합이고,
   줌 viewBox는 가로 전체를 유지한 채 위도만 잘라낸다. */

export const MAP_W = 1000;
export const MAP_H = 500;

export type PresetId = "all" | "ring" | "japan" | "korea";

export interface Preset {
  id: PresetId;
  label: string;
  /** 필터: 경도 구간의 합집합 (환태평양은 [100,180] ∪ [-180,-60]) */
  lonRanges: ReadonlyArray<readonly [number, number]>;
  latRange: readonly [number, number];
  /** 줌: viewBox 계산용 경도/위도 범위 (환태평양은 가로 전체 유지) */
  viewLon: readonly [number, number];
  viewLat: readonly [number, number];
}

export const PRESETS: ReadonlyArray<Preset> = [
  {
    id: "all",
    label: "전체",
    lonRanges: [[-180, 180]],
    latRange: [-90, 90],
    viewLon: [-180, 180],
    viewLat: [-90, 90],
  },
  {
    id: "ring",
    label: "환태평양",
    lonRanges: [[100, 180], [-180, -60]],
    latRange: [-60, 65],
    viewLon: [-180, 180],
    viewLat: [-60, 65],
  },
  {
    id: "japan",
    label: "일본 주변",
    lonRanges: [[122, 150]],
    latRange: [24, 46],
    viewLon: [122, 150],
    viewLat: [24, 46],
  },
  {
    id: "korea",
    label: "한반도 주변",
    lonRanges: [[122, 134]],
    latRange: [32, 43],
    viewLon: [122, 134],
    viewLat: [32, 43],
  },
];

export const DEFAULT_PRESET: Preset = PRESETS[0];

/* equirectangular projection (지도와 동일) */
const px = (lon: number): number => ((lon + 180) / 360) * MAP_W;
const py = (lat: number): number => ((90 - lat) / 180) * MAP_H;

export function presetViewBox(p: Preset): string {
  const x = px(p.viewLon[0]);
  const y = py(p.viewLat[1]);
  const w = px(p.viewLon[1]) - x;
  const h = py(p.viewLat[0]) - y;
  return `${x.toFixed(1)} ${y.toFixed(1)} ${w.toFixed(1)} ${h.toFixed(1)}`;
}

/** 줌 배율: 화면 픽셀 크기를 유지하기 위한 world-unit 축소 계수 */
export function presetZoomK(p: Preset): number {
  return (p.viewLon[1] - p.viewLon[0]) / 360;
}

export function inPreset(lon: number, lat: number, p: Preset): boolean {
  if (lat < p.latRange[0] || lat > p.latRange[1]) return false;
  return p.lonRanges.some(([a, b]) => lon >= a && lon <= b);
}

export function findPreset(id: string | null): Preset {
  return PRESETS.find((p) => p.id === id) ?? DEFAULT_PRESET;
}
