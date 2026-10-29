# Prepaid Recharge Insight Tool

SQL analysis over one year of prepaid recharges, an API that flags dormant subscribers, and a
retrieval-only chatbot over the product catalog and policy FAQ. Everything runs locally: SQLite for
the data, a small multilingual embedding model on CPU for the chatbot, no external API.

## Run it (Docker, about 5 minutes once Docker is installed)

Needs only Docker. No Python or database install on your machine.

1. Install Docker if you don't have it:
   - Windows or macOS: [Docker Desktop](https://docs.docker.com/get-started/get-docker/). On Windows it
     runs on WSL 2, and the installer may ask for a restart.
   - Linux: [Docker Engine](https://docs.docker.com/engine/install/) with the Compose plugin.
2. Start Docker Desktop (Linux: the Docker service) and check that both commands print a version:

   ```bash
   docker --version
   docker compose version
   ```

3. From the repository folder, build and start:

   ```bash
   docker compose up --build        # first build downloads ~1 GB and takes about 4 to 5 minutes
   ```

Then, in a second terminal:

```bash
# Part 2: the API (also browsable at http://localhost:8000/docs)
curl http://localhost:8000/subscriber/SUB0000001

# Part 1: run the four queries in queries.sql (prints the first 15 rows of each)
docker compose run --rm app python db.py queries

# Part 3: ask the chatbot, or regenerate results/chatbot_answers.md
docker compose run --rm app python chatbot.py "Berapa harga paket 10GB yang masa aktifnya 30 hari?"
docker compose run --rm app python chatbot.py --eval

# Tests (13)
docker compose run --rm app pytest
```

The database is built inside the image (`RUN python db.py`) because the data is static, and the
embedding model is downloaded at build time, so nothing is fetched at runtime.

<details>
<summary>Without Docker (Python 3.11+)</summary>

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
python db.py                  # builds recharge.db
python db.py queries
uvicorn api:app
pytest
python chatbot.py "What happens if I don't recharge for 60 days?"
```
The first chatbot run downloads the embedding model (about 470 MB).
</details>

## Repository

| Path | What it is |
|---|---|
| `db.py` | Loads the CSVs into `recharge.db` (SQLite), runs `queries.sql` |
| `queries.sql` | Part 1, four queries with a comment on the approach above each |
| `api.py` | Part 2, `GET /subscriber/{id}` |
| `chatbot.py` | Part 3, router, retrieval, catalog filter, eval runner |
| `tests/` | API and chatbot tests |
| `results/chatbot_answers.md` | Chatbot output for 9 questions, generated, not hand-written |
| `results/self_assessment.md` | Which of those answers are wrong or weak, and why |

## Part 1: SQL

| Query | Approach |
|---|---|
| Q1 top amounts per channel | `RANK()` over revenue per channel. There are only 10 distinct amounts, so every channel lists all of them. Revenue order still differs from face value and from transaction count, which is the useful part. |
| Q2 monthly rechargers and ARPU | Returns both `arppu` (revenue / subscribers who recharged that month) and `arpu` (revenue / all subscribers in the segment). They answer different questions and can rank segments differently: in August 2026 Mass beats Youth on ARPPU, Youth beats Mass on ARPU. First and last month are flagged `partial_month`. |
| Q3 recharged recently, not before | Windows `(today-30, today]` and `(today-60, today-30]`, with today = 2026-09-24. 2,099 subscribers, cross-checked in plain Python. |
| Q4 days since last recharge, average gap | Average of consecutive gaps equals `(last - first) / (n - 1)`, so a plain `GROUP BY` replaces a `LAG()` window. `NULL` gap below two recharges. `LEFT JOIN` keeps the 200 subscribers with no recharge. |

## Part 2: API

`GET /subscriber/{id}` returns the recharge summary (count, total, average, first and last date, most
used channel, days since last recharge, average gap) plus `dormant` and a `dormancy_note`.

```json
{"subscriber_id": "SUB0000001", "segment": "Mass", "recharge_count": 7, "last_recharge": "2026-06-06",
 "days_since_last_recharge": 110, "avg_gap_days": 38.7, "dormant": true,
 "dormancy_note": "threshold is 77.3 days without a recharge", "...": "..."}
```

| Case | Response |
|---|---|
| Two or more recharges | `dormant` = days since last recharge > 2 x average gap (strictly longer) |
| One recharge | `dormant: null`, note "insufficient history" (741 subscribers) |
| Registered, never recharged | HTTP 200, empty summary, `dormant: null` (200 subscribers) |
| Unknown id | HTTP 404 |

## Part 3: Chatbot

Model approach: **retrieval only, no generation.** Each question goes through four steps in order:

1. **Data question?** Keyword rules ("how many" + "subscribers" etc.). "Recharged last month" runs a SQL
   count for the previous calendar month (August 2026) and says which period it used. Any other data
   question gets an explicit "I cannot answer that, I will not guess a number".
2. **Out of scope?** The question is embedded with `paraphrase-multilingual-MiniLM-L12-v2` and compared
   (cosine, numpy) with 52 chunks: one per catalog package, one per FAQ section. Each FAQ section also
   has two Indonesian phrases ("perpanjangan otomatis" for Auto-renew) embedded as extra vectors, because
   customers ask in Indonesian and the FAQ is in English. The bot declines unless the question uses a
   word from the documents' topics (paket, pulsa, kuota, nomor, roaming...) and the best score is at
   least 0.35. The score alone cannot decide: relevant slang questions scored as low as 0.11, off-topic
   ones as high as 0.43.
3. **Package with a quota?** If the question names a quota in GB (and optionally days), the parsed
   catalog is filtered and every matching package is listed with price, quota, validity and notes.
4. **Otherwise** the top two passages are returned with their source and section title.

Answers to the four required questions and five of my own are in `results/chatbot_answers.md`. The
honest grading is in `results/self_assessment.md`: 5 correct, 2 correct but noisy, 1 handled poorly,
1 wrong.

Retrieval is also measured on 45 labelled questions in `tests/test_retrieval.py`. A question counts as
wrong if the bot answers when it should decline (or the reverse), or ranks the wrong chunk first.

| | 25 tuning questions | 20 held-out questions |
|---|---|---|
| Score threshold only | 12 wrong | 12 wrong |
| With aliases and topic words | 5 wrong | 8 wrong |

The aliases and the word list were written after seeing the tuning questions, so 5 of 25 is optimistic.
The held-out questions were written afterwards and measured once, with no tuning since. Most were
drafted with the AI assistant, which had seen the aliases, so they are not fully independent either.
The 8 misses are listed in `results/self_assessment.md`.

## Assumptions

- Today is 2026-09-24 everywhere (SQL, API, chatbot). Override with the `TODAY` env var for the API and chatbot.
- "Last 30 days" includes today: 2026-08-26 to 2026-09-24. The data has no rows dated today.
- Partial months (September 2025 and September 2026) are shown, flagged.
- "Last month" in the chatbot means the previous full calendar month, August 2026.
- `last_active_date` is shown in the API summary but not used for dormancy, which the brief defines on recharges only.
- When several packages match a question, the chatbot lists all of them.
- The chatbot replies in the language of the question for its own text. Passages stay in English.

## Design decisions

- **SQLite**: in the Python standard library, nothing to install, and window functions cover Part 1.
- **FastAPI**: one endpoint, typed path parameter, free `/docs` page for the reviewer.
- **Read-only DB connection per request**: a missing database fails loudly instead of creating an empty file.
- **Retrieval only**: the brief does not penalise skipping generation, and without an LLM the bot cannot invent a number or a CEO name. It also keeps setup to one `docker compose up`.
- **Multilingual MiniLM over TF-IDF**: the required questions mix Indonesian and English, the documents are English. TF-IDF would need a hand-made synonym list ("masa aktif" to "validity").
- **Topic words on top of the score threshold**: relevant and off-topic scores overlap, so no threshold
  separates them, and `multilingual-e5-small` did not separate them either. A word list is crude (see the
  misses) but predictable and testable.
- **Structured catalog filter**: embeddings do not compare numbers. Without it, the 10GB question retrieves Yellow Mingguan 2GB first.
- **Docker image with data and model baked in**: the reviewer needs no Python, no database and no network at runtime.

## Deliberately left out

- An LLM to phrase answers. It would read better but adds a 2 GB model, slower answers and a hallucination risk on the data question.
- Free-form text-to-SQL in the chatbot. Only one data question is supported, the rest are refused.
- Authentication, rate limiting, pagination, response schemas. One read-only endpoint on synthetic data does not need them yet.
- A slim image. It is 2.9 GB, mostly PyTorch.
- A web or chat UI. The chatbot runs from the command line and the API has FastAPI's `/docs` page, which covers what a reviewer needs to try it.

## With more time

- Hybrid retrieval (BM25 plus embeddings) so numbers and exact package names score properly, and a price filter ("di bawah 100 ribu").
- Parse words for durations ("seminggu", "sebulan") and drop the second passage when its score is far below the first.
- More labelled questions, written by people who have not seen the aliases, and recall@k per section.
- A fallback dormancy flag, in its own field, for the 941 subscribers the brief's rule cannot judge.
  `null` hides likely dormant ones: half of the one-recharge group last recharged 185 or more days ago,
  and the never-recharged have a median tenure of 3.4 years. Compare against the median gap of all
  subscribers (55.6 days), or tenure for those who never recharged.
- Optional local LLM (Ollama, qwen2.5:3b) to rewrite slang questions into plain English before retrieval,
  which would replace the hand-written aliases, and to summarise retrieved passages. Never as a source of
  numbers: if its answer contains a number that is not in the passages, show the passages instead.
- Replace PyTorch with an ONNX runtime for the embedding model to cut the image size.

## At 50 million rows

| Part | What breaks | What I would do |
|---|---|---|
| Loading | Row-by-row `executemany` into SQLite takes a long time, and baking the DB into the Docker image makes a multi-GB image | DuckDB `read_csv` into Parquet partitioned by month, mounted as a volume |
| Q1, Q2 | Full scans with `GROUP BY` and `COUNT(DISTINCT)` on one SQLite thread | DuckDB (columnar, parallel) or a monthly aggregate table updated daily |
| Q4 | One pass over the whole table on every run, 10 million output rows | Per-subscriber summary table (count, first, last date) updated incrementally from new recharges |
| API | Holds up: the `(subscriber_id, date)` index keeps each lookup to a few rows. Concurrent writes would not, SQLite allows one writer | Serve from the summary table, move to Postgres if recharges are written live |
| Chatbot data question | `COUNT(DISTINCT)` over a month of rows on each question | Read from the monthly aggregate table |
| Retrieval | Not affected: it searches the two documents, not the recharge data | Nothing |

## AI assistant

I used Claude Code (Anthropic) as a coding assistant for this submission: assessing the data,
drafting the code and this README. I chose the approach and the assumptions, and I can explain each
decision in the follow-up.
