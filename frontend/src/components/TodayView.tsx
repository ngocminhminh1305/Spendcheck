// Today: greeting in your voice, log something, see "am I okay?" and your latest receipts.

import { ChevronRight } from "lucide-react";
import type { MonthData } from "../App";
import type { Prefs } from "../prefs";
import { greeting } from "../voice";
import CategoryList from "./CategoryList";
import QuickLog from "./QuickLog";
import TransactionList from "./TransactionList";
import Verdict from "./Verdict";

export default function TodayView({ prefs, data, categories, onChanged, onToast, onOpenMonth }: {
  prefs: Prefs; data: MonthData; categories: string[]; onChanged: () => void;
  onToast: (t: string) => void; onOpenMonth: () => void;
}) {
  return (
    <>
      <h1 className="hello">{greeting(prefs, new Date().getHours())}</h1>
      <div className="grid grid--today">
        <div className="stack">
          <QuickLog prefs={prefs} categories={categories} onSaved={onChanged} onToast={onToast} />
          <section className="card reveal today__receipts" aria-labelledby="recent-title">
            <h2 className="card__title" id="recent-title">Latest receipts</h2>
            <TransactionList transactions={data.transactions.slice(0, 8)} onChanged={onChanged} />
          </section>
        </div>
        <div className="stack">
          {data.summary && <Verdict prefs={prefs} summary={data.summary} forecast={data.forecast} />}
          {data.summary && (
            <section className="card reveal" aria-labelledby="where-title">
              <h2 className="card__title" id="where-title">Where it went</h2>
              <CategoryList summary={data.summary} limit={5} />
              <button className="btn btn--ghost" style={{ marginTop: 14 }} onClick={onOpenMonth}>
                The full month <ChevronRight size={16} aria-hidden />
              </button>
            </section>
          )}
        </div>
      </div>
    </>
  );
}
