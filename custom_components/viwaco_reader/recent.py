"""Pure helpers for the latest three *invoiced* months, matched to meter readings.

Using invoice billing periods rather than positional indices prevents inaccurate
combinations when an invoice is published later than a reading or a month has
more than one meter-reading event.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .parser import Invoice, Reading, ViwacoData


def latest_billing_periods(data: ViwacoData, count: int = 3) -> list[tuple[Invoice, Reading | None]]:
    """Pair each unique billed month with the latest regular reading in that month."""
    readings = {}
    for r in sorted(data.readings, key=lambda v: v.read_date, reverse=True):
        key = (r.year, r.month)
        # Ignore installation-only entries when a regular reading exists.
        if key not in readings or readings[key].reading_type.lower() == "lắp mới":
            readings[key] = r
    invoices = sorted(data.invoices, key=lambda v: (v.year, v.month), reverse=True)
    result = []
    seen = set()
    for invoice in invoices:
        key = (invoice.year, invoice.month)
        if key in seen:
            continue
        seen.add(key)
        result.append((invoice, readings.get(key)))
        if len(result) >= count:
            break
    return result
