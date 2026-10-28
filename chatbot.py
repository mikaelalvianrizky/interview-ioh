"""Retrieval-only chatbot over product_catalog.md and policy_faq.md.

    python chatbot.py "Berapa harga paket 10GB yang masa aktifnya 30 hari?"
    python chatbot.py --eval     # writes results/chatbot_answers.md
"""
import re
import sys
from datetime import timedelta
from functools import cache

import numpy as np

import db

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
# Below this cosine score the best passage is treated as unrelated and the bot declines.
# Relevant and off-topic scores overlap (slang 0.11, "harga iPhone" 0.43), so DOMAIN_WORDS does most declining.
MIN_SCORE = 0.35

# Questions must use at least one word from the documents' topics, otherwise the bot declines.
DOMAIN_WORDS = re.compile(
    r"paket|pulsa|kuota|internet|\bdata\b|\d+\s*gb|recharg|isi ulang|top.?up|masa (aktif|tenggang)|"
    r"nomor|\be?sim\b|kartu|voucher|refund|roaming|langganan|perpanjang|hangus|sinyal|jaringan|unlimited|"
    r"registrasi|promo|komplain|keluhan|blokir|telepon|nelpon|sms|"
    r"package|quota|validity|grace|number|balance|plan\b|call")

# The FAQ is English, customers ask in Indonesian. Each phrase gets its own vector:
# appended to the section text it was drowned out and changed no score.
ALIASES = {
    "1. Active period (masa aktif)": ("kartu aktif sampai kapan", "tambah masa aktif"),
    "2. Grace period (masa tenggang)": ("masa tenggang", "tidak bisa telepon keluar"),
    "3. What happens if I do not recharge for a long time": ("nomor hangus", "lama tidak isi ulang"),
    "4. Recharge channels": ("cara isi pulsa", "beli pulsa di mana"),
    "5. Physical voucher rules": ("voucher fisik", "kode voucher gagal"),
    "6. Package activation and stacking": ("cara aktifkan paket", "beli dua paket sekaligus"),
    "7. Auto-renew": ("perpanjangan otomatis", "berhenti berlangganan"),
    "8. Fair usage policy (FUP)": ("kecepatan internet diturunkan", "batas pemakaian wajar"),
    "9. Refunds": ("uang kembali", "pengembalian dana"),
    "10. Balance transfer": ("transfer pulsa", "kirim pulsa ke nomor lain"),
    "11. Registration": ("registrasi kartu", "daftar NIK dan KK"),
    "12. Number ownership transfer": ("balik nama nomor", "pindah kepemilikan nomor"),
    "13. Lost or damaged SIM replacement": ("kartu hilang", "ganti kartu rusak"),
    "14. eSIM": ("esim", "sim digital"),
    "15. Network priority during congestion": ("internet lemot saat ramai", "jaringan padat"),
    "16. Data usage measurement": ("cara hitung pemakaian kuota", "kuota cepat habis"),
    "17. Complaint handling": ("komplain", "lapor keluhan"),
    "18. Promotional messages": ("sms promo", "berhenti terima promosi"),
    "19. Quota alerts": ("notifikasi kuota", "pemberitahuan sisa kuota"),
    "20. Service suspension for policy breach": ("nomor diblokir", "layanan diputus"),
}

ID_WORDS = {"apa", "berapa", "yang", "jika", "kalau", "saya", "tidak", "harga", "bagaimana", "apakah",
            "bisa", "untuk", "dengan", "hari", "bulan", "masa", "aktif", "siapa", "isi", "ulang", "mau"}
ID_MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus",
             "September", "Oktober", "November", "Desember"]

TEXT = {
    "decline": {
        "en": "Sorry, I can only answer questions about prepaid packages and policies, "
              "and this question is not covered by those documents.",
        "id": "Maaf, saya hanya bisa menjawab pertanyaan tentang paket dan kebijakan prabayar, "
              "dan pertanyaan ini tidak tercakup di dokumen tersebut.",
    },
    "data_unsupported": {
        "en": "That needs subscriber data, which is not in the documents. The only data question I can "
              "answer is how many subscribers recharged last month. I will not guess a number.",
        "id": "Pertanyaan ini butuh data pelanggan, yang tidak ada di dokumen. Satu-satunya pertanyaan data "
              "yang bisa saya jawab adalah jumlah pelanggan yang isi ulang bulan lalu. Saya tidak akan menebak angka.",
    },
    "data_answer": {
        "en": "{n} subscribers recharged at least once in {month} ({start} to {end}). "
              "Source: recharges table, not the documents.",
        "id": "{n} pelanggan melakukan isi ulang minimal sekali pada {month} ({start} s.d. {end}). "
              "Sumber: tabel recharges, bukan dokumen.",
    },
    "catalog": {"en": "Packages that match:", "id": "Paket yang cocok:"},
    "passages": {"en": "Most relevant passages:", "id": "Bagian dokumen yang paling relevan:"},
}


def language(question):
    return "id" if ID_WORDS & set(re.findall(r"[a-z]+", question.lower())) else "en"


def parse_docs():
    """Split the catalog per package (###) and the FAQ per section (##)."""
    chunks, packages = [], []
    family = ""
    catalog = (db.ROOT / "data" / "product_catalog.md").read_text(encoding="utf-8")
    for block in re.split(r"\n(?=##+ )", catalog):
        heading, _, body = _split(block)
        if heading.startswith("## Family: "):
            family = heading.removeprefix("## Family: ")
        elif heading.startswith("### "):
            name = heading.removeprefix("### ")
            # Indented lines continue the previous bullet, join them so long notes are not cut.
            fields = dict(re.findall(r"- \*\*(.+?):\*\* (.+)", re.sub(r"\n\s+", " ", body)))
            packages.append({"name": name, "family": family, **fields})
            chunks.append({"source": "product_catalog.md", "title": name, "text": f"{family}: {name}\n{body}"})
    faq = (db.ROOT / "data" / "policy_faq.md").read_text(encoding="utf-8")
    for block in re.split(r"\n(?=## )", faq)[1:]:
        heading, _, body = _split(block)
        title = heading.removeprefix("## ")
        chunks.append({"source": "policy_faq.md", "title": title, "text": f"{title}\n{body}"})
    return chunks, packages


def _split(block):
    """Heading line, separator, body without the markdown '---' rules between sections."""
    heading, sep, body = block.partition("\n")
    return heading, sep, re.sub(r"^---$", "", body, flags=re.M).strip()


@cache
def index():
    from sentence_transformers import SentenceTransformer  # slow import, only when retrieval is needed

    model = SentenceTransformer(MODEL_NAME)
    chunks, packages = parse_docs()
    texts, owner = [], []
    for i, c in enumerate(chunks):
        for text in (c["text"], *ALIASES.get(c["title"], ())):
            texts.append(text)
            owner.append(i)
    vectors = model.encode(texts, normalize_embeddings=True)
    return model, chunks, vectors, np.array(owner), packages


def search(question, k=2):
    """Top k chunks, each scored by its best vector (section text or one of its aliases)."""
    model, chunks, vectors, owner, _ = index()
    scores = np.full(len(chunks), -1.0)
    np.maximum.at(scores, owner, vectors @ model.encode(question, normalize_embeddings=True))
    top = np.argsort(-scores)[:k]
    return [(float(scores[i]), chunks[i]) for i in top]


def data_question(question):
    q = question.lower()
    asks_count = re.search(r"how many|berapa (banyak|orang|pelanggan)|jumlah|number of", q)
    about_people = re.search(r"subscriber|pelanggan|customer|user|pengguna|people|orang", q)
    return bool(asks_count and about_people)


def recharged_last_month():
    end = db.TODAY.replace(day=1) - timedelta(days=1)
    start = end.replace(day=1)
    with db.connect() as con:
        (n,) = con.execute(
            "SELECT COUNT(DISTINCT subscriber_id) FROM recharges WHERE date BETWEEN ? AND ?",
            (start.isoformat(), end.isoformat()),
        ).fetchone()
    return n, start, end


def answer_data(question, lang):
    q = question.lower()
    recharge = re.search(r"recharg|top(ped)?.?up|isi ulang|pulsa", q)
    last_month = re.search(r"last month|bulan lalu|bulan kemarin", q)
    if not (recharge and last_month):
        return TEXT["data_unsupported"][lang]
    n, start, end = recharged_last_month()
    if lang == "id":
        month, count = f"{ID_MONTHS[start.month - 1]} {start.year}", f"{n:,}".replace(",", ".")
    else:
        month, count = start.strftime("%B %Y"), f"{n:,}"
    return TEXT["data_answer"][lang].format(n=count, month=month, start=start, end=end)


def quota_gb(package):
    # Main quota is the first GB figure, e.g. "10 GB general + 5 GB education" -> 10.
    # "(?!/)" skips daily FUP limits such as "1.5 GB/day".
    found = re.findall(r"(\d+)\s*GB(?!/)", package.get("Quota", ""))
    return int(found[0]) if found else None


def validity_days(package):
    found = re.match(r"(\d+) days?", package.get("Validity", ""))
    return int(found[1]) if found else None


def match_packages(question):
    """Packages whose main quota (and validity, if asked) match the numbers in the question."""
    q = question.lower()
    gb = re.search(r"(\d+)\s*gb", q)
    if not gb:
        return []
    days = re.search(r"(\d+)\s*(hari|days?)", q)
    *_, packages = index()
    return [p for p in packages
            if quota_gb(p) == int(gb[1]) and (not days or validity_days(p) == int(days[1]))]


def format_package(p, lang):
    validity = p.get("Validity", "-")
    if lang == "id":
        validity = validity.replace("days", "hari").replace("day", "hari")
    notes = f". {p['Notes']}" if "Notes" in p else ""  # keeps restrictions such as night-only quota
    return f"- {p['name']}: {p['Price']}, {p.get('Quota', '-')}, {validity}{notes} (product_catalog.md)"


def ask(question):
    """Return {"route", "score", "answer"}. Route is data, catalog, passages or decline."""
    lang = language(question)
    if data_question(question):
        return {"route": "data", "score": None, "answer": answer_data(question, lang)}

    hits = search(question)
    best = hits[0][0]
    if best < MIN_SCORE or not DOMAIN_WORDS.search(question.lower()):
        return {"route": "decline", "score": best, "answer": TEXT["decline"][lang]}

    matches = match_packages(question)
    if matches:
        lines = [TEXT["catalog"][lang], *(format_package(p, lang) for p in matches)]
        return {"route": "catalog", "score": best, "answer": "\n".join(lines)}

    lines = [TEXT["passages"][lang]]
    for score, chunk in hits:
        lines.append(f"\n[{chunk['source']} > {chunk['title']}] (score {score:.2f})\n{chunk['text']}")
    return {"route": "passages", "score": best, "answer": "\n".join(lines)}


EVAL_QUESTIONS = [
    # The four required questions from the assignment.
    "Berapa harga paket 10GB yang masa aktifnya 30 hari?",
    "What happens if I don't recharge for 60 days?",
    "How many subscribers recharged last month?",
    "Who is the CEO of Indosat?",
    # Five of our own, picked to probe the weak spots.
    "Can I get a refund if I activated a package by mistake?",
    "Berapa harga paket roaming untuk umrah?",
    "Saya mau paket 5GB untuk seminggu, ada apa saja?",
    "Paket unlimited apa yang harganya di bawah 100 ribu?",
    "How many subscribers churned last quarter?",
]


def write_eval():
    out = ["# Chatbot answers", "",
           "Generated by `python chatbot.py --eval`. Do not edit by hand, see `self_assessment.md`.", ""]
    for i, question in enumerate(EVAL_QUESTIONS, 1):
        result = ask(question)
        score = "-" if result["score"] is None else f"{result['score']:.2f}"
        out += [f"## {i}. {question}", "", f"Route: `{result['route']}`, top retrieval score: {score}",
                "", "```text", result["answer"], "```", ""]
    path = db.ROOT / "results" / "chatbot_answers.md"
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    if sys.argv[1:] == ["--eval"]:
        write_eval()
    elif sys.argv[1:]:
        print(ask(" ".join(sys.argv[1:]))["answer"])
    else:
        print(__doc__)
