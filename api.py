import sqlite3
from contextlib import closing
from datetime import date

from fastapi import FastAPI, HTTPException

from db import DB_PATH, TODAY

app = FastAPI(title="Recharge Insight API")

SUMMARY_SQL = """
SELECT s.subscriber_id, s.segment, s.tenure_days, s.last_active_date,
       COUNT(r.date) AS recharge_count,
       COALESCE(SUM(r.amount), 0) AS total_amount,
       ROUND(AVG(r.amount)) AS avg_amount,
       MIN(r.date) AS first_recharge,
       MAX(r.date) AS last_recharge
FROM subscribers s
LEFT JOIN recharges r USING (subscriber_id)
WHERE s.subscriber_id = ?
GROUP BY s.subscriber_id
"""

TOP_CHANNEL_SQL = """
SELECT channel FROM recharges WHERE subscriber_id = ?
GROUP BY channel ORDER BY COUNT(*) DESC, channel LIMIT 1
"""


def is_dormant(days_since_last, avg_gap):
    """Dormant = no recharge for longer than twice the average gap. None when the gap is unknown."""
    if avg_gap is None:
        return None
    return days_since_last > 2 * avg_gap


def subscriber_summary(con, subscriber_id):
    con.row_factory = sqlite3.Row
    row = con.execute(SUMMARY_SQL, (subscriber_id,)).fetchone()
    if row is None:
        return None
    summary = dict(row)
    n = summary["recharge_count"]
    summary.update(top_channel=None, days_since_last_recharge=None, avg_gap_days=None,
                   dormant=None, dormancy_note=None)
    if n == 0:
        summary["dormancy_note"] = "no recharge history"
        return summary

    first = date.fromisoformat(summary["first_recharge"])
    last = date.fromisoformat(summary["last_recharge"])
    days_since = (TODAY - last).days
    avg_gap = (last - first).days / (n - 1) if n > 1 else None
    summary.update(
        top_channel=con.execute(TOP_CHANNEL_SQL, (subscriber_id,)).fetchone()[0],
        days_since_last_recharge=days_since,
        avg_gap_days=None if avg_gap is None else round(avg_gap, 1),
        dormant=is_dormant(days_since, avg_gap),
    )
    if avg_gap is None:
        summary["dormancy_note"] = "insufficient history: one recharge, no gap to compare"
    else:
        summary["dormancy_note"] = f"threshold is {round(2 * avg_gap, 1)} days without a recharge"
    return summary


@app.get("/subscriber/{subscriber_id}")
def get_subscriber(subscriber_id: str):
    # Read-only connection per request: a missing DB fails loudly instead of creating an empty file.
    with closing(sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)) as con:
        summary = subscriber_summary(con, subscriber_id)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"subscriber {subscriber_id} not found")
    return summary
