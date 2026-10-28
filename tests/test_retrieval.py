from chatbot import ask, search

FAQ3 = "3. What happens if I do not recharge for a long time"

# Question -> chunk title that should come first, "*" for any (answered by the catalog filter),
# None when the bot must decline. The aliases and DOMAIN_WORDS were written after seeing these,
# so the error count here is optimistic.
TUNING = [
    ("pulsa gw ilang ga kalo lama ga isi?", FAQ3),
    ("klo paket abis bisa diperpanjang otomatis ga", "7. Auto-renew"),
    ("gimana cara matiin perpanjangan otomatis", "7. Auto-renew"),
    ("salah beli paket, duitnya bisa balik ga?", "9. Refunds"),
    ("paket buat nonton youtube yg murah apa", "Unlimited Streaming 30 Hari"),
    ("kartu sim saya hilang, gimana?", "13. Lost or damaged SIM replacement"),
    ("bisa transfer pulsa ke temen?", "10. Balance transfer"),
    ("internet lemot pas jam sibuk kenapa", "15. Network priority during congestion"),
    ("nomor saya mau hangus nih", FAQ3),
    ("ada esim ga?", "14. eSIM"),
    ("What happens if I don't recharge for 60 days?", FAQ3),
    ("Can I get a refund if I activated a package by mistake?", "9. Refunds"),
    ("Berapa harga paket roaming untuk umrah?", "Roaming Umrah 8GB"),
    ("Berapa harga paket 10GB yang masa aktifnya 30 hari?", "*"),
    ("Saya mau paket 5GB untuk seminggu, ada apa saja?", "*"),
    ("Paket unlimited apa yang harganya di bawah 100 ribu?", "*"),
    ("harga iPhone 15 berapa?", None),
    ("Telkomsel punya paket apa aja?", None),
    ("harga saham Indosat hari ini", None),
    ("promo pulsa di Shopee ada ga", None),
    ("berapa gaji karyawan Indosat", None),
    ("resep nasi goreng", None),
    ("cuaca Jakarta besok gimana", None),
    ("siapa presiden Indonesia", None),
    ("Who is the CEO of Indosat?", None),
]

# Written after the fixes, partly by someone who had not seen the aliases, and measured once.
HELD_OUT = [
    ("kalo pulsa abis dan udah lewat masa aktif, masih bisa ditelpon ga?", "2. Grace period (masa tenggang)"),
    ("isi pulsa di alfamart kena biaya tambahan ga?", "4. Recharge channels"),
    ("salah masukin kode voucher berkali-kali, sekarang ke-lock", "5. Physical voucher rules"),
    ("beli yellow harian 2x sehari, kuota yang pertama hilang?", "6. Package activation and stacking"),
    ("kenapa paket unlimited saya jadi pelan setelah dipakai banyak?", "8. Fair usage policy (FUP)"),
    ("Can I give my number to my brother?", "12. Number ownership transfer"),
    ("satu KTP bisa buat daftar berapa nomor?", "11. Registration"),
    ("kok sisa kuota di hp beda sama di aplikasi?", "16. Data usage measurement"),
    ("gimana caranya biar ga dapet sms iklan terus", "18. Promotional messages"),
    ("How long does a complaint about slow network take?", "17. Complaint handling"),
    ("paket internet buat ke Jepang ada?", ("Roaming Asia 10GB", "Roaming Asia 3GB")),
    ("paket nelpon yang paling murah apa?", "Voice 30 Menit"),
    ("nomorku tiba-tiba ga bisa dipake, katanya kena suspend", "20. Service suspension for policy breach"),
    ("rekomendasiin dong paket internet yang paling terjangkau", "Yellow Harian 1GB"),
    ("XL lagi ada promo apa?", None),
    ("kartu kredit BCA saya keblokir, gimana?", None),
    ("cara reset hp android lupa pola", None),
    ("Indosat berdiri tahun berapa?", None),
    ("jadwal KRL Bogor besok pagi", None),
    ("kurs dollar hari ini berapa", None),
]


def mistakes(labeled):
    """Questions where the bot answered when it should decline, or the reverse, or ranked the wrong chunk first."""
    wrong = []
    for question, expected in labeled:
        answered = ask(question)["route"] != "decline"
        top = search(question)[0][1]["title"]
        accepted = expected if isinstance(expected, tuple) else (expected,)
        if answered != (expected is not None) or (answered and expected != "*" and top not in accepted):
            wrong.append((question, expected, top if answered else "declined"))
    return wrong


# Bounds are the measured counts, so these guard against regressions, not prove quality.
# Before the aliases and DOMAIN_WORDS: 12 of 25 and 12 of 20 wrong.
def test_tuning_questions():
    wrong = mistakes(TUNING)
    assert len(wrong) <= 5, wrong


def test_held_out_questions():
    wrong = mistakes(HELD_OUT)
    assert len(wrong) <= 8, wrong
