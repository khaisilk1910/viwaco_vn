"""Fetch VIWACO HTML using a manually authenticated browser session Cookie."""

import asyncio

from aiohttp import ClientError, ClientTimeout
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import INVOICE_URL, READING_URL
from .cookie import normalize_cookie, CookieFormatError
from .session import merge_response_cookies
from .parser import _ViwacoTableParser
from .parser import (
    ViwacoData,
    ViwacoParseError,
    ViwacoWrongAccountError,
    parse_invoice_html,
    parse_reading_html,
    parse_customer_html,
)


class ViwacoAuthError(Exception):
    """Authentication error with a public, non-secret UI reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ViwacoConnectionError(Exception):
    """Site request or response format error."""


class ViwacoApi:
    """Read VIWACO data without solving or bypassing CAPTCHA."""

    def __init__(self, hass, customer_id: str, cookie: str, on_cookie_change=None) -> None:
        self.hass = hass
        self.customer_id = customer_id
        self.cookie = cookie.strip()
        self._on_cookie_change = on_cookie_change
        self._request_lock = asyncio.Lock()
        self._operation_lock = asyncio.Lock()

    def _accept_response_cookies(self, response_cookies) -> None:
        """Commit rotation only after authenticated page identity was verified."""
        updated = merge_response_cookies(self.cookie, response_cookies)
        if updated != normalize_cookie(self.cookie):
            self.cookie = updated
            if self._on_cookie_change is not None:
                self._on_cookie_change(updated)

    async def _async_fetch_html(self, url: str) -> tuple[str, dict]:
        session = async_get_clientsession(self.hass)
        page = url.rsplit("/", 1)[-1]
        try:
            async with self._request_lock:
                try:
                    cookie = normalize_cookie(self.cookie)
                except CookieFormatError as exc:
                    raise ViwacoAuthError("invalid_cookie_format") from exc
                async with session.get(
                    url,
                    headers={
                        "Cookie": cookie,
                        "Accept": "text/html",
                        "User-Agent": "Mozilla/5.0 (compatible; HomeAssistant-VIWACO/1.5)",
                    },
                    timeout=ClientTimeout(total=25), allow_redirects=False,
                ) as response:
                    if response.status in (301, 302, 303, 307, 308, 401, 403):
                        raise ViwacoAuthError("session_expired")
                    if response.status != 200:
                        raise ViwacoConnectionError(f"VIWACO HTTP status {response.status} on {page}")
                    # Only the two fixed first-party HTTPS pages are requested.
                    if len(response.cookies) > 20:
                        raise ViwacoConnectionError("Too many Set-Cookie values")
                    html = (await response.content.read(2 * 1024 * 1024 + 1))
                    if len(html) > 2 * 1024 * 1024:
                        raise ViwacoConnectionError(f"VIWACO {page}: HTML exceeds 2 MiB")
                    return html.decode("utf-8", errors="replace"), dict(response.cookies)
        except asyncio.TimeoutError as exc:
            raise ViwacoConnectionError(f"Timeout 25s when fetching {page}") from exc
        except ClientError as exc:
            raise ViwacoConnectionError(
                f"Network error {type(exc).__name__} when fetching {page}"
            ) from exc

    async def async_keepalive(self) -> None:
        """Validate one HTML page every 15 minutes without overlapping a refresh."""
        async with self._operation_lock:
            await self._async_keepalive_locked()

    async def _async_keepalive_locked(self) -> None:
        """Validate only one page; no bulk history parsing or archive download."""
        try:
            html, new_cookies = await self._async_fetch_html(INVOICE_URL)
            parser = _ViwacoTableParser()
            parser.feed(html)
            if parser.customer_id is None:
                raise ViwacoAuthError("session_expired")
            if parser.customer_id != self.customer_id:
                raise ViwacoAuthError("wrong_customer")
            if not parser.found_table:
                raise ViwacoConnectionError("Invoice.aspx: missing authenticated invoice table")
            self._accept_response_cookies(new_cookies)
        except ViwacoWrongAccountError as exc:
            raise ViwacoAuthError(exc.reason) from exc

    async def async_fetch_data(self) -> ViwacoData:
        """Fetch one customer snapshot without overlapping keep-alive."""
        async with self._operation_lock:
            return await self._async_fetch_data_locked()

    async def _async_fetch_data_locked(self) -> ViwacoData:
        """Return validated invoices + meter readings, or fail as a unit."""
        try:
            invoice_html, invoice_cookies = await self._async_fetch_html(INVOICE_URL)
            try:
                invoices = parse_invoice_html(invoice_html, self.customer_id)
                customer = parse_customer_html(invoice_html, self.customer_id)
            except ViwacoWrongAccountError:
                raise
            except ViwacoParseError as exc:
                raise ViwacoConnectionError(f"Invoice.aspx: {exc}") from exc
            self._accept_response_cookies(invoice_cookies)
            reading_html, reading_cookies = await self._async_fetch_html(READING_URL)
            try:
                readings = parse_reading_html(reading_html, self.customer_id)
                reading_customer = parse_customer_html(reading_html, self.customer_id)
            except ViwacoWrongAccountError:
                raise
            except ViwacoParseError as exc:
                raise ViwacoConnectionError(f"Reading.aspx: {exc}") from exc
            # Never combine data from distinct customer profiles. Missing fields
            # on either page are allowed (VIWACO may alter its page layout).
            for field in ("name", "address", "phone"):
                first, second = getattr(customer, field), getattr(reading_customer, field)
                if first and second and first != second:
                    raise ViwacoConnectionError("Customer details disagree between VIWACO pages")
            customer = type(customer)(
                customer_id=self.customer_id,
                name=customer.name or reading_customer.name,
                address=customer.address or reading_customer.address,
                phone=customer.phone or reading_customer.phone,
            )
            self._accept_response_cookies(reading_cookies)
            return ViwacoData(invoices=invoices, readings=readings, customer=customer)
        except ViwacoWrongAccountError as exc:
            raise ViwacoAuthError(exc.reason) from exc
        except ViwacoParseError as exc:
            raise ViwacoConnectionError(str(exc)) from exc
