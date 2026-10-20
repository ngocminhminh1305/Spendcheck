// Ask: one chat for your money AND for SGX companies (Module 4, which calls Modules 3 and 5).
// First visit: a built-in greeting asks your name and tone (no AI request spent).
// Every answer can show how it was worked out, and company answers cite report pages.

import { useEffect, useRef, useState, type FormEvent } from "react";
import ReactMarkdown from "react-markdown";
import { Database, FileText, Send, Sparkles, TrendingUp } from "lucide-react";
import { api, ApiError, type ChatResponse, type DocumentInfo, type Tone } from "../api";
import { personaOf, validName, type Prefs } from "../prefs";
import { AI_DOWN_TEXT, AI_LIMIT_TEXT, askIntro } from "../voice";

export interface Message {
  role: "user" | "assistant";
  content: string;
  reply?: ChatResponse;
  failed?: boolean;
}

export const TONES: { id: Tone; label: string }[] = [
  { id: "chill", label: "😌 Chill friend" },
  { id: "hype", label: "🔥 Hype me up" },
];

const STEP_TEXT: Record<string, { Icon: typeof Database; text: (input: Record<string, unknown>) => string }> = {
  run_sql: { Icon: Database, text: () => "Checked your transactions" },
  get_forecast: { Icon: TrendingUp, text: () => "Ran the month-end forecaster" },
  search_annual_reports: { Icon: FileText, text: (i) => `Read the annual reports: “${String(i.question ?? "")}”` },
};

/** One document per company: the longest, which is the annual report rather than a quarterly or earnings release. */
export function onePerCompany(docs: DocumentInfo[]): DocumentInfo[] {
  const best = new Map<string, DocumentInfo>();
  for (const d of docs) {
    const kept = best.get(d.company);
    if (!kept || d.n_pages > kept.n_pages) best.set(d.company, d);
  }
  return [...best.values()];
}

const COMPANY_QUESTIONS = [
  (c: string, y: string) => `How much revenue did ${c} make${y}?`,
  (c: string, y: string) => `What was ${c}'s net income${y}?`,
  (c: string, y: string) => `How much cash did ${c} make from operations${y}?`,
];

function suggestions(docs: DocumentInfo[], prefs: Prefs): string[] {
  const picked = onePerCompany(docs.filter((d) => prefs.companies.includes(d.company)));
  const companies = (picked.length ? picked : onePerCompany(docs).slice(0, 2)).slice(0, 3);
  return [
    "How much did I spend on food last week?",
    "Can I afford a S$300 concert ticket this month?",
    "Where did most of my money go this month?",
    ...companies.map((d, i) => COMPANY_QUESTIONS[i](d.company, d.fiscal_year ? ` in ${d.fiscal_year}` : "")),
  ];
}

function Greeting({ prefs, setPrefs }: { prefs: Prefs; setPrefs: (p: Prefs) => void }) {
  const [name, setName] = useState(prefs.name);
  const [tone, setTone] = useState<Tone>(prefs.tone);
  const ok = validName(name);
  return (
    <div className="msg msg--bot">
      <span className="from">Spendcheck</span>
      <div className="bubble">
        <p>Hey! I'm Spendcheck, your money buddy. I can check your spending, tell you if the month's going okay, and explain what's in a company's annual report.</p>
        <p>Before we start: what should I call you, and how should I talk to you?</p>
        <div className="q" style={{ marginTop: 10 }}>
          <label className="q__label" htmlFor="g-name">Your name <span>optional</span></label>
          <input id="g-name" type="text" value={name} maxLength={30} onChange={(e) => setName(e.target.value)} placeholder="e.g. Bo" />
          {!ok && <span className="q__err">Just a name please: letters, spaces and hyphens, up to 30.</span>}
        </div>
        <div className="q" style={{ marginTop: 10 }}>
          <span className="q__label">How should I talk to you?</span>
          <div className="chips">{TONES.map((t) => <button key={t.id} className="chip" aria-pressed={tone === t.id} onClick={() => setTone(t.id)}>{t.label}</button>)}</div>
        </div>
        <div className="receipt__actions">
          <button className="btn btn--signal" disabled={!ok} onClick={() => setPrefs({ ...prefs, name: name.trim(), tone, greeted: true })}>
            <Sparkles size={16} aria-hidden /> Let's go
          </button>
          <button className="btn btn--ghost" onClick={() => setPrefs({ ...prefs, greeted: true })}>Skip</button>
        </div>
      </div>
    </div>
  );
}

function Answer({ reply }: { reply: ChatResponse }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <>
      {reply.steps.length > 0 && (
        <details className="workings">
          <summary>How I worked it out ({reply.steps.length} step{reply.steps.length > 1 ? "s" : ""})</summary>
          <ol>
            {reply.steps.map((s, i) => {
              const meta = STEP_TEXT[s.tool] ?? { Icon: Database, text: () => s.tool };
              return (
                <li key={i}>
                  <meta.Icon size={13} aria-hidden /> {meta.text(s.input)}{s.is_error ? " (that try failed, so I adjusted)" : ""}
                  {s.tool === "run_sql" && typeof s.input.query === "string" && (
                    <pre style={{ whiteSpace: "pre-wrap", fontSize: 12, margin: "4px 0 0", fontFamily: "var(--mono)" }}>{s.input.query}</pre>
                  )}
                </li>
              );
            })}
          </ol>
        </details>
      )}
      {reply.citations.length > 0 && (
        <div className="cites" aria-label="Sources">
          {reply.citations.map((c, i) => (
            <button key={i} className="cite" aria-expanded={open === i} onClick={() => setOpen(open === i ? null : i)}>
              <b>{c.company}{c.fiscal_year ? ` FY${c.fiscal_year}` : ""} · p.{c.page}</b>
              {open === i && <span className="cite__quote">“{c.quote}”</span>}
            </button>
          ))}
        </div>
      )}
    </>
  );
}

export default function AskView({ prefs, setPrefs, docs, messages, setMessages, draft, setDraft }: {
  prefs: Prefs; setPrefs: (p: Prefs) => void; docs: DocumentInfo[];
  messages: Message[]; setMessages: (m: Message[] | ((m: Message[]) => Message[])) => void;
  draft: string; setDraft: (s: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages, busy]);
  useEffect(() => {
    if (!busy) return;
    setSeconds(0);
    const id = window.setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => window.clearInterval(id);
  }, [busy]);

  async function send(text: string) {
    const question = text.trim();
    if (!question || busy) return;
    const history = messages.filter((m) => !m.failed).slice(-10).map(({ role, content }) => ({ role, content }));
    setMessages((m) => [...m, { role: "user", content: question }]);
    setDraft(""); setBusy(true);
    try {
      const reply = await api.chat(question, history, personaOf(prefs));
      setMessages((m) => [...m, { role: "assistant", content: reply.answer, reply }]);
    } catch (err) {
      const text = err instanceof ApiError && err.status === 429 ? AI_LIMIT_TEXT : AI_DOWN_TEXT;
      setMessages((m) => [...m, { role: "assistant", content: text, failed: true }]);
    } finally {
      setBusy(false);
    }
  }

  const onSubmit = (e: FormEvent) => { e.preventDefault(); send(draft); };

  return (
    <div className="chat">
      <h1 className="hello">Ask Spendcheck</h1>
      <div className="msgs" aria-live="polite">
        {!prefs.greeted && <Greeting prefs={prefs} setPrefs={setPrefs} />}
        {prefs.greeted && messages.length === 0 && (
          <div className="msg msg--bot">
            <span className="from">Spendcheck</span>
            <div className="bubble">
              <p>{askIntro(prefs)}</p>
            </div>
            <div className="chips">{suggestions(docs, prefs).map((s) => <button key={s} className="chip" onClick={() => send(s)}>{s}</button>)}</div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg msg--${m.role === "user" ? "user" : "bot"}`}>
            {m.role === "assistant" && <span className="from">Spendcheck</span>}
            <div className="bubble">{m.role === "assistant" ? <ReactMarkdown>{m.content}</ReactMarkdown> : m.content}</div>
            {m.reply && <Answer reply={m.reply} />}
          </div>
        ))}
        {busy && <p className="typing">Spendcheck is checking… {seconds}s (the free AI takes 10 to 30 seconds)</p>}
        <div ref={endRef} />
      </div>
      <form className="composer" onSubmit={onSubmit}>
        <label htmlFor="ask" className="visually-hidden">Your question</label>
        <input id="ask" value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={2000} autoComplete="off"
               placeholder="Ask about your money or a company" />
        <button className="btn" disabled={busy || !draft.trim()} aria-label="Send"><Send size={16} aria-hidden /></button>
      </form>
      <p className="disclaimer">Company answers are facts from annual reports, not investment advice. Forecasts are estimates.</p>
    </div>
  );
}
