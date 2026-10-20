# Prompts for drafting evaluation questions with ChatGPT

Paste each prompt into ChatGPT Edu as written. ChatGPT's output is a **draft**: the checks under
each prompt are what make the evaluation trustworthy, so do not skip them.

---

## Module 4: 45 budget-chat questions

Copy everything in the box. Save ChatGPT's output by **adding** it to
`services/chat-agent/eval/questions.jsonl` (keep the 5 existing lines q01 to q05).

```text
I am building an evaluation set for a budgeting chatbot that answers questions by writing SQL.
Write 45 new test questions, each with the SQL that computes the correct answer.

THE DATA
One synthetic user's spending in Singapore from 2026-04-01 to 2026-10-13. Treat Tuesday 2026-10-13
as "today" for every question.

PostgreSQL tables (already limited to this one user: never mention or filter by user_id):
  transactions(txn_id, txn_date DATE, amount NUMERIC -- SGD spent, always positive,
               merchant TEXT, category TEXT, raw_text TEXT)
  budgets(month DATE -- first day of the month, category TEXT -- NULL means the overall budget,
          amount NUMERIC)

Categories, exact spelling: Food & Drink, Groceries, Transport, Shopping, Entertainment,
Bills & Utilities, Health, Education, Travel, Others

Merchants, exact spelling, by category:
  Food & Drink: Kopitiam, Koufu, Chagee, McDonald's, Ya Kun Kaya Toast, Starbucks, Saizeriya
  Groceries: FairPrice, Sheng Siong, Cold Storage
  Transport: Grab, Gojek, SimplyGo MRT
  Shopping: Shopee, Lazada, Uniqlo, Daiso, Apple Store
  Entertainment: Golden Village, Teo Heng KTV, Spotify, Netflix
  Bills & Utilities: Singtel
  Health: Guardian, Watsons, Polyclinic
  Education: Popular Bookstore, NUS Co-op
  Travel: Scoot, Agoda

Budgets, every month from April to October 2026: overall 900, Food & Drink 350,
Transport 120, Shopping 150.

DATE RULES
Weeks run Monday to Sunday. "Last week" = 2026-10-05 to 2026-10-11. "This week" = 2026-10-12 to
2026-10-13. "This month" = 2026-10-01 to 2026-10-13. "Last month" = September 2026.
In SQL, write dates as literals like DATE '2026-09-01'. Never use CURRENT_DATE or NOW().

RULES FOR EACH QUESTION
- Phrase it the way a university student would type it: casual, sometimes short, occasionally
  with Singlish ("how much i spend on makan last week").
- It has exactly one correct answer, computed by ONE PostgreSQL SELECT statement. The answer is
  the first column of the first row.
- answer_type is "number" (an amount or a count; round money with ROUND(..., 2)) or "text"
  (a single category or merchant name, spelled exactly as above).
- For "text" questions, avoid possible ties (e.g. "which merchant did I visit most" can tie);
  ask about amounts rather than counts where you can.
- Nothing about the future, forecasts, predictions or other people.
- Mix: 10 totals over a period, 8 counts, 6 max/min/average, 8 comparisons with a text answer
  (category or merchant), 7 budget questions, 6 month-by-month trend questions.

OUTPUT
JSON Lines only, no commentary, one object per line, ids q06 to q50, exactly these keys:
{"id": "q06", "question": "...", "gold_sql": "...", "answer_type": "number", "asked_on": "2026-10-13"}

Two existing examples of the style:
{"id": "q01", "question": "How much did I spend on food last week?", "gold_sql": "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE category = 'Food & Drink' AND txn_date BETWEEN DATE '2026-10-05' AND DATE '2026-10-11'", "answer_type": "number", "asked_on": "2026-10-13"}
{"id": "q04", "question": "Which category did I spend the most on last month?", "gold_sql": "SELECT category FROM transactions WHERE txn_date BETWEEN DATE '2026-09-01' AND DATE '2026-09-30' GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1", "answer_type": "text", "asked_on": "2026-10-13"}
```

**Checks after pasting the output:** tell Claude Code "check the Module 4 questions". It will run
every `gold_sql` against the database (no AI requests used) and flag SQL that fails, returns
nothing, or has a tie.

---

## Module 5: about 30 SGX annual-report questions

Use one ChatGPT conversation per company and **attach that company's annual report PDF**.
Proposed companies (change if the group prefers others):

| Company | SGX code | Report | doc_id |
|---|---|---|---|
| DBS Group Holdings | D05 | Annual Report 2025 | `sgx/D05/2025` |
| Singapore Airlines | C6L | Annual Report FY2025/26 | `sgx/C6L/2026` |
| Singtel | Z74 | Annual Report FY2026 | `sgx/Z74/2026` |
| CapitaLand Integrated Commercial Trust | C38U | Annual Report 2025 | `sgx/C38U/2025` |
| Sheng Siong Group | OV8 | Annual Report 2025 | `sgx/OV8/2025` |

Fill in the three `<...>` placeholders, then paste:

```text
I've attached <COMPANY NAME>'s annual report for <YEAR>. I'm building an evaluation set for a system
that answers questions about annual reports and cites the pages it used. Write 6 questions about
this report.

REQUIREMENTS
- Every answer must be stated explicitly in the report. No calculations that combine numbers from
  different places, no opinions, no investment advice.
- Mix: 3 numeric facts (e.g. net profit, revenue, dividend per share, total assets, a key ratio),
  2 narrative facts (e.g. number of employees, a named strategic priority, a named key risk), and
  1 question whose answer is a short explanation the report gives (e.g. what it says drove a
  change in profit).
- Each question names the company and the year, e.g. "What was DBS Group's net profit for 2025?"
- For each question give the answer exactly as the report states it, with units and currency
  (e.g. "S$11.4 billion"), the sentence or table row that contains it, and the page number(s).
- PAGE NUMBERS: use the page number a PDF viewer shows, where page 1 is the cover. Do NOT use the
  number printed on the page itself.

OUTPUT
JSON Lines only, no commentary, exactly these keys:
{"id": "sgx_<CODE>_1", "doc_id": "<DOC_ID>", "question": "...", "gold_answer": "...", "answer_type": "number", "gold_pages": [12], "evidence": "exact quote from the report"}
answer_type is "number" for numeric facts and "text" otherwise.
```

**Checks (essential):** ChatGPT often gets page numbers wrong. For every question, open the PDF,
go to the page it gave, and confirm the evidence quote is really there. Fix the page or the answer
if not. Wrong gold data makes the evaluation meaningless, and citation accuracy is one of Module 5's
headline results. Save the checked lines in `services/report-reader/eval/sgx_questions.jsonl`
(replace the 3 placeholder lines).

**FinanceBench** needs no drafting: its 150 questions, answers and evidence pages are published
(github.com/patronus-ai/financebench).
