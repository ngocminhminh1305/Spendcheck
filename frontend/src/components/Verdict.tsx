// "Am I okay this month?" in one sentence, the hero number, and why the forecast says so.
// Combines the summary (Modules 1 + 2 data) with Module 3's forecast.

import { CircleAlert, CircleCheck, Info, TriangleAlert } from "lucide-react";
import type { Forecast, Summary } from "../api";
import { sgd, sgdWhole, shortDate } from "../format";
import type { Prefs } from "../prefs";
import { health, HEALTH_LABEL, verdict, type Health } from "../voice";

const ICONS: Record<Health, typeof Info> = { none: Info, good: CircleCheck, warning: TriangleAlert, critical: CircleAlert };

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Spending allowed per remaining day (after today) to finish within budget. */
export function perDayLeft(summary: Summary, forecast: Forecast | null): number | null {
  if (!summary.budget || !forecast) return null;
  const daysAfterToday = Math.max(1, forecast.days_in_month - forecast.days_elapsed);
  return Math.max(0, summary.budget - summary.spent) / daysAfterToday;
}

export default function Verdict({ prefs, summary, forecast, showWhy = false }: {
  prefs: Prefs; summary: Summary; forecast: Forecast | null; showWhy?: boolean;
}) {
  const h = health(summary, forecast);
  const Icon = ICONS[h];
  const perDay = perDayLeft(summary, forecast);
  const share = summary.budget ? Math.min(1, summary.spent / summary.budget) : 0;
  const daysLeft = forecast ? forecast.days_in_month - forecast.days_elapsed : null;

  return (
    <section className="card verdict reveal" aria-labelledby="verdict-title">
      <h2 className="card__title" id="verdict-title">This month</h2>
      <span className={`status status--${h}`}><Icon size={16} aria-hidden /> {HEALTH_LABEL[h]}</span>
      <p className="verdict__line">{verdict(prefs, summary, forecast, perDay)}</p>
      <div className="hero">
        <span className="hero__num">{sgd(summary.spent)}</span>
        <span className="hero__of">{summary.budget ? `of ${sgdWhole(summary.budget)} budget` : "spent so far"}</span>
      </div>
      {summary.budget ? (
        <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={summary.budget} aria-valuenow={summary.spent}
             aria-label={`${sgd(summary.spent)} of ${sgd(summary.budget)} spent`}>
          <div className={`meter__fill${summary.spent > summary.budget ? " meter__fill--over" : ""}`} style={{ width: `${share * 100}%` }} />
        </div>
      ) : null}
      <div className="facts">
        {perDay !== null && perDay > 0 && <span><b>{sgd(perDay)}</b> a day left</span>}
        {daysLeft !== null && (daysLeft === 0
          ? <span><b>Last day</b> of the month</span>
          : <span><b>{daysLeft}</b> {daysLeft === 1 ? "day" : "days"} to go</span>)}
        {forecast && <span>Month-end forecast <b>{sgd(forecast.forecast_total)}</b></span>}
      </div>
      {showWhy && forecast && (
        <div className="why">
          <strong>Why we think this:</strong> you've spent {sgd(forecast.spent_so_far)} in {plural(forecast.days_elapsed, "day")}
          {forecast.one_off_spend > 0 && <>, including {sgd(forecast.one_off_spend)} of one-off purchases (counted once, not as your daily pace)</>}.
          The forecaster learned your usual pattern from {plural(forecast.months_of_history, "month")} of history and expects about{" "}
          {sgd(forecast.forecast_total)} by {shortDate(`${forecast.month}-${String(forecast.days_in_month).padStart(2, "0")}`)}.
          {" "}It's an estimate, not a promise.
        </div>
      )}
    </section>
  );
}
