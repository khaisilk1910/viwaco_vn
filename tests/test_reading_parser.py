"""Synthetic fixture tests. No real personal customer data included."""

import importlib.util
from pathlib import Path
import sys
import unittest

MODULE = Path(__file__).resolve().parents[1] / "custom_components" / "viwaco_reader" / "parser.py"
spec = importlib.util.spec_from_file_location("viwaco_reading_parser", MODULE)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

HEADER = ("<tr><th>TT</th><th>Serial ĐH</th><th>Năm</th><th>Tháng</th>"
          "<th>Ngày đọc</th><th>TTSĐ</th><th>Chỉ số trước</th>"
          "<th>Chỉ số sau</th><th>Tiêu thụ (m<sup>3</sup>)</th>"
          "<th>Loại chỉ số</th></tr>")
ROWS = (
    "<tr><td>1</td><td>TEST-123 - WATER_D15</td><td>2026</td><td>10</td>"
    "<td>08/10/2026</td><td>O</td><td>1,377</td><td>1,394</td>"
    "<td>17</td><td>Định kỳ</td></tr>"
    "<tr><td>2</td><td>TEST-123 - WATER_D15</td><td>2026</td><td>9</td>"
    "<td>08/09/2026</td><td>O</td><td>1,363</td><td>1,377</td>"
    "<td>14</td><td>Định kỳ</td></tr>"
)
SAMPLE = ('<input id="content_lblCustID" value="000000001">'
          '<table id="tableInvoice">' + HEADER + ROWS + '</table>')


class TestReadingParser(unittest.TestCase):
    def test_reading_values_and_sorted(self):
        r = mod.parse_reading_html(SAMPLE, "000000001")
        self.assertEqual(len(r), 2)
        self.assertEqual(r[0].serial, "TEST-123 - WATER_D15")
        self.assertEqual(r[0].period, "10/2026")
        self.assertEqual(r[0].read_date.isoformat(), "2026-10-08")
        self.assertEqual(r[0].previous_m3, 1377)
        self.assertEqual(r[0].current_m3, 1394)
        self.assertEqual(r[0].usage_m3, 17)
        self.assertEqual(r[0].history_item()["current_m3"], 1394)

    def test_expired_cookie_returns_no_identity(self):
        with self.assertRaises(mod.ViwacoWrongAccountError):
            mod.parse_reading_html('<html><form id="form1"></form></html>', "000000001")

    def test_blocks_wrong_customer(self):
        with self.assertRaises(mod.ViwacoWrongAccountError):
            mod.parse_reading_html(SAMPLE, "000000002")

    def test_wrong_table_structure(self):
        with self.assertRaises(mod.ViwacoParseError):
            mod.parse_reading_html(SAMPLE.replace("Chỉ số sau", "Tên chủ hộ"), "000000001")

    def test_rejects_invoice_page_as_reading(self):
        with self.assertRaises(mod.ViwacoParseError):
            mod.parse_reading_html(SAMPLE.replace("<th>Serial ĐH</th>", "<th>Tháng</th>"), "000000001")

    def test_sorted_by_read_date_not_by_billing_period(self):
        extra = ("<tr><td>3</td><td>TEST-123</td><td>2026</td><td>10</td>"
                 "<td>09/10/2026</td><td>O</td><td>1,394</td><td>1,395</td>"
                 "<td>1</td><td>Đột xuất</td></tr>")
        r = mod.parse_reading_html(SAMPLE.replace('</table>',extra+'</table>'), "000000001")
        self.assertEqual(r[0].current_m3, 1395)
        self.assertEqual(r[0].period, "10/2026")


if __name__ == "__main__":
    unittest.main()
