# AI-Powered Transaction Processing Pipeline

A production-ready, containerised backend that ingests dirty financial CSVs, cleans them, detects anomalies, classifies transactions with an LLM, and returns a structured summary — all processed asynchronously through a job queue.

---

## Architecture

```
Client
  │
  ▼
FastAPI (port 8000)
  │  POST /jobs/upload → saves CSV → creates Job (pending) → enqueues task
  │
  ▼
Redis (broker + result backend)
  │
  ▼
Celery Worker
  │  1. Data Cleaning      (pandas)
  │  2. Anomaly Detection  (statistical + cross-border)
  │  3. LLM Classification (Gemini 1.5 Flash — batched)
  │  4. LLM Narrative      (Gemini 1.5 Flash — single call)
  │  5. Persist results
  ▼
PostgreSQL
  └── jobs, transactions, job_summaries
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI 0.111 + Pydantic v2 |
| Database | PostgreSQL 16 + SQLAlchemy 2 (async) |
| Job Queue | Celery 5 + Redis 7 |
| LLM | Google Gemini 1.5 Flash |
| Containerisation | Docker + Docker Compose |

---

## Quick Start

### 1. Prerequisites
- Docker Desktop (or Docker Engine + Compose plugin)
- A free [Google AI Studio](https://aistudio.google.com/app/apikey) API key

### 2. Clone & Configure

```bash
git clone <your-repo-url>
cd ai-txn-pipeline
cp .env.example .env
# Edit .env and set GEMINI_API_KEY=<your key>
```

### 3. Boot the stack

```bash
docker compose up --build
```

That's it. All four services (web, worker, redis, db) start, health checks pass, and the API is ready at `http://localhost:8000`.

---

## API Reference

### Upload a CSV
```bash
curl -X POST http://localhost:8000/jobs/upload \
  -F "file=@transactions.csv"
```

Response:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "filename": "transactions.csv",
  "message": "Job enqueued successfully"
}
```

---

### Poll job status
```bash
curl http://localhost:8000/jobs/550e8400-e29b-41d4-a716-446655440000/status
```

Response when completed:
```json
{
  "job_id": "550e8400-...",
  "status": "completed",
  "row_count_raw": 90,
  "row_count_clean": 87,
  "summary": {
    "total_spend_inr": 450000.00,
    "total_spend_usd": 3200.00,
    "anomaly_count": 4,
    "risk_level": "medium",
    "narrative": "The account shows elevated spending across Food and Shopping categories...",
    "top_merchants": [{"merchant": "Amazon", "total": 85000}]
  }
}
```

---

### Get full results
```bash
curl http://localhost:8000/jobs/550e8400-e29b-41d4-a716-446655440000/results
```

Returns:
- `transactions[]` — all cleaned transactions with LLM categories
- `anomalies[]` — subset flagged as anomalous
- `category_breakdown[]` — spend totals per category
- `summary` — LLM narrative + risk level

---

### List all jobs
```bash
# All jobs
curl http://localhost:8000/jobs

# Filter by status
curl "http://localhost:8000/jobs?status=completed"
curl "http://localhost:8000/jobs?status=failed"
```

---

### Health check
```bash
curl http://localhost:8000/health
```

---

## Processing Pipeline Details

### Data Cleaning
- Normalises `DD-MM-YYYY` and `YYYY/MM/DD` dates → ISO 8601
- Strips `$` and other currency symbols from amounts
- Uppercases `status` and `currency` fields
- Fills blank `category` with `"Uncategorised"`
- Removes exact duplicate rows

### Anomaly Detection
- **Statistical outlier**: `amount > 3 × median(amount)` for the same `account_id`
- **Cross-border domestic brand**: `currency = USD` but merchant is Swiggy, Ola, IRCTC, Zomato, etc.

### LLM Classification (Gemini 1.5 Flash)
- Batches uncategorised transactions (20 per call)
- Categories: Food, Shopping, Travel, Transport, Utilities, Cash Withdrawal, Entertainment, Other
- Exponential backoff retry (up to 3 attempts); if all fail, row is marked `llm_failed=true`

### LLM Narrative (single call)
- Generates JSON with total spend breakdown, top 3 merchants, anomaly count, 2–3 sentence narrative, and `risk_level` (low/medium/high)

---

## Scalability Considerations

| Bottleneck | Current | Fix at 100× |
|---|---|---|
| File ingestion | In-memory pandas | Stream upload to S3; chunked CSV parse in worker |
| DB connections | SQLAlchemy pool (10) | Add PgBouncer; tune `pool_size` |
| LLM rate limits | Sequential batches | Token-bucket rate limiter at worker layer; async Celery beat |
| Single worker | 2 concurrent tasks | Horizontal Celery worker replicas; task routing |

---

## Project Structure

```
ai-txn-pipeline/
├── app/
│   ├── main.py           # FastAPI routes
│   ├── config.py         # Settings (pydantic-settings)
│   ├── database.py       # Async SQLAlchemy engine
│   ├── models.py         # ORM: Job, Transaction, JobSummary
│   ├── schemas.py        # Pydantic v2 request/response schemas
│   ├── tasks.py          # Celery task + pipeline orchestration
│   └── services/
│       ├── data_cleaner.py     # CSV normalisation
│       ├── anomaly_detector.py # Outlier & cross-border detection
│       └── llm_processor.py    # Gemini batched calls + narrative
├── docker-compose.yml
├── Dockerfile
├── entrypoint.sh         # Wait-for-db + start web or worker
├── requirements.txt
├── transactions.csv      # Sample data
└── .env.example
```
