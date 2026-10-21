"""Verify issuer-provided VIWACO PDF without rewriting the original bytes.

The PDF's visible invoice fields are checked against independent lookup data.
Do not infer a cryptographic signature from the printed 'Signature Valid' label.
"""
from __future__ import annotations

import re
import unicodedata
from .archive_parser import ArchiveParseError, invoice_number_digits
from .pdf_tools import InvoicePdfError, check_or_repair_pdf


def _compact(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def filename_invoice_number(disposition: str) -> str | None:
    """Only inspect supplier file name, never use it as a filesystem path."""
    if not disposition:
        return None
    match = re.search(r"filename\s*=\s*(?:\"([^\"]+)\"|([^;\s]+))", disposition, re.I)
    if not match:
        return None
    name = match.group(1) or match.group(2)
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.[0-9]{4,12}\.pdf", name, re.I):
        raise ArchiveParseError("Tên tệp PDF nhà cung cấp không đúng định dạng số hóa đơn")
    return invoice_number_digits(name[:-4])


def verify_supplier_pdf(payload: bytes, *, customer_id: str, code: str,
                        invoice_number: str | None, total_vnd: int | None,
                        year: int, month: int, content_disposition: str = "") -> tuple[bytes, int]:
    """Require authentic source bytes and matching bill identity/amount/period.

    The supplier PDF must be readable unchanged. If its text is not searchable,
    require an exact Content-Disposition serial from the trusted PDF response.
    """
    checked = check_or_repair_pdf(payload)
    if checked.repaired:
        raise InvoicePdfError("PDF gốc cần sửa cấu trúc; từ chối chỉnh sửa tệp do VIWACO cấp")

    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(payload)
    try:
        chunks = []
        for index in range(len(doc)):
            page = doc[index]
            try:
                textpage = page.get_textpage()
                try:
                    chunks.append(textpage.get_text_range())
                finally:
                    textpage.close()
            finally:
                page.close()
    finally:
        doc.close()
    text = _compact(" ".join(chunks))
    expected_number = invoice_number_digits(invoice_number)
    header_number = filename_invoice_number(content_disposition)
    if expected_number and header_number and header_number != expected_number:
        raise ArchiveParseError("Số hóa đơn trong filename PDF không khớp kỳ thanh toán")

    # Explicit printed fields are stronger evidence than filenames. Reject any
    # *present but conflicting* identity even if other metadata looks right.
    printed_customer = re.search(r"Mã khách hàng\s*:\s*(\d{6,15})", text, re.I)
    if printed_customer and printed_customer.group(1) != customer_id:
        raise ArchiveParseError("Mã khách hàng trong PDF chính thức không khớp")
    printed_number = re.search(r"\bSố\s*:\s*(\d{4,12})\b", text, re.I)
    if printed_number and expected_number and printed_number.group(1) != expected_number:
        raise ArchiveParseError("Số hóa đơn trong PDF chính thức không khớp")
    printed_code = re.search(r"Mã tra cứu hóa đơn\s*:\s*([A-Za-z0-9]+)", text, re.I)
    if printed_code and printed_code.group(1).upper() != code.upper():
        raise ArchiveParseError("Mã tra cứu trong PDF chính thức không khớp")
    printed_period = re.search(r"Tháng\s*(\d{1,2})\s*năm\s*(\d{4})", text, re.I)
    if printed_period and (int(printed_period.group(1)), int(printed_period.group(2))) != (month, year):
        raise ArchiveParseError("Kỳ hóa đơn trong PDF chính thức không khớp")
    amount = re.search(r"TỔNG CỘNG\s*([\d.,]+)", text, re.I)
    if amount and total_vnd is not None:
        digits = amount.group(1).replace(".", "").replace(",", "")
        if digits.isdecimal() and int(digits) != total_vnd:
            raise ArchiveParseError("Tổng tiền trong PDF chính thức không khớp")

    # A searchable PDF should expose the identity in its content. For a
    # non-searchable/scanned PDF, the issuer-supplied filename may validate the
    # number only if the independent /tra-cuu/ lookup was already checked.
    if len(text) >= 120:
        if not printed_customer or not printed_number or not printed_code or not printed_period or not amount:
            raise ArchiveParseError("Không đọc được đủ trường nhận dạng trong PDF VIWACO")
    elif not expected_number or header_number != expected_number:
        raise ArchiveParseError("PDF dạng ảnh thiếu tên file để xác minh số hóa đơn")
    return payload, checked.pages
