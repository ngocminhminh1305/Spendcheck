// Personalisation answers that only shape the website and the assistant's voice.
// Budgets (questions 3 and 4) are NOT here: they live in the database, because Modules 3 and 4
// use them. Everything here is saved in this browser only.

import type { Persona, Tone } from "./api";

export type Theme = "system" | "light" | "dark";

export interface Prefs {
  name: string;          // Q1  what should I call you?
  tone: Tone;            // Q2  how should I talk to you?
  companies: string[];   // Q5  names of companies you're curious about
  theme: Theme;          // Q6  light or dark?
  greeted: boolean;      // the Ask greeting has been answered or skipped
}

export const DEFAULT_PREFS: Prefs = {
  name: "", tone: "chill", companies: [], theme: "system", greeted: false,
};

const KEY = "spendcheck.prefs.v1";

export function loadPrefs(): Prefs {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? { ...DEFAULT_PREFS, ...JSON.parse(raw) } : DEFAULT_PREFS;
  } catch {
    return DEFAULT_PREFS;   // private window or blocked storage: run with defaults
  }
}

export function savePrefs(prefs: Prefs): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(prefs));
  } catch {
    /* storage unavailable: the choices still apply until the page is closed */
  }
}

export function applyTheme(theme: Theme): void {
  if (theme === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
}

/** What Module 4 receives with every chat message. */
export function personaOf(prefs: Prefs): Persona {
  return { name: prefs.name.trim() || null, tone: prefs.tone };
}

/** Same rule as Module 4, so the form can say no before the server does. */
export function validName(name: string): boolean {
  const n = name.trim();
  return n === "" || (n.length <= 30 && /^\p{L}[\p{L} '-]*$/u.test(n));
}
