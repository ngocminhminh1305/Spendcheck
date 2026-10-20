// Type it like you'd text a friend -> Module 1 reads it, Module 2 files it -> a receipt you check
// and save. Nothing reaches the database until you press Save.

import { useState, type FormEvent } from "react";
import { Check, Info, X } from "lucide-react";
import { api, ApiError, type Draft } from "../api";
import { codeFor } from "../format";
import type { Prefs } from "../prefs";
import { savedText } from "../voice";

export default function QuickLog({ prefs, categories, onSaved, onToast }: {
  prefs: Prefs; categories: string[]; onSaved: () => void; onToast: (t: string) => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [form, setForm] = useState({ amount: "", merchant: "", date: "", category: "" });

  async function read(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true); setError(null);
    try {
      const d = await api.parse(text.trim());
      setDraft(d);
      setForm({ amount: d.amount?.toString() ?? "", merchant: d.merchant ?? "", date: d.date, category: d.category ?? "" });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't read that entry.");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!draft) return;
    setBusy(true); setError(null);
    try {
      const amount = Number(form.amount);
      await api.save({ amount, merchant: form.merchant.trim(), date: form.date, category: form.category,
                       raw_text: draft.text, category_confidence: draft.category_confidence });
      onToast(savedText(prefs, amount, form.merchant.trim(), form.category));
      setDraft(null); setText(""); onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save that.");
    } finally {
      setBusy(false);
    }
  }

  const amountOk = Number(form.amount) > 0;
  const ready = amountOk && form.merchant.trim() !== "" && form.category !== "" && form.date !== "";
  const guessed = draft?.category_source === "model" && form.category === draft.category;

  return (
    <section className="card reveal" aria-labelledby="log-title">
      <h2 className="card__title" id="log-title">What did you spend?</h2>
      <form className="logbox" onSubmit={read}>
        <label htmlFor="entry" className="visually-hidden">Spending entry</label>
        <input id="entry" value={text} onChange={(e) => setText(e.target.value)} autoComplete="off"
               placeholder="chagee 4.25 yesterday" maxLength={500} />
        <button className="btn" disabled={busy || !text.trim()}>{busy && !draft ? "Reading…" : "Log"}</button>
      </form>
      <p className="hint">Type it like a text: amount, place, and when. "grab to school 14.60" works too.</p>
      {error && <p className="error" role="alert">{error}</p>}

      {draft && (
        <div className="receipt receipt--printing" style={{ marginTop: 14 }} aria-live="polite">
          <div className="receipt__head"><span>Spendcheck</span><span>{draft.needs_review ? "Please check" : "Read correctly ✓"}</span></div>
          <hr className="receipt__rule" />
          <div className={`receipt__row${!amountOk ? " receipt__row--missing" : ""}`}>
            <label htmlFor="r-amt">Amount S$</label>
            <input id="r-amt" inputMode="decimal" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
          </div>
          <div className={`receipt__row${!form.merchant.trim() ? " receipt__row--missing" : ""}`}>
            <label htmlFor="r-mer">Merchant</label>
            <input id="r-mer" value={form.merchant} maxLength={120} onChange={(e) => setForm({ ...form, merchant: e.target.value })} />
          </div>
          <div className="receipt__row">
            <label htmlFor="r-date">Date</label>
            <input id="r-date" type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} />
          </div>
          <div className={`receipt__row${!form.category ? " receipt__row--missing" : ""}`}>
            <label htmlFor="r-cat">Category</label>
            <div style={{ display: "flex", gap: 8, alignItems: "center", minWidth: 0 }}>
              <span className={`code${form.category ? "" : " code--unknown"}`} aria-hidden>{codeFor(form.category || null)}</span>
              <select id="r-cat" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                <option value="">Choose…</option>
                {categories.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              {draft.category_source === "lookup" && form.category === draft.category && <span className="tag">known merchant</span>}
              {guessed && <span className="tag tag--check">best guess {Math.round((draft.category_confidence ?? 0) * 100)}%</span>}
            </div>
          </div>
          {draft.notes.length > 0 && (
            <ul className="receipt__notes">
              {draft.notes.map((n) => <li key={n}><Info size={14} aria-hidden style={{ flex: "none", marginTop: 3 }} /> {n}</li>)}
            </ul>
          )}
          <div className="receipt__actions">
            <button className="btn btn--signal" onClick={save} disabled={!ready || busy}><Check size={16} aria-hidden /> Save</button>
            <button className="btn btn--ghost" onClick={() => setDraft(null)} disabled={busy}><X size={16} aria-hidden /> Discard</button>
          </div>
        </div>
      )}
    </section>
  );
}
