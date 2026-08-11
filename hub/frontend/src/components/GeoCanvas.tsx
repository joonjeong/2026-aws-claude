/* 공용 SVG 지도 베이스 — 등장방형(equirectangular) 투영 + bbox 뷰포트 줌.
   contrail·wake가 공유. 색은 사용하는 앱의 네임스페이스 CSS 변수
   (--map-bg, --land)를 소비한다. */
import type { ReactNode } from "react";
import { CONTINENTS } from "./continents";

export const WORLD_W = 1000;
export const WORLD_H = 500;

/** (lat_min, lon_min, lat_max, lon_max) — 백엔드 프리셋 bbox와 동일 순서 */
export type BBox = readonly [number, number, number, number];

export function project(lon: number, lat: number): [number, number] {
  return [((lon + 180) / 360) * WORLD_W, ((90 - lat) / 180) * WORLD_H];
}

export function bboxViewBox(bbox: BBox | null): string {
  if (!bbox) return `0 0 ${WORLD_W} ${WORLD_H}`;
  const [latMin, lonMin, latMax, lonMax] = bbox;
  const [x1, y1] = project(lonMin, latMax); // 좌상단 = (lon_min, lat_max)
  const [x2, y2] = project(lonMax, latMin);
  return `${x1} ${y1} ${x2 - x1} ${y2 - y1}`;
}

/** 줌 배율 — 마커를 1/k 스케일해 화면상 크기를 일정하게 유지 */
export function bboxZoomK(bbox: BBox | null): number {
  if (!bbox) return 1;
  const [, lonMin, , lonMax] = bbox;
  return 360 / Math.max(1e-6, lonMax - lonMin);
}

export default function GeoCanvas(props: {
  bbox?: BBox | null;
  className?: string;
  children?: ReactNode;
}) {
  const { bbox = null, className, children } = props;
  return (
    <svg
      viewBox={bboxViewBox(bbox)}
      className={className}
      preserveAspectRatio="xMidYMid meet"
      role="img"
    >
      <rect x={0} y={0} width={WORLD_W} height={WORLD_H} className="geo-ocean" />
      {CONTINENTS.map((poly, i) => (
        <polyline
          key={i}
          points={poly.map(([lon, lat]) => project(lon, lat).join(",")).join(" ")}
          className="geo-land"
          vectorEffect="non-scaling-stroke"
        />
      ))}
      {children}
    </svg>
  );
}
