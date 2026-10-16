"""Mock HTTP tests: validate first-party Set-Cookie only after customer ID check."""
from __future__ import annotations

from http.cookies import SimpleCookie
import importlib
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1] / 'custom_components' / 'viwaco_reader'
PKG = 'viwaco_api_keepalive_test_pkg'
pkg = types.ModuleType(PKG)
pkg.__path__ = [str(ROOT)]
sys.modules[PKG] = pkg

if 'homeassistant' not in sys.modules:
    fake_ha = types.ModuleType('homeassistant')
    fake_ha.__path__ = []
    sys.modules['homeassistant'] = fake_ha
if 'homeassistant.const' not in sys.modules:
    fake_const = types.ModuleType('homeassistant.const')
    fake_const.Platform = types.SimpleNamespace(SENSOR='sensor')
    sys.modules['homeassistant.const'] = fake_const
if 'homeassistant.helpers' not in sys.modules:
    fake_helpers = types.ModuleType('homeassistant.helpers')
    fake_helpers.__path__ = []
    sys.modules['homeassistant.helpers'] = fake_helpers

if 'homeassistant.helpers.aiohttp_client' not in sys.modules:
    module = types.ModuleType('homeassistant.helpers.aiohttp_client')
    sys.modules['homeassistant.helpers.aiohttp_client'] = module
else:
    module = sys.modules['homeassistant.helpers.aiohttp_client']


class FakeContent:
    def __init__(self, html):
        self.html = html

    async def read(self, _limit):
        return self.html.encode()


class FakeResponse:
    def __init__(self, html, status=200, cookies=''):
        self.content = FakeContent(html)
        self.status = status
        self.cookies = SimpleCookie()
        self.cookies.load(cookies)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return self.response


session_box = {}
module.async_get_clientsession = lambda hass: session_box['session']
api = importlib.import_module(f'{PKG}.api')


def html(customer='000000001'):
    return f'<input id="content_lblCustID" value="{customer}"/><table id="tableInvoice"><tr><th>Test</th></tr></table>'


@pytest.mark.asyncio
async def test_keepalive_rotates_and_saves_verified_cookie():
    session_box['session'] = FakeSession(FakeResponse(
        html(), cookies='ASP.NET_SessionId=new; Path=/; HttpOnly; Secure'))
    rotated = []
    client = api.ViwacoApi(None, '000000001', 'ASP.NET_SessionId=old', rotated.append)
    await client.async_keepalive()
    assert rotated == ['ASP.NET_SessionId=new']
    assert session_box['session'].requests[0][1]['headers']['Cookie'] == 'ASP.NET_SessionId=old'
    assert 'Invoice.aspx' in session_box['session'].requests[0][0]


@pytest.mark.asyncio
async def test_keepalive_wrong_account_refuses_rotated_cookie():
    session_box['session'] = FakeSession(FakeResponse(
        html('different'), cookies='ASP.NET_SessionId=bad; Path=/'))
    rotated = []
    client = api.ViwacoApi(None, '000000001', 'ASP.NET_SessionId=old', rotated.append)
    with pytest.raises(api.ViwacoAuthError) as err:
        await client.async_keepalive()
    assert err.value.reason == 'wrong_customer'
    assert rotated == []


@pytest.mark.asyncio
async def test_keepalive_redirect_triggers_auth_error_without_rotating_cookie():
    session_box['session'] = FakeSession(FakeResponse(
        '', status=302, cookies='ASP.NET_SessionId=bad; Path=/'))
    rotated = []
    client = api.ViwacoApi(None, '000000001', 'ASP.NET_SessionId=old', rotated.append)
    with pytest.raises(api.ViwacoAuthError) as err:
        await client.async_keepalive()
    assert err.value.reason == 'session_expired'
    assert rotated == []
