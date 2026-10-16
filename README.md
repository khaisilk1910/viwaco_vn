# VIWACO Reader cho Home Assistant

Tích hợp **không chính thức**, lấy thông tin tiêu thụ nước và hóa đơn từ cổng tra cứu VIWACO vào Home Assistant, cài đặt qua **HACS (Custom repository)**. Mã nguồn hiện tại: **v1.7.0**.

> Không do VIWACO hoặc Home Assistant phát hành/bảo trợ. Cổng tra cứu có thể thay đổi hoặc ngừng cung cấp dữ liệu. **Phiên bản hiện tại bắt buộc nhập Cookie đăng nhập hợp lệ**; không tự vượt CAPTCHA hay đăng nhập không cần Cookie.

## Tính năng

- Thêm nhiều **mã khách hàng**, mỗi mã có cấu hình, cảm biến và phiên đăng nhập riêng.
- Theo dõi m³ tiêu thụ, chỉ số đồng hồ, hóa đơn, số tiền, thanh toán, công nợ, so sánh năm và lịch sử theo kỳ.
- Hiển thị số nguyên (không thêm `.00`) ở cảm biến có đơn vị m³/VND; dữ liệu thực không bị làm tròn thêm.
- Card Lovelace `custom:viwaco-overview-card`, giao diện chỉnh sửa trực quan, dùng được trên điện thoại.
- Đồng bộ định kỳ (mặc định **6 giờ**); kiểm tra duy trì phiên (mặc định **15 phút**, có thể tắt/chỉnh). Hỗ trợ sửa Cookie và yêu cầu xác thực lại.
- Xem chi tiết hóa đơn; tải **PDF chính thức** và/hoặc PNG (tạo từ PDF) theo yêu cầu. Có thể **bật tự lưu** hóa đơn mới cho từng đồng hồ: lần bật đầu chỉ thử kỳ mới nhất, các kỳ phát sinh tiếp theo được thử sau lần đồng bộ thành công; các kỳ thất bại được thử lại.
- Kiểm tra PDF trước khi lưu, thử phục hồi lỗi cấu trúc khi có thể; **không bảo đảm mọi hóa đơn đều có PDF hợp lệ**.

## Cài đặt qua HACS

### Thêm vào HACS tự động:
Nhấn nút dưới đây để mở trực tiếp repository này trong HACS:

[![Mở repository trong HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=khaisilk1910&repository=viwaco_vn&category=integration)

Sau đó:
1. Chọn **Download** trong HACS để cài đặt tích hợp.
2. Khởi động lại Home Assistant.
3. Vào **Settings → Devices & services → Add integration**.
4. Tìm **VIWACO Reader** và hoàn tất cấu hình theo giao diện.
   
### Cài thủ công:
1. Cần Home Assistant có [HACS](https://www.hacs.xyz/docs/use/download/download/) và kết nối Internet. Đăng nhập GitHub nếu HACS yêu cầu.
2. Mở **HACS → dấu ba chấm (⋮) → Custom repositories**.
3. Dán `https://github.com/khaisiik1910/viwaco_vn`, chọn loại **Integration**, rồi **Add**.
4. Tìm **VIWACO Reader** trong HACS → **Download**. Khởi động lại Home Assistant.
5. Vào **Settings → Devices & services → Add integration → VIWACO Reader**. Nhập **mã khách hàng** (giữ các số 0 đầu), **Cookie** và tên đồng hồ tùy chọn.
6. Sau khi cấu hình, vào **Configure** của tích hợp để chỉnh chu kỳ đồng bộ, duy trì phiên, số tháng lịch sử và **tự lưu hóa đơn** (mặc định **tắt**).

**Cài thủ công:** Chép nguyên thư mục `custom_components/viwaco_reader` vào `/config/custom_components/viwaco_reader`, khởi động lại Home Assistant, sau đó thêm tích hợp như bước 5. Không chép toàn bộ ZIP vào `/config/custom_components`.

**Card Lovelace:** Với dashboard ở chế độ Storage, tích hợp sẽ thử đăng ký resource tự động. Nếu card báo không tìm thấy, vào **Settings → Dashboards → Resources** thêm URL `/viwaco_reader/viwaco-dashboard.js?v=1.7.0` kiểu **JavaScript module**, rồi thêm card bằng YAML:
<img width="491" height="420" alt="image" src="https://github.com/user-attachments/assets/c7bfe762-a8d4-4393-9be1-2b9219092974" />
- Nên thiết lập cho card này full 1 Dashboard vì có nhiều thông tin.

Các ví dụ dashboard khác nằm trong thư mục `dashboard/`.

## Cách lấy Cookie (máy tính, Chrome/Edge)
<img width="960" height="492" alt="image" src="https://github.com/user-attachments/assets/ba085a93-1777-4c48-9a0e-a9ff113e7801" />

1. Mở **https://tracuu.viwaco.vn/**, truy cập đúng tài khoản/mã khách hàng, **tự nhập CAPTCHA** và vào trang tra cứu sau khi đăng nhập.
2. Nhấn **F12 → Network**, bật **Preserve log** nếu cần. Mở lại mục hóa đơn để có request `Invoice.aspx` (hoặc tải lại trang khi phiên đang đăng nhập).
3. Chọn request `Invoice.aspx` tới **`tracuu.viwaco.vn` → Headers → Request Headers → Cookie**.
4. Sao chép **toàn bộ giá trị của header `Cookie`**, dạng `ten_cookie=gia_tri; ten_khac=gia_tri`; có thể dán cả tiền tố `Cookie:`. Chỉ dán vào form cấu hình Home Assistant.
5. Thử đồng bộ. Nếu thêm mã khách hàng khác, phải xác nhận phiên trình duyệt đang thuộc đúng mã đó và lấy Cookie tương ứng.

**Chú ý:** Lấy ở **Request Headers**, **không** lấy `Set-Cookie` trong Response Headers; không chỉ sao chép tên cookie hoặc một giá trị rời. Các chuỗi trên là **mẫu định dạng, không phải Cookie thật**. Trên Android, Chrome thường không có DevTools đầy đủ: nên lấy bằng trình duyệt máy tính/remote debugging đáng tin cậy; không cài tiện ích hoặc trang web lạ để lấy Cookie. Không chia sẻ ảnh chụp có Cookie.

## Lỗi Cookie & cách xử lý

| Triệu chứng | Nguyên nhân thường gặp / xử lý |
| --- | --- |
| `session_expired`, `expired`, yêu cầu đăng nhập lại, HTTP 302/401/403 | Cookie hết hạn, bị đăng xuất hoặc bị thay sau CAPTCHA. Đăng nhập lại trên trang chính thức, lấy Cookie **mới**, vào **Devices & services → VIWACO Reader → Reconfigure** (hoặc luồng Reauthenticate). |
| `invalid_cookie_format` | Dán nhầm `Set-Cookie`, thiếu `tên=giá_trị`, cookie trống hoặc có ký tự xuống dòng. Lấy lại **Request Headers → Cookie**, dán trên một dòng. |
| `wrong_customer`, mã khách hàng không khớp | Cookie thuộc phiên của **mã khác**. Chuyển đúng mã trên website, đăng nhập và lấy lại Cookie. |
| `cannot_connect`, `offline`, lỗi mạng, HTTP 5xx | Kiểm tra Internet/DNS và `tracuu.viwaco.vn`, thử lại sau; không mặc định kết luận Cookie sai. |
| `PDFium: Data format error`, PDF không mở được | Máy chủ hóa đơn có thể trả PDF hỏng/HTML. Bản tích hợp thử kiểm tra/khôi phục, **không lưu PDF không hợp lệ**; thử lại sau, thử chế độ `details` hoặc `pdf`. Bản PDF đã khôi phục có thể **mất hiệu lực chữ ký điện tử**. |
| Tự lưu chưa thấy hóa đơn mới | Bật tùy chọn tự lưu cho đúng đồng hồ, chờ kỳ xuất hiện trên VIWACO và một lần đồng bộ **thành công**; kiểm tra Logs, trạng thái lưu trữ và quyền ghi `/config/www/`. |

Cookie có thể được máy chủ làm mới tự động trong khi phiên còn hợp lệ, nhưng **không thể bảo đảm Cookie không bao giờ hết hạn**.

## Tải hóa đơn thủ công

Vào **Developer tools → Actions** (trên phiên bản Home Assistant cũ là Services), chọn `viwaco_reader.archive_invoices`. Ví dụ chỉ thử một kỳ:

```yaml
action: viwaco_reader.archive_invoices
data:
  customer_id: "000000001" # thay bằng mã khách hàng của bạn
  mode: pdf             # details | pdf | png | both
  max_invoices: 1
  overwrite: false
```

PDF/PNG được lưu dưới `/config/www/viwaco_reader/<thư_mục_ngẫu_nhiên>/<năm>/` và có thể mở qua `/local/viwaco_reader/...`. Danh mục/cache nội bộ ở `/config/viwaco_reader_cache/` và `.storage/`. Nếu không muốn tạo file PDF/PNG trong thư mục công khai, dùng `mode: details` và **không bật tự lưu**.

## Bảo mật, rủi ro và khuyến cáo

- **Cookie là thông tin xác thực tương đương phiên đăng nhập.** Người có Cookie còn hiệu lực có thể truy cập thông tin được phiên đó cho phép. **Không** đưa Cookie vào GitHub, Issues, log công khai, ảnh chụp, mã nguồn hoặc file cấu hình chia sẻ.
- Cookie được lưu trong Home Assistant config entries (thư mục **`.storage`**), có thể đi theo **backup**; chỉ chủ sở hữu HA tin cậy được truy cập. Bảo vệ thiết bị, giới hạn quyền, mã hóa bản sao lưu nơi có thể và thay Cookie khi nghi lộ.
- **Rất quan trọng:** `/config/www/` được phục vụ qua `/local/` và **không được Home Assistant kiểm soát truy cập như các trang yêu cầu đăng nhập**. Hóa đơn có thể chứa **họ tên, địa chỉ, mã khách hàng, dữ liệu tiêu dùng/thanh toán**. Tên thư mục ngẫu nhiên **không phải cơ chế bảo mật**. Không bật tự lưu PDF/PNG nếu HA của bạn có truy cập Internet hoặc được chia sẻ mà chưa hạn chế đường dẫn này tại reverse proxy. Tắt tự lưu **không xóa file đã tải**; hãy xóa thủ công nếu cần.
- Tích hợp đọc trang web bên thứ ba, không được nhà cung cấp bảo đảm API ổn định; chỉ dùng với dữ liệu/tài khoản mà bạn được quyền truy cập. Không thu thập hoặc công khai dữ liệu người khác, không tìm cách vượt CAPTCHA, không tăng tần suất truy vấn quá mức.
- Kiểm tra chứng từ và **chữ ký số** trên hệ thống hóa đơn chính thức trước khi dùng làm căn cứ pháp lý; dữ liệu trong Home Assistant mang tính tham khảo.
- Khi báo lỗi trên GitHub, **che mã khách hàng, địa chỉ, tên, số điện thoại, URL hóa đơn chứa mã và toàn bộ Cookie**. Xem thêm [SECURITY.md](SECURITY.md).

## Giới hạn & hỗ trợ

- Cần Cookie hợp lệ; chưa hỗ trợ đăng nhập tự động không Cookie. Không phải cảm biến thời gian thực.
- Trang VIWACO hoặc cấu trúc PDF thay đổi có thể khiến một số kỳ không đọc được; tính năng tự lưu chỉ áp dụng các kỳ mà cổng trả về dữ liệu và liên kết hóa đơn.
- Nếu có lỗi, xem **Settings → System → Logs**, lọc `custom_components.viwaco_reader`, rồi tạo [GitHub Issue](https://github.com/khaisiik1910/viwaco_vn/issues) với thông tin **đã ẩn dữ liệu cá nhân**.
- Lịch sử thay đổi: [CHANGELOG.md](CHANGELOG.md). Đây là repository dành cho **HACS Custom repository**, chưa đồng nghĩa được đưa vào kho mặc định của HACS.

## Giấy phép

Dự án được phát hành theo [MIT License](LICENSE). Bạn có thể sử dụng, chỉnh sửa và phân phối mã nguồn theo các điều kiện trong giấy phép. MIT chỉ áp dụng cho phần mã nguồn mà chủ sở hữu có quyền cấp phép; thương hiệu, dữ liệu và nội dung từ VIWACO hoặc bên thứ ba không mặc nhiên được cấp phép theo MIT.
