// Cumulative spending this month on ONE axis (S$): what you've spent so far (solid), where the
// forecaster says you'll land (dashed projection to month end), and your budget (reference line).
// Hover or touch anywhere for a crosshair with that day's numbers.

import { useMemo, useState, type PointerEvent } from "react";
import type { Forecast, Summary } from "../api";
import { sgd, sgdWhole, shortDate } from "../format";

const W = 680, H = 260, M = { l: 52, r: 108, t: 14, b: 28 };

function niceStep(max: number): number {
  const raw = max / 4;
  const pow = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? raw;
}

export default function SpendChart({ summary, forecast }: { summary: Summary; forecast: Forecast | null }) {
  const [hover, setHover] = useState<number | null>(null);
  const [year, mon] = summary.month.split("-").map(Number);
  const daysInMonth = forecast?.days_in_month ?? new Date(year, mon, 0).getDate();
  const today = forecast?.days_elapsed ?? daysInMonth;

  const daily = useMemo(() => {
    const byDay = new Map(summary.by_day.map((d) => [Number(d.date.slice(8, 10)), d.amount]));
    let run = 0;
    return Array.from({ length: today }, (_, i) => {
      const spent = byDay.get(i + 1) ?? 0;
      run += spent;
      return { day: i + 1, spent, total: run };
    });
  }, [summary.by_day, today]);

  const end = forecast?.forecast_total ?? null;
  const budget = summary.budget;
  const step = niceStep(Math.max(budget ?? 0, end ?? 0, daily.at(-1)?.total ?? 0, 10) * 1.05);
  const yMax = Math.ceil(Math.max(budget ?? 0, end ?? 0, daily.at(-1)?.total ?? 0, 10) * 1.05 / step) * step;
  const x = (day: number) => M.l + ((day - 1) / Math.max(1, daysInMonth - 1)) * (W - M.l - M.r);
  const y = (v: number) => H - M.b - (v / yMax) * (H - M.t - M.b);
  const ticks = Array.from({ length: Math.round(yMax / step) + 1 }, (_, i) => i * step);

  const actualPath = daily.map((d, i) => `${i ? "L" : "M"}${x(d.day).toFixed(1)},${y(d.total).toFixed(1)}`).join("");
  const last = daily.at(-1);
  const forecastAt = (day: number) =>
    last && end !== null ? last.total + ((end - last.total) * (day - last.day)) / Math.max(1, daysInMonth - last.day) : null;

  // Right-edge labels: keep the forecast and budget labels from colliding.
  let yForecast = end !== null ? y(end) : null;
  const yBudget = budget ? y(budget) : null;
  if (yForecast !== null && yBudget !== null && Math.abs(yForecast - yBudget) < 16) {
    yForecast = yForecast <= yBudget ? yBudget - 16 : yBudget + 16;
  }

  function onMove(e: PointerEvent<SVGRectElement>) {
    const box = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * W;
    const day = Math.round(((px - M.l) / (W - M.l - M.r)) * (daysInMonth - 1)) + 1;
    setHover(Math.min(daysInMonth, Math.max(1, day)));
  }

  const hovered = hover === null ? null
    : hover <= today ? { kind: "actual" as const, ...daily[hover - 1] }
    : { kind: "forecast" as const, day: hover, total: forecastAt(hover) ?? 0, spent: 0 };
  const dateOf = (day: number) => shortDate(`${summary.month}-${String(day).padStart(2, "0")}`);

  return (
    <div className="chart">
      <div className="legend" aria-hidden>
        <span><i />Spent so far</span>
        {end !== null && <span><i className="dash" />Forecast</span>}
        {budget ? <span><i className="ref" />Budget</span> : null}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={`Cumulative spending: ${sgd(last?.total ?? 0)} by ${dateOf(today)}${end !== null ? `, forecast ${sgd(end)} by month end` : ""}${budget ? `, budget ${sgd(budget)}` : ""}.`}>
        <g className="grid">{ticks.map((t) => <line key={t} x1={M.l} x2={W - M.r} y1={y(t)} y2={y(t)} />)}</g>
        <g className="axis">
          {ticks.map((t) => <text key={t} x={M.l - 8} y={y(t) + 4} textAnchor="end">{sgdWhole(t)}</text>)}
          {[1, 8, 15, 22, daysInMonth].map((d) => <text key={d} x={x(d)} y={H - 8} textAnchor="middle">{dateOf(d)}</text>)}
        </g>
        {budget ? (
          <>
            <line x1={M.l} x2={W - M.r} y1={yBudget!} y2={yBudget!} stroke="var(--ink-2)" strokeWidth={1} />
            <text className="lbl" x={W - M.r + 8} y={yBudget! + 4}>Budget {sgdWhole(budget)}</text>
          </>
        ) : null}
        {last && end !== null && (
          <>
            <line x1={x(last.day)} y1={y(last.total)} x2={x(daysInMonth)} y2={y(end)}
                  stroke="var(--series)" strokeWidth={2} strokeDasharray="6 5" strokeLinecap="round" />
            <text className="lbl" x={W - M.r + 8} y={yForecast! + 4}>Forecast {sgdWhole(end)}</text>
          </>
        )}
        <path d={`${actualPath}L${x(today)},${y(0)}L${x(1)},${y(0)}Z`} fill="var(--series-soft)" />
        <path d={actualPath} fill="none" stroke="var(--series)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {last && <circle cx={x(last.day)} cy={y(last.total)} r={4.5} fill="var(--series)" stroke="var(--card)" strokeWidth={2} />}

        {hovered && (
          <g pointerEvents="none">
            <line x1={x(hovered.day)} x2={x(hovered.day)} y1={M.t} y2={H - M.b} stroke="var(--ink-3)" strokeWidth={1} />
            <circle cx={x(hovered.day)} cy={y(hovered.total)} r={4.5} fill="var(--series)" stroke="var(--card)" strokeWidth={2} />
          </g>
        )}
        <rect x={M.l} y={M.t} width={W - M.l - M.r} height={H - M.t - M.b} fill="transparent"
              onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setHover(null)} />
      </svg>
      {hovered && (
        <div className="tooltip" style={{ left: `${(x(hovered.day) / W) * 100}%`, top: `${(y(hovered.total) / H) * 100}%` }}>
          {dateOf(hovered.day)}<br />
          {hovered.kind === "actual"
            ? <>spent {sgd(hovered.spent)} · total {sgd(hovered.total)}</>
            : <>forecast total {sgd(hovered.total)}</>}
        </div>
      )}
    </div>
  );
}
