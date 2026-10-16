"""Historical data range (six months to all, with future month rollover)."""
import importlib.util
from dataclasses import dataclass
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1] / 'custom_components' / 'viwaco_reader'
spec = importlib.util.spec_from_file_location('viwaco_history_tests', ROOT / 'history.py')
history = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = history
spec.loader.exec_module(history)


@dataclass(frozen=True)
class Item:
    year: int
    month: int


@dataclass(frozen=True)
class Data:
    invoices: tuple
    readings: tuple
    customer: str = '001'


def source():
    # Installation record in 2018 is older than first bill.
    return Data(
        invoices=tuple(Item(y, m) for y in range(2019, 2027)
                       for m in range(1, 13) if y != 2026 or m <= 10),
        readings=(Item(2018,9), Item(2018,12), Item(2026,10)),
    )


def test_span_is_calendar_months_even_with_gaps():
    assert history.available_month_span(source()) == 98  # Sep 2018 .. Oct 2026


def test_six_months_contains_may_through_october_2026():
    d = history.selected_history(source(), 6)
    assert [(i.year, i.month) for i in d.invoices] == [
        (2026,m) for m in (5,6,7,8,9,10)
    ]
    assert [(r.year, r.month) for r in d.readings] == [(2026,10)]
    assert d.customer == '001'


def test_all_is_open_ended_including_future_months():
    d = source()
    assert history.selected_history(d, 0) is d
    more = Data(invoices=(Item(2026,11),)+d.invoices, readings=d.readings)
    assert history.selected_history(more, 0) is more
    assert history.selected_history(more, 6).invoices[0].month == 11


def test_twelve_months_does_not_take_twelve_rows_when_gaps():
    d = Data(invoices=(Item(2026,10),Item(2026,7),Item(2025,11)), readings=(Item(2026,10),))
    assert [(i.year,i.month) for i in history.selected_history(d, 6).invoices] == [(2026,10),(2026,7)]


def test_empty_and_readings_only():
    d = Data((),())
    assert history.available_month_span(d) == 0
    assert history.selected_history(d, 6) == d
    d2 = Data((),(Item(2026,10),Item(2026,1)))
    assert history.selected_history(d2, 6).readings == (Item(2026,10),)


def test_reject_invalid_range():
    for n in (-1,1,5):
        with pytest.raises(ValueError): history.selected_history(source(), n)


def test_two_accounts_do_not_interfere():
    a = source()
    b = Data((Item(2026,10), Item(2026,9)), (Item(2026,10),), '002')
    assert len(history.selected_history(a,6).invoices) == 6
    assert len(history.selected_history(b,6).invoices) == 2
    assert len(history.selected_history(a,0).invoices) > 6
