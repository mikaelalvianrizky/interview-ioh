"""Build recharge.db from the CSVs in data/, or run queries.sql against it.

    python db.py               # (re)build recharge.db
    python db.py queries [N]   # run queries.sql, print first N rows of each (default 15)
"""
import csv
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "recharge.db"
# Fixed "today" so the API and chatbot match queries.sql and the tests. Override with the TODAY env var.
TODAY = date.fromisoformat(os.environ.get("TODAY", "2026-09-24"))

SCHEMA = """
DROP TABLE IF EXISTS recharges;
DROP TABLE IF EXISTS subscribers;
CREATE TABLE subscribers (
    subscriber_id    TEXT PRIMARY KEY,
    tenure_days      INTEGER NOT NULL,
    segment          TEXT NOT NULL,
    last_active_date TEXT
);
CREATE TABLE recharges (
    subscriber_id  TEXT NOT NULL REFERENCES subscribers(subscriber_id),
    date           TEXT NOT NULL,
    amount         INTEGER NOT NULL,
    channel        TEXT NOT NULL,
    package_bought TEXT
);
CREATE INDEX idx_recharges_sub_date ON recharges(subscriber_id, date);
CREATE INDEX idx_recharges_date ON recharges(date);
"""


def connect():
    return sqlite3.connect(DB_PATH)


def _rows(name):
    with open(ROOT / "data" / name, newline="", encoding="utf-8") as f:
        # Empty CSV cells become NULL so COUNT/AVG skip them: package_bought "" -> None (14,131 rows).
        yield from ([v or None for v in row.values()] for row in csv.DictReader(f))


def build():
    DB_PATH.unlink(missing_ok=True)
    con = connect()
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO subscribers VALUES (?, ?, ?, ?)", _rows("subscribers.csv"))
    con.executemany("INSERT INTO recharges VALUES (?, ?, ?, ?, ?)", _rows("recharges.csv"))
    con.commit()
    for table in ("subscribers", "recharges"):
        print(f"{table}: {con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]} rows")
    con.close()


def run_queries(limit=15):
    con = connect()
    sql = (ROOT / "queries.sql").read_text(encoding="utf-8")
    for block in filter(str.strip, sql.split(";")):
        # -> "-- Q1. Top 10 recharge amounts by total revenue, per channel."
        title = next(line for line in block.splitlines() if line.startswith("--"))
        cur = con.execute(block)
        rows = cur.fetchall()
        print(f"\n{title}\n({len(rows)} rows, showing {min(limit, len(rows))})")
        print(" | ".join(d[0] for d in cur.description))
        for row in rows[:limit]:
            print(" | ".join("" if v is None else str(v) for v in row))
    con.close()


if __name__ == "__main__":
    if sys.argv[1:2] == ["queries"]:
        run_queries(int(sys.argv[2]) if len(sys.argv) > 2 else 15)
    else:
        build()
