import { fmtNum } from "../api/client";

export function deltaClass(v: number): string {
  return v > 0 ? "up" : v < 0 ? "down" : "dim";
}

export function arrow(v: number): string {
  return v > 0 ? "▲" : v < 0 ? "▼" : "";
}

export default function Delta({
  change,
  pct,
}: {
  change?: number;
  pct: number;
}) {
  return (
    <span className={deltaClass(pct)}>
      {arrow(pct)} {change !== undefined ? `${fmtNum(Math.abs(change))} ` : ""}
      ({pct > 0 ? "+" : ""}
      {fmtNum(pct)}%)
    </span>
  );
}
