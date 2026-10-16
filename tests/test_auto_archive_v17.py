"""Offline tests for v1.7 automatic new-period invoice archive and precision."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import types
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1] / 'custom_components' / 'viwaco_reader'


@pytest.fixture
def env(monkeypatch):
    records = {}

    class FakeStore:
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, hass, version, key):
            self.key = key

        async def async_load(self):
            return records.get(self.key)

        async def async_save(self, state):
            records[self.key] = dict(state)

    storage = types.ModuleType('homeassistant.helpers.storage')
    storage.Store = FakeStore
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers.storage', storage)
    pkg_name = 'viwaco_auto_archive_v17_fixture'
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(ROOT)]
    monkeypatch.setitem(sys.modules, pkg_name, pkg)
    for module_name in ['const', 'auto_archive']:
        fullname = f'{pkg_name}.{module_name}'
        spec = importlib.util.spec_from_file_location(fullname, ROOT / f'{module_name}.py')
        mod = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, fullname, mod)
        spec.loader.exec_module(mod)
    auto = sys.modules[f'{pkg_name}.auto_archive']

    class FakeEntry:
        def __init__(self, enabled=True, mode='both'):
            self.data = {'customer_id': '000000001'}
            self.entry_id = 'entryid'
            self.options = {'auto_archive_enabled': enabled, 'auto_archive_mode': mode}
            self.tasks = []

        def async_create_background_task(self, hass, coroutine, name):
            task = asyncio.create_task(coroutine, name=name)
            self.tasks.append(task)
            return task

        async def wait(self):
            while self.tasks:
                tasks, self.tasks = self.tasks, []
                await asyncio.gather(*tasks)

    class FakeArchive:
        def __init__(self):
            self.calls = []
            self.fail_months = set()
            self.lock = False

        async def async_sync(self, invoices, **opts):
            self.calls.append((tuple(i.period for i in invoices), opts))
            if self.lock:
                return None
            return {'completed': [i.period for i in invoices if i.period not in self.fail_months],
                    'failures': [i.period for i in invoices if i.period in self.fail_months]}

    def invoice(year, month, code=True):
        return SimpleNamespace(year=year, month=month, period=f'{month:02d}/{year}',
                               invoice_url='https://hoadon.viwaco.vn/tra-cuu/?code=FAKE' if code else None)

    return auto, FakeEntry, FakeArchive, invoice, records


@pytest.mark.asyncio
async def test_disabled_by_default_no_task_or_write(env):
    auto, Entry, Archive, invoice, saved = env
    entry = Entry(enabled=False)
    archiver = auto.AutoInvoiceArchiver(None, entry, Archive())
    archiver.schedule([invoice(2026, 10)])
    await entry.wait()
    assert not entry.tasks
    assert not saved


@pytest.mark.asyncio
async def test_opt_in_archives_latest_only_then_new_month_no_duplicate(env):
    auto, Entry, Archive, invoice, saved = env
    entry = Entry()
    archive = Archive()
    archiver = auto.AutoInvoiceArchiver(None, entry, archive)
    archiver.schedule([invoice(2026, 10), invoice(2026, 9), invoice(2026, 8)])
    await entry.wait()
    assert archive.calls[0][0] == ('10/2026',)
    assert archive.calls[0][1]['notify'] is False
    archiver.schedule([invoice(2026, 10), invoice(2026, 9)])
    await entry.wait()
    assert len(archive.calls) == 1
    archiver.schedule([invoice(2026, 12), invoice(2026, 11), invoice(2026, 10)])
    await entry.wait()
    assert archive.calls[-1][0] == ('11/2026', '12/2026')
    assert len(saved) == 1


@pytest.mark.asyncio
async def test_failed_month_retried_and_persists_restart(env):
    auto, Entry, Archive, invoice, saved = env
    entry = Entry()
    archive = Archive()
    archive.fail_months.add('10/2026')
    archiver = auto.AutoInvoiceArchiver(None, entry, archive)
    archiver.schedule([invoice(2026, 10), invoice(2026, 9)])
    await entry.wait()
    assert not saved[next(iter(saved))]['completed']
    archive.fail_months.clear()
    restarted = auto.AutoInvoiceArchiver(None, entry, archive)
    restarted.schedule([invoice(2026, 11), invoice(2026, 10), invoice(2026, 9)])
    await entry.wait()
    assert archive.calls[-1][0] == ('10/2026', '11/2026')
    assert set(saved[next(iter(saved))]['completed']) == {'10/2026', '11/2026'}


@pytest.mark.asyncio
async def test_mode_changed_reprocesses_latest_to_create_png(env):
    auto, Entry, Archive, invoice, saved = env
    entry = Entry(mode='pdf')
    archive = Archive()
    one = auto.AutoInvoiceArchiver(None, entry, archive)
    one.schedule([invoice(2026, 10)])
    await entry.wait()
    entry.options['auto_archive_mode'] = 'both'
    two = auto.AutoInvoiceArchiver(None, entry, archive)
    two.schedule([invoice(2026, 10)])
    await entry.wait()
    assert len(archive.calls) == 2
    assert archive.calls[-1][1]['mode'] == 'both'


def test_zero_decimal_precision_applies_to_numeric_sensors():
    sensor_source = (ROOT / 'sensor.py').read_text()
    assert 'description.native_unit_of_measurement in ("m³", "VND")' in sensor_source
    assert 'self._attr_suggested_display_precision = 0' in sensor_source
    assert 'state_class=SensorStateClass.TOTAL_INCREASING' in sensor_source
