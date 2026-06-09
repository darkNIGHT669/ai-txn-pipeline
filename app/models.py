import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, Numeric,
    String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------

class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )  # pending | processing | completed | failed
    row_count_raw: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    row_count_clean: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction", back_populates="job", cascade="all, delete-orphan"
    )
    summary: Mapped[Optional["JobSummary"]] = relationship(
        "JobSummary", back_populates="job", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Job id={self.id} status={self.status}>"


# ---------------------------------------------------------------------------
# Transaction
# ---------------------------------------------------------------------------

class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Raw / cleaned fields
    txn_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)   # ISO 8601 string
    merchant: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)

    # Anomaly
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    anomaly_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # LLM
    llm_category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    llm_raw_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    llm_failed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationship
    job: Mapped["Job"] = relationship("Job", back_populates="transactions")

    def __repr__(self) -> str:
        return f"<Transaction id={self.id} txn_id={self.txn_id} amount={self.amount}>"


# ---------------------------------------------------------------------------
# JobSummary
# ---------------------------------------------------------------------------

class JobSummary(Base):
    __tablename__ = "job_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )

    total_spend_inr: Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)
    total_spend_usd: Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)
    top_merchants: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)  # [{merchant, total}]
    anomaly_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    narrative: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risk_level: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # low|medium|high

    # Relationship
    job: Mapped["Job"] = relationship("Job", back_populates="summary")

    def __repr__(self) -> str:
        return f"<JobSummary job_id={self.job_id} risk_level={self.risk_level}>"
