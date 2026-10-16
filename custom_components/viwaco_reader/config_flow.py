"""UI add, configure, reconfigure and reauthenticate independent customer meters."""
from __future__ import annotations

from typing import Any
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    TextSelector, TextSelectorConfig, TextSelectorType,
    NumberSelector, NumberSelectorConfig, NumberSelectorMode,
)

from .api import ViwacoApi, ViwacoAuthError, ViwacoConnectionError
from .history import available_month_span
from .const import (
    CONF_COOKIE, CONF_CUSTOMER_ID, CONF_METER_NAME, CONF_UPDATE_HOURS,
    DEFAULT_UPDATE_INTERVAL_HOURS, DOMAIN, MIN_UPDATE_HOURS, MAX_UPDATE_HOURS,
    CONF_HISTORY_MONTHS, DEFAULT_HISTORY_MONTHS, MIN_HISTORY_MONTHS,
    CONF_KEEPALIVE_ENABLED, CONF_KEEPALIVE_MINUTES,
    DEFAULT_KEEPALIVE_ENABLED, DEFAULT_KEEPALIVE_MINUTES,
    CONF_AUTO_ARCHIVE_ENABLED, CONF_AUTO_ARCHIVE_MODE,
    DEFAULT_AUTO_ARCHIVE_ENABLED, DEFAULT_AUTO_ARCHIVE_MODE,
)

COOKIE_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


class ViwacoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """One customer code = one independent config entry/device."""
    VERSION = 1

    async def _validate(self, customer: str, cookie: str) -> str | None:
        try:
            await ViwacoApi(self.hass, customer, cookie).async_fetch_data()
        except ViwacoAuthError as exc:
            return exc.reason
        except ViwacoConnectionError:
            return "cannot_connect"
        return None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ViwacoOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors = {}
        if user_input:
            customer = str(user_input[CONF_CUSTOMER_ID]).strip()
            cookie = str(user_input[CONF_COOKIE]).strip()
            if not customer.isascii() or not customer.isdecimal():
                errors[CONF_CUSTOMER_ID] = "invalid_customer_id"
            else:
                await self.async_set_unique_id(customer)
                self._abort_if_unique_id_configured()
                error = await self._validate(customer, cookie)
                if error:
                    errors["base"] = error
                else:
                    return self.async_create_entry(
                        title=f"VIWACO {customer}",
                        data={CONF_CUSTOMER_ID: customer, CONF_COOKIE: cookie},
                        options={CONF_METER_NAME: str(user_input.get(CONF_METER_NAME, "")).strip() or f"VIWACO {customer}",
                                 CONF_UPDATE_HOURS: DEFAULT_UPDATE_INTERVAL_HOURS,
                                 CONF_HISTORY_MONTHS: DEFAULT_HISTORY_MONTHS,
                                 CONF_KEEPALIVE_ENABLED: DEFAULT_KEEPALIVE_ENABLED,
                                 CONF_KEEPALIVE_MINUTES: DEFAULT_KEEPALIVE_MINUTES,
                                 CONF_AUTO_ARCHIVE_ENABLED: DEFAULT_AUTO_ARCHIVE_ENABLED,
                                 CONF_AUTO_ARCHIVE_MODE: DEFAULT_AUTO_ARCHIVE_MODE},
                    )
        return self.async_show_form(step_id="user", errors=errors, data_schema=vol.Schema({
            vol.Required(CONF_CUSTOMER_ID): str,
            vol.Required(CONF_COOKIE): COOKIE_SELECTOR,
            vol.Optional(CONF_METER_NAME): str,
        }))

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        """Edit Cookie for an existing meter without deleting its entities."""
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input:
            cookie = str(user_input[CONF_COOKIE]).strip()
            error = await self._validate(entry.data[CONF_CUSTOMER_ID], cookie)
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(entry.data[CONF_CUSTOMER_ID])
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_COOKIE: cookie},
                )
        return self.async_show_form(step_id="reconfigure", errors=errors, data_schema=vol.Schema({
            vol.Required(CONF_COOKIE): COOKIE_SELECTOR,
        }))

    async def async_step_reauth(self, entry_data: dict[str, Any]):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        entry = self._get_reauth_entry()
        errors = {}
        if user_input:
            cookie = str(user_input[CONF_COOKIE]).strip()
            error = await self._validate(entry.data[CONF_CUSTOMER_ID], cookie)
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(entry.data[CONF_CUSTOMER_ID])
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_COOKIE: cookie},
                )
        return self.async_show_form(step_id="reauth_confirm", errors=errors, data_schema=vol.Schema({
            vol.Required(CONF_COOKIE): COOKIE_SELECTOR,
        }))


class ViwacoOptionsFlow(config_entries.OptionsFlowWithReload):
    """Change settings independently, with a real HA slider for history length.

    Slider maximum represents ALL available months, not a hardcoded cap.
    If source data is currently unavailable a fallback span is used; the
    maximum still means ALL. No network I/O occurs while opening settings.
    """

    def _slider_max(self) -> int:
        runtime = getattr(self.config_entry, "runtime_data", None)
        available = int(getattr(runtime, "available_history_months", 0) or 0)
        # Keep the UI usable offline, without introducing network calls in options.
        saved = int(self.config_entry.options.get(CONF_HISTORY_MONTHS, 0))
        return max(MIN_HISTORY_MONTHS + 1, available or 120, saved)

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        slider_max = self._slider_max()
        if user_input is not None:
            requested = int(user_input[CONF_HISTORY_MONTHS])
            if not MIN_HISTORY_MONTHS <= requested <= slider_max:
                return self.async_show_form(step_id="init", errors={CONF_HISTORY_MONTHS: "invalid_history_months"},
                                            data_schema=self._schema(slider_max))
            # The far-right position is a persistent ALL sentinel: new VIWACO
            # months are automatically included without reconfiguring.
            configured_months = DEFAULT_HISTORY_MONTHS if requested >= slider_max else requested
            options = {
                **self.config_entry.options,
                CONF_METER_NAME: str(user_input[CONF_METER_NAME]).strip(),
                CONF_UPDATE_HOURS: int(user_input[CONF_UPDATE_HOURS]),
                CONF_HISTORY_MONTHS: configured_months,
                CONF_KEEPALIVE_ENABLED: bool(user_input[CONF_KEEPALIVE_ENABLED]),
                CONF_KEEPALIVE_MINUTES: int(user_input[CONF_KEEPALIVE_MINUTES]),
                CONF_AUTO_ARCHIVE_ENABLED: bool(user_input[CONF_AUTO_ARCHIVE_ENABLED]),
                CONF_AUTO_ARCHIVE_MODE: str(user_input[CONF_AUTO_ARCHIVE_MODE]),
            }
            return self.async_create_entry(data=options)
        return self.async_show_form(
            step_id="init", data_schema=self._schema(slider_max),
            description_placeholders={"max_months": str(slider_max)},
        )

    def _schema(self, slider_max: int):
        current = self.config_entry.options
        current_months = int(current.get(CONF_HISTORY_MONTHS, DEFAULT_HISTORY_MONTHS))
        value = slider_max if current_months == DEFAULT_HISTORY_MONTHS else min(max(MIN_HISTORY_MONTHS, current_months), slider_max)
        return vol.Schema({
            vol.Required(CONF_METER_NAME, default=current.get(CONF_METER_NAME, self.config_entry.title)): str,
            vol.Required(CONF_UPDATE_HOURS, default=current.get(CONF_UPDATE_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS)): vol.All(
                vol.Coerce(int), vol.Range(min=MIN_UPDATE_HOURS, max=MAX_UPDATE_HOURS)
            ),
            vol.Required(CONF_KEEPALIVE_ENABLED, default=current.get(CONF_KEEPALIVE_ENABLED, DEFAULT_KEEPALIVE_ENABLED)): bool,
            vol.Required(CONF_KEEPALIVE_MINUTES, default=current.get(CONF_KEEPALIVE_MINUTES, DEFAULT_KEEPALIVE_MINUTES)): NumberSelector(NumberSelectorConfig(
                min=5, max=60, step=5, mode=NumberSelectorMode.SLIDER, unit_of_measurement="phút",
            )),
            vol.Required(CONF_AUTO_ARCHIVE_ENABLED, default=current.get(CONF_AUTO_ARCHIVE_ENABLED, DEFAULT_AUTO_ARCHIVE_ENABLED)): bool,
            vol.Required(CONF_AUTO_ARCHIVE_MODE, default=current.get(CONF_AUTO_ARCHIVE_MODE, DEFAULT_AUTO_ARCHIVE_MODE)): vol.In(("pdf", "png", "both")),
            vol.Required(CONF_HISTORY_MONTHS, default=value): NumberSelector(NumberSelectorConfig(
                min=MIN_HISTORY_MONTHS, max=slider_max, step=1,
                mode=NumberSelectorMode.SLIDER, unit_of_measurement="tháng",
            )),
        })
