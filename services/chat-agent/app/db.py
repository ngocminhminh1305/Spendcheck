"""Database access for the chat agent.

Every query the agent runs goes through `user_scoped_readonly`, which gives three layers of
protection on top of the SQL validation in tools/sql_tool.py:
  1. the connection logs in as chat_agent_ro, which only has SELECT grants;
  2. the transaction is READ ONLY, so even a mis-validated write statement fails;
  3. app.user_id is set, so row-level security hides other users' rows (db/init/002_schema.sql).
"""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool


def create_pool(database_url: str) -> ConnectionPool:
    """Small pool; the agent makes at most a few queries per question.

    open=True starts connecting in the background, so the service still starts if Postgres is
    not up yet. /ready reports when the database is reachable.
    """
    return ConnectionPool(database_url, min_size=1, max_size=5, open=True, kwargs={"autocommit": True})


@contextmanager
def user_scoped_readonly(pool: ConnectionPool, user_id: str, timeout_ms: int) -> Iterator[psycopg.Connection]:
    """Yield a connection inside a read-only transaction that can only see `user_id`'s rows."""
    with pool.connection() as conn, conn.transaction():
        conn.execute("SET TRANSACTION READ ONLY")
        # set_config(..., is_local=true) lasts only until this transaction ends, so a pooled
        # connection never leaks one user's ID into the next request.
        conn.execute("SELECT set_config('app.user_id', %s, true)", (user_id,))
        conn.execute("SELECT set_config('statement_timeout', %s, true)", (str(timeout_ms),))
        yield conn


def ping(pool: ConnectionPool) -> bool:
    """True if Postgres answers within 2 seconds (used by the /ready probe)."""
    try:
        with pool.connection(timeout=2) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False
