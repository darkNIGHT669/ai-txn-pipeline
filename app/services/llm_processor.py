"""
LLM processing service.

Responsibilities:
  1. Batch-classify uncategorised transactions using Gemini 1.5 Flash.
  2. Generate a single JSON narrative summary for the entire job.
  3. Wrap every LLM call with exponential-backoff retry (up to 3 attempts).
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

import pandas as pd

from app.config import settings

logger = logging.getLogger(__name__)

# Allowed categories the LLM must choose from
VALID_CATEGORIES = {
    "Food", "Shopping", "Travel", "Transport",
    "Utilities", "Cash Withdrawal", "Entertainment", "Other",
}

# Batch size: number of transactions sent in one LLM call
BATCH_SIZE = 20


# ---------------------------------------------------------------------------
# Low-level Gemini helper
# ---------------------------------------------------------------------------

def _get_gemini_model():
    """Lazy-import and configure the Gemini generative model."""
    import google.generativeai as genai  # type: ignore
    genai.configure(api_key=settings.GEMINI_API_KEY)
    return genai.GenerativeModel(settings.GEMINI_MODEL)


def _call_with_retry(prompt: str) -> Optional[str]:
    """
    Call Gemini with exponential-backoff retry.

    Returns the raw text response or None if all retries fail.
    """
    delay = settings.LLM_RETRY_BASE_DELAY
    last_error: Optional[Exception] = None

    for attempt in range(1, settings.LLM_MAX_RETRIES + 1):
        try:
            model = _get_gemini_model()
            response = model.generate_content(prompt)
            return response.text
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning(
                "Gemini call failed (attempt %d/%d): %s",
                attempt, settings.LLM_MAX_RETRIES, exc,
            )
            if attempt < settings.LLM_MAX_RETRIES:
                time.sleep(delay)
                delay *= 2  # exponential backoff

    logger.error("All %d Gemini retries exhausted. Last error: %s", settings.LLM_MAX_RETRIES, last_error)
    return None


# ---------------------------------------------------------------------------
# Category classification
# ---------------------------------------------------------------------------

def _build_classification_prompt(rows: list[dict]) -> str:
    """
    Build a batch classification prompt.

    Rows are passed as a compact JSON list so the model maps each index to a category.
    """
    row_list = [
        {"index": i, "merchant": r.get("merchant", ""), "amount": r.get("amount", 0)}
        for i, r in enumerate(rows)
    ]
    categories_str = ", ".join(sorted(VALID_CATEGORIES))
    return f"""
You are a financial transaction categorisation engine.
Classify each transaction below into EXACTLY ONE of these categories:
{categories_str}

Transactions (JSON list):
{json.dumps(row_list, indent=2)}

Respond with ONLY a JSON array of objects in this exact format, no extra text:
[{{"index": 0, "category": "Food"}}, {{"index": 1, "category": "Shopping"}}, ...]

Rules:
- Use only the provided category names (exact casing).
- If unsure, use "Other".
- Do not include any explanation or markdown.
""".strip()


def classify_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """
    For rows where category == 'Uncategorised', call Gemini in batches and
    fill in `llm_category`.  Sets `llm_failed=True` if a batch fails entirely.
    """
    df = df.copy()
    if "llm_category" not in df.columns:
        df["llm_category"] = None
    if "llm_failed" not in df.columns:
        df["llm_failed"] = False
    if "llm_raw_response" not in df.columns:
        df["llm_raw_response"] = None

    uncategorised_idx = df.index[df["category"] == "Uncategorised"].tolist()
    if not uncategorised_idx:
        logger.info("No uncategorised transactions; skipping LLM classification.")
        return df

    logger.info("Classifying %d uncategorised transaction(s) in batches of %d",
                len(uncategorised_idx), BATCH_SIZE)

    for batch_start in range(0, len(uncategorised_idx), BATCH_SIZE):
        batch_idx = uncategorised_idx[batch_start: batch_start + BATCH_SIZE]
        rows = df.loc[batch_idx, ["merchant", "amount"]].to_dict("records")

        prompt = _build_classification_prompt(rows)
        raw = _call_with_retry(prompt)

        if raw is None:
            # Mark entire batch as failed; pipeline continues
            df.loc[batch_idx, "llm_failed"] = True
            logger.error("Batch %d failed; marked llm_failed=True.", batch_start // BATCH_SIZE)
            continue

        # Store raw response on first row of batch for debugging
        df.loc[batch_idx[0], "llm_raw_response"] = raw[:2000]  # truncate for DB

        try:
            # Strip possible markdown fences
            clean_raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            results: list[dict] = json.loads(clean_raw)
            for item in results:
                local_idx = item.get("index")
                category = item.get("category", "Other")
                if local_idx is None or local_idx >= len(batch_idx):
                    continue
                if category not in VALID_CATEGORIES:
                    category = "Other"
                df.loc[batch_idx[local_idx], "llm_category"] = category
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.error("Failed to parse LLM classification response: %s — %s", exc, raw[:500])
            df.loc[batch_idx, "llm_failed"] = True

    return df


# ---------------------------------------------------------------------------
# Narrative summary
# ---------------------------------------------------------------------------

def _build_narrative_prompt(df: pd.DataFrame, anomaly_count: int) -> str:
    total_inr = float(df.loc[df["currency"] == "INR", "amount"].sum())
    total_usd = float(df.loc[df["currency"] == "USD", "amount"].sum())

    top_merchants_series = (
        df.groupby("merchant")["amount"].sum().nlargest(3)
    )
    top_merchants = [
        {"merchant": m, "total": round(float(v), 2)}
        for m, v in top_merchants_series.items()
    ]

    category_col = df["llm_category"].fillna(df["category"])
    category_breakdown = (
        df.assign(effective_category=category_col)
        .groupby("effective_category")["amount"]
        .sum()
        .round(2)
        .to_dict()
    )

    return f"""
You are a financial analyst AI. Generate a structured JSON summary for the following batch of transactions.

Context:
- Total transactions: {len(df)}
- Total spend INR: {total_inr:.2f}
- Total spend USD: {total_usd:.2f}
- Top 3 merchants by spend: {json.dumps(top_merchants)}
- Anomaly count: {anomaly_count}
- Category breakdown: {json.dumps(category_breakdown)}

Respond with ONLY a valid JSON object in this exact format (no markdown, no extra text):
{{
  "total_spend_inr": <number>,
  "total_spend_usd": <number>,
  "top_merchants": [{{"merchant": "...", "total": <number>}}, ...],
  "anomaly_count": <number>,
  "narrative": "<2-3 sentence qualitative spending summary>",
  "risk_level": "<low|medium|high>"
}}

Risk level guidelines:
- high: anomaly_count >= 5 OR any single transaction > 50000 INR
- medium: anomaly_count 2-4 OR transactions with unusual patterns
- low: clean data, no significant anomalies
""".strip()


def generate_narrative(df: pd.DataFrame, anomaly_count: int) -> Optional[dict[str, Any]]:
    """
    Generate a single structured JSON narrative summary for the entire job.
    Returns a parsed dict or None if the LLM call fails.
    """
    prompt = _build_narrative_prompt(df, anomaly_count)
    raw = _call_with_retry(prompt)

    if raw is None:
        logger.error("Narrative generation failed after all retries.")
        return None

    try:
        clean_raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        result = json.loads(clean_raw)
        # Validate risk_level
        if result.get("risk_level") not in {"low", "medium", "high"}:
            result["risk_level"] = "low"
        return result
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("Failed to parse narrative response: %s — %s", exc, raw[:500])
        return None
