"""Unified storage schema for normalized marketplace transactions.

One row = one operation (sale, return, commission, logistics, storage,
promotion, penalty, ...) already normalized to a common set of columns so
WB and Ozon data can be aggregated together. Multi-tenant: every row is
scoped by client_id so one database can serve several clients' dashboards.
"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("MP_DB_PATH", "mp_dashboard.sqlite3"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL,
    marketplace TEXT NOT NULL CHECK(marketplace IN ('wb', 'ozon')),
    period_date TEXT NOT NULL,
    sku TEXT,
    product_name TEXT,
    quantity INTEGER NOT NULL DEFAULT 0,
    realization REAL NOT NULL DEFAULT 0,
    returns REAL NOT NULL DEFAULT 0,
    commission REAL NOT NULL DEFAULT 0,
    logistics REAL NOT NULL DEFAULT 0,
    storage REAL NOT NULL DEFAULT 0,
    promotion REAL NOT NULL DEFAULT 0,
    penalty REAL NOT NULL DEFAULT 0,
    other_deduction REAL NOT NULL DEFAULT 0,
    payout REAL NOT NULL DEFAULT 0,
    source_report TEXT NOT NULL,
    raw_ref TEXT NOT NULL,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(client_id, marketplace, raw_ref)
);

CREATE INDEX IF NOT EXISTS idx_transactions_client_period
    ON transactions(client_id, period_date);

CREATE INDEX IF NOT EXISTS idx_transactions_client_sku
    ON transactions(client_id, sku);

CREATE TABLE IF NOT EXISTS plan_targets (
    client_id TEXT NOT NULL,
    period TEXT NOT NULL,
    metric TEXT NOT NULL CHECK(metric IN ('net_revenue', 'payout')),
    plan_value REAL NOT NULL,
    PRIMARY KEY (client_id, period, metric)
);
"""


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


UPSERT_SQL = """
INSERT INTO transactions (
    client_id, marketplace, period_date, sku, product_name, quantity,
    realization, returns, commission, logistics, storage, promotion,
    penalty, other_deduction, payout, source_report, raw_ref
) VALUES (
    :client_id, :marketplace, :period_date, :sku, :product_name, :quantity,
    :realization, :returns, :commission, :logistics, :storage, :promotion,
    :penalty, :other_deduction, :payout, :source_report, :raw_ref
)
ON CONFLICT(client_id, marketplace, raw_ref) DO UPDATE SET
    period_date=excluded.period_date,
    sku=excluded.sku,
    product_name=excluded.product_name,
    quantity=excluded.quantity,
    realization=excluded.realization,
    returns=excluded.returns,
    commission=excluded.commission,
    logistics=excluded.logistics,
    storage=excluded.storage,
    promotion=excluded.promotion,
    penalty=excluded.penalty,
    other_deduction=excluded.other_deduction,
    payout=excluded.payout,
    ingested_at=CURRENT_TIMESTAMP;
"""


def upsert_transactions(rows: list[dict]) -> int:
    """Idempotent bulk insert/update — safe to re-run the same pull twice."""
    if not rows:
        return 0
    with connect() as conn:
        conn.executemany(UPSERT_SQL, rows)
        return len(rows)


def set_plan_target(client_id: str, period: str, metric: str, plan_value: float) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO plan_targets (client_id, period, metric, plan_value)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(client_id, period, metric) DO UPDATE SET plan_value=excluded.plan_value
            """,
            (client_id, period, metric, plan_value),
        )
