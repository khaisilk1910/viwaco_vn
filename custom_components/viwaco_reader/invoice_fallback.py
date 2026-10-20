"""Labeled, non-legal reference document if supplier's official PDF is unavailable.

All content comes from an identity-checked VIWACO lookup, never made-up tariff
amounts. A reference summary is NEVER described as an official tax invoice.
Called only from an executor; no browser, remote fonts, or external binaries.
"""
from __future__ import annotations

from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

_FONT_FILES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/local/share/fonts/DejaVuSans.ttf",
    "DejaVuSans.ttf",
)


def _font(size: int):
    for name in _FONT_FILES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _as_text(value) -> str:
    return " ".join(str(value if value is not None else "—").split())[:700]


def _amount(value, unit="") -> str:
    if isinstance(value, (int, float)):
        return f"{int(value):,}".replace(",", ".") + unit
    return _as_text(value)


def create_reference_pdf_and_png(lookup: dict, period: str, customer_id: str) -> tuple[bytes, bytes]:
    """Create explicitly labeled PNG + openable image-based PDF (not original).

    The first image is pixel-identical to the PDF and always visibly marked.
    """
    if not isinstance(lookup, dict) or not lookup.get("invoice_number"):
        # Identity alone isn't enough for an invoice-like document. Require
        # official invoice number and other amounts from the lookup screen.
        raise ValueError("Chưa có đủ dữ liệu hóa đơn VIWACO để tạo bản tóm tắt")
    if lookup.get("total_vnd") is None:
        raise ValueError("Thiếu số tiền tổng hóa đơn; không tạo bản tóm tắt")

    width, height = 1240, 3000
    image = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(image)
    main, bold, small = _font(34), _font(39), _font(27)
    x, right, y = 90, width - 90, 85
    draw.rectangle((0, 0, width, 18), fill="#b45309")
    draw.text((x, y), "BẢN TÓM TẮT THAM KHẢO", font=bold, fill="#92400e")
    y += 68
    draw.text((x, y), "KHÔNG PHẢI HÓA ĐƠN ĐIỆN TỬ / PDF GỐC", font=small, fill="#b91c1c")
    y += 70
    draw.line((x, y, right, y), fill="#d1d5db", width=3)
    y += 38

    def add(label, value, color="#172033"):
        nonlocal y
        draw.text((x, y), label, font=small, fill="#475569")
        y += 34
        # wrap based on measured glyph widths rather than raw character count
        tokens = _as_text(value).split()
        line = ""
        for word in tokens:
            proposed = (line + " " + word).strip()
            if line and draw.textbbox((0, 0), proposed, font=main)[2] > right-x:
                draw.text((x, y), line, font=main, fill=color)
                y += 42
                line = word
            else:
                line = proposed
        if line:
            draw.text((x, y), line, font=main, fill=color)
            y += 42
        y += 12

    add("Nguồn số liệu", "VIWACO - trang tra cứu hóa đơn")
    add("Kỳ hóa đơn", period)
    add("Mã khách hàng", customer_id)
    add("Số / ký hiệu", lookup.get("invoice_number"))
    add("Ngày xuất hóa đơn", lookup.get("invoice_date"))
    add("Khách hàng", lookup.get("customer_name"))
    add("Địa chỉ", lookup.get("customer_address"))
    add("Thời gian sử dụng", lookup.get("service_dates"))
    add("Sản lượng", _amount(lookup.get("usage_m3"), " m³"))
    add("Tiền nước", _amount(lookup.get("water_charge_vnd"), " VND"))
    add("Tổng hóa đơn", _amount(lookup.get("total_vnd"), " VND"), "#0f766e")
    add("Trạng thái", lookup.get("invoice_status"))
    y = max(y + 24, 1445)
    draw.line((x, y, right, y), fill="#d1d5db", width=3)
    y += 26
    for note in (
        "Đây là bản tổng hợp được tạo từ dữ liệu tra cứu công khai.",
        "Không có chữ ký số. Không dùng để kê khai hoặc xác minh thuế.",
        "Lấy XML/PDF có giá trị pháp lý trực tiếp tại hoadon.viwaco.vn.",
    ):
        draw.text((x, y), note, font=small, fill="#92400e")
        y += 39

    # Never clip the warning footer even for long Vietnamese addresses/names.
    image = image.crop((0, 0, width, max(1754, y + 105)))
    png_buffer, pdf_buffer = BytesIO(), BytesIO()
    image.save(png_buffer, format="PNG", optimize=True)
    image.save(pdf_buffer, format="PDF", resolution=150.0)
    return pdf_buffer.getvalue(), png_buffer.getvalue()
