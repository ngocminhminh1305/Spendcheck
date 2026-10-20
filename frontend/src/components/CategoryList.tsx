// Where the money went: one bar per category (one series, one colour), with a tick at the
// category's budget when the user watches it. Over-budget rows say so in words with an icon.

import { CircleAlert } from "lucide-react";
import type { Summary } from "../api";
import { codeFor, sgd, sgdWhole } from "../format";

export default function CategoryList({ summary, limit }: { summary: Summary; limit?: number }) {
  const rows = [...summary.by_category].sort((a, b) => (b.budget ? 1 : 0) - (a.budget ? 1 : 0) || b.amount - a.amount);
  const shown = limit ? rows.slice(0, limit) : rows;
  const scale = Math.max(1, ...rows.map((r) => Math.max(r.amount, r.budget ?? 0)));

  if (shown.length === 0) return <p className="empty">No spending this month yet.</p>;
  return (
    <ul className="cats">
      {shown.map((r) => {
        const over = r.budget !== null && r.amount > r.budget;
        const share = summary.spent ? Math.round((r.amount / summary.spent) * 100) : 0;
        return (
          <li key={r.category} className={`cat${r.budget ? " cat--watched" : ""}`}
              title={`${r.category}: ${sgd(r.amount)} (${share}% of this month)${r.budget ? `, budget ${sgd(r.budget)}` : ""}`}>
            <div className="cat__top">
              <span className="code" aria-hidden>{codeFor(r.category)}</span>
              <span className="cat__name">{r.category}</span>
              <span className="cat__amt">{sgd(r.amount)}{r.budget ? <small> / {sgdWhole(r.budget)}</small> : null}</span>
            </div>
            <div className="cat__track" aria-hidden>
              <div className="cat__bar" style={{ width: `${(r.amount / scale) * 100}%` }} />
              {r.budget ? <div className="cat__limit" style={{ left: `calc(${(r.budget / scale) * 100}% - 1px)` }} /> : null}
            </div>
            {over && (
              <span className="status status--critical" style={{ fontSize: 12 }}>
                <CircleAlert size={14} aria-hidden /> Over by {sgd(r.amount - (r.budget ?? 0))}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
