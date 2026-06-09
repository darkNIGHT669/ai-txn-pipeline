"""
Celery task definitions.

The `process_job` task orchestrates the full pipeline:
  1. Data Cleaning
  2. Anomaly Detection
  3. LLM Category Classification
  4. LLM Narrative Summary
  5. Persist results to PostgreSQL
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

import pandas as pd
from celery import Celery
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.services.data_cleaner import clean_dataframe
from app.services.anomaly_detector import detect_anomalies
from app.services.llm_processor import classify_transactions, generate_narrative

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Celery application
# ---------------------------------------------------------------------------

celery_app = Celery(
    "txn_pipeline",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,   # process one job at a time per worker
    task_acks_late=True,            # ack only after successful completion
)


# ---------------------------------------------------------------------------
# Synchronous SQLAlchemy session (Celery workers are sync)
# ---------------------------------------------------------------------------

def _get_sync_session() -> Session:
    engine = create_engine(
        settings.DATABASE_URL_SYNC,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return factory()


# ---------------------------------------------------------------------------
# Helper: update job status
# ---------------------------------------------------------------------------

def _set_job_status(session: Session, job_id: uuid.UUID, status: str, **kwargs):
    from app.models import Job  # local import to avoid circular issues

    stmt = (
        update(Job)
        .where(Job.id == job_id)
        .values(status=status, **kwargs)
    )
    session.execute(stmt)
    session.commit()


# ---------------------------------------------------------------------------
# Main pipeline task
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, name="tasks.process_job", max_retries=0)
def process_job(self, job_id_str: str, file_path: str):
    """
    Full processing pipeline for a single uploaded CSV job.
    """
    from app.models import Job, Transaction, JobSummary  # local import

    job_id = uuid.UUID(job_id_str)
    session = _get_sync_session()

    try:
        # ── Mark job as processing ────────────────────────────────────────
        _set_job_status(session, job_id, "processing")
        logger.info("[Job %s] Pipeline started. File: %s", job_id, file_path)

        # ── Step 1: Load CSV ──────────────────────────────────────────────
        df_raw = pd.read_csv(file_path, dtype=str)
        row_count_raw = len(df_raw)
        logger.info("[Job %s] Loaded %d raw rows", job_id, row_count_raw)

        # ── Step 2: Data Cleaning ─────────────────────────────────────────
        df_clean = clean_dataframe(df_raw)
        row_count_clean = len(df_clean)
        logger.info("[Job %s] %d rows after cleaning", job_id, row_count_clean)

        # Cast amount to numeric after cleaning
        df_clean["amount"] = pd.to_numeric(df_clean["amount"], errors="coerce")

        # ── Step 3: Anomaly Detection ─────────────────────────────────────
        df_clean = detect_anomalies(df_clean)
        anomaly_count = int(df_clean["is_anomaly"].sum())
        logger.info("[Job %s] %d anomalies detected", job_id, anomaly_count)

        # ── Step 4: LLM Classification ────────────────────────────────────
        df_clean = classify_transactions(df_clean)

        # ── Step 5: LLM Narrative Summary ─────────────────────────────────
        narrative_data = generate_narrative(df_clean, anomaly_count)

        # ── Step 6: Persist Transactions ──────────────────────────────────
        transactions = []
        for _, row in df_clean.iterrows():
            t = Transaction(
                job_id=job_id,
                txn_id=_safe_str(row.get("txn_id")),
                date=_safe_str(row.get("date")),
                merchant=_safe_str(row.get("merchant")),
                amount=_safe_float(row.get("amount")),
                currency=_safe_str(row.get("currency")),
                status=_safe_str(row.get("status")),
                category=_safe_str(row.get("category")),
                account_id=_safe_str(row.get("account_id")),
                is_anomaly=bool(row.get("is_anomaly", False)),
                anomaly_reason=_safe_str(row.get("anomaly_reason")),
                llm_category=_safe_str(row.get("llm_category")),
                llm_raw_response=_safe_str(row.get("llm_raw_response")),
                llm_failed=bool(row.get("llm_failed", False)),
            )
            transactions.append(t)

        session.bulk_save_objects(transactions)
        session.flush()

        # ── Step 7: Persist Summary ───────────────────────────────────────
        summary = JobSummary(
            job_id=job_id,
            total_spend_inr=narrative_data.get("total_spend_inr") if narrative_data else _calc_spend(df_clean, "INR"),
            total_spend_usd=narrative_data.get("total_spend_usd") if narrative_data else _calc_spend(df_clean, "USD"),
            top_merchants=narrative_data.get("top_merchants") if narrative_data else _calc_top_merchants(df_clean),
            anomaly_count=anomaly_count,
            narrative=narrative_data.get("narrative") if narrative_data else None,
            risk_level=narrative_data.get("risk_level") if narrative_data else _infer_risk(anomaly_count),
        )
        session.add(summary)

        # ── Step 8: Mark job completed ────────────────────────────────────
        _set_job_status(
            session, job_id, "completed",
            row_count_raw=row_count_raw,
            row_count_clean=row_count_clean,
            completed_at=datetime.now(timezone.utc),
        )
        session.commit()
        logger.info("[Job %s] Pipeline completed successfully.", job_id)

    except Exception as exc:
        session.rollback()
        logger.exception("[Job %s] Pipeline failed: %s", job_id, exc)
        _set_job_status(
            session, job_id, "failed",
            error_message=str(exc)[:1000],
            completed_at=datetime.now(timezone.utc),
        )
        raise
    finally:
        # Clean up temp file
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError:
            pass
        session.close()


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _safe_str(val) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    return s if s else None


def _safe_float(val) -> float | None:
    try:
        f = float(val)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def _calc_spend(df: pd.DataFrame, currency: str) -> float:
    return float(df.loc[df["currency"] == currency, "amount"].sum())


def _calc_top_merchants(df: pd.DataFrame) -> list[dict]:
    top = df.groupby("merchant")["amount"].sum().nlargest(3)
    return [{"merchant": m, "total": round(float(v), 2)} for m, v in top.items()]


def _infer_risk(anomaly_count: int) -> str:
    if anomaly_count >= 5:
        return "high"
    if anomaly_count >= 2:
        return "medium"
    return "low"
