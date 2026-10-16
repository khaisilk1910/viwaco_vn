"""Opt-in automatic archiving of newly published invoice periods.

After the user enables this feature, archive the latest available invoice once,
then any later invoice periods at the next successful meter poll. Processing is
outside the coordinator update path, persistent across restarts, and retries
failed periods without hammering the invoice site during the HA startup path.
"""
from __future__ import annotations

import asyncio
import logging

from homeassistant.helpers.storage import Store

from .const import (
    CONF_AUTO_ARCHIVE_ENABLED, CONF_AUTO_ARCHIVE_MODE,
    DEFAULT_AUTO_ARCHIVE_ENABLED, DEFAULT_AUTO_ARCHIVE_MODE,
)

_LOGGER = logging.getLogger(__name__)


def period_order(invoice) -> int:
    """Use year/month ordering, not lexicographic MM/YYYY ordering."""
    return int(invoice.year) * 12 + int(invoice.month)


class AutoInvoiceArchiver:
    """Per-entry archive tracker; no HTTP or PDF work on the HA event loop."""

    def __init__(self, hass, entry, archive) -> None:
        self.hass = hass
        self.entry = entry
        self.archive = archive
        self.customer_id = entry.data["customer_id"]
        self.enabled = bool(entry.options.get(CONF_AUTO_ARCHIVE_ENABLED, DEFAULT_AUTO_ARCHIVE_ENABLED))
        self.mode = entry.options.get(CONF_AUTO_ARCHIVE_MODE, DEFAULT_AUTO_ARCHIVE_MODE)
        self._store = Store[dict](hass, 1, f"viwaco_reader.auto_archive_{entry.entry_id}")
        self._loaded = False
        self._baseline: int | None = None
        self._completed: set[str] = set()
        self._busy = False
        self._load_lock = asyncio.Lock()

    async def async_restore(self) -> None:
        """Load only in an entry-owned background task, never in setup."""
        if self._loaded or not self.enabled:
            return
        async with self._load_lock:
            if self._loaded:
                return
            try:
                state = await self._store.async_load() or {}
                if isinstance(state, dict):
                    baseline = state.get("baseline")
                    self._baseline = int(baseline) if baseline is not None else None
                    if state.get("mode") == self.mode:
                        self._completed = set(
                            period for period in state.get("completed", [])
                            if isinstance(period, str)
                        )
            except (ValueError, TypeError, OSError) as exc:
                _LOGGER.warning("VIWACO customer=%s auto archive state unreadable: %s",
                                self.customer_id, type(exc).__name__)
            self._loaded = True

    async def _save(self) -> None:
        await self._store.async_save({
            "baseline": self._baseline,
            "mode": self.mode,
            "completed": sorted(self._completed),
        })

    def schedule(self, invoices) -> None:
        """Never await network/PDF processing in a sensor data refresh."""
        if not self.enabled or self._busy or not invoices:
            return
        self._busy = True
        # Task belongs to this particular config entry and is cancelled on unload.
        try:
            self.entry.async_create_background_task(
                self.hass, self._run(tuple(invoices)),
                f"VIWACO automatic invoice archive {self.entry.entry_id}",
            )
        except BaseException:
            self._busy = False
            raise

    async def _run(self, invoices) -> None:
        try:
            await self.async_restore()
            with_codes = [invoice for invoice in invoices if invoice.invoice_url]
            if not with_codes:
                return
            newest = max(with_codes, key=period_order)
            if self._baseline is None:
                # On opt-in: first archive only the latest invoice (not the
                # entire historical archive); later months are above this mark.
                self._baseline = period_order(newest) - 1
                await self._save()
            pending = sorted(
                (inv for inv in with_codes
                 if period_order(inv) > self._baseline and inv.period not in self._completed),
                key=period_order,
            )
            if not pending:
                return
            results = await self.archive.async_sync(
                pending, mode=self.mode, overwrite=False, notify=False,
            )
            if results is None:  # An explicit manual archive was already running.
                return
            succeeded = set(results.get("completed", ()))
            if succeeded:
                self._completed.update(succeeded)
                await self._save()
                _LOGGER.info("VIWACO customer=%s automatic invoice archive saved=%s",
                             self.customer_id, ",".join(sorted(succeeded)))
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("VIWACO customer=%s automatic invoice archive failed", self.customer_id)
        finally:
            self._busy = False
