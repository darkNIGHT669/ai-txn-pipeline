# 🏦 AI-Powered Transaction Processing Pipeline

> A production-ready, fully containerised backend that ingests dirty financial CSVs, cleans them, detects anomalies, classifies transactions with an LLM, and returns a structured summary — all processed asynchronously through a job queue.

---

## 🏗️ System Architecture

```
                        ┌─────────────────────────────────────────────────────┐
                        │                  Docker Network                      │
                        │                                                       │
  ┌──────────┐          │  ┌─────────────┐        ┌──────────────────────────┐ │
  │          │  POST    │  │             │ enqueue │                          │ │
  │  Client  │─────────▶│  │  FastAPI    │────────▶│  Redis (Broker/Backend)  │ │
  │ (curl /  │  /jobs/  │  │  :8000      │         │  :6379                   │ │
  │  Swagger)│  upload  │  │             │         └──────────┬───────────────┘ │
  │          │          │  │  • Validate │                    │ dequeue         │
  │          │◀─────────│  │  • Save Job │                    ▼                 │
  │          │ job_id   │  │  • Return   │         ┌──────────────────────────┐ │
  └──────────┘ (instant)│  │   job_id   │         │   Celery Worker          │ │
                        │  └──────┬──────┘         │                          │ │
                        │         │ async           │  Step 1: Data Cleaning   │ │
  ┌──────────┐          │         │ poll            │  ├─ Normalize dates      │ │
  │          │  GET     │         │                 │  ├─ Strip $ symbols      │ │
  │  Client  │─────────▶│         │                 │  ├─ Uppercase status     │ │
  │          │ /status  │         │                 │  └─ Drop duplicates      │ │
  │          │ /results │         │                 │                          │ │
  └──────────┘          │         │                 │  Step 2: Anomaly Det.    │ │
                        │         │                 │  ├─ 3x median outlier    │ │
                        │         │                 │  └─ Cross-border brand   │ │
                        │         │                 │                          │ │
                        │         │                 │  Step 3: LLM Classify    │ │
                        │         │                 │  └─ Batched (20/call)    │ │
                        │         │                 │      ┌───────────────┐   │ │
                        │         │                 │      │  Gemini 1.5   │   │ │
                        │         │                 │      │  Flash API    │   │ │
                        │         │                 │      └───────────────┘   │ │
                        │         │                 │                          │ │
                        │         │                 │  Step 4: LLM Narrative   │ │
                        │         │                 │  └─ Single summary call  │ │
                        │         │                 │                          │ │
                        │         │                 │  Step 5: Persist         │ │
                        │         │                 └──────────┬───────────────┘ │
                        │         │                            │ write           │
                        │         │                            ▼                 │
                        │         │                 ┌──────────────────────────┐ │
                        │         └────────────────▶│   PostgreSQL :5432       │ │
                        │           read results    │                          │ │
                        │                           │  • jobs                  │ │
                        │                           │  • transactions          │ │
                        │                           │  • job_summaries         │ │
                        │                           └──────────────────────────┘ │
                        │                                                       │
                        └─────────────────────────────────────────────────────┘
```

---

## 📊 Data Flow — Single Request Lifecycle

```
 Client                FastAPI              Redis            Celery Worker         PostgreSQL
   │                      │                   │                    │                    │
   │── POST /jobs/upload ─▶│                   │                    │                    │
   │   (transactions.csv)  │                   │                    │                    │
   │                       │── INSERT Job ────────────────────────────────────────────▶│
   │                       │   status=pending  │                    │                    │
   │                       │── enqueue task ──▶│                    │                    │
   │◀── 202 { job_id } ────│                   │── deliver task ───▶│                    │
   │                       │                   │                    │                    │
   │                       │                   │                    │── UPDATE pending──▶│
   │                       │                   │                    │   → processing     │
   │                       │                   │                    │                    │
   │                       │                   │                    │── clean CSV        │
   │                       │                   │                    │── detect anomalies │
   │                       │                   │                    │── LLM classify     │
   │                       │                   │                    │── LLM narrative    │
   │                       │                   │                    │                    │
   │                       │                   │                    │── INSERT txns ────▶│
   │                       │                   │                    │── INSERT summary ─▶│
   │                       │                   │                    │── UPDATE completed▶│
   │                       │                   │                    │                    │
   │── GET /jobs/{id}/status▶│                  │                    │                    │
   │◀── { completed, summary}│◀──────────────────────────────────────────────────────────│
   │                       │                   │                    │                    │
   │── GET /jobs/{id}/results▶│                 │                    │                    │
   │◀── { transactions, anomalies, breakdown } ─────────────────────────────────────────│
```

---

## ⚙️ Tech Stack

| Layer | Technology | Why |
|---|---|---|
| API Framework | FastAPI 0.111 + Pydantic v2 | Async-first, auto-docs, fast validation |
| Database | PostgreSQL 16 + SQLAlchemy 2 (async) | ACID compliance, JSONB for flexible fields |
| Job Queue | Celery 5 + Redis 7 | Decouples upload from heavy processing |
| LLM | Google Gemini 1.5 Flash | Free tier, fast, strong instruction following |
| Data Processing | Pandas 2.2 | Vectorised cleaning, efficient groupby stats |
| Containerisation | Docker + Docker Compose | Single-command boot, zero manual setup |

---

## 🚀 Quick Start

### Prerequisites
- Docker Desktop
- A free Gemini API key from [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)

### 1. Clone & configure
```bash
git clone https://github.com/YOUR_USERNAME/ai-txn-pipeline.git
cd ai-txn-pipeline
cp .env.example .env
# Open .env and set: GEMINI_API_KEY=your_key_here
```

### 2. Boot everything
```bash
docker compose up --build
```

All four services start automatically with health checks. The API is live at `http://localhost:8000`.

---

## 📡 API Reference

### `POST /jobs/upload`
Upload a CSV file. Returns a `job_id` immediately.
```bash
curl -X POST http://localhost:8000/jobs/upload \
  -F "file=@transactions.csv"
```
```json
{
  "job_id": "7c56b768-bd21-4d23-ac00-f0aed4584673",
  "status": "pending",
  "filename": "transactions.csv",
  "message": "Job enqueued successfully"
}
```

---

### `GET /jobs/{job_id}/status`
Poll for job status. Returns summary stats when completed.
```bash
curl http://localhost:8000/jobs/7c56b768-bd21-4d23-ac00-f0aed4584673/status
```
```json
{
  "job_id": "7c56b768-...",
  "status": "completed",
  "row_count_raw": 95,
  "row_count_clean": 85,
  "summary": {
    "total_spend_inr": 1339923.0,
    "total_spend_usd": 74185.14,
    "anomaly_count": 15,
    "risk_level": "high",
    "top_merchants": [{"merchant": "IRCTC", "total": 450697.69}]
  }
}
```

---

### `GET /jobs/{job_id}/results`
Full structured output: cleaned transactions, flagged anomalies, category breakdown, narrative.
```bash
curl http://localhost:8000/jobs/7c56b768-bd21-4d23-ac00-f0aed4584673/results
```

---

### `GET /jobs`
List all jobs. Supports `?status=` filter.
```bash
curl http://localhost:8000/jobs
curl "http://localhost:8000/jobs?status=completed"
```

---

## 🔬 Processing Pipeline

### Step 1 — Data Cleaning
| Issue | Fix |
|---|---|
| Mixed dates (`DD-MM-YYYY`, `YYYY/MM/DD`) | Normalized to ISO 8601 |
| Amount with `$` prefix | Stripped to plain float |
| Inconsistent `status`/`currency` casing | Uppercased |
| Blank `category` | Filled with `"Uncategorised"` |
| Exact duplicate rows | Dropped |

### Step 2 — Anomaly Detection
- **Statistical outlier**: `amount > 3 × median(amount)` for the same `account_id`
- **Cross-border domestic brand**: `currency = USD` but merchant is Swiggy, Ola, IRCTC, Zomato, MakeMyTrip, etc.

### Step 3 — LLM Classification (Gemini 1.5 Flash)
- Batches uncategorised transactions (20 per call) — never one call per row
- Categories: `Food`, `Shopping`, `Travel`, `Transport`, `Utilities`, `Cash Withdrawal`, `Entertainment`, `Other`
- Exponential backoff retry (2s → 4s → 8s); marks `llm_failed=true` gracefully on failure

### Step 4 — LLM Narrative Summary
- Single call producing: total spend by currency, top 3 merchants, anomaly count, 2–3 sentence narrative, `risk_level` (low / medium / high)

---

## 🗄️ Database Schema

```
┌─────────────────────────┐       ┌──────────────────────────────┐
│          jobs           │       │        transactions           │
├─────────────────────────┤       ├──────────────────────────────┤
│ id          UUID  PK    │──┐    │ id           INT   PK        │
│ filename    VARCHAR     │  │    │ job_id       UUID  FK        │
│ status      VARCHAR IDX │  └───▶│ txn_id       VARCHAR         │
│ row_count_raw  INT      │       │ date         VARCHAR         │
│ row_count_clean INT     │       │ merchant     VARCHAR         │
│ created_at  TIMESTAMP   │       │ amount       NUMERIC         │
│ completed_at TIMESTAMP  │       │ currency     VARCHAR         │
│ error_message TEXT      │       │ status       VARCHAR         │
└─────────────────────────┘       │ category     VARCHAR         │
            │                     │ account_id   VARCHAR  IDX    │
            │                     │ is_anomaly   BOOLEAN         │
            │                     │ anomaly_reason TEXT          │
            │                     │ llm_category VARCHAR         │
            │                     │ llm_failed   BOOLEAN         │
            │                     └──────────────────────────────┘
            │
            │          ┌──────────────────────────────┐
            │          │        job_summaries          │
            │          ├──────────────────────────────┤
            └─────────▶│ id           INT   PK        │
                       │ job_id       UUID  FK        │
                       │ total_spend_inr NUMERIC      │
                       │ total_spend_usd NUMERIC      │
                       │ top_merchants   JSONB        │
                       │ anomaly_count   INT          │
                       │ narrative       TEXT         │
                       │ risk_level      VARCHAR      │
                       └──────────────────────────────┘
```

---

## ⚠️ Scalability — Bottlenecks & Fixes

| Bottleneck | Breaks at 100× Because | Production Fix |
|---|---|---|
| **In-memory CSV parsing** | Entire file loaded into Pandas on the worker; large files OOM the container | Stream upload to S3/GCS; worker reads in chunks via `pd.read_csv(chunksize=1000)` |
| **DB connection pool** | SQLAlchemy pool (10 connections) exhausted under concurrent load | Add **PgBouncer** as connection pooler; index `account_id` and `job_id` |
| **LLM rate limits** | Gemini free tier enforces RPM/TPM limits; bulk batches trigger HTTP 429 | Token-bucket rate limiter at Celery layer; async task throttling via `celery beat` |
| **Single worker** | One worker processes one job at a time; queue backs up | Horizontal worker replicas: `docker compose --scale worker=N`; separate priority queues |

---

## 📁 Project Structure

```
ai-txn-pipeline/
├── app/
│   ├── main.py                 # FastAPI routes (4 endpoints)
│   ├── config.py               # pydantic-settings env config
│   ├── database.py             # Async SQLAlchemy engine + session
│   ├── models.py               # ORM: Job, Transaction, JobSummary
│   ├── schemas.py              # Pydantic v2 request/response schemas
│   ├── tasks.py                # Celery app + pipeline orchestration
│   └── services/
│       ├── data_cleaner.py     # Date/amount/status normalization
│       ├── anomaly_detector.py # Statistical + cross-border detection
│       └── llm_processor.py   # Gemini batched calls + retry logic
├── docker-compose.yml          # 4-service orchestration
├── Dockerfile                  # Multi-stage Python 3.11 slim
├── entrypoint.sh               # Wait-for-db + web/worker branching
├── requirements.txt
├── transactions.csv            # Sample data
└── .env.example                # Template — copy to .env and add GEMINI_API_KEY
```

---

## 🔗 Architecture Diagram
[View on draw.io](https://drive.google.com/file/d/1PI2sSve6rY_eP6aFw90js1BhCY6ytIFk/view)

## 📹 Technical Walkthrough
[Watch on Loom](https://www.loom.com/share/1ed1bf90b2064358980c03ddd6a4ebf9) 
