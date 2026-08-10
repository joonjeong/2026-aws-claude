import { useQuery } from "@tanstack/react-query";
import { fetchInvestors, fmtVolume, InvestorDay } from "../api/client";

const SERIES = [
  { key: "individual", label: "개인" },
  { key: "foreign", label: "외국인" },
  { key: "institution", label: "기관" },
] as const;

function SignedBar({ value, max }: { value: number; max: number }) {
  const pct = Math.min(100, (Math.abs(value) / max) * 100);
  const cls = value > 0 ? "up" : value < 0 ? "down" : "dim";
  return (
    <div className="inv-cell">
      <span className={`inv-num ${cls}`}>
        {value > 0 ? "+" : value < 0 ? "-" : ""}
        {fmtVolume(Math.abs(value))}
      </span>
      <div className="inv-track">
        <div className={`inv-bar ${cls}`} style={{ width: `${Math.max(2, pct)}%` }} />
      </div>
    </div>
  );
}

export default function InvestorPanel({ symbol }: { symbol: string }) {
  const q = useQuery({
    queryKey: ["investors", symbol],
    queryFn: () => fetchInvestors(symbol),
  });

  const days: InvestorDay[] = q.data?.days ?? [];
  const max = Math.max(
    1,
    ...days.flatMap((d) => SERIES.map((s) => Math.abs(d[s.key]))),
  );

  return (
    <div className="panel">
      <h3>
        투자자별 순매수 (10일) <span className="sim-badge">시뮬레이션</span>
      </h3>
      {q.isLoading && <div className="dim">수급 불러오는 중…</div>}
      {q.isError && <div className="error-note">수급 정보를 불러오지 못했습니다.</div>}
      {days.length > 0 && (
        <div className="inv-wrap">
          <table className="inv-table">
            <thead>
              <tr>
                <th>날짜</th>
                {SERIES.map((s) => (
                  <th key={s.key}>{s.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[...days].reverse().map((d) => (
                <tr key={d.date}>
                  <td className="dim">{d.date.slice(5)}</td>
                  {SERIES.map((s) => (
                    <td key={s.key}>
                      <SignedBar value={d[s.key]} max={max} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
