from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Shared / Base
# ---------------------------------------------------------------------------

class OrmBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Job schemas
# ---------------------------------------------------------------------------

class JobCreateResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    filename: str
    message: str = "Job enqueued successfully"


class JobSummaryEmbedded(BaseModel):
    """Lightweight summary embedded in status responses when completed."""
    total_spend_inr: Optional[float] = None
    total_spend_usd: Optional[float] = None
    anomaly_count: int = 0
    risk_level: Optional[str] = None
    narrative: Optional[str] = None
    top_merchants: Optional[Any] = None


class JobStatusResponse(OrmBase):
    job_id: uuid.UUID = Field(alias="id")
    filename: str
    status: str
    row_count_raw: Optional[int] = None
    row_count_clean: Optional[int] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    summary: Optional[JobSummaryEmbedded] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class JobListItem(OrmBase):
    job_id: uuid.UUID = Field(alias="id")
    filename: str
    status: str
    row_count_raw: Optional[int] = None
    row_count_clean: Optional[int] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# Transaction schemas
# ---------------------------------------------------------------------------

class TransactionOut(OrmBase):
    id: int
    txn_id: Optional[str] = None
    date: Optional[str] = None
    merchant: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    status: Optional[str] = None
    category: Optional[str] = None
    account_id: Optional[str] = None
    is_anomaly: bool
    anomaly_reason: Optional[str] = None
    llm_category: Optional[str] = None
    llm_failed: bool


# ---------------------------------------------------------------------------
# Results response
# ---------------------------------------------------------------------------

class CategoryBreakdown(BaseModel):
    category: str
    total_spend: float
    transaction_count: int


class JobResultsResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    row_count_raw: Optional[int]
    row_count_clean: Optional[int]

    transactions: list[TransactionOut]
    anomalies: list[TransactionOut]
    category_breakdown: list[CategoryBreakdown]
    summary: Optional[JobSummaryEmbedded] = None
