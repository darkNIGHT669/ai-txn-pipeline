"""
Anomaly detection service.

Two detection rules:
  1. Statistical outlier  – amount > 3× median for the same account_id.
  2. Cross-border anomaly – currency is USD but merchant is a domestic-only Indian brand.
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

# Known domestic-only Indian brands (case-insensitive prefix match)
DOMESTIC_BRANDS: set[str] = {
    "swiggy",
    "ola",
    "irctc",
    "zomato",
    "bigbasket",
    "dunzo",
    "blinkit",
    "zepto",
    "myntra",
    "nykaa",
    "meesho",
    "jiomart",
    "phonepe",
    "paytm",
    "gpay",
    "bookmyshow",
    "makemytrip",
    "goibibo",
    "yatra",
    "redbus",
}


def _is_domestic_brand(merchant: str) -> bool:
    if not isinstance(merchant, str):
        return False
    return merchant.strip().lower() in DOMESTIC_BRANDS


def detect_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add / update `is_anomaly` and `anomaly_reason` columns in-place (returns copy).

    Rule 1 – Statistical outlier:
        amount > 3 × median(amount) for the same account_id.

    Rule 2 – Cross-border domestic brand:
        currency == 'USD' AND merchant is a domestic-only brand.
    """
    df = df.copy()

    if "is_anomaly" not in df.columns:
        df["is_anomaly"] = False
    if "anomaly_reason" not in df.columns:
        df["anomaly_reason"] = None

    # ── Rule 1: statistical outlier ─────────────────────────────────────────
    median_by_account = (
        df.groupby("account_id")["amount"]
        .median()
        .rename("median_amount")
    )
    df = df.join(median_by_account, on="account_id")

    stat_mask = df["amount"] > (3 * df["median_amount"])
    stat_count = stat_mask.sum()
    if stat_count:
        logger.info("Flagged %d statistical outlier(s)", stat_count)

    df.loc[stat_mask, "is_anomaly"] = True
    df.loc[stat_mask, "anomaly_reason"] = df.loc[stat_mask].apply(
        lambda r: (
            f"Amount {r['amount']:.2f} exceeds 3× account median "
            f"({r['median_amount']:.2f}) for account {r['account_id']}"
        ),
        axis=1,
    )

    df.drop(columns=["median_amount"], inplace=True)

    # ── Rule 2: cross-border domestic brand ─────────────────────────────────
    cross_mask = (df["currency"] == "USD") & df["merchant"].apply(_is_domestic_brand)
    cross_count = cross_mask.sum()
    if cross_count:
        logger.info("Flagged %d cross-border domestic brand anomaly(ies)", cross_count)

    # Append reason (a row can trigger both rules)
    def _append_cross_reason(row: pd.Series) -> str:
        base = row["anomaly_reason"] or ""
        extra = (
            f"Currency is USD but '{row['merchant']}' is a domestic-only Indian brand"
        )
        return f"{base}; {extra}".lstrip("; ") if base else extra

    df.loc[cross_mask, "is_anomaly"] = True
    df.loc[cross_mask, "anomaly_reason"] = df.loc[cross_mask].apply(
        _append_cross_reason, axis=1
    )

    return df
