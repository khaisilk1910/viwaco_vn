"""Exercise the invoice archive class with real local file I/O and fake HTTP."""
from __future__ import annotations
import asyncio
import importlib.util
from pathlib import Path
from io import BytesIO
import sys
import types
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1] / 'custom_components' / 'viwaco_reader'


def load_archive(monkeypatch):
    ha = types.ModuleType('homeassistant')
    ha.__path__ = []
    components = types.ModuleType('homeassistant.components')
    components.__path__ = []
    notification = types.ModuleType('homeassistant.components.persistent_notification')
    notification.async_create = lambda *args, **kwargs: None
    components.persistent_notification = notification
    for name, mod in [('homeassistant',ha),('homeassistant.components',components),
                      ('homeassistant.components.persistent_notification',notification)]:
        monkeypatch.setitem(sys.modules,name,mod)
    pkgname = 'viwaco_archive_flow_testpkg'
    pkg = types.ModuleType(pkgname)
    pkg.__path__ = [str(ROOT)]
    monkeypatch.setitem(sys.modules,pkgname,pkg)
    for item in ('archive_parser','archive_store','pdf_tools','archive'):
        name = f'{pkgname}.{item}'
        spec=importlib.util.spec_from_file_location(name, ROOT / (item+'.py'))
        mod=importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules,name,mod)
        spec.loader.exec_module(mod)
    return sys.modules[f'{pkgname}.archive']


class FakeHass:
    def __init__(self,tmp):
        self.config = SimpleNamespace(path=lambda *parts: str(tmp.joinpath(*parts)))
    async def async_add_executor_job(self,callback,*args):
        return await asyncio.to_thread(callback,*args)


def fake_invoice():
    return SimpleNamespace(period='10/2026',month=10,year=2026,
                           invoice_url='https://hoadon.viwaco.vn/tra-cuu/?code=FAKE1234',total_vnd=100)


def lookup():
    return b'<html><div id="divInfo"><div class="tableInfo"><table><tr><td class="label">M\xc3\xa3 s\xe1\xbb\x91 kh\xc3\xa1ch h\xc3\xa0ng</td><td>000000001</td></tr><tr><td class="label">T\xe1\xbb\x95ng ti\xe1\xbb\x81n h\xc3\xb3a \xc4\x91\xc6\xa1n</td><td>100</td></tr></table></div></div></html>'


@pytest.mark.parametrize('mode',['pdf','both','png'])
def test_invalid_supplier_pdf_never_saved(monkeypatch,tmp_path,mode):
    archive = load_archive(monkeypatch)
    inst=archive.InvoiceArchive(FakeHass(tmp_path), SimpleNamespace(data={'customer_id':'000000001'},entry_id='xyz'))
    inst._catalog={'records':{},'folder':'0123456789abcdef1234'}
    async def mock_get(session,path,params,is_pdf=False):
        return b'%PDF-1.6' + b'invalid' * 100 if is_pdf else lookup()
    async def save():
        return None
    inst._get=mock_get
    inst._save=save
    async def run():
        with pytest.raises(Exception, match='không thể phục hồi'):
            await inst._process_one(None,fake_invoice(),mode,False)
    asyncio.run(run())
    assert list(tmp_path.glob('www/**/*.pdf'))==[]
    assert list(tmp_path.glob('www/**/*.png'))==[]
    assert inst.records=={}


def test_valid_pdf_only_saved_after_validation(monkeypatch,tmp_path):
    from reportlab.pdfgen import canvas
    raw = BytesIO()
    c = canvas.Canvas(raw)
    c.drawString(20,740,'Sample')
    c.save()
    content = raw.getvalue()
    archive=load_archive(monkeypatch)
    inst=archive.InvoiceArchive(FakeHass(tmp_path),SimpleNamespace(data={'customer_id':'000000001'},entry_id='xyz'))
    inst._catalog={'records':{},'folder':'0123456789abcdef1234'}
    async def mock_get(session,path,params,is_pdf=False):
        return content if is_pdf else lookup()
    async def save():
        return None
    inst._get=mock_get
    inst._save=save
    async def run():
        assert await inst._process_one(None,fake_invoice(),'pdf',False) is True
    asyncio.run(run())
    saved=list(tmp_path.glob('www/**/*.pdf'))
    assert len(saved)==1
    assert saved[0].read_bytes()==content
    assert inst.records['10/2026']['pdf_source']=='viwaco-original'


def test_http_500_retried_then_clearly_reported(monkeypatch,tmp_path):
    archive=load_archive(monkeypatch)
    inst=archive.InvoiceArchive(FakeHass(tmp_path),SimpleNamespace(data={'customer_id':'000000001'},entry_id='xyz'))
    class FakeContent:
        async def read(self,n):
            return b''
    class FakeResponse:
        status=500
        content_length=0
        headers={}
        content=FakeContent()
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    class FakeSession:
        calls=0
        def get(self,*args,**kwargs):
            self.calls+=1
            return FakeResponse()
    session=FakeSession()
    async def no_sleep(_):pass
    monkeypatch.setattr(archive.asyncio,'sleep',no_sleep)
    async def run():
        with pytest.raises(ValueError,match='HTTP 500'):
            await inst._get(session,'/View.aspx',{'Code':'FAKE1234','Mode':'PDF'},is_pdf=True)
    asyncio.run(run())
    assert session.calls==3


def test_fake_html_pdf_response_rejected(monkeypatch,tmp_path):
    archive=load_archive(monkeypatch)
    inst=archive.InvoiceArchive(FakeHass(tmp_path),SimpleNamespace(data={'customer_id':'000000001'},entry_id='xyz'))
    class FakeContent:
        async def read(self,n): return b'<html><title>Error</title></html>'
    class FakeResponse:
        status=200
        content_length=None
        headers={'Content-Type':'text/html; charset=utf-8'}
        content=FakeContent()
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    class FakeSession:
        def get(self,*args,**kwargs):return FakeResponse()
    async def run():
        with pytest.raises(ValueError,match='text/html thay vì PDF'):
            await inst._get(FakeSession(),'/View.aspx',{'Code':'FAKE1234','Mode':'PDF'},is_pdf=True)
    asyncio.run(run())


def test_existing_broken_file_link_is_cleared_if_supplier_fails(monkeypatch,tmp_path):
    archive=load_archive(monkeypatch)
    inv=fake_invoice()
    folder='0123456789abcdef1234'
    inst=archive.InvoiceArchive(FakeHass(tmp_path), SimpleNamespace(data={'customer_id':'000000001'},entry_id='xyz'))
    inst._catalog={'records':{'10/2026': {'details':{'dummy':1},'pdf_url':'/local/viwaco_reader/broken/2026-10.pdf'}},'folder':folder}
    pdf_path=tmp_path/'www'/'viwaco_reader'/folder/'2026'/'2026-10.pdf'
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b'%PDF-1.4' + b'garbage' * 100)
    async def no_data(session,path,params,is_pdf=False):
        if is_pdf:
            return b'%PDF-1.4' + b'garbage' * 100
        return lookup()
    async def save():return None
    inst._get=no_data
    inst._save=save
    async def run():
        with pytest.raises(Exception,match='không thể phục hồi'):
            await inst._process_one(None,inv,'pdf',overwrite=True)
    asyncio.run(run())
    assert pdf_path.read_bytes().endswith(b'garbage'*100)
    assert 'pdf_url' not in inst.records['10/2026']
