// "Make it yours": the six personalisation questions. 1, 2, 5, 6 are saved in this browser;
// 3 and 4 are budgets in the database, because Modules 3 and 4 use them.

import { useState } from "react";
import { X } from "lucide-react";
import { api, type Budget, type DocumentInfo, type Tone } from "../api";
import { codeFor, sgd } from "../format";
import { validName, type Prefs, type Theme } from "../prefs";
import { onePerCompany, TONES } from "./AskView";

const MAX_WATCHED = 3;
const THEMES: { id: Theme; label: string }[] = [
  { id: "light", label: "Light" }, { id: "dark", label: "Dark" }, { id: "system", label: "Follow my phone" },
];

export default function SettingsSheet({ prefs, categories, docs, budgets, month, onClose, onSaved }: {
  prefs: Prefs; categories: string[]; docs: DocumentInfo[]; budgets: Budget[]; month: string;
  onClose: () => void; onSaved: (prefs: Prefs, note: string) => void;
}) {
  const overall = budgets.find((b) => b.category === null)?.amount ?? null;
  const watchedBefore = Object.fromEntries(budgets.filter((b) => b.category).map((b) => [b.category as string, b.amount]));

  const [name, setName] = useState(prefs.name);
  const [tone, setTone] = useState<Tone>(prefs.tone);
  const [budget, setBudget] = useState(overall?.toString() ?? "");
  const [watched, setWatched] = useState<Record<string, string>>(
    Object.fromEntries(Object.entries(watchedBefore).map(([c, a]) => [c, String(a)])));
  const [companies, setCompanies] = useState<string[]>(prefs.companies);
  const [theme, setTheme] = useState<Theme>(prefs.theme);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const nameOk = validName(name);
  const budgetOk = budget === "" || Number(budget) > 0;
  const watchedOk = Object.values(watched).every((a) => Number(a) > 0);

  const toggleWatch = (c: string) => setWatched((w) => {
    const next = { ...w };
    if (c in next) delete next[c];
    else if (Object.keys(next).length < MAX_WATCHED) next[c] = watchedBefore[c]?.toString() ?? "";
    return next;
  });
  const toggleCompany = (name: string) => setCompanies((cs) => (cs.includes(name) ? cs.filter((c) => c !== name) : [...cs, name]));

  async function save() {
    setSaving(true); setError(null);
    try {
      if (budget !== "" && Number(budget) !== overall) await api.setBudget(month, Number(budget));
      for (const [c, a] of Object.entries(watched)) {
        if (Number(a) !== watchedBefore[c]) await api.setBudget(month, Number(a), c);
      }
      for (const c of Object.keys(watchedBefore)) if (!(c in watched)) await api.removeBudget(month, c);
      onSaved({ ...prefs, name: name.trim(), tone, companies, theme, greeted: true },
              name.trim() ? `Got it, ${name.trim()}. Spendcheck is all yours now.` : "Saved. Spendcheck is all yours now.");
    } catch {
      setError("Couldn't save your budgets. Is the server running?");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="sheet-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <aside className="sheet" role="dialog" aria-modal="true" aria-labelledby="sheet-title">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 id="sheet-title">Make it yours</h2>
          <button className="btn btn--ghost" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </div>

        <div className="q">
          <label className="q__label" htmlFor="s-name">1. What should I call you?</label>
          <input id="s-name" type="text" value={name} maxLength={30} onChange={(e) => setName(e.target.value)} placeholder="e.g. Bo" />
          {!nameOk && <span className="q__err">Just a name please: letters, spaces and hyphens, up to 30.</span>}
        </div>

        <div className="q">
          <span className="q__label">2. How should I talk to you?</span>
          <div className="chips">{TONES.map((t) => <button key={t.id} className="chip" aria-pressed={tone === t.id} onClick={() => setTone(t.id)}>{t.label}</button>)}</div>
        </div>

        <div className="q">
          <label className="q__label" htmlFor="s-budget">3. What's your monthly spending budget? <span>S$</span></label>
          <input id="s-budget" type="number" min={1} step="10" value={budget} onChange={(e) => setBudget(e.target.value)} placeholder="e.g. 900" />
          {!budgetOk && <span className="q__err">A budget has to be more than S$0.</span>}
        </div>

        <div className="q">
          <span className="q__label">4. Which categories do you want to watch? <span>up to {MAX_WATCHED}, with a monthly limit</span></span>
          {categories.map((c) => {
            const on = c in watched;
            const full = !on && Object.keys(watched).length >= MAX_WATCHED;
            return (
              <div className="watch" key={c}>
                <input type="checkbox" id={`w-${c}`} checked={on} disabled={full} onChange={() => toggleWatch(c)} />
                <label htmlFor={`w-${c}`}><span className="code" aria-hidden>{codeFor(c)}</span> {c}</label>
                {on ? (
                  <input type="number" min={1} step="10" aria-label={`${c} monthly limit in S$`} value={watched[c]}
                         onChange={(e) => setWatched({ ...watched, [c]: e.target.value })} placeholder="S$" />
                ) : <span className="hint" style={{ margin: 0 }}>{watchedBefore[c] ? `was ${sgd(watchedBefore[c])}` : ""}</span>}
              </div>
            );
          })}
        </div>

        <div className="q">
          <span className="q__label">5. Any companies you're curious about?</span>
          {docs.length === 0 ? <span className="hint">No annual reports loaded yet.</span> : (
            <div className="chips">
              {onePerCompany(docs).map((d) => (
                <button key={d.company} className="chip" aria-pressed={companies.includes(d.company)} onClick={() => toggleCompany(d.company)}>
                  {d.company}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="q">
          <span className="q__label">6. Light or dark?</span>
          <div className="chips">{THEMES.map((t) => <button key={t.id} className="chip" aria-pressed={theme === t.id} onClick={() => setTheme(t.id)}>{t.label}</button>)}</div>
        </div>

        {error && <p className="error" role="alert">{error}</p>}
        <button className="btn btn--signal" onClick={save} disabled={saving || !nameOk || !budgetOk || !watchedOk}>
          {saving ? "Saving…" : "Save"}
        </button>
      </aside>
    </div>
  );
}
