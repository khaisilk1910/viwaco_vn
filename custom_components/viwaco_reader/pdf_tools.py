"""Validate VIWACO binary PDFs before publication; repair broken xrefs if possible.

This module never invents invoice information or substitutes an HTML printout
for an original invoice. A repaired PDF is explicitly marked as modified, since
rewriting a PDF can invalidate embedded electronic signatures.
"""
from __future__ import annotations

from io import BytesIO
from dataclasses import dataclass
import logging

_LOGGER = logging.getLogger(__name__)
MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_PAGES = 10


class InvoicePdfError(ValueError):
    """The supplier has not provided a usable PDF binary."""


@dataclass(frozen=True)
class CheckedPdf:
    content: bytes
    repaired: bool
    original_bytes: int
    pages: int


def _check_pdf_with_pdfium(data: bytes, *, preview: bool = True) -> int:
    """Require a structurally readable document and a renderable first page."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(data)
    try:
        count = len(doc)
        if not 1 <= count <= MAX_PAGES:
            raise InvoicePdfError(f"Số trang PDF không hợp lệ: {count}")
        for index in (range(count) if preview else range(1)):
            page = doc[index]
            try:
                if page.get_width() <= 0 or page.get_height() <= 0:
                    raise InvoicePdfError("PDF có kích thước trang không hợp lệ")
                if preview:
                    bitmap = page.render(scale=0.35)
                    bitmap.close()
            finally:
                page.close()
        return count
    finally:
        doc.close()


def _recover_pdf(data: bytes) -> bytes:
    """Best-effort xref/trailer repair with pypdf, never signing the result."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(BytesIO(data), strict=False)
    if reader.is_encrypted:
        raise InvoicePdfError("PDF được mã hóa; không thể tự phục hồi")
    count = len(reader.pages)
    if not 1 <= count <= MAX_PAGES:
        raise InvoicePdfError(f"PDF sau phục hồi có {count} trang, không hợp lệ")
    writer = PdfWriter()
    writer.append(reader)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def check_or_repair_pdf(payload: bytes) -> CheckedPdf:
    """Return only PDF that PDFium can actually open and render.

    Unmodified official bytes are always preferred. Rewriting with pypdf is a
    fallback for recoverable broken cross-reference tables only.
    """
    if not isinstance(payload, bytes) or len(payload) < 100:
        raise InvoicePdfError("Máy chủ trả PDF rỗng hoặc quá ngắn")
    if len(payload) > MAX_PDF_BYTES:
        raise InvoicePdfError("PDF vượt dung lượng cho phép 25 MB")
    if b"%PDF-" not in payload[:1024]:
        raise InvoicePdfError("Máy chủ không trả nội dung PDF (có thể là HTML báo lỗi)")

    try:
        pages = _check_pdf_with_pdfium(payload)
        return CheckedPdf(payload, False, len(payload), pages)
    except InvoicePdfError:
        # Policy violations such as too many pages must not be bypassed.
        raise
    except Exception as first_error:
        _LOGGER.debug("VIWACO original PDF failed PDFium validation: %s", type(first_error).__name__)

    try:
        recovered = _recover_pdf(payload)
        pages = _check_pdf_with_pdfium(recovered)
        return CheckedPdf(recovered, True, len(payload), pages)
    except Exception as exc:
        _LOGGER.debug("VIWACO attempted PDF recovery failed: %s", type(exc).__name__)
        raise InvoicePdfError(
            "PDF do VIWACO trả về bị hỏng, PDFium không đọc được và pypdf "
            "không thể phục hồi. Không lưu PDF lỗi; thử lại sau hoặc gửi mẫu "
            "PDF hỏng để kiểm tra."
        ) from exc


def existing_pdf_is_valid(path: str) -> bool:
    """Verify old v1.6.0 files; an invalid old PDF must be fetched anew."""
    from pathlib import Path
    try:
        data = Path(path).read_bytes()
        if len(data) < 100 or len(data) > MAX_PDF_BYTES:
            return False
        _check_pdf_with_pdfium(data, preview=False)
        return True
    except Exception:  # a broken PDF must not stop a new archive run
        return False
