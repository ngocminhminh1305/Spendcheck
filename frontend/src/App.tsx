// App shell: the signage band (wordmark, live module status, navigation), data loading, and the
// three screens of the journey: Today (log + "am I okay?"), Month (why + where), Ask (one chat).

import { useCallback, useEffect, useState } from "react";
import { CalendarDays, Home, MessageCircle, Settings } from "lucide-react";
import { api, type Budget, type DocumentInfo, type Forecast, type Status, type Summary, type Transaction } from "./api";
import { applyTheme, loadPrefs, savePrefs, type Prefs } from "./prefs";
import AskView, { type Message } from "./components/AskView";
import MonthView from "./components/MonthView";
import SettingsSheet from "./components/SettingsSheet";
import StatusStrip from "./components/StatusStrip";
import TodayView from "./components/TodayView";

export type View = "today" | "month" | "ask";

export interface MonthData {
  summary: Summary | null;
  forecast: Forecast | null;
  budgets: Budget[];
  transactions: Transaction[];
}

const TABS: { id: View; label: string; Icon: typeof Home }[] = [
  { id: "today", label: "Today", Icon: Home },
  { id: "month", label: "Month", Icon: CalendarDays },
  { id: "ask", label: "Ask", Icon: MessageCircle },
];

const initialView = (): View => {
  const v = window.location.hash.slice(1);
  return v === "month" || v === "ask" ? v : "today";
};

export default function App() {
  const [prefs, setPrefs] = useState<Prefs>(loadPrefs);
  const [view, setView] = useState<View>(initialView);
  const [status, setStatus] = useState<Status | null>(null);
  const [data, setData] = useState<MonthData>({ summary: null, forecast: null, budgets: [], transactions: [] });
  const [loadError, setLoadError] = useState<string | null>(null);
  const [categories, setCategories] = useState<string[]>([]);
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [askDraft, setAskDraft] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => { applyTheme(prefs.theme); savePrefs(prefs); }, [prefs]);
  useEffect(() => { window.history.replaceState(null, "", `#${view}`); }, [view]);
  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 4200);
    return () => window.clearTimeout(t);
  }, [toast]);

  const month = status?.today.slice(0, 7) ?? new Date().toISOString().slice(0, 7);

  const refresh = useCallback(async () => {
    const [summary, forecast, transactions] = await Promise.allSettled([api.summary(), api.forecast(), api.transactions(20)]);
    const m = summary.status === "fulfilled" ? summary.value.month : month;
    const budgets = await api.budgets(m).catch(() => [] as Budget[]);
    setData({
      summary: summary.status === "fulfilled" ? summary.value : null,
      forecast: forecast.status === "fulfilled" ? forecast.value : null,   // forecaster down: the rest still works
      budgets,
      transactions: transactions.status === "fulfilled" ? transactions.value : [],
    });
    setLoadError(summary.status === "rejected" ? "Can't reach Spendcheck's server. Is the gateway running?" : null);
  }, [month]);

  useEffect(() => {
    refresh();
    api.categories().then(setCategories).catch(() => setCategories([]));
    api.documents().then(setDocs).catch(() => setDocs([]));
    const poll = () => api.status().then(setStatus).catch(() => setStatus(null));
    poll();
    const id = window.setInterval(poll, 30_000);
    return () => window.clearInterval(id);
  }, [refresh]);

  const ask = (text: string) => { setAskDraft(text); setView("ask"); };

  const nav = (
    <nav className="tabs" aria-label="Screens">
      {TABS.map(({ id, label, Icon }) => (
        <button key={id} className="tab" aria-current={view === id ? "page" : undefined} onClick={() => setView(id)}>
          <Icon size={18} aria-hidden /> {label}
        </button>
      ))}
    </nav>
  );

  return (
    <>
      <header className="band">
        <div className="band__inner">
          <div className="wordmark">Spendcheck</div>
          {nav}
          <StatusStrip status={status} />
          <button className="iconbtn" onClick={() => setSettingsOpen(true)} aria-label="Make it yours: personalise Spendcheck">
            <Settings size={18} />
          </button>
        </div>
      </header>

      <main>
        {loadError && <p className="error" role="alert">{loadError}</p>}
        {view === "today" && (
          <TodayView prefs={prefs} data={data} categories={categories} onChanged={refresh}
                     onToast={setToast} onOpenMonth={() => setView("month")} />
        )}
        {view === "month" && (
          <MonthView prefs={prefs} data={data} onAsk={ask} onEditBudgets={() => setSettingsOpen(true)} />
        )}
        {view === "ask" && (
          <AskView prefs={prefs} setPrefs={setPrefs} docs={docs} messages={messages} setMessages={setMessages}
                   draft={askDraft} setDraft={setAskDraft} />
        )}
      </main>

      <div className="bottomnav band">{nav}</div>

      {settingsOpen && (
        <SettingsSheet prefs={prefs} categories={categories} docs={docs} budgets={data.budgets} month={month}
                       onClose={() => setSettingsOpen(false)}
                       onSaved={(next, note) => { setPrefs(next); setSettingsOpen(false); refresh(); setToast(note); }} />
      )}
      {toast && <div className="toast" role="status">{toast}</div>}
    </>
  );
}
