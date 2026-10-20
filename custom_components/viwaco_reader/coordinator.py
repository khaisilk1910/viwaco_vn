"""Per-entry VIWACO data, 15-minute keep-alive and restart-safe snapshot cache.

All network and disk I/O is asynchronous, scheduled after HA entry setup.
If a cached snapshot exists, failed requests preserve the numerical sensors;
session_status provides explicit health rather than claiming a fresh reading.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from homeassistant.components import persistent_notification
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ViwacoApi, ViwacoAuthError, ViwacoConnectionError
from .archive import InvoiceArchive
from .auto_archive import AutoInvoiceArchiver
from .const import (
    CONF_COOKIE, CONF_CUSTOMER_ID, CONF_UPDATE_HOURS, CONF_HISTORY_MONTHS,
    DEFAULT_HISTORY_MONTHS, DEFAULT_UPDATE_INTERVAL_HOURS,
)
from .parser import ViwacoData
from .history import available_month_span, selected_history
from .snapshot import encode_snapshot, decode_snapshot

_LOGGER = logging.getLogger(__name__)

_AUTH_MESSAGES = {
    "session_expired": "Phiên VIWACO đã hết hạn hoặc chưa đăng nhập.",
    "wrong_customer": "Cookie không thuộc mã khách hàng đã cấu hình.",
    "invalid_cookie_format": "Cookie không đúng định dạng.",
}


class ViwacoCoordinator(DataUpdateCoordinator[ViwacoData]):
    """Expose cached readings plus independently monitored session health."""

    def __init__(self, hass, entry) -> None:
        hours = int(entry.options.get(CONF_UPDATE_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS))
        super().__init__(
            hass, _LOGGER, config_entry=entry,
            name=f"VIWACO {entry.data[CONF_CUSTOMER_ID]}",
            update_interval=timedelta(hours=hours), always_update=False,
        )
        self.entry = entry
        self.customer_id = entry.data[CONF_CUSTOMER_ID]
        self.api = ViwacoApi(hass, self.customer_id, entry.data[CONF_COOKIE], self._persist_cookie)
        self.archive = InvoiceArchive(hass, entry)
        self.auto_archive = AutoInvoiceArchiver(hass, entry, self.archive)
        self.last_error: str | None = None
        self.last_successful_fetch: datetime | None = None
        self.last_session_check: datetime | None = None
        self.cache_saved_at: str | None = None
        self.session_status = "initializing"
        self.available_history_months = 0
        self.history_months = int(entry.options.get(CONF_HISTORY_MONTHS, DEFAULT_HISTORY_MONTHS))
        self._store = Store[dict](hass, 1, f"viwaco_reader.snapshot_{entry.entry_id}")
        self._notification_id = f"viwaco_reader_{entry.entry_id}_error"
        self._reported_message: str | None = None
        self._reauth_started = False
        self._keepalive_running = False
        self._auth_failure_count = 0
        self._auth_first_failure: datetime | None = None

    def _persist_cookie(self, cookie: str) -> None:
        """Persist server-rotated cookies using HA's event-loop config API."""
        if cookie == self.entry.data.get(CONF_COOKIE):
            return
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, CONF_COOKIE: cookie},
        )
        _LOGGER.debug("VIWACO customer=%s: first-party session Cookie rotated and saved", self.customer_id)

    def _state(self, state: str, *, error: str | None = None) -> None:
        changed = self.session_status != state or self.last_error != error
        self.session_status = state
        self.last_error = error
        self.last_session_check = datetime.now(timezone.utc)
        if changed:
            self.async_update_listeners()

    def _alert(self, message: str, auth: bool) -> None:
        if self._reported_message == message:
            return
        self._reported_message = message
        fix = (
            "Đăng nhập lại tracuu.viwaco.vn, giải CAPTCHA và cập nhật Cookie qua "
            "Settings → Devices & services → VIWACO Reader → Reconfigure/Reauthenticate."
            if auth else
            "Kiểm tra mạng/VIWACO; dùng action viwaco_reader.refresh để thử lại. "
            "Chi tiết tại Settings → System → Logs."
        )
        persistent_notification.async_create(
            self.hass,
            message=(f"**Mã khách hàng:** `{self.customer_id}`\n\n"
                     f"**Lỗi:** {message}\n\n{fix}\n\nKhông chia sẻ Cookie."),
            title="VIWACO Reader – phiên hết hạn" if auth else "VIWACO Reader – lỗi kết nối",
            notification_id=self._notification_id,
        )

    def clear_alert(self) -> None:
        if self._reported_message is not None:
            persistent_notification.async_dismiss(self.hass, self._notification_id)
            _LOGGER.info("VIWACO customer=%s: kết nối được khôi phục", self.customer_id)
        self._reported_message = None
        self.last_error = None
        self._auth_failure_count = 0
        self._auth_first_failure = None
        self._reauth_started = False

    def _auth_failed(self, exc: ViwacoAuthError) -> tuple[str, bool]:
        """Confirm auth errors across checks before starting an HA repair.

        At least two authentication failures >=45 seconds apart are required.
        The first failure is a diagnostic, not evidence the session is expired.
        """
        now = datetime.now(timezone.utc)
        if (self._auth_first_failure is None
                or now - self._auth_first_failure > timedelta(hours=3)):
            self._auth_first_failure = now
            self._auth_failure_count = 1
        elif now - self._auth_first_failure >= timedelta(seconds=45):
            self._auth_failure_count += 1

        reason = exc.reason
        message = _AUTH_MESSAGES.get(reason, "Phiên VIWACO không hợp lệ.")
        if self._auth_failure_count < 2:
            _LOGGER.warning(
                "VIWACO customer=%s AUTH_UNCONFIRMED reason=%s evidence=%s; will recheck (no credentials logged)",
                self.customer_id, reason, getattr(exc, "evidence", "unspecified"),
            )
            self._state("offline", error="Đang kiểm tra lại xác thực VIWACO.")
            return message, False

        if self.session_status != "expired":
            _LOGGER.error(
                "VIWACO customer=%s AUTH_FAILED reason=%s evidence=%s confirmed across checks (no credentials logged)",
                self.customer_id, reason, getattr(exc, "evidence", "unspecified"),
            )
        self._state("expired", error=message)
        self._alert(message, auth=True)
        if not self._reauth_started:
            self._reauth_started = True
            self.entry.async_start_reauth(self.hass)
        return message, True

    def _network_failed(self, exc: ViwacoConnectionError, source: str) -> str:
        self._auth_failure_count = 0
        self._auth_first_failure = None
        message = f"Không tải được dữ liệu ({source}): {exc}"
        _LOGGER.error("VIWACO customer=%s NETWORK_ERROR source=%s type=%s detail=%s",
                      self.customer_id, source, type(exc).__name__, str(exc))
        self._state("offline", error=message)
        self._alert(message, auth=False)
        return message

    async def async_restore_and_refresh(self) -> None:
        """Run only as an entry-owned background task AFTER entities are added."""
        try:
            raw = await self._store.async_load()
            if raw:
                restored = decode_snapshot(raw, self.customer_id)
                self.cache_saved_at = raw.get("saved_at")
                self.available_history_months = available_month_span(restored)
                self._state("cached")
                self.async_set_updated_data(selected_history(restored, self.history_months))
                _LOGGER.info("VIWACO customer=%s: restored local snapshot; waiting for live verification",
                             self.customer_id)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            _LOGGER.warning("VIWACO customer=%s: snapshot unreadable (%s); fetching online",
                            self.customer_id, type(exc).__name__)
        try:
            await self.archive.async_load()
        except (OSError, ValueError) as exc:
            _LOGGER.warning("VIWACO customer=%s: archive metadata unavailable (%s)",
                            self.customer_id, type(exc).__name__)
        await self.auto_archive.async_restore()
        await self.async_refresh()

    async def _async_update_data(self) -> ViwacoData:
        try:
            all_data = await self.api.async_fetch_data()
            self.available_history_months = available_month_span(all_data)
            selected = selected_history(all_data, self.history_months)
        except ViwacoAuthError as exc:
            message, confirmed = self._auth_failed(exc)
            if self.data is not None:
                # Preserve last good data on expired auth; status clearly says expired.
                return self.data
            if confirmed:
                raise ConfigEntryAuthFailed(message) from exc
            raise UpdateFailed("VIWACO authentication under verification") from exc
        except ViwacoConnectionError as exc:
            message = self._network_failed(exc, "refresh")
            if self.data is not None:
                return self.data
            raise UpdateFailed(message) from exc
        else:
            self.last_successful_fetch = datetime.now(timezone.utc)
            self._state("valid")
            self.clear_alert()
            # Cache has only current history selection (not raw HTML or cookies).
            payload = encode_snapshot(selected)
            self.cache_saved_at = payload["saved_at"]
            try:
                await self._store.async_save(payload)
            except (OSError, TypeError, ValueError) as exc:
                _LOGGER.warning("VIWACO customer=%s: unable to persist snapshot: %s",
                                self.customer_id, type(exc).__name__)
            try:
                self.auto_archive.schedule(selected.invoices)
            except Exception:
                # Archiving is optional and must never mark sensor refresh failed.
                _LOGGER.exception("VIWACO customer=%s cannot queue automatic archive", self.customer_id)
            _LOGGER.debug("VIWACO customer=%s: refresh OK invoices=%s readings=%s",
                          self.customer_id, len(selected.invoices), len(selected.readings))
            return selected

    async def async_keepalive(self) -> None:
        """Check session without downloading PDF/PNG or re-parsing meter history."""
        if self._keepalive_running:
            return
        self._keepalive_running = True
        try:
            await self.api.async_keepalive()
        except ViwacoAuthError as exc:
            self._auth_failed(exc)
        except ViwacoConnectionError as exc:
            self._network_failed(exc, "keepalive")
        else:
            self._state("valid")
            self.clear_alert()
            _LOGGER.debug("VIWACO customer=%s: keep-alive session valid", self.customer_id)
        finally:
            self._keepalive_running = False
