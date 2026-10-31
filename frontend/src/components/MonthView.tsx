// Month, ordered the way a student thinks: am I okay -> why -> how it built up -> where it went
// -> what to do next.

import { MessageCircle, SlidersHorizontal } from "lucide-react";
import type { MonthData } from "../App";
import { monthName } from "../format";
import type { Prefs } from "../prefs";
import CategoryList from "./CategoryList";
import SpendChart from "./SpendChart";
import Verdict from "./Verdict";

export default function MonthView({ prefs, data, onAsk, onEditBudgets }: {
  prefs: Prefs; data: MonthData; onAsk: (q: string) => void; onEditBudgets: () => void;
}) {
  const { summary, forecast } = data;
  if (!summary) return <p className="empty">Loading your month…</p>;
  const over = summary.by_category.find((c) => c.budget !== null && c.amount > c.budget);

  return (
    <>
      <h1 className="hello">{monthName(summary.month)}</h1>
      <div className="stack">
        <Verdict prefs={prefs} summary={summary} forecast={forecast} showWhy />
        <section className="card reveal" aria-labelledby="build-title">
          <h2 className="card__title" id="build-title">How it built up</h2>
          <SpendChart summary={summary} forecast={forecast} />
        </section>
        <section className="card reveal" aria-labelledby="cats-title">
          <h2 className="card__title" id="cats-title">Where it went · {summary.transactions} receipt{summary.transactions === 1 ? "" : "s"}</h2>
          <CategoryList summary={summary} />
        </section>
        <section className="card reveal" aria-labelledby="next-title">
          <h2 className="card__title" id="next-title">What next</h2>
          <div className="chips">
            <button className="chip" onClick={() => onAsk("Can I afford a S$300 concert ticket this month?")}>
              <MessageCircle size={14} aria-hidden /> Can I afford a S$300 concert?
            </button>
            {over && (
              <button className="chip" onClick={() => onAsk(`Why is my ${over.category} spending so high this month?`)}>
                <MessageCircle size={14} aria-hidden /> Why is {over.category} so high?
              </button>
            )}
            <button className="chip" onClick={onEditBudgets}><SlidersHorizontal size={14} aria-hidden /> Set budgets</button>
          </div>
        </section>
      </div>
    </>
  );
}
