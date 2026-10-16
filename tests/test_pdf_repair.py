"""Regression: never archive an unreadable PDF, and preserve official bytes."""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
import importlib.util
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "viwaco_reader"


def _module(filename: str):
    name = "viwaco_test_" + filename.replace(".", "_")
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pdf = _module("pdf_tools.py")
store = _module("archive_store.py")


@pytest.fixture
def good_pdf():
    from reportlab.pdfgen import canvas
    buff = BytesIO()
    c = canvas.Canvas(buff, pagesize=(250, 340))
    c.drawString(50, 290, "Invoice sample")
    c.showPage()
    c.save()
    return buff.getvalue()


def test_preserve_official_binary_when_valid(good_pdf):
    checked = pdf.check_or_repair_pdf(good_pdf)
    assert checked.content == good_pdf
    assert checked.repaired is False
    assert checked.pages == 1
    assert store.render_pdf_pngs(checked.content)[0].startswith(b"\x89PNG\r\n")


def test_reject_header_only_corrupt_pdf():
    with pytest.raises(pdf.InvoicePdfError, match="không thể phục hồi"):
        pdf.check_or_repair_pdf(b"%PDF-1.6" + b"Z" * 600)


def test_reject_server_html_not_pdf():
    with pytest.raises(pdf.InvoicePdfError, match="không trả nội dung PDF"):
        pdf.check_or_repair_pdf(b"<html>500 server error</html>" * 20)


def test_recover_rewritable_pdf(good_pdf, monkeypatch):
    original_validator = pdf._check_pdf_with_pdfium
    calls = {"n": 0}

    def fail_original_once(blob):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("PDFium: Data format error")
        return original_validator(blob)

    monkeypatch.setattr(pdf, "_check_pdf_with_pdfium", fail_original_once)
    recovered = pdf.check_or_repair_pdf(good_pdf)
    assert recovered.repaired is True
    assert recovered.content.startswith(b"%PDF-")
    assert recovered.pages == 1
    assert store.render_pdf_pngs(recovered.content)


def test_check_old_v16_file(good_pdf, tmp_path):
    path = tmp_path / "2026-10.pdf"
    path.write_bytes(b"%PDF-1.6" + b"Z" * 300)
    assert pdf.existing_pdf_is_valid(str(path)) is False
    path.write_bytes(good_pdf)
    assert pdf.existing_pdf_is_valid(str(path)) is True


def test_pdf_not_written_until_validation(good_pdf, tmp_path):
    target = tmp_path / "bill.pdf"
    bad_bytes = b"%PDF-1.7" + b"Z" * 300
    with pytest.raises(pdf.InvoicePdfError):
        checked = pdf.check_or_repair_pdf(bad_bytes)
        store.write_bytes_atomic(str(target), checked.content)
    assert not target.exists()
    checked = pdf.check_or_repair_pdf(good_pdf)
    store.write_bytes_atomic(str(target), checked.content)
    assert pdf.existing_pdf_is_valid(str(target))
