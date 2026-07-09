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
    category TEXT,
    brand TEXT,
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
    -- raw_ref (WB rrd_id / Ozon operation_id) is assumed unique per client
    -- for the lifetime of that client's data. It's assigned by the
    -- marketplace, not us — if WB or Ozon ever reused one for a different
    -- operation, a later upsert would silently overwrite the earlier row
    -- instead of erroring. Not observed in practice, but worth knowing if
    -- synced totals ever look wrong after a re-run.
    UNIQUE(client_id, marketplace, raw_ref)
);

CREATE INDEX IF NOT EXISTS idx_transactions_client_period
    ON transactions(client_id, period_date);

CREATE INDEX IF NOT EXISTS idx_transactions_client_sku
    ON transactions(client_id, sku);

CREATE TABLE IF NOT EXISTS product_costs (
    client_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    unit_cost REAL NOT NULL,
    source_file TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (client_id, sku)
);

CREATE TABLE IF NOT EXISTS plan_targets (
    client_id TEXT NOT NULL,
    period TEXT NOT NULL,
    metric TEXT NOT NULL CHECK(metric IN ('net_revenue', 'payout')),
    plan_value REAL NOT NULL,
    PRIMARY KEY (client_id, period, metric)
);

CREATE TABLE IF NOT EXISTS uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL,
    marketplace TEXT NOT NULL CHECK(marketplace IN ('wb', 'ozon')),
    filename TEXT NOT NULL,
    -- staged: rows parsed, waiting for review/import
    -- imported: ok/fixed rows are in transactions
    status TEXT NOT NULL DEFAULT 'staged' CHECK(status IN ('staged', 'imported')),
    file_fixes TEXT NOT NULL DEFAULT '[]',
    columns_mapped TEXT NOT NULL DEFAULT '{}',
    uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS upload_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id INTEGER NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('ok', 'fixed', 'error')),
    fixes TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    data TEXT NOT NULL,
    raw TEXT NOT NULL,
    UNIQUE(upload_id, row_index)
);

CREATE INDEX IF NOT EXISTS idx_upload_rows_upload
    ON upload_rows(upload_id, status);
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
        # Migrate databases created before category/brand existed — SQLite
        # can't add "IF NOT EXISTS" to ALTER, so check the live columns first.
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(transactions)")}
        for column in ("category", "brand"):
            if column not in existing:
                conn.execute(f"ALTER TABLE transactions ADD COLUMN {column} TEXT")


UPSERT_SQL = """
INSERT INTO transactions (
    client_id, marketplace, period_date, sku, product_name, category, brand,
    quantity, realization, returns, commission, logistics, storage, promotion,
    penalty, other_deduction, payout, source_report, raw_ref
) VALUES (
    :client_id, :marketplace, :period_date, :sku, :product_name, :category, :brand,
    :quantity, :realization, :returns, :commission, :logistics, :storage, :promotion,
    :penalty, :other_deduction, :payout, :source_report, :raw_ref
)
ON CONFLICT(client_id, marketplace, raw_ref) DO UPDATE SET
    period_date=excluded.period_date,
    sku=excluded.sku,
    product_name=excluded.product_name,
    category=excluded.category,
    brand=excluded.brand,
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
    """Idempotent bulk insert/update — safe to re-run the same pull twice.

    category/brand are optional columns added later; default them so callers
    predating them (and any WB/Ozon row without the field) still upsert."""
    if not rows:
        return 0
    prepared = [{"category": "", "brand": "", **row} for row in rows]
    with connect() as conn:
        conn.executemany(UPSERT_SQL, prepared)
        return len(rows)


def set_product_costs(client_id: str, costs: dict[str, float], source_file: str | None = None) -> int:
    """Bulk upsert per-SKU unit costs (себестоимость) for a client. Returns count."""
    if not costs:
        return 0
    with connect() as conn:
        conn.executemany(
            """
            INSERT INTO product_costs (client_id, sku, unit_cost, source_file)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(client_id, sku) DO UPDATE SET
                unit_cost=excluded.unit_cost,
                source_file=excluded.source_file,
                updated_at=CURRENT_TIMESTAMP
            """,
            [(client_id, sku, cost, source_file) for sku, cost in costs.items()],
        )
        return len(costs)


def get_product_costs(client_id: str) -> dict[str, float]:
    with connect() as conn:
        return {
            r["sku"]: r["unit_cost"]
            for r in conn.execute(
                "SELECT sku, unit_cost FROM product_costs WHERE client_id = ?", (client_id,)
            ).fetchall()
        }


def product_costs_meta(client_id: str) -> dict:
    """Count and most-recent source file for the client's loaded costs."""
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n, MAX(source_file) AS source_file FROM product_costs WHERE client_id = ?",
            (client_id,),
        ).fetchone()
    return {"count": row["n"], "source_file": row["source_file"]}


def clear_product_costs(client_id: str) -> int:
    with connect() as conn:
        return conn.execute("DELETE FROM product_costs WHERE client_id = ?", (client_id,)).rowcount


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


# --- CSV upload staging ---------------------------------------------------

def create_upload(client_id: str, marketplace: str, filename: str, file_fixes: str, columns_mapped: str, rows: list[dict]) -> int:
    """Persist a parsed upload with its staged rows in one transaction."""
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO uploads (client_id, marketplace, filename, file_fixes, columns_mapped) VALUES (?, ?, ?, ?, ?)",
            (client_id, marketplace, filename, file_fixes, columns_mapped),
        )
        upload_id = cursor.lastrowid
        conn.executemany(
            """INSERT INTO upload_rows (upload_id, row_index, status, fixes, error, data, raw)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (upload_id, r["row_index"], r["status"], r["fixes"], r["error"], r["data"], r["raw"])
                for r in rows
            ],
        )
        return upload_id


def list_uploads(client_id: str) -> list[dict]:
    with connect() as conn:
        uploads = [dict(r) for r in conn.execute(
            "SELECT * FROM uploads WHERE client_id = ? ORDER BY id DESC", (client_id,)
        ).fetchall()]
        for upload in uploads:
            counts = {
                r["status"]: r["n"]
                for r in conn.execute(
                    "SELECT status, COUNT(*) AS n FROM upload_rows WHERE upload_id = ? GROUP BY status",
                    (upload["id"],),
                ).fetchall()
            }
            upload["rows_ok"] = counts.get("ok", 0)
            upload["rows_fixed"] = counts.get("fixed", 0)
            upload["rows_error"] = counts.get("error", 0)
        return uploads


def get_upload(upload_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM uploads WHERE id = ?", (upload_id,)).fetchone()
        return dict(row) if row else None


def get_upload_rows(upload_id: int, status: str | None = None) -> list[dict]:
    query = "SELECT * FROM upload_rows WHERE upload_id = ?"
    params: list = [upload_id]
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY row_index"
    with connect() as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def update_upload_row(row_id: int, status: str, fixes: str, error: str | None, data: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE upload_rows SET status = ?, fixes = ?, error = ?, data = ? WHERE id = ?",
            (status, fixes, error, data, row_id),
        )


def get_upload_row(row_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM upload_rows WHERE id = ?", (row_id,)).fetchone()
        return dict(row) if row else None


def mark_upload_imported(upload_id: int) -> None:
    with connect() as conn:
        conn.execute("UPDATE uploads SET status = 'imported' WHERE id = ?", (upload_id,))


def delete_upload(upload_id: int) -> int:
    """Remove the upload, its staged rows, and any transactions it imported.
    Returns how many imported transactions were rolled back."""
    with connect() as conn:
        removed = conn.execute(
            "DELETE FROM transactions WHERE source_report = ?",
            (f"csv_upload:{upload_id}",),
        ).rowcount
        conn.execute("DELETE FROM uploads WHERE id = ?", (upload_id,))
        return removed
