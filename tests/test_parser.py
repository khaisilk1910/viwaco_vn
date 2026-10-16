"""Tests require only standard Python libraries; no Home Assistant installation."""

import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[1] / "custom_components" / "viwaco_reader" / "parser.py"
spec = importlib.util.spec_from_file_location("viwaco_invoice_parser", MODULE)
mod = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

HEADER = """<tr><th>TT</th><th>Tháng</th><th>Năm</th><th>Sổ đọc</th><th>Từ ngày</th><th>Đến ngày</th><th>Tiêu thụ (m<sup>3</sup>)</th><th>Tiền (đ)</th><th>Thanh toán (đ)</th><th>Ngày thanh toán</th><th>Tạm thu</th><th>Số hóa đơn tài chính</th><th>Hóa đơn điện tử</th></tr>"""
SAMPLE = (
    '<input id="content_lblCustID" value="000000001" />'
    '<table id="tableInvoice">'
    + HEADER
    + '<tr><td>1</td><td>10</td><td>2026</td><td>XP</td><td>09/09/2026</td><td>08/10/2026</td>'
    '<td>17</td><td>177,445</td><td>177,445</td><td>10/10/2026</td><td>0</td>'
    '<td>TEST-001</td><td><a href="https://hoadon.viwaco.vn/tra-cuu/?code=TEST">View</a></td></tr></table>'
)


class TestInvoiceParser(unittest.TestCase):
    def test_parses_synthetic_example(self):
        invoices = mod.parse_invoice_html(SAMPLE, "000000001")
        self.assertEqual(len(invoices), 1)
        i = invoices[0]
        self.assertEqual(i.period, "10/2026")
        self.assertEqual(i.usage_m3, 17)
        self.assertEqual(i.total_vnd, 177445)
        self.assertEqual(i.paid_vnd, 177445)
        self.assertEqual(i.payment_date.isoformat(), "2026-10-10")
        self.assertEqual(i.invoice_number, "TEST-001")
        self.assertEqual(i.history_item()["period"], "10/2026")

    def test_blocks_wrong_customer(self):
        with self.assertRaises(mod.ViwacoWrongAccountError):
            mod.parse_invoice_html(SAMPLE, "000000002")

    def test_rejects_no_table(self):
        with self.assertRaises(mod.ViwacoParseError):
            mod.parse_invoice_html('<input id="content_lblCustID" value="000000001">', "000000001")

    def test_rejects_wrong_invoice_link_domain(self):
        invoice = mod.parse_invoice_html(SAMPLE.replace("hoadon.viwaco.vn", "example.com"), "000000001")[0]
        self.assertIsNone(invoice.invoice_url)


if __name__ == "__main__":
    unittest.main()
