"""Render VIWACO's real Mode=HTML invoice into an A4 PNG and PDF.

The HTML is parsed as data, NEVER executed. This renderer intentionally avoids
Chromium/system binaries so it works in Home Assistant containers. The result
is a printable visual reproduction, not a supplier-signed electronic invoice.
"""
from __future__ import annotations

from io import BytesIO
import re
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

BLUE = '#4169e1'
BLACK = '#172033'
MUTED = '#5b6475'
RED = '#b42318'
BORDER = '#9daedb'
A4_WIDTH, A4_HEIGHT, DPI = 1240, 1754, 150
_FONT_NAMES = (
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf',
    '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf',
    '/usr/share/fonts/TTF/DejaVuSans.ttf',
    'DejaVuSans.ttf',
)
_BOLD_NAMES = (
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf',
    '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf',
    '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf',
    'DejaVuSans-Bold.ttf',
)


def _font(size: int, bold: bool = False):
    for path in (_BOLD_NAMES if bold else _FONT_NAMES):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def _text(element) -> str:
    return ' '.join(element.get_text(' ', strip=True).split()) if element else ''


def _norm_amount(value: object) -> str:
    if value is None:
        return ''
    return f'{value:,}'.replace(',', '.') if isinstance(value, int) else str(value)


def _extract_render_data(html: str, expected_customer_id: str, code: str, period: str) -> dict:
    """Demand identity, actual item grid and matching invoice amounts."""
    from .archive_parser import parse_invoice_view, ArchiveParseError

    if not isinstance(html, str) or len(html) > 2_000_000:
        raise ValueError('HTML hóa đơn rỗng hoặc quá lớn')
    soup = BeautifulSoup(html, 'html.parser')
    root = soup.select_one('div.root')
    if root is None or root.select_one('#tableItems') is None:
        raise ArchiveParseError('HTML VIWACO thiếu bản thể hiện hóa đơn hoặc bảng chi tiết')
    details = parse_invoice_view(html, expected_customer_id)
    plain = _text(root)
    # Do not create a plausible looking printout from a mismatched month's data.
    month_match = re.search(r'Tháng\s+(\d{1,2})\s+năm\s+(\d{4})', plain, re.I)
    if month_match:
        expected_month, expected_year = (int(n) for n in period.split('/'))
        if (int(month_match.group(1)), int(month_match.group(2))) != (expected_month, expected_year):
            raise ArchiveParseError('Kỳ hóa đơn trên HTML không khớp kỳ đang lưu')
    displayed_code = re.search(r'Mã tra cứu hóa đơn\s*:\s*([A-Za-z0-9]+)', plain, re.I)
    if displayed_code and displayed_code.group(1) != code:
        raise ArchiveParseError('Mã tra cứu trong bản HTML không khớp')
    # Invoice code can also be embedded in QR query string.
    qr = root.select_one('img[src*="qrcode.ashx"]')
    if qr:
        found = parse_qs(urlsplit(qr.get('src', '')).query).get('code', [])
        if found and found[0] != code:
            raise ArchiveParseError('Mã QR hóa đơn không khớp mã đang lưu')

    def regex(pattern, default=''):
        m = re.search(pattern, plain, re.I)
        return m.group(1).strip() if m else default

    # The 2026 invoice layout exposes buyer fields in the table preceding #tableItems.
    buyer = {}
    for tr in root.select('table tr'):
        cells = tr.find_all('td', recursive=False)
        for pair in range(0, len(cells)-1, 2):
            key = _text(cells[pair]).rstrip(':').casefold()
            if key in ('tên khách hàng', 'địa chỉ khách hàng', 'thời gian sử dụng',
                       'ngày hóa đơn', 'ngày ghi - sổ đọc', 'số hộ sử dụng nước'):
                buyer[key] = _text(cells[pair + 1])
    return {
        'details': details,
        'seller_tax': details.get('seller_tax_id') or regex(r'Mã số thuế\s*:\s*(\d{8,14})'),
        'invoice_symbol': regex(r'Ký hiệu\s*:\s*([A-Za-z0-9]+)'),
        'invoice_number': regex(r'Số\s*:\s*(\d{4,12})'),
        'name': buyer.get('tên khách hàng', ''),
        'address': buyer.get('địa chỉ khách hàng', ''),
        'service_dates': buyer.get('thời gian sử dụng', ''),
        'date': buyer.get('ngày hóa đơn', ''),
        'reading_date_book': buyer.get('ngày ghi - sổ đọc', ''),
        'households': buyer.get('số hộ sử dụng nước', ''),
        'code': code,
        'period': period,
        'customer_id': expected_customer_id,
    }


class _Page:
    def __init__(self):
        self.image = Image.new('RGB', (A4_WIDTH, A4_HEIGHT), '#fff')
        self.d = ImageDraw.Draw(self.image)
        self.fonts = {}

    def font(self, size, bold=False):
        key = (size, bold)
        if key not in self.fonts:
            self.fonts[key] = _font(size, bold)
        return self.fonts[key]

    def width(self, text, size, bold=False):
        return self.d.textbbox((0, 0), str(text), font=self.font(size, bold))[2]

    def put(self, x, y, value, size=19, color=BLACK, bold=False, max_width=None, align='left'):
        txt = str(value or '')
        if max_width is not None:
            while txt and self.width(txt, size, bold) > max_width:
                txt = txt[:-1]
            if txt != str(value or '') and len(txt) >= 2:
                txt = txt[:-1] + '…'
        if align == 'right':
            x -= self.width(txt, size, bold)
        elif align == 'center':
            x -= self.width(txt, size, bold) // 2
        self.d.text((int(x), int(y)), txt, fill=color, font=self.font(size, bold))

    def wrap(self, value, x, y, max_width, size=19, color=BLACK, bold=False, lh=None, max_lines=3):
        lh = lh or int(size * 1.48)
        words = str(value or '').split()
        lines, line = [], ''
        for word in words:
            trial = f'{line} {word}'.strip()
            if self.width(trial, size, bold) <= max_width or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        if line:
            lines.append(line)
        for item in lines[:max_lines]:
            self.put(x, y, item, size, color, bold, max_width=max_width)
            y += lh
        return y

    def line(self, x1, y1, x2, y2, width=2, color=BORDER):
        self.d.line((x1, y1, x2, y2), fill=color, width=width)

    def box(self, x1, y1, x2, y2, color=BORDER, width=2):
        self.d.rectangle((x1, y1, x2, y2), outline=color, width=width)


def _paste_safe(page: _Page, data: bytes | None, rect: tuple[int, int, int, int], *, opacity=1.0):
    if not data or len(data) > 1_500_000:
        return
    try:
        with Image.open(BytesIO(data)) as opened:
            if opened.width * opened.height > 12_000_000:
                return
            opened.load()
            img = opened.convert('RGBA')
        x1, y1, x2, y2 = rect
        img.thumbnail((x2-x1, y2-y1), Image.Resampling.LANCZOS)
        if opacity < 1.0:
            img.putalpha(img.getchannel('A').point(lambda a: int(a * opacity)))
        px = x1 + (x2-x1-img.width)//2
        py = y1 + (y2-y1-img.height)//2
        page.image.paste(img, (px, py), img)
        page.d = ImageDraw.Draw(page.image)
    except (ValueError, OSError, UnidentifiedImageError):
        return


def render_viwaco_html_invoice(html: str, customer_id: str, code: str,
                               period: str, expected_total: int | None = None,
                               qr_png: bytes | None = None,
                               background_jpg: bytes | None = None,
                               expected_number: str | None = None) -> tuple[bytes, bytes]:
    """Produce readable one-page A4 (PDF, PNG) exclusively from supplied HTML.

    Does not preserve cryptographic signatures, even when HTML itself displays
    a 'Signature Valid' icon; any such icon is never treated as verification.
    """
    data = _extract_render_data(html, customer_id, code, period)
    info = data['details']
    if info.get('total_vnd') is None:
        raise ValueError('Bản HTML không có tổng tiền hóa đơn')
    if expected_total is not None and info['total_vnd'] != expected_total:
        raise ValueError('Tổng tiền trong HTML khác số liệu hóa đơn tra cứu')
    if not data['invoice_number'] or not data['invoice_symbol']:
        raise ValueError('Bản HTML thiếu ký hiệu hoặc số hóa đơn; từ chối kết xuất')
    if expected_number:
        m = re.search(r'(\d{4,12})\s*$', expected_number)
        if m and m.group(1).lstrip('0') != data['invoice_number'].lstrip('0'):
            raise ValueError('Số hóa đơn trên HTML khác trang tra cứu')
    if not data['name'] or not data['address']:
        raise ValueError('Bản HTML thiếu thông tin người mua; từ chối kết xuất')
    if not info.get('tariffs'):
        raise ValueError('Bản HTML thiếu bảng bậc giá; từ chối kết xuất')
    if len(info['tariffs']) > 8:
        raise ValueError('Hóa đơn quá nhiều bậc giá cho mẫu A4; không cắt dữ liệu')

    p = _Page()
    # Decorative invoice.jpg is optional and is faded to maintain readability.
    _paste_safe(p, background_jpg, (25, 40, 1215, 1660), opacity=0.16)
    p.put(230, 74, 'CÔNG TY CỔ PHẦN VIWACO', 25, BLUE, True, 410, 'center')
    p.wrap('Địa chỉ: Tầng 1, nhà 17 T7, Khu đô thị Trung Hòa Nhân Chính, Hà Nội',
           40, 119, 410, 17, BLUE, max_lines=3)
    p.put(705, 67, 'HÓA ĐƠN GIÁ TRỊ GIA TĂNG', 27, BLUE, True, 460, 'center')
    p.put(705, 104, '(TIỀN NƯỚC)', 26, BLUE, True, 400, 'center')
    p.put(705, 144, 'Bản thể hiện của hóa đơn điện tử', 19, BLUE, False, 460, 'center')
    p.put(705, 174, f'Tháng {period.split("/")[0]} năm {period.split("/")[1]}', 19, BLACK, False, 300, 'center')
    p.put(705, 206, f'Mã khách hàng: {customer_id}', 21, BLACK, True, 430, 'center')

    p.box(955, 62, 1195, 235, color=BLUE)
    p.put(970, 76, 'Mã số thuế:', 17, BLUE)
    p.put(970, 101, data['seller_tax'], 17, BLACK, True)
    p.put(970, 139, 'Ký hiệu:', 17, BLUE)
    p.put(1050, 139, data['invoice_symbol'], 18, BLACK, True, 135)
    p.put(970, 181, 'Số:', 20, BLUE)
    p.put(1190, 177, data['invoice_number'], 27, RED, True, 165, 'right')

    p.line(35, 253, 1205, 253, 2, BLUE)
    # Buyer metadata, pulled directly from the HTML document.
    meta = [
        ('Tên khách hàng', data['name']),
        ('Địa chỉ khách hàng', data['address']),
    ]
    y = 280
    for label, value in meta:
        p.put(42, y, label, 19, BLUE)
        y = max(y + 36, p.wrap(value, 295, y-2, 882, 20, BLACK, True,
                                max_lines=2) + 6)
    y += 6
    rows = [
        (('Mã số thuế', ''), ('Số hộ sử dụng nước', data['households'])),
        (('Số định danh cá nhân', ''), ('Thời gian sử dụng', data['service_dates'])),
        (('Số hộ chiếu', ''), ('Ngày hóa đơn', data['date'])),
        (('Mã quan hệ ngân sách', ''), ('Ngày ghi - Sổ đọc', data['reading_date_book'])),
    ]
    for (left_label, left_value), (right_label, right_value) in rows:
        p.put(43, y, left_label, 18, BLUE, max_width=220)
        p.put(271, y, left_value, 18, BLACK, max_width=255)
        p.put(630, y, right_label, 18, BLUE, max_width=270)
        p.put(906, y, right_value, 18, BLACK, max_width=282)
        y += 39

    y += 24
    bounds = (39, 215, 390, 600, 780, 960, 1201)
    header_height = 82
    p.box(bounds[0], y, bounds[-1], y + header_height, BLUE)
    headers = ['SỐ ĐỌC\nTHÁNG NÀY', 'SỐ ĐỌC\nTHÁNG TRƯỚC', 'TỔNG\nTIÊU THỤ',
               'ĐỊNH MỨC\nTIÊU THỤ', 'ĐƠN GIÁ', 'THÀNH TIỀN']
    for j, h in enumerate(headers):
        cx = (bounds[j] + bounds[j+1]) // 2
        for n, line in enumerate(h.split('\n')):
            p.put(cx, y + 18 + n*26, line, 18, BLUE, True, bounds[j+1]-bounds[j]-10, 'center')
        if j:
            p.line(bounds[j], y, bounds[j], y+header_height, 2, BLUE)
    y += header_height
    tariffs = info['tariffs'][:10]
    tier_rows = max(4, len(tariffs))
    row_height = 56
    end = y + row_height * tier_rows
    p.box(bounds[0], y, bounds[-1], end, BLUE)
    for x in bounds[1:-1]:
        p.line(x, y, x, end, 2, BLUE)
    for i in range(tier_rows):
        if i:
            p.line(39, y+row_height*i, 1201, y+row_height*i, 1, '#e0e6f6')
        if i >= len(tariffs):
            continue
        tier = tariffs[i]
        values = [
            _norm_amount(info.get('current_meter_m3')) if i == 0 else '',
            _norm_amount(info.get('previous_meter_m3')) if i == 0 else '',
            _norm_amount(info.get('usage_m3')) if i == 0 else '',
            f"{tier.get('tariff', '')}  {_norm_amount(tier.get('quantity_m3'))}",
            _norm_amount(tier.get('unit_price_vnd')),
            _norm_amount(tier.get('amount_vnd')),
        ]
        for j, value in enumerate(values):
            p.put(bounds[j+1]-12 if j in (0,1,2,4,5) else bounds[j]+17,
                  y+i*row_height+14, value, 20, BLACK,
                  max_width=bounds[j+1]-bounds[j]-22,
                  align='right' if j in (0,1,2,4,5) else 'left')
    y = end + 25
    # Lower section reproduces the charges and the textual signature statement.
    lower_start = y
    p.put(330, y+14, 'ĐƠN VỊ BÁN HÀNG', 21, BLUE, True, 550, 'center')
    p.put(65, y+67, 'Thông tin hiển thị trên trang VIWACO:', 17, MUTED)
    p.put(65, y+99, 'Ký bởi: CÔNG TY CỔ PHẦN VIWACO', 18, BLUE, True, 525)
    p.put(65, y+136, f"Ký ngày: {data['date']}", 18, BLUE)
    p.wrap('Bản PDF kết xuất từ HTML không chứa chữ ký số gốc.',
           65, y+181, 535, 18, RED, max_lines=2)
    if qr_png:
        _paste_safe(p, qr_png, (70, y+275, 260, y+465))
        p.put(165, y+475, 'QR tra cứu hóa đơn', 15, MUTED, align='center')

    x1, x2 = 624, 1202
    items = [
        ('CỘNG TIỀN NƯỚC', sum(t.get('amount_vnd') or 0 for t in tariffs)),
        ('Tiền nước', info.get('water_charge_vnd')),
        ('Phí bảo vệ môi trường' + (f" ({info['environment_fee_rate_percent']}%)" if info.get('environment_fee_rate_percent') else ''),
         info.get('environment_fee_vnd')),
        ('Thuế VAT' + (f" ({info['vat_rate_percent']}%)" if info.get('vat_rate_percent') else ''), info.get('vat_vnd')),
        ('TIỀN ĐỒNG HỒ', info.get('meter_charge_vnd')),
        ('CÁC KHOẢN GIẢM TRỪ', info.get('discount_vnd')),
        ('TỔNG CỘNG', info.get('total_vnd')),
    ]
    height = 55
    p.box(x1, y, x2, y + len(items)*height, BLUE)
    for i, (label, value) in enumerate(items):
        ry = y + height*i
        if i:
            p.line(x1, ry, x2, ry, 1, BLUE)
        is_final = i == len(items)-1
        p.put(x1+13, ry+13, label, 18 if len(label)<28 else 16,
              BLUE, bold=is_final, max_width=420)
        p.put(x2-13, ry+12, _norm_amount(value), 21, BLACK, bold=is_final,
              align='right', max_width=180)
    y = max(y + len(items)*height + 30, lower_start+410)
    p.line(35, y, 1205, y, 2, BLUE)
    p.put(49, y+23, 'Số tiền bằng chữ:', 19, BLUE, True)
    p.wrap(info.get('total_in_words', ''), 240, y+22, 932, 20, BLACK, max_lines=2)
    p.put(620, y+103, f'Tra cứu: hoadon.viwaco.vn/tra-cuu/  •  Mã: {code}',
          17, BLUE, align='center', max_width=1100)
    note_y = min(1630, max(y+163, 1520))
    p.line(35, note_y, 1205, note_y, 2, '#c9ccd2')
    p.put(620, note_y+22, 'BẢN IN KẾT XUẤT TỪ HTML DO VIWACO CUNG CẤP',
          19, RED, True, align='center', max_width=1160)
    p.put(620, note_y+54, 'Không có chữ ký số nhúng; không thay thế tệp hóa đơn điện tử gốc (XML/PDF ký số).',
          17, RED, align='center', max_width=1160)
    if note_y+90 >= A4_HEIGHT or note_y - y < 140:
        raise ValueError('Nội dung hóa đơn quá dài, không thể in an toàn trên A4')

    png_io, pdf_io = BytesIO(), BytesIO()
    p.image.save(png_io, format='PNG', optimize=True)
    p.image.save(pdf_io, format='PDF', resolution=DPI)
    return pdf_io.getvalue(), png_io.getvalue()
