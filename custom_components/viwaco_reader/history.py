"""Calendar month window for independently configured VIWACO customer entries.

The VIWACO HTML endpoints do not support server-side date/month filters.
Both pages must be downloaded in full, then history is filtered in memory.
A stored value of zero is an open-ended "all history, including future months".
"""
from __future__ import annotations
from dataclasses import replace

MIN_HISTORY_MONTHS = 6
ALL_HISTORY_MONTHS = 0


def _month_index(item) -> int:
    return item.year * 12 + item.month - 1


def available_month_span(data) -> int:
    """Span of source calendar months (including gaps), not number of rows."""
    periods = [_month_index(i) for i in (*data.invoices, *data.readings)]
    return max(periods) - min(periods) + 1 if periods else 0


def selected_history(data, months: int):
    """Keep at most the last `months` calendar months relative to latest source period."""
    months = int(months)
    if months == ALL_HISTORY_MONTHS:
        return data
    if months < MIN_HISTORY_MONTHS:
        raise ValueError("History window must be at least 6 months or 0 (all)")
    periods = [_month_index(i) for i in (*data.invoices, *data.readings)]
    if not periods:
        return data
    cutoff = max(periods) - months + 1
    return replace(
        data,
        invoices=tuple(item for item in data.invoices if _month_index(item) >= cutoff),
        readings=tuple(item for item in data.readings if _month_index(item) >= cutoff),
    )
