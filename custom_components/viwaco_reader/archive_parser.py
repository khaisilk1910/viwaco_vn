"""Pure HTML/PDF-archive helpers. No auth tokens, sessions or HA dependencies."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit, urljoin, urlunsplit

from bs4 import BeautifulSoup

HOST = "hoadon.viwaco.vn"
BASE = "https://hoadon.viwaco.vn"
CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 /_.-]{0,79}$")


class ArchiveParseError(ValueError):
    """Unexpected invoice structure, code, or customer identity."""


def invoice_code(invoice_url: str | None) -> str | None:
    """Accept only official VIWACO lookup links; never fetch arbitrary URLs."""
    if not invoice_url:
        return None
    parsed = urlsplit(invoice_url)
    if parsed.scheme != "https" or parsed.hostname != HOST or parsed.port is not None:
        return None
    if parsed.path.rstrip("/").lower() != "/tra-cuu":
        return None
    values = parse_qs(parsed.query, keep_blank_values=False)
    matches = [v for k, vs in values.items() if k.lower() == "code" for v in vs]
    if len(matches) != 1 or not CODE_PATTERN.fullmatch(matches[0]):
        return None
    return matches[0]


def invoice_number_digits(number: str | None) -> str | None:
    """Extract the printed serial number, preserving its leading zeros.

    The billing portal may label it ``K26TYY 01634639`` while the issuer
    HTML uses ``1K26TYY`` as its symbol plus ``01634639`` as its number.
    Do not silently guess a serial from a short or absent value.
    """
    if not number:
        return None
    match = re.search(r"(\d{4,12})\s*$", number.strip())
    return match.group(1) if match else None


def verify_invoice_number(billing_number: str | None, portal_number: str | None) -> None:
    """Reject a different printed invoice number before fetching a view."""
    expected = invoice_number_digits(billing_number)
    if not expected:
        # Manual archive of legacy rows without a parseable printed number
        # still verifies customer, lookup code, period and total.
        return
    actual = invoice_number_digits(portal_number)
    if actual != expected:
        raise ArchiveParseError("Số hóa đơn tại cổng hóa đơn không khớp bảng thanh toán")


def _simple_text(element) -> str:
    return " ".join(element.get_text(" ", strip=True).split()) if element else ""


def _money(text: str) -> int | None:
    stripped = text.strip().replace("\xa0", "").replace(" ", "")
    if not stripped:
        return None
    digits = stripped.replace(".", "").replace(",", "")
    if not digits.isdecimal():
        return None
    return int(digits)


def _get_labels(table) -> dict[str, str]:
    result: dict[str, str] = {}
    if table:
        for tr in table.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) >= 2:
                label = _simple_text(tds[0]).rstrip(":").casefold()
                if label:
                    result[label] = _simple_text(tds[-1])
    return result


def parse_lookup(html: str, expected_customer_id: str, expected_code: str | None = None) -> dict:
    """Parse the official lookup screen and verify the customer before downloading."""
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one("#divInfo") is None:
        raise ArchiveParseError("Trang tra cứu không có #divInfo")
    # Verify the code shown by the real lookup form / ShowInvoice script, if
    # present. Synthetic legacy pages may not carry those controls.
    if expected_code is not None:
        shown = soup.select_one("#txtInvoice_Lookup")
        if shown is not None and shown.get("value") != expected_code:
            raise ArchiveParseError("Mã tra cứu trên trang hóa đơn không khớp URL")
        matches = re.findall(r"ShowInvoice\(\s*['\"]([A-Za-z0-9]+)['\"]", html)
        if matches and (len(set(matches)) != 1 or matches[0] != expected_code):
            raise ArchiveParseError("Trang tra cứu trả về mã hóa đơn khác URL")
    values: dict[str, str] = {}
    for tr in soup.select("#divInfo .tableInfo tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) >= 2 and "label" in (tds[0].get("class") or []):
            values[_simple_text(tds[0]).casefold()] = _simple_text(tds[1])
    if values.get("mã số khách hàng") != expected_customer_id:
        raise ArchiveParseError("Mã khách hàng trang hóa đơn điện tử không khớp")
    return {
        "invoice_number": values.get("số/ký hiệu hóa đơn"),
        "invoice_date": values.get("ngày xuất hóa đơn"),
        "households": _money(values.get("số hộ sử dụng", "")),
        "service_dates": values.get("thời gian sử dụng"),
        "reading_date_book": values.get("ngày ghi - sổ đọc"),
        "usage_m3": _money(values.get("sản lượng", "")),
        "water_charge_vnd": _money(values.get("tiền nước", "")),
        "meter_charge_vnd": _money(values.get("tiền đồng hồ", "")),
        "discount_vnd": _money(values.get("các khoản giảm trừ", "")),
        "total_vnd": _money(values.get("tổng tiền hóa đơn", "")),
        "invoice_status": values.get("tình trạng hóa đơn"),
        "customer_name": values.get("tên khách hàng"),
        "customer_address": values.get("địa chỉ khách hàng"),
    }


def parse_invoice_view(html: str, expected_customer_id: str) -> dict:
    """Parse the tier prices and actual fees in official Mode=HTML invoice."""
    soup = BeautifulSoup(html, "html.parser")
    text = _simple_text(soup)
    if not re.search(r"Mã khách hàng\s*:\s*" + re.escape(expected_customer_id) + r"\b", text):
        raise ArchiveParseError("Không xác nhận được mã khách hàng trong bản thể hiện HTML")
    table = soup.select_one("#tableItems")
    if table is None:
        raise ArchiveParseError("Bản thể hiện HTML thiếu #tableItems")
    tiers = []
    summary = {}
    seller_tax = re.search(r"Mã số thuế\s*:\s*(\d{8,14})", text)
    if seller_tax:
        summary["seller_tax_id"] = seller_tax.group(1)
    money_words = re.search(r"Số tiền bằng chữ\s*:\s*(.*?)\s*Hóa đơn điện tử tra cứu", text)
    if money_words:
        summary["total_in_words"] = money_words.group(1).strip()
    first_reading = True
    for tr in table.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if not tds:
            continue
        # The tier rows contain the nested table SH1, SH2 etc.
        if len(tds) >= 6:
            nested = tds[3].find("table")
            if first_reading and _money(_simple_text(tds[0])) is not None:
                summary["current_meter_m3"] = _money(_simple_text(tds[0]))
                summary["previous_meter_m3"] = _money(_simple_text(tds[1]))
                summary["usage_m3"] = _money(_simple_text(tds[2]))
                first_reading = False
            label = ""
            quantity = None
            if nested:
                nested_tds = nested.find_all("td")
                if len(nested_tds) >= 2:
                    label = _simple_text(nested_tds[0])
                    quantity = _money(_simple_text(nested_tds[1]))
            if label and quantity is not None:
                tiers.append({
                    "tariff": label,
                    "quantity_m3": quantity,
                    "unit_price_vnd": _money(_simple_text(tds[4])),
                    "amount_vnd": _money(_simple_text(tds[5])),
                })
        # Exact per-invoice line items, not a synthetic tariff calculation.
        if len(tds) >= 2:
            label = _simple_text(tds[0]).casefold()
            if label.startswith("- tiền nước"):
                summary["water_charge_vnd"] = _money(_simple_text(tds[-1]))
            elif "phí bảo vệ môi trường" in label:
                summary["environment_fee_vnd"] = _money(_simple_text(tds[-1]))
                rate = re.search(r"(\d+(?:[.,]\d+)?)\s*%", label)
                summary["environment_fee_rate_percent"] = rate.group(1) if rate else None
            elif "thuế vat" in label:
                summary["vat_vnd"] = _money(_simple_text(tds[-1]))
                rate = re.search(r"(\d+(?:[.,]\d+)?)\s*%", label)
                summary["vat_rate_percent"] = rate.group(1) if rate else None
            elif "tiền đồng hồ" in label:
                summary["meter_charge_vnd"] = _money(_simple_text(tds[-1]))
            elif "giảm trừ" in label:
                summary["discount_vnd"] = _money(_simple_text(tds[-1]))
            elif "tổng cộng" in label:
                summary["total_vnd"] = _money(_simple_text(tds[-1]))
    return {**summary, "tariffs": tiers}


def download_candidates(lookup_html: str, view_html: str = "") -> list[str]:
    """Look for *actual* PDF download URLs advertised by the official pages.

    No guesswork about server APIs, no off-host or javascript URLs, and no
    forwarding of the tracing-portal login Cookie. Returns absolute HTTPS URLs.
    """
    candidates: list[str] = []
    for html in (lookup_html, view_html):
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(["a", "button", "iframe", "embed", "object"]):
            label = " ".join((" ".join([
                tag.get_text(" ", strip=True),
                str(tag.get("title", "")), str(tag.get("id", "")),
                " ".join(tag.get("class") or []),
                str(tag.get("download", "")), str(tag.get("aria-label", "")),
            ])).casefold().split())
            # Some web portals supply a PDF iframe only after clicking preview.
            embedded = tag.name in ("iframe", "embed", "object") and (
                "pdf" in label or "invoice" in label or "hoadon" in label
            )
            relevant = embedded or any(t in label for t in (
                "tải bản thể hiện", "tai ban the hien", "download pdf",
                "tải pdf", "tai pdf", "download-pdf", "downloadpdf",
                "invoice-download", "download-invoice",
            ))
            if not relevant:
                continue
            values = [tag.get(k) for k in ("href", "data-url", "data-href", "data-pdf", "src", "data")]
            # Select a URL literal only; do NOT evaluate javascript handlers.
            handler = tag.get("onclick") or ""
            values.extend(re.findall(r"['\"](https?://[^'\"]+|/[^'\"]+)['\"]", handler, re.I))
            for value in values:
                if not isinstance(value, str) or not value.strip():
                    continue
                value = value.strip()
                if value.startswith(("#", "javascript:", "data:", "//")):
                    continue
                url = urlsplit(urljoin(BASE + "/tra-cuu/", value))
                try:
                    permitted = (url.scheme == "https" and url.hostname == HOST
                                 and url.port is None and not url.username
                                 and not url.password)
                except ValueError:
                    continue
                if not permitted:
                    continue
                if url.username or url.password or len(value) > 1000:
                    continue
                if url.path.rstrip("/").lower() in ("/tra-cuu", "/"):
                    continue
                absolute = urlunsplit((url.scheme, url.netloc, url.path, url.query, ""))
                if absolute not in candidates:
                    candidates.append(absolute)
                if len(candidates) == 8:
                    return candidates
    return candidates
