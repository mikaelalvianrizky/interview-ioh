from fastapi.testclient import TestClient

import db
from api import app, is_dormant

if not db.DB_PATH.exists():
    db.build()

client = TestClient(app)


def test_is_dormant_rule():
    assert is_dormant(days_since_last=61, avg_gap=30) is True
    assert is_dormant(days_since_last=60, avg_gap=30) is False  # "longer than", so exactly 2x is not dormant
    assert is_dormant(days_since_last=200, avg_gap=None) is None


def test_unknown_subscriber_is_404():
    assert client.get("/subscriber/SUB9999999").status_code == 404


def test_summary_matches_q4():
    # Expected values come from Q4 in queries.sql: 7 recharges, last 2026-06-06, avg gap 38.7 days.
    body = client.get("/subscriber/SUB0000001").json()
    assert body["recharge_count"] == 7
    assert body["days_since_last_recharge"] == 110
    assert body["avg_gap_days"] == 38.7
    assert body["dormant"] is True


def test_recent_recharger_is_not_dormant():
    body = client.get("/subscriber/SUB0000002").json()
    assert body["days_since_last_recharge"] == 2
    assert body["dormant"] is False


def test_single_recharge_has_no_dormancy_flag():
    body = client.get("/subscriber/SUB0000003").json()
    assert body["recharge_count"] == 1
    assert body["avg_gap_days"] is None
    assert body["dormant"] is None


def test_subscriber_without_recharges_returns_empty_summary():
    with db.connect() as con:
        (sub_id,) = con.execute(
            "SELECT subscriber_id FROM subscribers WHERE subscriber_id NOT IN "
            "(SELECT subscriber_id FROM recharges) LIMIT 1"
        ).fetchone()
    response = client.get(f"/subscriber/{sub_id}")
    assert response.status_code == 200
    assert response.json()["recharge_count"] == 0
    assert response.json()["dormant"] is None
