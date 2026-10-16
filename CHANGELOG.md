## v1.7.0 (2026-10-16)
- Opt-in auto archive of latest invoice after enabling, then newly published months on successful sync.
- Asynchronous background process, persistent completion state, retry failed months, support PDF/PNG/both.
- Set display precision to 0 for m³ and VND sensors (example: 1,614 m³ instead of 1,614.00 m³).
- Keep v1.6.1 PDF validation and all existing config entries and entity unique IDs.

## v1.6.1 (2026-10-16)
- Validate the entire supplier PDF with PDFium before writing any invoice file.
- Try non-destructive recovery of broken xref/trailer with pypdf, then revalidate; record repaired copies distinctly because digital signatures can be invalidated.
- Reject HTML/incomplete PDF responses and avoid persisting unreadable PDFs.
- Detect/re-fetch broken archived PDFs from v1.6.0 and remove stale catalog links.
- Bounded retries on HTTP 429/500/502/503/504, serialized invoice downloads across meter entries.
- 74 offline tests passed; prior backend/frontend behavior preserved.

## 1.6.0 (2026-10-16)
- Visual Lovelace Card Editor (`getConfigElement`, `config-changed`) to set title, meter, color, opacity and visible content.
- 11 color palettes and 0–100% card background opacity.
- Container-query mobile layout, two-column KPIs, swipeable charts, mobile recent-month cards.
- Existing backend, config entries, unique IDs, and services preserved.

## v1.5.0 — 2026-10-16

- Session Keep-Alive ON every 15 minutes per meter (can configure 5–60 minutes or disable).
- Rotate first-party response Set-Cookie only after checking customer identity; persist in ConfigEntry without duplicate reload listeners.
- New diagnostic session status sensor (valid, initializing, cached, offline, expired) plus timestamps/error metadata.
- Restart-safe private Store snapshot cache; restore asynchronously and retain stale values with explicit status on network/auth errors.
- Start reauth only once per failed session and create HA persistent notifications; never log Cookie content.
- No first-refresh I/O awaited in config-entry setup; entry-owned background tasks/timers cancelled on unload.
- Dashboard shows offline/cached/expired warnings even when cached data is still present.
- 61 pytest offline tests, JS syntax/card smoke checks. Requires live Home Assistant verification.

## v1.4.0
- Thêm NumberSelector slider cho mỗi config entry: 6 tháng → tối đa (All), cập nhật theo nguồn VIWACO.
- Lọc dữ liệu hóa đơn/đồng hồ theo khoảng tháng và giới hạn tác vụ lưu PDF/PNG theo tùy chọn.
- Giữ nguyên entities, tránh HTTP khi mở cấu hình và khi Home Assistant khởi động.
- Dashboard hiển thị mức lịch sử đang chọn.

# VIWACO Reader Changelog

## 1.3.0 (2026-10-16)

- Preserve all 1.2.0 sensors and multi-meter configuration entries.
- Expose all monthly invoice/readings via existing authenticated WebSocket.
- Add historical invoice details from official lookup HTML and bill preview HTML; match customer IDs before caching.
- Add `viwaco_reader.archive_invoices` service for details / PDF / PNG / both, by year or all years.
- Store private metadata in `/config/viwaco_reader_cache` and original official PDF plus derived PNG in `/config/www/viwaco_reader` on demand only.
- Surface all periods across years in dashboard with links, tax/fee/tier breakdown, archive progress and actions.
- Keep download, parsing, and PDF rendering from blocking Home Assistant startup. Network requests async, file IO/PDFium in executor, tasks entry-owned.
- Strict URL validation, PDF signature validation, per-period failure isolation, no cross-domain forwarding of `tracuu.viwaco.vn` session Cookie.

## 1.2.0

- Three billing period groups (12 sensors), dashboard registration and alerts.
