"""Regression tests: billing-month alignment, gaps and duplicate meter readings."""
from dataclasses import dataclass
from datetime import date
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1] / 'custom_components' / 'viwaco_reader'
spec = importlib.util.spec_from_file_location('recent_test', ROOT / 'recent.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


@dataclass
class Inv:
    year: int
    month: int
    usage_m3: int
    total_vnd: int
    @property
    def period(self): return f'{self.month:02d}/{self.year}'


@dataclass
class Rd:
    year: int
    month: int
    previous_m3: int
    current_m3: int
    read_date: date
    reading_type: str = 'Định kỳ'


@dataclass
class Data:
    invoices: tuple
    readings: tuple


def sample():
    return Data(
        invoices=(Inv(2026,8,12,120520), Inv(2026,10,17,177445), Inv(2026,9,14,143290)),
        readings=(
            Rd(2026,9,1363,1377,date(2026,9,8)),
            Rd(2026,8,1351,1363,date(2026,8,8)),
            Rd(2026,10,1377,1394,date(2026,10,8)),
        ),
    )


def test_latest_three_invoiced_months_match_correct_readings():
    periods = module.latest_billing_periods(sample())
    assert [i.period for i, _ in periods] == ['10/2026','09/2026','08/2026']
    assert [(i.usage_m3, i.total_vnd, r.previous_m3, r.current_m3) for i,r in periods] == [
        (17,177445,1377,1394), (14,143290,1363,1377), (12,120520,1351,1363)
    ]


def test_missing_reading_does_not_reuse_previous_month():
    d = sample()
    d.readings = tuple(r for r in d.readings if r.month != 9)
    periods = module.latest_billing_periods(d)
    assert periods[1][1] is None
    assert periods[0][1].current_m3 == 1394


def test_duplicate_reading_period_chooses_newest_date():
    d = sample()
    d.readings += (Rd(2026,10,1394,1399,date(2026,10,9)),)
    periods = module.latest_billing_periods(d)
    assert periods[0][1].current_m3 == 1399


def test_newer_reading_without_invoice_is_not_billed_month():
    d = sample()
    d.readings += (Rd(2026,11,1394,1402,date(2026,11,8)),)
    assert module.latest_billing_periods(d)[0][0].period == '10/2026'


def test_no_data_yields_no_periods():
    assert module.latest_billing_periods(Data((),())) == []
