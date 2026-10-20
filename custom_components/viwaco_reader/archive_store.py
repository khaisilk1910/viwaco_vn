"""Private archive metadata + PDF/PNG file writes outside the event loop."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import secrets
import tempfile


MAX_FILE_SIZE = 25 * 1024 * 1024


def load_catalog(path: str, customer_id: str) -> dict:
    """Tolerate broken/no cache without destroying downloaded bills."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("customer_id") == customer_id and isinstance(data.get("records"), dict):
            if data.get("folder") and data["folder"].isalnum():
                return data
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return {"version": 1, "customer_id": customer_id, "folder": secrets.token_hex(10), "records": {}}


def write_bytes_atomic(path: str, payload: bytes) -> None:
    """Protect against partial downloads or out-of-disk responses."""
    if not payload or len(payload) > MAX_FILE_SIZE:
        raise ValueError("File rỗng hoặc vượt giới hạn 25 MB")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_path = tempfile.mkstemp(dir=target.parent, prefix=".download-")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def write_catalog_atomic(path: str, catalog: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(catalog, ensure_ascii=False, indent=2).encode("utf-8")
    write_bytes_atomic(str(target), payload)


def render_pdf_pngs(pdf: bytes) -> list[bytes]:
    """Render official PDF pages using pypdfium2. Called in HA executor only."""
    if not pdf.startswith(b"%PDF-"):
        raise ValueError("Nội dung không phải PDF hợp lệ")
    import pypdfium2 as pdfium

    result: list[bytes] = []
    doc = pdfium.PdfDocument(pdf)
    try:
        if len(doc) > 10:
            raise ValueError("Hóa đơn có hơn 10 trang")
        for i in range(len(doc)):
            page = doc[i]
            try:
                bitmap = page.render(scale=1.8)
                try:
                    image = bitmap.to_pil()
                    buffer = io.BytesIO()
                    image.save(buffer, format="PNG", optimize=True)
                    result.append(buffer.getvalue())
                finally:
                    bitmap.close()
            finally:
                page.close()
    finally:
        doc.close()
    if not result:
        raise ValueError("Không tạo được ảnh PNG từ PDF")
    return result


def make_archive_relative(folder: str, year: int, month: int, extension: str, page: int = 1, variant: str = "official") -> str:
    """No user-supplied paths. Random folder obscures listing, not access control."""
    if not (folder.isalnum() and 2010 <= year <= 2100 and 1 <= month <= 12):
        raise ValueError("Đường dẫn lưu trữ không hợp lệ")
    if extension not in ("pdf", "png") or not (1 <= page <= 10) or variant not in ("official", "reference", "html"):
        raise ValueError("Loại file không hợp lệ")
    suffix = ("_tham-khao" if variant == "reference" else "_html" if variant == "html" else "") + (f"_p{page:02d}" if page > 1 else "")
    return f"viwaco_reader/{folder}/{year}/{year}-{month:02d}{suffix}.{extension}"


def local_url(relative: str) -> str:
    return "/local/" + relative


def existing_pngs_are_valid(paths: list[str]) -> bool:
    """Verify all cataloged PNGs actually exist and can be decoded."""
    from PIL import Image
    if not paths or len(paths) > 10:
        return False
    for path in paths:
        try:
            with Image.open(path) as img:
                if img.format != "PNG" or img.width < 100 or img.height < 100:
                    return False
                img.verify()
        except (OSError, ValueError, SyntaxError):
            return False
    return True
