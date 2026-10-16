"""Pure HTML/PDF-archive helpers. No auth tokens, sessions or HA dependencies."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

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


def parse_lookup(html: str, expected_customer_id: str) -> dict:
    """Parse the official lookup screen and verify the customer before downloading."""
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one("#divInfo") is None:
        raise ArchiveParseError("Trang tra cứu không có #divInfo")
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
