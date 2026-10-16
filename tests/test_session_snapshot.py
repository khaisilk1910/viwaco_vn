"""Pure unit tests for v1.5.0 cookie rotation and persistent snapshot.

No Home Assistant installation or real customer credentials required.
"""
from __future__ import annotations

from datetime import date
from http.cookies import SimpleCookie
import importlib
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "viwaco_reader"
# Load pure modules without importing integration __init__ (which requires HA).
PKG = "test_viwaco_v15_pkg"
if PKG not in sys.modules:
    mod = types.ModuleType(PKG)
    mod.__path__ = [str(ROOT)]
    sys.modules[PKG] = mod
session = importlib.import_module(f"{PKG}.session")
snapshot = importlib.import_module(f"{PKG}.snapshot")
parser = importlib.import_module(f"{PKG}.parser")


def invoice():
    return parser.Invoice(
        month=10, year=2026, book="XP52", start_date=date(2026, 9, 9),
        end_date=date(2026, 10, 8), usage_m3=17, total_vnd=177445,
        paid_vnd=177445, payment_date=date(2026, 10, 10), advance_vnd=0,
        invoice_number="INV", invoice_url="https://hoadon.viwaco.vn/tra-cuu/?code=TEST",
    )


def reading():
    return parser.Reading(
        serial="meter-a", year=2026, month=10,
        read_date=date(2026, 10, 8), reading_code="O", previous_m3=1377,
        current_m3=1394, usage_m3=17, reading_type="Định kỳ",
    )


def fixture_data():
    return parser.ViwacoData((invoice(),), (reading(),), parser.CustomerInfo("000000001", "Test User", "Hidden", ""))


def test_set_cookie_rotation_session_id():
    cookies = SimpleCookie()
    cookies.load("ASP.NET_SessionId=rotated; Path=/; HttpOnly; Secure")
    assert session.merge_response_cookies("ASP.NET_SessionId=old; foo=bar", cookies) == "ASP.NET_SessionId=rotated; foo=bar"


def test_cookie_domain_isolation():
    cookies = SimpleCookie()
    cookies.load("ASP.NET_SessionId=stolen; Domain=hoadon.viwaco.vn; Path=/")
    assert session.merge_response_cookies("ASP.NET_SessionId=old", cookies) == "ASP.NET_SessionId=old"


def test_cookie_path_isolation():
    cookies = SimpleCookie()
    cookies.load("Other=new; Path=/admin")
    assert session.merge_response_cookies("Session=original", cookies) == "Session=original"


def test_cookie_deletion_but_keep_another():
    cookies = SimpleCookie()
    cookies.load("Session=bye; Max-Age=0; Path=/")
    assert session.merge_response_cookies("Session=old; extra=stable", cookies) == "extra=stable"


def test_cookie_empty_deletion_does_not_wipe_final_session():
    cookies = SimpleCookie()
    cookies.load("Session=bye; Max-Age=0; Path=/")
    assert session.merge_response_cookies("Session=old", cookies) == "Session=old"


def test_cookie_no_change_when_no_set_cookie():
    assert session.merge_response_cookies("Cookie: a=1; b=2", {}) == "a=1; b=2"


def test_cookie_malformed_value_ignored():
    cookies = SimpleCookie()
    cookies.load('Session="bad value"; Path=/')
    assert session.merge_response_cookies("Session=original", cookies) == "Session=original"


def test_cache_round_trip_dates_and_values():
    raw = snapshot.encode_snapshot(fixture_data())
    out = snapshot.decode_snapshot(raw, "000000001")
    assert out == fixture_data()
    assert raw["invoices"][0]["payment_date"] == "2026-10-10"
    assert "cookie" not in repr(raw).lower()


def test_cache_reject_wrong_customer():
    with pytest.raises(ValueError, match="customer"):
        snapshot.decode_snapshot(snapshot.encode_snapshot(fixture_data()), "another")


def test_cache_reject_bad_version():
    raw = snapshot.encode_snapshot(fixture_data())
    raw["version"] = 99
    with pytest.raises(ValueError, match="version"):
        snapshot.decode_snapshot(raw, "000000001")


def test_cache_reject_bad_date():
    raw = snapshot.encode_snapshot(fixture_data())
    raw["readings"][0]["read_date"] = "not-a-date"
    with pytest.raises(ValueError):
        snapshot.decode_snapshot(raw, "000000001")


def test_cache_reject_external_invoice_url():
    raw = snapshot.encode_snapshot(fixture_data())
    raw["invoices"][0]["invoice_url"] = "https://attacker.example/private"
    assert snapshot.decode_snapshot(raw, "000000001").invoices[0].invoice_url is None


def test_cache_reject_unbounded_rows():
    raw = snapshot.encode_snapshot(fixture_data())
    raw["invoices"] *= 501
    with pytest.raises(ValueError, match="too large"):
        snapshot.decode_snapshot(raw, "000000001")
