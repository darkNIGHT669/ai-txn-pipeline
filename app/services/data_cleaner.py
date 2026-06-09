"""
Data cleaning and normalisation service.

Handles:
- Multi-format date parsing → ISO 8601
- Amount string normalisation (strip $ etc.)
- Status & currency uppercasing
- Missing category fill
- Exact duplicate removal
"""
from __future__ import annotations

import re
import logging
from datetime import datetime
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Supported date formats to try in order
_DATE_FORMATS = [
    "%d-%m-%Y",   # DD-MM-YYYY
    "%Y/%m/%d",   # YYYY/MM/DD
    "%Y-%m-%d",   # ISO 8601 (already clean)
    "%m/%d/%Y",   # MM/DD/YYYY (edge case)
]


def _parse_date(raw: str) -> Optional[str]:
    """Try each known format; return ISO 8601 string or None."""
    if not raw or not isinstance(raw, str):
        return None
    raw = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    logger.warning("Could not parse date: %r", raw)
    return raw  # keep raw if unparseable; don't discard the row


def _clean_amount(raw) -> Optional[float]:
    """Strip currency symbols and whitespace, then cast to float."""
    if pd.isna(raw):
        return None
    cleaned = re.sub(r"[^\d.\-]", "", str(raw).strip())
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        logger.warning("Could not parse amount: %r", raw)
        return None


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply all cleaning steps and return a new, clean DataFrame.

    Steps:
    1. Normalise date formats to ISO 8601.
    2. Clean amount strings.
    3. Uppercase status & currency.
    4. Fill missing categories.
    5. Drop exact duplicate rows.
    """
    df = df.copy()

    # 1. Dates
    df["date"] = df["date"].apply(_parse_date)

    # 2. Amounts
    df["amount"] = df["amount"].apply(_clean_amount)

    # 3. Uppercase status & currency
    df["status"] = df["status"].str.strip().str.upper()
    df["currency"] = df["currency"].str.strip().str.upper()

    # 4. Fill missing categories
    df["category"] = df["category"].fillna("Uncategorised")
    df.loc[df["category"].str.strip() == "", "category"] = "Uncategorised"

    # 5. Normalise merchant & account_id whitespace
    df["merchant"] = df["merchant"].str.strip()
    df["account_id"] = df["account_id"].str.strip()

    # 6. Drop exact duplicate rows (all columns)
    before = len(df)
    df = df.drop_duplicates()
    dropped = before - len(df)
    if dropped:
        logger.info("Dropped %d duplicate row(s)", dropped)

    df = df.reset_index(drop=True)
    return df
