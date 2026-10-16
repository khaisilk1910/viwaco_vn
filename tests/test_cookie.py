"""Cookie handling tests independent of Home Assistant installation."""
import importlib.util
from pathlib import Path
import sys
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'custom_components' / 'viwaco_reader' / 'cookie.py'
spec = importlib.util.spec_from_file_location('viwaco_cookie', MODULE)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

class CookieTests(unittest.TestCase):
    def test_request_cookie_value(self):
        self.assertEqual(mod.normalize_cookie('ASP.NET_SessionId=xyz; .ASPXAUTH=sign'), 'ASP.NET_SessionId=xyz; .ASPXAUTH=sign')

    def test_full_cookie_header(self):
        self.assertEqual(mod.normalize_cookie('Cookie: ASP.NET_SessionId=xyz; .ASPXAUTH=sign'), 'ASP.NET_SessionId=xyz; .ASPXAUTH=sign')

    def test_header_case_insensitive(self):
        self.assertEqual(mod.normalize_cookie('cookie: a=1'), 'a=1')

    def test_invalid_set_cookie(self):
        with self.assertRaises(mod.CookieFormatError):
            mod.normalize_cookie('Set-Cookie: ASP.NET_SessionId=xyz; path=/')

    def test_reject_newlines(self):
        with self.assertRaises(mod.CookieFormatError):
            mod.normalize_cookie('a=1\r\nAuthorization: evil')

    def test_reject_missing_value(self):
        with self.assertRaises(mod.CookieFormatError):
            mod.normalize_cookie('ASP.NET_SessionId=')

    def test_reject_cookie_flags_from_response(self):
        with self.assertRaises(mod.CookieFormatError):
            mod.normalize_cookie('ASP.NET_SessionId=xyz; HttpOnly')

if __name__ == '__main__':
    unittest.main()
