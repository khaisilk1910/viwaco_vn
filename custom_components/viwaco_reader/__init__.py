"""VIWACO Reader: separate config entries, lightweight setup, rich history API."""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlsplit
from pathlib import Path
from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_CUSTOMER_ID, CONF_HISTORY_MONTHS, DOMAIN, PLATFORMS,
    CONF_KEEPALIVE_ENABLED, CONF_KEEPALIVE_MINUTES,
    DEFAULT_KEEPALIVE_ENABLED, DEFAULT_KEEPALIVE_MINUTES,
)
from .coordinator import ViwacoCoordinator
from .recent import latest_billing_periods

_LOGGER = logging.getLogger(__name__)
DASHBOARD_URL = "/viwaco_reader/viwaco-dashboard.js?v=1.7.4"


async def _async_register_dashboard_resource(hass: HomeAssistant) -> None:
    """Install card resource only in storage mode; never mutate YAML resources.

    Resource collections were lazy-loaded in older HA versions. Explicitly
    wait for a loaded collection before writes; never overwrite resources.
    Dashboard registration failure must never interrupt HA startup.
    """
    try:
        lovelace = hass.data.get("lovelace")
        if not lovelace or getattr(lovelace, "resource_mode", "yaml") != "storage":
            _LOGGER.info("VIWACO dashboard: add JS resource manually (Lovelace YAML or not ready)")
            return
        resources = lovelace.resources
        if not hasattr(resources, "loaded"):
            _LOGGER.warning("VIWACO dashboard: unknown resource API; use manual resource registration")
            return
        if not resources.loaded:
            await resources.async_load()
        url_path = "/viwaco_reader/viwaco-dashboard.js"
        for item in resources.async_items():
            if urlsplit(item["url"]).path == url_path:
                # Update only our exact resource path, preserving unrelated
                # Lovelace resources and YAML dashboards.
                if item["url"] != DASHBOARD_URL or item.get("res_type") != "module":
                    await resources.async_update_item(
                        item["id"], {"res_type": "module", "url": DASHBOARD_URL},
                    )
                    _LOGGER.info("VIWACO dashboard resource updated to %s", DASHBOARD_URL)
                return
        await resources.async_create_item({"res_type": "module", "url": DASHBOARD_URL})
        _LOGGER.info("VIWACO dashboard resource installed at %s", DASHBOARD_URL)
    except Exception:  # Dashboard is optional, do not impact HA services.
        _LOGGER.exception("VIWACO dashboard resource registration failed; add it manually")


# No blocking network call in async_setup_entry: initial refresh runs after setup.
# Every customer has its own entry.runtime_data and independent poll schedule.


def _coordinators(hass):
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if isinstance(getattr(entry, "runtime_data", None), ViwacoCoordinator)
    ]


@callback
@websocket_api.websocket_command({vol.Required("type"): "viwaco_reader/history"})
def websocket_history(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Provide historical rows on demand, avoiding huge sensor attributes."""
    records: list[dict[str, Any]] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        co = getattr(entry, "runtime_data", None)
        if not isinstance(co, ViwacoCoordinator):
            continue
        data = co.data
        records.append({
            "customer_id": entry.data[CONF_CUSTOMER_ID],
            "entry_id": entry.entry_id,
            "name": entry.options.get("meter_name") or entry.title,
            "available": data is not None,
            "session_status": co.session_status,
            "cache_saved_at": co.cache_saved_at,
            "last_successful_fetch": co.last_successful_fetch.isoformat() if co.last_successful_fetch else None,
            "last_error": co.last_error,
            "history_months": co.history_months,
            "history_all": co.history_months == 0,
            "history_available_months": co.available_history_months,
            "archive_status": co.archive.status,
            "archived_months": len(co.archive.records),
            "recent_months": [
                {"period": inv.period, "usage_m3": inv.usage_m3,
                 "total_vnd": inv.total_vnd, "previous_m3": r.previous_m3 if r else None,
                 "current_m3": r.current_m3 if r else None,
                 "read_date": r.read_date.isoformat() if r else None}
                for inv, r in latest_billing_periods(data)
            ] if data else [],
            "meter_serial": data.readings[0].serial if data and data.readings else None,
            "customer": data.customer.as_dict() if data else None,
            "reading_book": data.invoices[0].book if data and data.invoices else None,
            "invoices": [
                {**i.history_item(),
                 "start_date": i.start_date.isoformat() if i.start_date else None,
                 "end_date": i.end_date.isoformat() if i.end_date else None,
                 "invoice_url": i.invoice_url,
                 "invoice_number": i.invoice_number,
                 "archive": co.archive.records.get(i.period, {})}
                for i in data.invoices
            ] if data else [],
            "readings": [
                {**r.history_item(), "serial": r.serial, "type": r.reading_type}
                for r in data.readings
            ] if data else [],
        })
    connection.send_result(msg["id"], records)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register commands once, independently of any one meter."""
    await hass.http.async_register_static_paths([
        StaticPathConfig(
            "/viwaco_reader/viwaco-dashboard.js",
            str(Path(__file__).parent / "frontend" / "viwaco-dashboard.js"),
            False,
        ),
        StaticPathConfig(
            "/viwaco_reader/icon.png",
            str(Path(__file__).parent / "brand" / "icon.png"),
            True,
        ),
    ])
    websocket_api.async_register_command(hass, websocket_history)
    # Registration is a background task, not a startup network operation.
    hass.async_create_background_task(
        _async_register_dashboard_resource(hass), "VIWACO dashboard resource registration",
    )

    async def async_refresh_service(call: ServiceCall) -> None:
        customer_id = call.data.get(CONF_CUSTOMER_ID)
        targets = [c for c in _coordinators(hass) if not customer_id or c.api.customer_id == customer_id]
        if targets:
            await asyncio.gather(*(c.async_request_refresh() for c in targets))

    async def async_reload_service(call: ServiceCall) -> None:
        customer_id = call.data.get(CONF_CUSTOMER_ID)
        targets = [
            entry for entry in hass.config_entries.async_entries(DOMAIN)
            if not customer_id or entry.data[CONF_CUSTOMER_ID] == customer_id
        ]
        if targets:
            await asyncio.gather(*(hass.config_entries.async_reload(e.entry_id) for e in targets))

    schema = vol.Schema({vol.Optional(CONF_CUSTOMER_ID): cv.string})
    hass.services.async_register(DOMAIN, "refresh", async_refresh_service, schema=schema)
    hass.services.async_register(DOMAIN, "reload", async_reload_service, schema=schema)

    async def async_archive_service(call: ServiceCall) -> None:
        """Queue on-demand downloads; never delay Home Assistant or service return."""
        customer_id = call.data.get(CONF_CUSTOMER_ID)
        for entry in hass.config_entries.async_entries(DOMAIN):
            if customer_id and entry.data[CONF_CUSTOMER_ID] != customer_id:
                continue
            co = getattr(entry, "runtime_data", None)
            if not isinstance(co, ViwacoCoordinator) or co.data is None:
                _LOGGER.warning("VIWACO archive: customer %s has no loaded invoice history",
                                entry.data[CONF_CUSTOMER_ID])
                continue
            if co.archive.status.get("running"):
                _LOGGER.info("VIWACO archive: customer=%s sync already in progress", co.customer_id)
                continue
            entry.async_create_background_task(
                hass,
                co.archive.async_sync(
                    co.data.invoices,
                    year=call.data.get("year", 0),
                    mode=call.data.get("mode", "both"),
                    max_invoices=call.data.get("max_invoices", 0),
                    overwrite=call.data.get("overwrite", False),
                ),
                f"VIWACO archive {entry.entry_id}",
            )

    archive_schema = vol.Schema({
        vol.Optional(CONF_CUSTOMER_ID): cv.string,
        vol.Optional("year", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=2100)),
        vol.Optional("mode", default="both"): vol.In(("details", "pdf", "png", "both")),
        vol.Optional("overwrite", default=False): cv.boolean,
        vol.Optional("max_invoices", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=200)),
    })
    hass.services.async_register(DOMAIN, "archive_invoices", async_archive_service, schema=archive_schema)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Create entities immediately; fetch in a background task (never block boot)."""
    coordinator = ViwacoCoordinator(hass, entry)
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Cache hydration + network I/O happen AFTER returning from entry setup.
    entry.async_create_background_task(
        hass, coordinator.async_restore_and_refresh(), f"VIWACO startup restore {entry.entry_id}",
    )
    if entry.options.get(CONF_KEEPALIVE_ENABLED, DEFAULT_KEEPALIVE_ENABLED):
        minutes = max(5, min(60, int(entry.options.get(CONF_KEEPALIVE_MINUTES, DEFAULT_KEEPALIVE_MINUTES))))

        @callback
        def keepalive_tick(_now) -> None:
            # Timer callbacks never wait for network I/O.
            if coordinator._keepalive_running:
                return
            entry.async_create_background_task(
                hass, coordinator.async_keepalive(),
                f"VIWACO keepalive {entry.entry_id}",
            )

        entry.async_on_unload(async_track_time_interval(hass, keepalive_tick, timedelta(minutes=minutes)))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload only this customer, cancelling its background tasks."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        if isinstance(getattr(entry, "runtime_data", None), ViwacoCoordinator):
            entry.runtime_data.clear_alert()
        entry.runtime_data = None
    return unloaded
