"""Regression tests for historical invoice details and PDF -> PNG conversion.

Provided HTML fixture paths are optional and only used during authoring; the
shipped synthetic fixtures below make the archive self-testing on any machine.
"""
from __future__ import annotations

import importlib.util
from io import BytesIO
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1] / 'custom_components' / 'viwaco_reader'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


archive_parser = load('viwaco_archive_parser_tests', 'archive_parser.py')
store = load('viwaco_store_tests', 'archive_store.py')


def test_lookup_rejects_customer_mismatch():
    html = '<div id="divInfo"><div class="tableInfo"><table><tr><td class="label">Mã số khách hàng</td><td>000123456</td></tr></table></div></div>'
    import pytest
    with pytest.raises(archive_parser.ArchiveParseError):
        archive_parser.parse_lookup(html, '000000001')


def test_lookups_only_official_host_and_code():
    assert archive_parser.invoice_code('https://hoadon.viwaco.vn/tra-cuu/?code=4A6D1300') == '4A6D1300'
    assert archive_parser.invoice_code('https://evil.example/tra-cuu/?code=4A6D1300') is None
    assert archive_parser.invoice_code('http://hoadon.viwaco.vn/tra-cuu/?code=4A6D1300') is None
    assert archive_parser.invoice_code('https://hoadon.viwaco.vn.evil.com/tra-cuu/?code=4A6D1300') is None
    assert archive_parser.invoice_code('https://hoadon.viwaco.vn/evil/?code=4A6D1300') is None
    assert archive_parser.invoice_code('https://hoadon.viwaco.vn/tra-cuu/?code=4A6D1300&code=X') is None
    assert archive_parser.invoice_code('https://hoadon.viwaco.vn/tra-cuu/?code=../../x') is None


def test_catalog_paths_and_atomic_writes():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'nested' / 'archived.pdf'
        store.write_bytes_atomic(str(path), b'%PDF-demo')
        assert path.read_bytes() == b'%PDF-demo'
        fn = Path(tmp) / 'private' / 'catalog.json'
        catalog = store.load_catalog(str(fn), '000000001')
        assert len(catalog['folder']) == 20
        store.write_catalog_atomic(str(fn), catalog)
        assert store.load_catalog(str(fn), '000000001') == catalog
        assert store.load_catalog(str(fn), '000999999')['customer_id'] == '000999999'
        assert store.make_archive_relative(catalog['folder'], 2026, 10, 'pdf') == f"viwaco_reader/{catalog['folder']}/2026/2026-10.pdf"


def test_pdf_to_png_renders_official_bytes_without_synthetic_invoice():
    from reportlab.pdfgen import canvas
    from PIL import Image
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(250, 350))
    c.drawString(20,300,'VIWACO PDF TEST PAGE')
    c.showPage()
    c.save()
    pngs = store.render_pdf_pngs(buf.getvalue())
    assert len(pngs) == 1
    image = Image.open(BytesIO(pngs[0]))
    assert image.format == 'PNG'
    assert image.width > 250 and image.height > 350


def test_simple_document_prices_and_taxes():
    html = """<root><div class="root"><p>Mã khách hàng: 000000001</p>
    <table id="tableItems"><tbody>
    <tr><td>Đọc mới</td><td>Đọc cũ</td><td>m3</td><td>Bậc</td><td>Đơn giá</td><td>Thành tiền</td></tr>
    <tr><td>123</td><td>117</td><td>6</td>
      <td><table><tr><td>SH1</td><td>6</td></tr></table></td><td>8.500</td><td>51.000</td></tr>
    <tr><td>- Tiền nước</td><td>51.000</td></tr>
    <tr><td>- Phí bảo vệ môi trường (10%)</td><td>5.100</td></tr>
    <tr><td>- Tiền thuế VAT (5%)</td><td>2.550</td></tr>
    <tr><td>TỔNG CỘNG</td><td></td><td>58.650</td></tr>
    </tbody></table></div></root>"""
    record = archive_parser.parse_invoice_view(html, '000000001')
    assert record['water_charge_vnd'] == 51000
    assert record['environment_fee_vnd'] == 5100
    assert record['environment_fee_rate_percent'] == '10'
    assert record['vat_vnd'] == 2550
    assert record['total_vnd'] == 58650
    assert record['current_meter_m3'] == 123
    assert record['previous_meter_m3'] == 117
    assert record['tariffs'][0] == {'tariff':'SH1','quantity_m3':6,'unit_price_vnd':8500,'amount_vnd':51000}
