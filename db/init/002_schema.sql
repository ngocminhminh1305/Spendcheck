-- Spendcheck shared database schema.
-- STATUS: proposal. Agree it with the whole group before anyone builds on it (docs/CONTRACTS.md).
--
--   public.*   transaction data. Written by the gateway after Modules 1 and 2 have parsed and
--              categorised an entry; read by Module 3 (forecaster) and Module 4 (chat agent).
--   reports.*  SGX annual report text and embeddings. Used only by Module 5.

CREATE EXTENSION IF NOT EXISTS vector;   -- pgvector, for Module 5's similarity search


-- 1. Transaction data ---------------------------------------------------------------------------

CREATE TABLE users (
    user_id      TEXT PRIMARY KEY,
    display_name TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Budget categories: Module 2's nine labels (services/categoriser/app/settings.py, exact spelling)
-- plus 'Travel', which Module 2 never assigns but users (and the synthetic data) can choose.
CREATE TABLE categories (
    name TEXT PRIMARY KEY
);
INSERT INTO categories (name) VALUES
    ('Food & Drink'), ('Groceries'), ('Transport'), ('Shopping'), ('Entertainment'),
    ('Bills & Utilities'), ('Health'), ('Education'), ('Other'), ('Travel');

CREATE TABLE transactions (
    txn_id              BIGSERIAL PRIMARY KEY,
    user_id             TEXT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    txn_date            DATE NOT NULL,                              -- Module 1 (relative dates resolved)
    amount              NUMERIC(12, 2) NOT NULL CHECK (amount > 0), -- money spent, in SGD
    currency            CHAR(3) NOT NULL DEFAULT 'SGD',
    merchant            TEXT NOT NULL,                              -- Module 1, normalised
    category            TEXT NOT NULL REFERENCES categories (name), -- Module 2
    category_confidence REAL,                                       -- Module 2, 0 to 1
    raw_text            TEXT,                                       -- what the user typed
    source              TEXT NOT NULL DEFAULT 'chat',               -- chat | import | synthetic
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX transactions_user_date_idx ON transactions (user_id, txn_date);

-- Monthly budgets. category NULL means the overall budget for that month.
CREATE TABLE budgets (
    user_id  TEXT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    month    DATE NOT NULL CHECK (EXTRACT(DAY FROM month) = 1),  -- first day of the month
    category TEXT REFERENCES categories (name),
    amount   NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    UNIQUE NULLS NOT DISTINCT (user_id, month, category)
);

GRANT USAGE ON SCHEMA public TO spendcheck_app, chat_agent_ro;
GRANT SELECT, INSERT, UPDATE, DELETE ON users, transactions, budgets TO spendcheck_app;
GRANT USAGE ON SEQUENCE transactions_txn_id_seq TO spendcheck_app;
GRANT SELECT ON categories TO spendcheck_app, chat_agent_ro;
GRANT SELECT ON transactions, budgets TO chat_agent_ro;

-- Row-level security. Module 4 runs LLM-written SQL as chat_agent_ro after setting app.user_id
-- for the request. Postgres then hides every row belonging to other users, so even a wrong or
-- prompt-injected query cannot read someone else's spending.
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE budgets ENABLE ROW LEVEL SECURITY;

CREATE POLICY app_all_rows ON transactions TO spendcheck_app USING (true) WITH CHECK (true);
CREATE POLICY app_all_rows ON budgets      TO spendcheck_app USING (true) WITH CHECK (true);

CREATE POLICY agent_own_rows ON transactions FOR SELECT TO chat_agent_ro
    USING (user_id = current_setting('app.user_id', true));
CREATE POLICY agent_own_rows ON budgets FOR SELECT TO chat_agent_ro
    USING (user_id = current_setting('app.user_id', true));


-- 2. Annual reports (Module 5) ------------------------------------------------------------------

CREATE SCHEMA reports AUTHORIZATION report_reader;
SET ROLE report_reader;   -- so report_reader owns the tables below

CREATE TABLE reports.documents (
    doc_id      TEXT PRIMARY KEY,                -- e.g. 'sgx/D05/2024' or a FinanceBench doc_name
    corpus      TEXT NOT NULL CHECK (corpus IN ('sgx', 'financebench')),
    company     TEXT NOT NULL,
    ticker      TEXT,
    fiscal_year INT,
    source_uri  TEXT NOT NULL,                   -- where the PDF lives, e.g. s3://bucket/raw/...
    n_pages     INT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE reports.chunks (
    chunk_id   BIGSERIAL PRIMARY KEY,
    doc_id     TEXT NOT NULL REFERENCES reports.documents (doc_id) ON DELETE CASCADE,
    page       INT NOT NULL,                     -- 1-based, as a PDF viewer numbers pages
    chunk_type TEXT NOT NULL CHECK (chunk_type IN ('text', 'table')),
    content    TEXT NOT NULL,
    embedding  vector(384) NOT NULL,             -- must equal EMBEDDING_DIM (bge-small-en-v1.5 = 384)
    tsv        tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);
CREATE INDEX chunks_embedding_idx ON reports.chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunks_tsv_idx       ON reports.chunks USING gin (tsv);
CREATE INDEX chunks_doc_page_idx  ON reports.chunks (doc_id, page);

RESET ROLE;
