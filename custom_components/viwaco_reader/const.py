"""Constants and defaults for VIWACO Reader."""
DOMAIN = "viwaco_reader"
CONF_CUSTOMER_ID = "customer_id"
CONF_COOKIE = "cookie"
CONF_METER_NAME = "meter_name"
CONF_UPDATE_HOURS = "update_hours"
CONF_HISTORY_MONTHS = "history_months"  # 0 = all months offered by VIWACO
DEFAULT_HISTORY_MONTHS = 0
CONF_KEEPALIVE_ENABLED = "keepalive_enabled"
CONF_KEEPALIVE_MINUTES = "keepalive_minutes"
DEFAULT_KEEPALIVE_ENABLED = True
DEFAULT_KEEPALIVE_MINUTES = 15
CONF_AUTO_ARCHIVE_ENABLED = "auto_archive_enabled"
CONF_AUTO_ARCHIVE_MODE = "auto_archive_mode"
# Explicit opt-in: invoices under /config/www are public via /local/.
DEFAULT_AUTO_ARCHIVE_ENABLED = False
DEFAULT_AUTO_ARCHIVE_MODE = "both"
MIN_HISTORY_MONTHS = 6
INVOICE_URL = "https://tracuu.viwaco.vn/Invoice.aspx"
READING_URL = "https://tracuu.viwaco.vn/Reading.aspx"
DEFAULT_UPDATE_INTERVAL_HOURS = 6
MIN_UPDATE_HOURS = 1
MAX_UPDATE_HOURS = 24
from homeassistant.const import Platform

PLATFORMS = [Platform.SENSOR]
