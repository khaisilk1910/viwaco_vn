"""Archive VIWACO invoice HTML as printable A4 PDF and PNG.

No Mode=PDF requests. Identity and amounts are checked before rendering.
Output is labeled as an HTML printout, not an issuer-signed original.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, ClientError
from homeassistant.components import persistent_notification

from .archive_parser import (ArchiveParseError, invoice_code, invoice_number_digits, verify_invoice_number, parse_lookup, parse_invoice_view, BASE)
from .pdf_tools import InvoicePdfError, check_or_repair_pdf, existing_pdf_is_valid
from .html_invoice import render_viwaco_html_invoice
from .archive_store import (
    load_catalog, local_url, make_archive_relative, render_pdf_pngs, existing_pngs_are_valid,
    write_bytes_atomic, write_catalog_atomic,
)

_LOGGER = logging.getLogger(__name__)

# Keep simultaneous accounts from repeatedly hammering the invoice portal.
_DOWNLOAD_GATE = asyncio.Semaphore(1)


class InvoiceArchive:
    """One archive per VIWACO customer, persisted outside public /www."""

    def __init__(self, hass, entry) -> None:
        self.hass = hass
        self.customer_id = entry.data["customer_id"]
        self.entry_id = entry.entry_id
        self._path = hass.config.path("viwaco_reader_cache", f"{self.customer_id}.json")
        self._catalog: dict | None = None
        self._load_lock = asyncio.Lock()
        self._sync_lock = asyncio.Lock()
        self.status = {"running": False, "done": 0, "total": 0, "errors": 0, "message": "Chưa tải lưu trữ"}

    @property
    def records(self) -> dict:
        return self._catalog.get("records", {}) if self._catalog else {}

    async def async_load(self) -> dict:
        if self._catalog is not None:
            return self._catalog
        async with self._load_lock:
            if self._catalog is None:
                self._catalog = await self.hass.async_add_executor_job(
                    load_catalog, self._path, self.customer_id
                )
        return self._catalog

    async def _save(self) -> None:
        assert self._catalog is not None
        await self.hass.async_add_executor_job(
            write_catalog_atomic, self._path, self._catalog
        )

    async def _get(self, session: ClientSession, path: str, params: dict, is_pdf: bool = False) -> bytes:
        """Fetch fixed-host documents with bounded retry for transient failures."""
        for attempt in range(3):
            try:
                async with session.get(
                    BASE + path, params=params, allow_redirects=False
                ) as response:
                    if response.status in (429, 500, 502, 503, 504):
                        if attempt < 2:
                            retry_after = response.headers.get("Retry-After", "")
                            delay = min(int(retry_after), 10) if retry_after.isdecimal() else 1.0 * (attempt + 1)
                            _LOGGER.debug("VIWACO invoice portal transient HTTP %s, attempt=%s",
                                          response.status, attempt + 1)
                            await asyncio.sleep(delay)
                            continue
                    if response.status != 200:
                        raise ValueError(f"HTTP {response.status} từ máy chủ hóa đơn điện tử")
                    if response.content_length is not None and response.content_length > 25 * 1024 * 1024:
                        raise ValueError("Hóa đơn vượt giới hạn dung lượng 25 MB")
                    payload = await response.content.read(25 * 1024 * 1024 + 1)
                    if len(payload) > 25 * 1024 * 1024:
                        raise ValueError("Hóa đơn vượt giới hạn dung lượng 25 MB")
                    if is_pdf:
                        if b"%PDF-" not in payload[:1024]:
                            kind = response.headers.get("Content-Type", "unknown").split(";")[0][:50]
                            raise ValueError(
                                f"Máy chủ trả {kind} thay vì PDF. "
                                "Có thể dịch vụ xuất hóa đơn đang lỗi; không tạo file giả."
                            )
                    elif b"<html" not in payload[:4096].lower() and b"<root" not in payload[:4096].lower():
                        raise ValueError("Không nhận được HTML hợp lệ từ hóa đơn điện tử")
                    return payload
            except asyncio.TimeoutError as exc:
                if attempt == 2:
                    raise ValueError("Hết thời gian chờ website hóa đơn điện tử") from exc
            except ClientError as exc:
                if attempt == 2:
                    raise ValueError(f"Lỗi kết nối website hóa đơn: {type(exc).__name__}") from exc
            if attempt < 2:
                await asyncio.sleep(attempt + 1)
        raise ValueError("Không lấy được hóa đơn sau ba lần thử")

    async def _fetch_optional_asset(self, session, path: str, params: dict) -> bytes | None:
        """Only same-origin invoice background / QR image, bounded and optional.

        Assets contain no credentials; a failed image must not prevent archiving.
        """
        try:
            async with session.get(BASE + path, params=params, allow_redirects=False) as response:
                if response.status != 200:
                    return None
                kind = response.headers.get("Content-Type", "").lower()
                if not kind.startswith("image/"):
                    return None
                if response.content_length and response.content_length > 1_500_000:
                    return None
                payload = await response.content.read(1_500_001)
                return payload if len(payload) <= 1_500_000 else None
        except (ClientError, asyncio.TimeoutError, AttributeError, TypeError, ValueError):
            return None

    async def _process_one(self, session, inv, mode: str, overwrite: bool) -> bool:
        code = invoice_code(inv.invoice_url)
        if code is None:
            raise ValueError("Không có URL tra cứu hóa đơn điện tử hợp lệ")
        period = inv.period
        record = dict(self.records.get(period, {}))
        saved_number = invoice_number_digits(record.get("invoice_number"))
        current_number = invoice_number_digits(getattr(inv, "invoice_number", None))
        old_details = record.get("details") or {}
        revised_invoice = (
            (bool(record.get("lookup_code")) and record["lookup_code"] != code)
            or (bool(saved_number) and bool(current_number) and saved_number != current_number)
            or (old_details.get("total_vnd") is not None
                and old_details["total_vnd"] != inv.total_vnd)
        )
        # A new invoice code/serial for the same month must never re-use the
        # old PDF, even if the previous file remains perfectly valid.
        overwrite = overwrite or revised_invoice
        folder = self._catalog["folder"]
        variant = ("reference" if record.get("pdf_source") == "viwaco-summary"
                   else "html" if record.get("pdf_source") == "viwaco-html" else "official")
        relative_old_pdf = make_archive_relative(folder, inv.year, inv.month, "pdf", variant=variant)
        old_pdf_path = self.hass.config.path("www", relative_old_pdf)
        old_pdf_ok = bool(record.get("pdf_url")) and await self.hass.async_add_executor_job(
            existing_pdf_is_valid, old_pdf_path
        )
        if record.get("pdf_url") and not old_pdf_ok:
            record.pop("pdf_url", None)
            record.pop("pdf_source", None)
            record.pop("pdf_repaired", None)
            record.pop("pdf_pages", None)
            self._catalog["records"][period] = record
            await self._save()
            _LOGGER.warning("VIWACO customer=%s month=%s saved PDF missing/corrupt; link cleared",
                            self.customer_id, period)

        old_png_variant = ("reference" if record.get("png_source") == "viwaco-summary"
                           else "html" if record.get("png_source") == "viwaco-html" else "official")
        old_png_urls = record.get("png_urls") or []
        png_paths = [self.hass.config.path("www", make_archive_relative(
            folder, inv.year, inv.month, "png", page=i, variant=old_png_variant))
            for i in range(1, len(old_png_urls) + 1)]
        png_ok = bool(old_png_urls) and await self.hass.async_add_executor_job(
            existing_pngs_are_valid, png_paths
        )
        if old_png_urls and not png_ok:
            record.pop("png_urls", None)
            record.pop("png_source", None)
            self._catalog["records"][period] = record
            await self._save()

        need_details = overwrite or not record.get("details")
        # Evaluate each format independently. A valid original PDF must NEVER
        # be downgraded because the PNG happens to be a reference summary.
        need_pdf = mode in ("pdf", "both") and (
            overwrite or not old_pdf_ok or record.get("pdf_source") == "viwaco-summary"
        )
        need_png = mode in ("png", "both") and (
            overwrite or not png_ok or record.get("png_source") == "viwaco-summary"
        )
        if not any((need_details, need_pdf, need_png)):
            return False

        # Offline regeneration: an already validated original PDF can be used
        # for missing/corrupt reference PNG without another website request.
        if need_png and not need_pdf and not need_details and old_pdf_ok and variant in ("official", "html"):
            raw = await self.hass.async_add_executor_job(Path(old_pdf_path).read_bytes)
            pages = await self.hass.async_add_executor_job(render_pdf_pngs, raw)
            urls = []
            for index, payload in enumerate(pages, 1):
                relative = make_archive_relative(folder, inv.year, inv.month, "png", index, variant=variant)
                await self.hass.async_add_executor_job(
                    write_bytes_atomic, self.hass.config.path("www", relative), payload
                )
                urls.append(local_url(relative))
            record.update(png_urls=urls, png_source=record.get("pdf_source", "viwaco-original"),
                          saved_at=datetime.now(timezone.utc).isoformat())
            self._catalog["records"][period] = record
            await self._save()
            return True

        # Look up again to verify customer identity. No tracing-site cookie is
        # ever sent to hoadon.viwaco.vn, including for fallback references.
        lookup_bytes = await self._get(session, "/tra-cuu/", {"code": code})
        lookup_html = lookup_bytes.decode("utf-8", "replace")
        lookup = parse_lookup(lookup_html, self.customer_id, expected_code=code)
        verify_invoice_number(getattr(inv, "invoice_number", None), lookup.get("invoice_number"))
        if lookup.get("total_vnd") != inv.total_vnd:
            lookup["billing_table_total_vnd"] = inv.total_vnd
            lookup["total_mismatch"] = True

        if need_pdf or need_png or need_details:
            # The issuer's HTML is the single source for rendered PDF/PNG.
            view_bytes = await self._get(session, "/View.aspx", {"Code": code, "Mode": "HTML"})
            view_html = view_bytes.decode("utf-8-sig", "replace")
            detail = {**lookup, **parse_invoice_view(view_html, self.customer_id)}
        else:
            detail = dict(lookup)
            view_html = ""
        if need_details:
            record["details"] = detail

        if need_pdf or need_png:
            if lookup.get("total_mismatch"):
                raise InvoicePdfError("Số tiền bảng VIWACO khác cổng tra cứu; không tạo PDF/PNG")
            # Compare the signed issuer HTML view's amount against the lookup
            # and the billing row. Never generate a plausible wrong bill.
            total = detail.get("total_vnd")
            if total is None or total != lookup.get("total_vnd"):
                raise InvoicePdfError("Tổng tiền bản HTML khác trang tra cứu VIWACO")
            qr = await self._fetch_optional_asset(session, "/qrcode.ashx", {"code": code})
            background = await self._fetch_optional_asset(session, "/invoice.jpg", {})
            pdf, png = await self.hass.async_add_executor_job(
                render_viwaco_html_invoice, view_html, self.customer_id, code,
                period, total, qr, background, lookup.get("invoice_number")
            )
            checked = await self.hass.async_add_executor_job(check_or_repair_pdf, pdf)
            if checked.repaired:
                raise InvoicePdfError("Bản PDF HTML tạo ra không hợp lệ")
            source = "viwaco-html"
            if need_pdf:
                relative = make_archive_relative(folder, inv.year, inv.month, "pdf", variant="html")
                await self.hass.async_add_executor_job(
                    write_bytes_atomic, self.hass.config.path("www", relative), checked.content
                )
                record.update(pdf_url=local_url(relative), pdf_source=source,
                              pdf_repaired=False, pdf_pages=checked.pages)
            if need_png:
                relative = make_archive_relative(folder, inv.year, inv.month, "png", variant="html")
                await self.hass.async_add_executor_job(
                    write_bytes_atomic, self.hass.config.path("www", relative), png
                )
                record.update(png_urls=[local_url(relative)], png_source=source)

        record["lookup_code"] = code
        record["invoice_number"] = lookup.get("invoice_number")
        record["saved_at"] = datetime.now(timezone.utc).isoformat()
        self._catalog["records"][period] = record
        await self._save()
        return True

    async def async_sync(self, invoices, *, year: int = 0, mode: str = "both",
                         overwrite: bool = False, max_invoices: int = 0,
                         notify: bool = True) -> dict | None:
        """Download selected invoices; report successes for automatic retry tracking."""
        if self._sync_lock.locked():
            _LOGGER.info("VIWACO customer=%s: archive sync already running", self.customer_id)
            return
        async with self._sync_lock:
            await self.async_load()
            selected = [inv for inv in invoices if (not year or inv.year == year)]
            if max_invoices:
                selected = selected[:max_invoices]
            self.status = {"running": True, "done": 0, "total": len(selected),
                           "errors": 0, "message": "Đang đồng bộ lưu trữ"}
            failures = []
            completed = []
            changed = 0
            html_renders = 0
            references = 0
            notification = f"viwaco_reader_{self.entry_id}_archive"
            try:
                timeout = ClientTimeout(total=40, connect=12)
                async with ClientSession(timeout=timeout, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; HomeAssistant-VIWACO/1.3)",
                    "Accept": "text/html,image/png,image/jpeg;q=0.9,*/*;q=0.8",
                }) as session:
                    for idx, inv in enumerate(selected, start=1):
                        try:
                            async with _DOWNLOAD_GATE:
                                if await self._process_one(session, inv, mode, overwrite):
                                    changed += 1
                                    if self.records.get(inv.period, {}).get("pdf_source") == "viwaco-html":
                                        html_renders += 1
                                final = self.records.get(inv.period, {})
                                is_reference = ((mode in ("pdf", "both") and
                                                 final.get("pdf_source") == "viwaco-summary") or
                                                (mode in ("png", "both") and
                                                 final.get("png_source") == "viwaco-summary"))
                                if is_reference:
                                    references += 1
                                else:
                                    completed.append(inv.period)
                                # Rate-limit requests across customer IDs.
                                await asyncio.sleep(1.0)
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            # Per-invoice isolation: bad PDFium render or one
                            # legacy invoice must not abort all other months.
                            # Do not include full HTTP URLs/headers in logs.
                            known = isinstance(exc, (ValueError, OSError, RuntimeError, ImportError))
                            reason = str(exc) if known else type(exc).__name__
                            failures.append(f"{inv.period}: {reason[:150]}")
                            _LOGGER.warning("VIWACO customer=%s month=%s archive download failed: %s",
                                            self.customer_id, inv.period, reason[:150])
                        self.status.update(done=idx, errors=len(failures))
            except asyncio.CancelledError:
                self.status["message"] = "Đã hủy do integration unload/reload"
                raise
            except Exception:
                _LOGGER.exception("VIWACO customer=%s: unexpected invoice archive failure", self.customer_id)
                failures.append("Lỗi không mong đợi; xem System → Logs")
            finally:
                self.status["running"] = False
                self.status["message"] = (f"Hoàn tất: {changed} kỳ tải/cập nhật, "
                                          f"{len(failures)} kỳ lỗi, tổng {len(selected)} kỳ"
                                          + (f"; {html_renders} kỳ kết xuất PDF/PNG từ HTML "
                                             "(không chứa chữ ký số)" if html_renders else "")
                                          + (f"; {references} bản tóm tắt cũ chờ nâng cấp từ HTML" if references else ""))
                if notify:
                    persistent_notification.async_create(
                        self.hass,
                        title=f"VIWACO Reader – lưu hóa đơn ({self.customer_id})",
                        message=(self.status["message"] + "\n\nLưu tại `/config/www/viwaco_reader/`. "
                                 + ("\n\nMột số lỗi: " + "; ".join(failures[:5]) if failures else "")
                                 + "\n\nLưu ý: /local không được Home Assistant bảo vệ bằng đăng nhập."),
                        notification_id=notification,
                    )
                elif failures:
                    persistent_notification.async_create(
                        self.hass,
                        title=f"VIWACO Reader – lỗi tự lưu hóa đơn ({self.customer_id})",
                        message=(self.status["message"] + "\n\n" + "; ".join(failures[:5])
                                 + "\n\nSẽ thử lại sau khi đồng bộ dữ liệu thành công."),
                        notification_id=f"{notification}_auto_error",
                    )
                else:
                    persistent_notification.async_dismiss(self.hass, f"{notification}_auto_error")
                _LOGGER.info("VIWACO customer=%s archive: %s", self.customer_id,
                             self.status["message"])
            return {"completed": completed, "failures": failures}
