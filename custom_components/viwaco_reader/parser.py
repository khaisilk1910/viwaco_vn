"""Parse VIWACO monthly invoices and water meter readings from HTML.

Customer identity fields (name, address, phone) are also extracted from the
specific visible input elements. Sensitive VIEWSTATE and authentication tokens
are never stored in the coordinator snapshot.
"""

from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.parse import urlparse


class ViwacoParseError(ValueError):
    """An authenticated page has an unexpected structure."""


class ViwacoWrongAccountError(ViwacoParseError):
    """The response does not contain the authenticated expected customer."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Invoice:
    """Monthly water invoice."""

    month: int
    year: int
    book: str
    start_date: date | None
    end_date: date | None
    usage_m3: int
    total_vnd: int
    paid_vnd: int
    payment_date: date | None
    advance_vnd: int
    invoice_number: str
    invoice_url: str | None

    @property
    def period(self) -> str:
        return f"{self.month:02d}/{self.year}"

    def history_item(self) -> dict:
        return {
            "period": self.period,
            "usage_m3": self.usage_m3,
            "total_vnd": self.total_vnd,
            "paid_vnd": self.paid_vnd,
            "payment_date": self.payment_date.isoformat() if self.payment_date else None,
        }


@dataclass(frozen=True)
class Reading:
    """One recorded meter reading, not a live meter value."""

    serial: str
    year: int
    month: int
    read_date: date
    reading_code: str
    previous_m3: int
    current_m3: int
    usage_m3: int
    reading_type: str

    @property
    def period(self) -> str:
        return f"{self.month:02d}/{self.year}"

    def history_item(self) -> dict:
        return {
            "period": self.period,
            "read_date": self.read_date.isoformat(),
            "previous_m3": self.previous_m3,
            "current_m3": self.current_m3,
            "usage_m3": self.usage_m3,
        }


@dataclass(frozen=True)
class CustomerInfo:
    """Customer details displayed by VIWACO on authenticated HTML pages."""

    customer_id: str
    name: str
    address: str
    phone: str

    def as_dict(self) -> dict[str, str]:
        return {
            "customer_id": self.customer_id,
            "name": self.name,
            "address": self.address,
            "phone": self.phone,
        }


@dataclass(frozen=True)
class ViwacoData:
    """Authenticated customer profile, invoices and water-meter readings."""

    invoices: tuple[Invoice, ...]
    readings: tuple[Reading, ...]
    customer: CustomerInfo


class _ViwacoTableParser(HTMLParser):
    """Collect customer ID and rows of the *specific* table called tableInvoice.

    VIWACO uses the same table ID in Invoice.aspx and Reading.aspx.
    """

    PROFILE_FIELDS = {
        "content_lblCustID": "customer_id",
        "content_lblCustName": "name",
        "content_lblCustAddr": "address",
        "content_lblCustTel": "phone",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.customer_id: str | None = None
        self.profile: dict[str, str] = {}
        self.found_table = False
        self._table_depth = 0
        self._row: list[dict] | None = None
        self._cell: dict | None = None
        self._cell_text: list[str] = []
        self.rows: list[list[dict]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "input" and (field := self.PROFILE_FIELDS.get(attrs_dict.get("id"))):
            value = " ".join((attrs_dict.get("value") or "").split())
            self.profile[field] = value
            if field == "customer_id":
                self.customer_id = value
        if tag == "table":
            if self._table_depth:
                self._table_depth += 1
            elif attrs_dict.get("id") == "tableInvoice":
                self.found_table = True
                self._table_depth = 1
            return
        if not self._table_depth:
            return
        if tag == "tr" and self._row is None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = {"href": None, "header": tag == "th"}
            self._cell_text = []
        elif tag == "a" and self._cell is not None:
            self._cell["href"] = attrs_dict.get("href")

    def handle_data(self, data: str) -> None:
        if self._table_depth and self._cell is not None:
            self._cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._table_depth:
            return
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._cell["text"] = " ".join("".join(self._cell_text).split())
            self._row.append(self._cell)
            self._cell = None
            self._cell_text = []
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
        elif tag == "table":
            self._table_depth -= 1


def _int_value(value: str) -> int:
    """VIWACO uses comma thousand separators: '1,394' = 1394."""
    cleaned = value.strip().replace(",", "").replace(".", "").replace(" ", "")
    if not cleaned:
        return 0
    if not cleaned.isdecimal():
        raise ViwacoParseError("Invalid numeric field in VIWACO table")
    return int(cleaned)


def _date_value(value: str) -> date | None:
    if not value.strip():
        return None
    try:
        return datetime.strptime(value.strip(), "%d/%m/%Y").date()
    except ValueError as exc:
        raise ViwacoParseError("Invalid date field in VIWACO table") from exc


def _validated_rows(html: str, expected_customer_id: str) -> list[list[dict]]:
    parser = _ViwacoTableParser()
    parser.feed(html)
    if parser.customer_id is None:
        # Missing expected markup alone does not prove an expired session.
        raise ViwacoParseError("Customer ID field missing from VIWACO HTML")
    if parser.customer_id != expected_customer_id:
        raise ViwacoWrongAccountError("wrong_customer")
    if not parser.found_table or not parser.rows:
        raise ViwacoParseError("Missing #tableInvoice in authenticated response")
    return parser.rows


def parse_customer_html(html: str, expected_customer_id: str) -> CustomerInfo:
    """Read only the 4 known customer HTML inputs; never capture VIEWSTATE.

    A missing name, address or phone is represented by an empty string; the
    customer ID itself is required and must match the configured account.
    """
    parser = _ViwacoTableParser()
    parser.feed(html)
    if parser.customer_id is None:
        # Missing expected markup alone does not prove an expired session.
        raise ViwacoParseError("Customer ID field missing from VIWACO HTML")
    if parser.customer_id != expected_customer_id:
        raise ViwacoWrongAccountError("wrong_customer")
    return CustomerInfo(
        customer_id=expected_customer_id,
        name=parser.profile.get("name", ""),
        address=parser.profile.get("address", ""),
        phone=parser.profile.get("phone", ""),
    )


def parse_invoice_html(html: str, expected_customer_id: str) -> tuple[Invoice, ...]:
    """Extract actual invoice table, validating the expected column headers."""
    rows = _validated_rows(html, expected_customer_id)
    header = [cell["text"].lower() for cell in rows[0]]
    if (
        len(header) < 13
        or "tháng" not in header[1]
        or "tiêu thụ" not in header[6]
        or "thanh toán" not in header[8]
    ):
        raise ViwacoParseError("Invoice table columns have changed")

    invoices: list[Invoice] = []
    for row in rows[1:]:
        if len(row) < 13:
            raise ViwacoParseError("Incomplete invoice row")
        c = [cell["text"] for cell in row]
        try:
            month, year = _int_value(c[1]), _int_value(c[2])
            if month not in range(1, 13) or not 2000 <= year <= 2100:
                raise ViwacoParseError("Unexpected billing period")
            href = row[12]["href"]
            if href:
                url = urlparse(href)
                if url.scheme != "https" or url.netloc != "hoadon.viwaco.vn":
                    href = None
            invoices.append(Invoice(
                month=month,
                year=year,
                book=c[3],
                start_date=_date_value(c[4]),
                end_date=_date_value(c[5]),
                usage_m3=_int_value(c[6]),
                total_vnd=_int_value(c[7]),
                paid_vnd=_int_value(c[8]),
                payment_date=_date_value(c[9]),
                advance_vnd=_int_value(c[10]),
                invoice_number=c[11],
                invoice_url=href,
            ))
        except (IndexError, TypeError, KeyError) as exc:
            raise ViwacoParseError("Unable to parse invoice row") from exc
    if not invoices:
        raise ViwacoParseError("No invoice records available")
    return tuple(sorted(invoices, key=lambda i: (i.year, i.month), reverse=True))


def parse_reading_html(html: str, expected_customer_id: str) -> tuple[Reading, ...]:
    """Extract the water-meter table from Reading.aspx."""
    rows = _validated_rows(html, expected_customer_id)
    header = [cell["text"].lower() for cell in rows[0]]
    if (
        len(header) < 10
        or "serial" not in header[1]
        or "năm" not in header[2]
        or "tháng" not in header[3]
        or "ngày đọc" not in header[4]
        or "chỉ số trước" not in header[6]
        or "chỉ số sau" not in header[7]
        or "tiêu thụ" not in header[8]
    ):
        raise ViwacoParseError("Reading table columns have changed")

    readings: list[Reading] = []
    for row in rows[1:]:
        if len(row) < 10:
            raise ViwacoParseError("Incomplete reading row")
        c = [cell["text"] for cell in row]
        year, month = _int_value(c[2]), _int_value(c[3])
        if not 2000 <= year <= 2100 or month not in range(1, 13):
            raise ViwacoParseError("Unexpected meter period")
        read_date = _date_value(c[4])
        if read_date is None:
            raise ViwacoParseError("Meter reading has no read date")
        readings.append(Reading(
            serial=c[1], year=year, month=month,
            read_date=read_date, reading_code=c[5],
            previous_m3=_int_value(c[6]),
            current_m3=_int_value(c[7]),
            usage_m3=_int_value(c[8]),
            reading_type=c[9],
        ))
    if not readings:
        raise ViwacoParseError("No meter readings available")
    # Sort by actual reading date, not billing period (two records can share a period).
    return tuple(sorted(readings, key=lambda r: r.read_date, reverse=True))
