"""Archive invoices only on genuine billing changes, never on unchanged polls.

The first successful authenticated poll establishes a persistent baseline. A new
billing period, payment change, invoice number or lookup code can trigger an
archive; repeated identical polls (and restarts) cause no invoice-site request.
Failed jobs are retained for the *next change* or explicit manual service, not
retried on each refresh. This worker never uses the tracuu session Cookie.
"""
from __future__ import annotations

import asyncio
import logging

from homeassistant.helpers.storage import Store

from .archive_parser import invoice_code, invoice_number_digits
from .const import (
    CONF_AUTO_ARCHIVE_ENABLED, CONF_AUTO_ARCHIVE_MODE,
    DEFAULT_AUTO_ARCHIVE_ENABLED, DEFAULT_AUTO_ARCHIVE_MODE,
)

_LOGGER = logging.getLogger(__name__)
_MAX_PERIODS = 180


def period_order(invoice) -> int:
    return int(invoice.year) * 12 + int(invoice.month)


def payment_signature(invoice) -> dict:
    """Values behind HA billing/payment sensors, not update timestamps."""
    date = getattr(invoice, "payment_date", None)
    return {
        "total_vnd": int(invoice.total_vnd),
        "paid_vnd": int(invoice.paid_vnd),
        "advance_vnd": int(invoice.advance_vnd),
        "payment_date": date.isoformat() if date else None,
        "invoice_number": (invoice.invoice_number or "").strip(),
        "lookup_code": invoice_code(invoice.invoice_url),
    }


def invoice_identity(invoice) -> str | None:
    """A stable exact invoice version. A payment alone does not change it."""
    code = invoice_code(invoice.invoice_url)
    number = invoice_number_digits(invoice.invoice_number)
    if not code or not number or invoice.total_vnd <= 0:
        return None
    return f"{code}|{number}|{int(invoice.total_vnd)}"


def observation(invoices) -> dict[str, dict]:
    """Use only valid, bounded history. Retain rows without codes for later change detection."""
    rows = sorted(invoices, key=period_order, reverse=True)[:_MAX_PERIODS]
    return {inv.period: payment_signature(inv) for inv in rows}


class AutoInvoiceArchiver:
    """Per-entry, restart-safe and change-driven archive scheduler."""

    def __init__(self, hass, entry, archive) -> None:
        self.hass = hass
        self.entry = entry
        self.archive = archive
        self.customer_id = entry.data["customer_id"]
        self.enabled = bool(entry.options.get(CONF_AUTO_ARCHIVE_ENABLED, DEFAULT_AUTO_ARCHIVE_ENABLED))
        self.mode = entry.options.get(CONF_AUTO_ARCHIVE_MODE, DEFAULT_AUTO_ARCHIVE_MODE)
        # Keep HA's Store file version stable to read v1.7.3 state; schema is in payload.
        self._store = Store[dict](hass, 1, f"viwaco_reader.auto_archive_{entry.entry_id}")
        self._loaded = False
        self._observed: dict[str, dict] | None = None
        self._completed: dict[str, str] = {}
        self._pending: dict[str, str] = {}
        self._busy = False
        self._load_lock = asyncio.Lock()

    async def async_restore(self) -> None:
        if self._loaded or not self.enabled:
            return
        async with self._load_lock:
            if self._loaded:
                return
            try:
                state = await self._store.async_load() or {}
                if isinstance(state, dict) and state.get("schema") == 2:
                    observed = state.get("observed")
                    if isinstance(observed, dict):
                        self._observed = {
                            key: value for key, value in list(observed.items())[:_MAX_PERIODS]
                            if isinstance(key, str) and isinstance(value, dict)
                        }
                    if state.get("mode") == self.mode:
                        self._completed = {
                            key: value for key, value in (state.get("completed") or {}).items()
                            if isinstance(key, str) and isinstance(value, str)
                        }
                    self._pending = {
                        key: value for key, value in (state.get("pending") or {}).items()
                        if isinstance(key, str) and isinstance(value, str)
                    }
                # Legacy v1.7.3 baseline/completed cannot prove an event or
                # an exact invoice identity. Start with a fresh observation,
                # rather than downloading anything on upgrade/restart.
            except (ValueError, TypeError, OSError, AttributeError) as exc:
                _LOGGER.warning("VIWACO customer=%s billing archive state unreadable: %s",
                                self.customer_id, type(exc).__name__)
            self._loaded = True

    async def _save(self) -> None:
        await self._store.async_save({
            "schema": 2,
            "mode": self.mode,
            "observed": self._observed or {},
            "completed": self._completed,
            "pending": self._pending,
        })

    def schedule(self, invoices) -> None:
        """Fast no-op on unchanged refresh; never block the coordinator."""
        if not self.enabled or self._busy or not invoices:
            return
        incoming = tuple(invoices)
        if self._loaded and self._observed == observation(incoming):
            return
        self._busy = True
        try:
            self.entry.async_create_background_task(
                self.hass, self._run(incoming),
                f"VIWACO billing change invoice archive {self.entry.entry_id}",
            )
        except BaseException:
            self._busy = False
            raise

    async def _run(self, invoices) -> None:
        try:
            await self.async_restore()
            current = observation(invoices)
            if self._observed is None:
                # First live poll after enable/upgrade is an observation, not
                # a 'change' inferred from empty state.
                self._observed = current
                await self._save()
                _LOGGER.debug("VIWACO customer=%s archive: initial payment baseline saved", self.customer_id)
                return
            changed = {period for period, signature in current.items()
                       if self._observed.get(period) != signature}
            if not changed:
                return
            # Save the new observation *before* any optional website/network
            # work, ensuring failure never causes repeated downloads on polling.
            self._observed = current
            invoice_by_period = {i.period: i for i in invoices}
            for period in changed:
                inv = invoice_by_period[period]
                identity = invoice_identity(inv)
                if identity and self._completed.get(period) != identity:
                    self._pending[period] = identity
                else:
                    self._pending.pop(period, None)
            # Unpublished bills (no code/number) are never guessed. Old pending
            # jobs only retry when *another real payment event* arrives.
            await self._save()

            pending = []
            for period, identity in self._pending.items():
                inv = invoice_by_period.get(period)
                if inv and invoice_identity(inv) == identity:
                    record = self.archive.records.get(period, {})
                    correct_identity = (
                        record.get("lookup_code") == invoice_code(inv.invoice_url)
                        and invoice_number_digits(record.get("invoice_number"))
                            == invoice_number_digits(inv.invoice_number)
                        and (record.get("details") or {}).get("total_vnd") == inv.total_vnd
                    )
                    pdf_saved = bool(record.get("pdf_url"))
                    png_saved = bool(record.get("png_urls"))
                    already_stored = correct_identity and (
                        (self.mode == "pdf" and pdf_saved)
                        or (self.mode == "png" and png_saved)
                        or (self.mode == "both" and pdf_saved and png_saved)
                    )
                    if already_stored:
                        self._completed[period] = identity
                        continue
                    pending.append(inv)
            # A manual sync or another running archive does not count as success.
            if not pending:
                self._pending = {p: i for p, i in self._pending.items()
                                 if self._completed.get(p) != i}
                await self._save()
                return
            pending.sort(key=period_order)
            result = await self.archive.async_sync(
                pending, mode=self.mode, overwrite=False, notify=False,
            )
            if result is None:
                return
            succeeded = set(result.get("completed", ()))
            for inv in pending:
                if inv.period in succeeded:
                    self._completed[inv.period] = invoice_identity(inv)
            self._pending = {p: i for p, i in self._pending.items()
                             if self._completed.get(p) != i}
            await self._save()
            if succeeded:
                _LOGGER.info("VIWACO customer=%s archived changed invoices: %s",
                             self.customer_id, ", ".join(sorted(succeeded)))
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("VIWACO customer=%s change-driven invoice archive failed", self.customer_id)
        finally:
            self._busy = False
