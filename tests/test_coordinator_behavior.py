"""Coordinator behavior under simulated HA and VIWACO errors.

The real Home Assistant runtime is not installed in the build container.
These contract tests fake the HA APIs, so live HA compatibility remains unverified.
"""
import importlib
from pathlib import Path
import sys
import types
from datetime import date
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "viwaco_reader"
PKG = "viwaco_coordinator_test_pkg"
pkg = types.ModuleType(PKG)
pkg.__path__ = [str(ROOT)]
sys.modules[PKG] = pkg


def module(name):
    obj = types.ModuleType(name)
    sys.modules[name] = obj
    return obj


ha = module("homeassistant")
ha.__path__ = []
constants = module("homeassistant.const")
constants.Platform = types.SimpleNamespace(SENSOR="sensor")
components = module("homeassistant.components")
components.__path__ = []
notifications = module("homeassistant.components.persistent_notification")
notifications.async_create = Mock()
notifications.async_dismiss = Mock()
components.persistent_notification = notifications
exceptions = module("homeassistant.exceptions")
exceptions.ConfigEntryAuthFailed = type("ConfigEntryAuthFailed", (Exception,), {})
helpers = module("homeassistant.helpers")
helpers.__path__ = []
storemodule = module("homeassistant.helpers.storage")
coordinator_module = module("homeassistant.helpers.update_coordinator")


class FakeCoordinator:
    def __class_getitem__(cls, typ):
        return cls

    def __init__(self, hass, logger, config_entry=None, **kwargs):
        self.hass = hass
        self.data = None
        self.last_update_success = False
        self._updates = 0

    def async_update_listeners(self):
        self._updates += 1

    def async_set_updated_data(self, data):
        self.data = data
        self.last_update_success = True
        self.async_update_listeners()

    async def async_refresh(self):
        try:
            self.async_set_updated_data(await self._async_update_data())
        except (exceptions.ConfigEntryAuthFailed, coordinator_module.UpdateFailed):
            self.last_update_success = False


coordinator_module.DataUpdateCoordinator = FakeCoordinator
coordinator_module.UpdateFailed = type("UpdateFailed", (Exception,), {})


class FakeStore:
    saved = None

    def __class_getitem__(cls, typ):
        return cls

    def __init__(self, *args):
        self.data = self.saved

    async def async_load(self):
        return self.data

    async def async_save(self, payload):
        self.data = payload


storemodule.Store = FakeStore

api_module = module(f"{PKG}.api")
api_module.ViwacoAuthError = type("ViwacoAuthError", (Exception,), {
    "__init__": lambda self, reason: (Exception.__init__(self, reason), setattr(self, "reason", reason))[-1],
})
api_module.ViwacoConnectionError = type("ViwacoConnectionError", (Exception,), {})


class FakeApi:
    def __init__(self, hass, customer_id, cookie, callback):
        self.cookie = cookie
        self.callback = callback
        self.fetch_response = None
        self.keepalive_error = None

    async def async_fetch_data(self):
        if isinstance(self.fetch_response, Exception):
            raise self.fetch_response
        return self.fetch_response

    async def async_keepalive(self):
        if self.keepalive_error:
            raise self.keepalive_error


api_module.ViwacoApi = FakeApi
archive_module = module(f"{PKG}.archive")


class FakeArchive:
    def __init__(self, hass, entry):
        self.status = {}
        self.records = {}

    async def async_load(self):
        return {}


archive_module.InvoiceArchive = FakeArchive
parser = importlib.import_module(f"{PKG}.parser")
snapshot = importlib.import_module(f"{PKG}.snapshot")
co_mod = importlib.import_module(f"{PKG}.coordinator")


def data():
    return parser.ViwacoData(
        (parser.Invoice(10, 2026, 'XP52', date(2026, 9, 9), date(2026, 10, 8),
                        17, 177445, 177445, date(2026, 10, 10), 0, 'inv', None),),
        (parser.Reading('TEST', 2026, 10, date(2026, 10, 8), 'O', 1377, 1394, 17, 'regular'),),
        parser.CustomerInfo('000000001', 'test', 'hidden', ''),
    )


class FakeEntry:
    data = {'customer_id': '000000001', 'cookie': 'ASP.NET_SessionId=abc'}
    options = {}
    entry_id = 'test-entry'

    def __init__(self):
        self.data = dict(self.data)
        self.reauth_calls = 0

    def async_start_reauth(self, hass):
        self.reauth_calls += 1


class FakeHass:
    def __init__(self):
        self.config_entries = types.SimpleNamespace(async_update_entry=self.update_entry)

    @staticmethod
    def update_entry(entry, data):
        entry.data = data


def build():
    FakeStore.saved = None
    entry = FakeEntry()
    co = co_mod.ViwacoCoordinator(FakeHass(), entry)
    co.api.fetch_response = data()
    return co, entry


@pytest.mark.asyncio
async def test_live_fetch_sets_valid_and_persists_cache():
    co, entry = build()
    co.async_set_updated_data(await co._async_update_data())
    assert co.session_status == 'valid'
    assert co._store.data['customer_id'] == '000000001'
    assert len(co.data.invoices) == 1


@pytest.mark.asyncio
async def test_network_error_retains_cached_reading():
    co, _ = build()
    co.async_set_updated_data(await co._async_update_data())
    co.api.fetch_response = api_module.ViwacoConnectionError('timeout')
    assert await co._async_update_data() is co.data
    assert co.session_status == 'offline'
    assert co.data.readings[0].current_m3 == 1394


@pytest.mark.asyncio
async def test_auth_expired_triggers_single_reauth_and_keeps_cache():
    co, entry = build()
    co.async_set_updated_data(await co._async_update_data())
    co.api.fetch_response = api_module.ViwacoAuthError('session_expired')
    assert await co._async_update_data() is co.data
    assert await co._async_update_data() is co.data
    assert co.session_status == 'expired'
    assert entry.reauth_calls == 1


@pytest.mark.asyncio
async def test_auth_without_cache_raises_after_requesting_reauth():
    co, entry = build()
    co.api.fetch_response = api_module.ViwacoAuthError('session_expired')
    with pytest.raises(exceptions.ConfigEntryAuthFailed):
        await co._async_update_data()
    assert entry.reauth_calls == 1


@pytest.mark.asyncio
async def test_cached_snapshot_restored_before_network_failure():
    co, entry = build()
    co._store.data = snapshot.encode_snapshot(data())
    co.api.fetch_response = api_module.ViwacoConnectionError('offline')
    await co.async_restore_and_refresh()
    assert co.data.readings[0].current_m3 == 1394
    assert co.session_status == 'offline'
    assert co.last_successful_fetch is None
    assert co.cache_saved_at is not None


@pytest.mark.asyncio
async def test_keepalive_sets_valid_and_failure_sets_expired():
    co, entry = build()
    await co.async_keepalive()
    assert co.session_status == 'valid'
    co.api.keepalive_error = api_module.ViwacoAuthError('session_expired')
    await co.async_keepalive()
    assert co.session_status == 'expired'
    assert entry.reauth_calls == 1


def test_cookie_rotation_persists_to_config_entry():
    co, entry = build()
    co._persist_cookie('ASP.NET_SessionId=new')
    assert entry.data['cookie'] == 'ASP.NET_SessionId=new'
