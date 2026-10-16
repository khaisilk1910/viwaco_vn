"""Invoice archiving on demand or (opt-in) after successful data refresh.

Official invoice HTML and official binary PDF are fetched from a fixed HTTPS
host. PNG images are rendered from PDF bytes in an executor. No CAPTCHA
bypass and no cross-host forwarding of the tracuu.viwaco.vn session Cookie.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, ClientError
from homeassistant.components import persistent_notification

from .archive_parser import ArchiveParseError, invoice_code, parse_lookup, parse_invoice_view, BASE
from .pdf_tools import check_or_repair_pdf, existing_pdf_is_valid
from .archive_store import (
    load_catalog, local_url, make_archive_relative, render_pdf_pngs,
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

    async def _process_one(self, session, inv, mode: str, overwrite: bool) -> bool:
        code = invoice_code(inv.invoice_url)
        if code is None:
            raise ValueError("Không có URL tra cứu hóa đơn điện tử hợp lệ")
        period = inv.period
        record = dict(self.records.get(period, {}))
        relative_pdf = make_archive_relative(self._catalog["folder"], inv.year, inv.month, "pdf")
        pdf_path = self.hass.config.path("www", relative_pdf)

        # v1.6.0 could save broken PDFs after checking only the %PDF header.
        # Never trust its catalog as evidence the PDF is openable.
        has_old_pdf = bool(record.get("pdf_url"))
        old_pdf_ok = False
        if has_old_pdf and mode in ("pdf", "png", "both"):
            old_pdf_ok = await self.hass.async_add_executor_job(existing_pdf_is_valid, pdf_path)
            if not old_pdf_ok:
                _LOGGER.warning(
                    "VIWACO customer=%s month=%s: saved PDF is damaged or missing; will fetch again",
                    self.customer_id, period,
                )
                # A stale link should not continue to point to a broken PDF,
                # even if the supplier also fails on the next attempt.
                record.pop("pdf_url", None)
                record.pop("pdf_source", None)
                record.pop("pdf_repaired", None)
                record.pop("pdf_pages", None)
                self._catalog["records"][period] = record
                await self._save()
        need_details = overwrite or not record.get("details")
        need_pdf = mode in ("pdf", "both") and (overwrite or not old_pdf_ok)
        need_png = mode in ("png", "both") and (overwrite or not record.get("png_urls"))
        if not any((need_details, need_pdf, need_png)):
            return False

        # Verify the customer before fetching the matching invoice detail.
        # The tracuu.viwaco.vn session Cookie is NEVER forwarded here.
        lookup_bytes = await self._get(session, "/tra-cuu/", {"code": code})
        lookup = parse_lookup(lookup_bytes.decode("utf-8", "replace"), self.customer_id)
        if lookup.get("total_vnd") != inv.total_vnd:
            lookup["billing_table_total_vnd"] = inv.total_vnd
            lookup["total_mismatch"] = True
        if need_details:
            detail = dict(lookup)
            try:
                view_bytes = await self._get(
                    session, "/View.aspx", {"Code": code, "Mode": "HTML"}
                )
                detail.update(parse_invoice_view(view_bytes.decode("utf-8", "replace"), self.customer_id))
            except (ValueError, ArchiveParseError) as exc:
                _LOGGER.debug("VIWACO customer=%s month=%s detailed view unavailable: %s",
                              self.customer_id, period, type(exc).__name__)
            record["details"] = detail

        if need_pdf or need_png:
            # If an intact local PDF exists, use it for a missing PNG instead of
            # issuing another PDF download. Otherwise fetch official binary.
            if old_pdf_ok and not need_pdf:
                raw_pdf = await self.hass.async_add_executor_job(Path(pdf_path).read_bytes)
            else:
                raw_pdf = await self._get(
                    session, "/View.aspx", {"Code": code, "Mode": "PDF"}, is_pdf=True
                )

            # CPU-intensive validation and optional xref repair must never block
            # the HA event loop. Both PDF-only and PNG modes use this check.
            checked = await self.hass.async_add_executor_job(check_or_repair_pdf, raw_pdf)
            png_pages = None
            if need_png:
                png_pages = await self.hass.async_add_executor_job(render_pdf_pngs, checked.content)

            # Publish only AFTER the PDF has passed PDFium validation and all
            # PNGs have been successfully rendered. No bogus PDFs ever written.
            if need_pdf:
                await self.hass.async_add_executor_job(write_bytes_atomic, pdf_path, checked.content)
                record["pdf_url"] = local_url(relative_pdf)
                record["pdf_repaired"] = checked.repaired
                record["pdf_source"] = "viwaco-repaired" if checked.repaired else "viwaco-original"
                record["pdf_pages"] = checked.pages
            if need_png:
                urls = []
                for idx, payload in enumerate(png_pages, start=1):
                    relative = make_archive_relative(
                        self._catalog["folder"], inv.year, inv.month, "png", idx
                    )
                    fullpath = self.hass.config.path("www", relative)
                    await self.hass.async_add_executor_job(write_bytes_atomic, fullpath, payload)
                    urls.append(local_url(relative))
                record["png_urls"] = urls
            if checked.repaired:
                _LOGGER.warning(
                    "VIWACO customer=%s month=%s: original supplier PDF had broken structure; "
                    "a repaired copy was saved (any embedded digital signature may no longer verify)",
                    self.customer_id, period,
                )

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
            repaired = 0
            notification = f"viwaco_reader_{self.entry_id}_archive"
            try:
                timeout = ClientTimeout(total=40, connect=12)
                async with ClientSession(timeout=timeout, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; HomeAssistant-VIWACO/1.3)",
                    "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.8",
                }) as session:
                    for idx, inv in enumerate(selected, start=1):
                        try:
                            async with _DOWNLOAD_GATE:
                                if await self._process_one(session, inv, mode, overwrite):
                                    changed += 1
                                    if self.records.get(inv.period, {}).get("pdf_repaired"):
                                        repaired += 1
                                completed.append(inv.period)
                                # Use shared limiter across customer IDs; avoid
                                # concurrent bursts to the invoice portal.
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
                                          + (f"; {repaired} PDF được phục hồi cấu trúc "
                                             "(chữ ký số có thể không còn hợp lệ)" if repaired else ""))
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
