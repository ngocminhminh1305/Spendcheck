// The website's own sentences, in the user's chosen voice ("a friend, not a bank").
// These are fixed templates, not LLM output: they cost no AI requests and never change a number.

import type { Forecast, Summary } from "./api";
import { sgd } from "./format";
import type { Prefs } from "./prefs";

type Voice = Pick<Prefs, "name" | "tone">;

const who = (v: Voice) => (v.name.trim() ? ` ${v.name.trim()}` : "");

/** The Ask tab's welcome line, above the suggested questions. */
export function askIntro(v: Voice): string {
  if (v.tone === "hype") return `Let's go${who(v)}! 🔥 Ask me about your spending or any company's annual report. Try one of these:`;
  return `Hi${who(v)}! Ask me about your spending, or about a company's annual report. Try one of these:`;
}

export function greeting(v: Voice, hour: number): string {
  const part = hour < 12 ? "Morning" : hour < 18 ? "Afternoon" : "Evening";
  return v.tone === "hype" ? `${part}${who(v)}! Let's make today count 🔥` : `${part}${who(v)}.`;
}

export type Health = "none" | "good" | "warning" | "critical";

/** Where this month stands, as a status the UI shows with icon + label (never colour alone). */
export function health(summary: Summary, forecast: Forecast | null): Health {
  if (!summary.budget) return "none";
  if (summary.spent > summary.budget) return "critical";
  if (forecast && forecast.forecast_total > summary.budget) return "warning";
  return "good";
}

export const HEALTH_LABEL: Record<Health, string> = {
  none: "No budget set",
  good: "On track",
  warning: "Heading over",
  critical: "Over budget",
};

/** The one-sentence answer to "am I okay this month?". */
export function verdict(v: Voice, summary: Summary, forecast: Forecast | null, perDay: number | null): string {
  const h = health(summary, forecast);
  const hype = v.tone === "hype";
  switch (h) {
    case "none":
      return "Set a monthly budget and I'll tell you if you're on track.";
    case "good":
      return hype
        ? `You're crushing it: keep under ${sgd(perDay ?? 0)} a day and you finish under budget! 🔥`
        : `You're on track. Up to ${sgd(perDay ?? 0)} a day keeps you inside your budget.`;
    case "warning": {
      const over = (forecast?.forecast_total ?? 0) - (summary.budget ?? 0);
      return hype
        ? `Comeback time! You're heading about ${sgd(over)} over, so trim to ${sgd(perDay ?? 0)} a day and you'll make it.`
        : `Heads up: at this pace you'll end about ${sgd(over)} over budget. ${sgd(perDay ?? 0)} a day gets you back.`;
    }
    case "critical": {
      const over = summary.spent - (summary.budget ?? 0);
      return hype
        ? `You're ${sgd(over)} past the budget, but next month is a fresh start. Let's keep the rest of this one light!`
        : `You've gone ${sgd(over)} over this month's budget. Maybe keep the rest of the month light?`;
    }
  }
}

export function savedText(v: Voice, amount: number, merchant: string, category: string): string {
  const base = `Saved: ${sgd(amount)} at ${merchant}, filed under ${category}.`;
  return v.tone === "hype" ? `${base} Nice tracking! ✨` : base;
}

export const AI_LIMIT_TEXT =
  "Our free AI is out of breath for today (daily limit). Logging still works though.";

export const AI_DOWN_TEXT =
  "I can't reach the AI right now. Your spending log still works, so try me again in a bit.";
