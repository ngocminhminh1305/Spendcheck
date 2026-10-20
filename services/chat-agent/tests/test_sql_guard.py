"""Unit tests for validate_sql, the first safety layer for LLM-written SQL.

Run inside Docker (no database or LLM needed):
    docker compose run --rm --no-deps chat-eval python -m unittest discover -s tests -v
"""

import unittest

from app.tools.sql_tool import UnsafeSQLError, validate_sql

LIMIT = 200


class AllowedQueries(unittest.TestCase):
    def assert_allowed(self, sql: str) -> str:
        try:
            return validate_sql(sql, LIMIT)
        except UnsafeSQLError as err:
            self.fail(f"rejected a safe query: {sql!r} ({err})")

    def test_simple_aggregate_gets_limit(self):
        out = self.assert_allowed("SELECT SUM(amount) FROM transactions WHERE category = 'Food & Drink'")
        self.assertIn("LIMIT 200", out)

    def test_existing_limit_is_kept(self):
        out = self.assert_allowed("SELECT merchant, amount FROM transactions ORDER BY amount DESC LIMIT 3")
        self.assertIn("LIMIT 3", out)
        self.assertNotIn("LIMIT 200", out)

    def test_group_by_date_functions_and_ilike(self):
        self.assert_allowed(
            "SELECT date_trunc('month', txn_date) AS m, category, SUM(amount) FROM transactions "
            "WHERE merchant ILIKE '%grab%' AND txn_date >= CURRENT_DATE - INTERVAL '30 days' "
            "GROUP BY 1, 2 ORDER BY 1"
        )

    def test_cte_names_are_allowed(self):
        self.assert_allowed(
            "WITH food AS (SELECT * FROM transactions WHERE category = 'Food & Drink') "
            "SELECT COUNT(*) FROM food"
        )

    def test_join_with_budgets_and_subquery(self):
        self.assert_allowed(
            "SELECT b.amount - (SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE txn_date >= '2026-10-01') "
            "FROM budgets b WHERE b.month = '2026-10-01' AND b.category IS NULL"
        )

    def test_union_and_public_schema(self):
        self.assert_allowed("SELECT name FROM public.categories UNION SELECT category FROM transactions")

    def test_generate_series_table_function(self):
        self.assert_allowed(
            "SELECT d::date, COALESCE(SUM(t.amount), 0) FROM generate_series('2026-10-01'::date, '2026-10-07'::date, "
            "INTERVAL '1 day') AS d LEFT JOIN transactions t ON t.txn_date = d::date GROUP BY 1"
        )


class RejectedQueries(unittest.TestCase):
    def assert_rejected(self, sql: str) -> None:
        with self.assertRaises(UnsafeSQLError, msg=f"accepted an unsafe query: {sql!r}"):
            validate_sql(sql, LIMIT)

    def test_writes_and_ddl(self):
        for sql in [
            "INSERT INTO transactions (user_id, amount) VALUES ('x', 1)",
            "UPDATE transactions SET amount = 0",
            "DELETE FROM transactions",
            "DROP TABLE transactions",
            "ALTER TABLE transactions ADD COLUMN x int",
            "CREATE TABLE x (id int)",
            "TRUNCATE transactions",
            "COPY transactions TO '/tmp/x.csv'",
        ]:
            self.assert_rejected(sql)

    def test_write_hidden_in_cte(self):
        self.assert_rejected("WITH gone AS (DELETE FROM transactions RETURNING *) SELECT COUNT(*) FROM gone")

    def test_select_into(self):
        self.assert_rejected("SELECT * INTO copy_of_txns FROM transactions")

    def test_multiple_statements(self):
        self.assert_rejected("SELECT 1 FROM transactions; DELETE FROM transactions")

    def test_other_tables_and_schemas(self):
        for sql in [
            "SELECT * FROM users",
            "SELECT * FROM reports.chunks",
            "SELECT * FROM pg_catalog.pg_roles",
            "SELECT * FROM pg_user",
            "SELECT table_name FROM information_schema.tables",
        ]:
            self.assert_rejected(sql)

    def test_switching_user_or_escaping_sandbox(self):
        for sql in [
            "SELECT set_config('app.user_id', 'bob', true), SUM(amount) FROM transactions",
            "SELECT current_setting('app.user_id') FROM transactions",
            "SELECT pg_sleep(10) FROM transactions",
            "SELECT query_to_xml('select * from users', true, true, '') FROM transactions",
            "SELECT pg_read_file('/etc/passwd')",
        ]:
            self.assert_rejected(sql)

    def test_not_sql(self):
        self.assert_rejected("how much did I spend?")
        self.assert_rejected("")


if __name__ == "__main__":
    unittest.main()
