# v1.7.0 — Automatically archive new invoices + integer sensor display
- Per-meter, explicit opt-in automatic archiving on invoice period changes.
- Archive the latest invoice on first activation, then any new invoice periods; persisted per-entry progress.
- Reuse PDF validation/repair and PNG conversion from v1.6.1; failed periods retry without losing existing files.
- Set integer display precision (0 decimals) for numeric water volume and monetary sensors.
- No changes to existing entity unique IDs, dashboard editor or keep-alive timer.

# VIWACO Reader 1.6.1 — PDF validation and recovery

**Fix:** v1.6.0 sometimes saved `.pdf` files containing the `%PDF-` header but malformed content. Such files could not open, and converting to PNG failed with `PDFium: Data format error`.

**New:** PDFium preflight before file writes, optional pypdf repair and validation, bounded HTTP error retries, stale archive detection, shared download limiting for multiple meters. No changes to existing entity unique IDs or Visual Editor.

**Warning:** Modified/repaired copies are not equivalent to an original digitally signed PDF. When VIWACO serves irrecoverably damaged bytes, the file is not saved and the archive job reports an error.

**Test:** 74 Python tests and JS checks. Not tested on a live VIWACO session. Read README.md for installation and a one-month test action.
