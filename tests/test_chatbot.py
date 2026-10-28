import db
from chatbot import ask, quota_gb, recharged_last_month

if not db.DB_PATH.exists():
    db.build()


def test_quota_parsing_ignores_daily_fup():
    assert quota_gb({"Quota": "10 GB general + 5 GB education"}) == 10
    assert quota_gb({"Quota": "Unlimited, FUP 1.5 GB/day"}) is None


def test_package_price_from_catalog():
    result = ask("Berapa harga paket 10GB yang masa aktifnya 30 hari?")
    assert result["route"] == "catalog"
    assert "Freedom Internet 10GB: Rp 25.000" in result["answer"]
    assert "Roaming Asia 10GB" not in result["answer"]  # 10 GB but 7 days
    assert "registered campus domains" in result["answer"]  # multi-line note kept whole


def test_policy_answer_from_faq():
    result = ask("What happens if I don't recharge for 60 days?")
    assert result["route"] == "passages"
    assert "3. What happens if I do not recharge for a long time" in result["answer"]


def test_data_question_uses_database_not_documents():
    result = ask("How many subscribers recharged last month?")
    n, _, _ = recharged_last_month()
    assert result["route"] == "data"
    assert f"{n:,} subscribers" in result["answer"]


def test_out_of_scope_is_declined():
    assert ask("Who is the CEO of Indosat?")["route"] == "decline"
