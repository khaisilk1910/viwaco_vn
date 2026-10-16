# Bảo mật và quyền riêng tư

## Cookie, dữ liệu cá nhân

- **Không tạo GitHub Issue chứa Cookie hoặc dữ liệu hóa đơn.** Cookie còn hiệu lực có thể cho phép truy cập tài khoản VIWACO.
- Không commit nội dung `/config/.storage/`, `/config/www/viwaco_reader/`, `/config/viwaco_reader_cache/`, backup HA, file HAR, ảnh chụp màn hình Network Headers hoặc log thô.
- `hacs.json` và `manifest.json` chỉ là metadata, **không phải nơi chứa Cookie**. Cookie được nhập trên giao diện Home Assistant và lưu trong config entries cục bộ.
- Hóa đơn lưu trong `/config/www/viwaco_reader/` có thể bị đọc trực tiếp qua `/local/viwaco_reader/` nếu người khác truy cập được URL. Hạn chế bằng reverse proxy/không đưa HA ra Internet hoặc tắt chế độ tải file. URL chứa thư mục ngẫu nhiên không phải lớp xác thực.
- Nếu lộ Cookie: đăng xuất/thu hồi phiên theo khả năng của VIWACO, đăng nhập lại và làm mới Cookie trong Home Assistant; kiểm tra các backup, Git commits và link công khai để xử lý rò rỉ. Chỉ sửa/xóa commit **không** khiến Cookie đã lộ an toàn trở lại.
- Nếu lỡ commit Cookie lên GitHub, hãy **thu hồi/thay phiên ngay**, sau đó xóa thông tin khỏi repository và lịch sử Git nơi có thể; cân nhắc yêu cầu GitHub hỗ trợ với dữ liệu nhạy cảm.

## Báo lỗi bảo mật

Nếu có mục **Report a vulnerability** trong tab Security của repository, hãy sử dụng kênh báo cáo riêng tư đó. Nếu không có, **không đăng thông tin khai thác, Cookie hoặc dữ liệu cá nhân** ở Issues công khai; trước hết liên hệ chủ repository theo kênh riêng tư mà họ công bố.

Đây là tích hợp cộng đồng không chính thức; chưa có cam kết kiểm định bảo mật độc lập.
