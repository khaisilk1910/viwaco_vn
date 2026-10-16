"""Tests for four customer profile fields; uses synthetic non-personal data."""
import importlib.util
from pathlib import Path
import sys
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'custom_components' / 'viwaco_reader' / 'parser.py'
spec = importlib.util.spec_from_file_location('viwaco_customer_parser', MODULE)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

SAMPLE = '''
<input id="__VIEWSTATE" value="SENSITIVE-STRING" />
<input id="content_lblCustID" value="000000001" disabled="disabled" />
<input id="content_lblCustName" value="Nguyễn Văn Mẫu" />
<input id="content_lblCustAddr" value="Số 10, Phường Mẫu" />
<input id="content_lblCustTel" value="0900000000" />
'''

class CustomerTests(unittest.TestCase):
    def test_extracts_all_customer_profile_fields(self):
        customer = mod.parse_customer_html(SAMPLE, '000000001')
        self.assertEqual(customer.customer_id, '000000001')
        self.assertEqual(customer.name, 'Nguyễn Văn Mẫu')
        self.assertEqual(customer.address, 'Số 10, Phường Mẫu')
        self.assertEqual(customer.phone, '0900000000')
        self.assertNotIn('SENSITIVE-STRING', str(customer.as_dict()))

    def test_refuses_wrong_customer(self):
        with self.assertRaises(mod.ViwacoWrongAccountError):
            mod.parse_customer_html(SAMPLE, '000000002')

    def test_handles_optional_fields_missing(self):
        profile = mod.parse_customer_html('<input id="content_lblCustID" value="000000001">', '000000001')
        self.assertEqual(profile.address, '')
        self.assertEqual(profile.phone, '')

    def test_does_not_parse_hidden_names_from_viewstate(self):
        html = '<input name="content_lblCustName" value="FAKE"><input id="content_lblCustID" value="000000001">'
        profile = mod.parse_customer_html(html, '000000001')
        self.assertEqual(profile.name, '')

if __name__ == '__main__':
    unittest.main()
