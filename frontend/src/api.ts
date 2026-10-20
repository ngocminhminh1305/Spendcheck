// Typed client for the gateway's /api routes (services/gateway/app/main.py).
// Every call goes to the same origin; Vite (dev) or nginx (production) forwards it to the gateway.

export type CategorySource = "lookup" | "model" | null;

export interface Draft {
  text: string;
  amount: number | null;
  merchant: string | null;
  date: string; // YYYY-MM-DD
  category: string | null;
  category_source: CategorySource;
  category_confidence: number | null;
  missing_fields: string[];
  needs_review: boolean;
  notes: string[];
}

export interface TransactionIn {
  date: string;
  amount: number;
  merchant: string;
  category: string;
  raw_text?: string | null;
  category_confidence?: number | null;
}

export interface Transaction extends TransactionIn {
  txn_id: number;
}

export interface Summary {
  month: string;
  spent: number;
  budget: number | null;
  transactions: number;
  by_category: { category: string; amount: number; budget: number | null }[];
  by_day: { date: string; amount: number }[];
}

export interface Forecast {
  as_of: string;
  month: string;
  method: string;
  spent_so_far: number;
  forecast_total: number;
  days_elapsed: number;
  days_in_month: number;
  months_of_history: number;
  one_off_spend: number;
  budget: number | null;
  risk: { alert: boolean; reference: number | null; source: "budget" | "usual_level" | null; reason: string };
}

export interface Status {
  gateway: boolean;
  database: boolean;
  modules: Record<string, boolean>;
  demo_user: string;
  today: string;
}

export interface ToolStep {
  tool: string;
  input: Record<string, unknown>;
  output_preview: string;
  is_error: boolean;
}

export interface Citation {
  doc_id: string;
  company: string;
  fiscal_year: number | null;
  page: number;
  quote: string;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export type Tone = "chill" | "hype";

/** How the assistant talks to you (Module 4); wording only, never the numbers. */
export interface Persona {
  name: string | null;
  tone: Tone;
}

export interface Budget {
  month: string;
  category: string | null;
  amount: number;
}

export interface ChatResponse {
  answer: string;
  mode: string;
  steps: ToolStep[];
  citations: Citation[];
  model: string | null;
}

export interface DocumentInfo {
  doc_id: string;
  corpus: string;
  company: string;
  ticker: string | null;
  fiscal_year: number | null;
  n_pages: number;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* not JSON: keep the status text */
    }
    throw new ApiError(response.status, detail);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

const post = <T>(path: string, body: unknown, method = "POST") =>
  request<T>(path, { method, body: JSON.stringify(body) });

export const api = {
  status: () => request<Status>("/status"),
  categories: () => request<string[]>("/categories"),
  parse: (text: string) => post<Draft>("/entries/parse", { text }),
  save: (t: TransactionIn) => post<Transaction>("/transactions", t),
  remove: (id: number) => request<void>(`/transactions/${id}`, { method: "DELETE" }),
  transactions: (limit = 12) => request<Transaction[]>(`/transactions?limit=${limit}`),
  summary: () => request<Summary>("/summary"),
  forecast: () => request<Forecast>("/forecast"),
  budgets: (month: string) => request<Budget[]>(`/budgets?month=${month}`),
  setBudget: (month: string, amount: number, category: string | null = null) =>
    post<Budget>("/budgets", { month, amount, category }, "PUT"),
  removeBudget: (month: string, category: string) =>
    request<void>(`/budgets?month=${month}&category=${encodeURIComponent(category)}`, { method: "DELETE" }),
  chat: (message: string, history: ChatTurn[], persona: Persona | null) =>
    post<ChatResponse>("/chat", { message, history, persona }),
  documents: () => request<DocumentInfo[]>("/reports/documents"),
};
