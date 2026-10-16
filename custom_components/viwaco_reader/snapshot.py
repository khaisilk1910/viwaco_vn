"""Versioned persistent snapshot (no Cookie/token/VIEWSTATE, never in /www)."""
from __future__ import annotations

from dataclasses import fields
from datetime import date, datetime, timezone
from urllib.parse import urlsplit
from .parser import CustomerInfo, Invoice, Reading, ViwacoData

VERSION = 1


def _row(item) -> dict:
    result = {}
    for fld in fields(item):
        value = getattr(item, fld.name)
        result[fld.name] = value.isoformat() if isinstance(value, date) else value
    return result


def encode_snapshot(data: ViwacoData) -> dict:
    """Build JSON-compatible cache representing *all selected* billing months."""
    return {
        "version": VERSION,
        "customer_id": data.customer.customer_id,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "customer": _row(data.customer),
        "invoices": [_row(i) for i in data.invoices],
        "readings": [_row(r) for r in data.readings],
    }


def decode_snapshot(raw: dict, expected_customer: str) -> ViwacoData:
    """Reject corrupt or cross-customer snapshots and malformed dates."""
    if not isinstance(raw, dict) or raw.get("version") != VERSION or raw.get("customer_id") != expected_customer:
        raise ValueError("Invalid snapshot version or customer")
    customer = CustomerInfo(**raw["customer"])
    if customer.customer_id != expected_customer:
        raise ValueError("Snapshot customer mismatch")
    if not isinstance(raw["invoices"], list) or not isinstance(raw["readings"], list):
        raise ValueError("Invalid snapshot lists")
    if len(raw["invoices"]) > 500 or len(raw["readings"]) > 600:
        raise ValueError("Snapshot too large")
    invoices = []
    for obj in raw["invoices"]:
        record = dict(obj)
        for key in ("start_date", "end_date", "payment_date"):
            record[key] = date.fromisoformat(record[key]) if record.get(key) else None
        if record.get("invoice_url"):
            url = urlsplit(record["invoice_url"])
            if url.scheme != "https" or url.netloc != "hoadon.viwaco.vn":
                record["invoice_url"] = None
        invoices.append(Invoice(**record))
    readings = []
    for obj in raw["readings"]:
        record = dict(obj)
        record["read_date"] = date.fromisoformat(record["read_date"])
        readings.append(Reading(**record))
    return ViwacoData(tuple(invoices), tuple(readings), customer)
