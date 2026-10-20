"""Per-customer VIWACO water/billing sensors, efficient state attributes."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CUSTOMER_ID, CONF_METER_NAME, DOMAIN
from .recent import latest_billing_periods

# Preserve the original v0.3 unique IDs, so existing recorder history survives.
DESCRIPTIONS = (
    SensorEntityDescription(key="usage_m3", name="Nước sử dụng kỳ hóa đơn", native_unit_of_measurement="m³", device_class=SensorDeviceClass.WATER, icon="mdi:water"),
    SensorEntityDescription(key="total_vnd", name="Tiền nước kỳ hóa đơn", native_unit_of_measurement="VND", device_class=SensorDeviceClass.MONETARY, icon="mdi:cash"),
    SensorEntityDescription(key="paid_vnd", name="Đã thanh toán kỳ hóa đơn", native_unit_of_measurement="VND", device_class=SensorDeviceClass.MONETARY, icon="mdi:cash-check"),
    SensorEntityDescription(key="period", name="Kỳ hóa đơn", icon="mdi:calendar-month"),
    SensorEntityDescription(key="payment_status", name="Trạng thái thanh toán", icon="mdi:receipt-text-check"),
    SensorEntityDescription(key="payment_date", name="Ngày thanh toán", device_class=SensorDeviceClass.DATE, icon="mdi:calendar-check"),
    SensorEntityDescription(key="invoice_count", name="Số kỳ hóa đơn", icon="mdi:counter", entity_category=EntityCategory.DIAGNOSTIC),
    SensorEntityDescription(key="meter_reading_m3", name="Chỉ số đồng hồ tích lũy", native_unit_of_measurement="m³", device_class=SensorDeviceClass.WATER, state_class=SensorStateClass.TOTAL_INCREASING, icon="mdi:counter"),
    SensorEntityDescription(key="previous_reading_m3", name="Chỉ số đầu kỳ", native_unit_of_measurement="m³", device_class=SensorDeviceClass.WATER, icon="mdi:water-minus"),
    SensorEntityDescription(key="reading_usage_m3", name="Nước sử dụng kỳ ghi chỉ số", native_unit_of_measurement="m³", device_class=SensorDeviceClass.WATER, icon="mdi:water"),
    SensorEntityDescription(key="reading_date", name="Ngày ghi chỉ số", device_class=SensorDeviceClass.DATE, icon="mdi:calendar-clock"),
    SensorEntityDescription(key="reading_period", name="Kỳ ghi chỉ số", icon="mdi:calendar-month"),
    SensorEntityDescription(key="meter_serial", name="Serial đồng hồ", icon="mdi:gauge", entity_category=EntityCategory.DIAGNOSTIC),
    SensorEntityDescription(key="customer_id", name="Mã khách hàng", icon="mdi:identifier", entity_category=EntityCategory.DIAGNOSTIC),
    SensorEntityDescription(key="customer_name", name="Tên khách hàng", icon="mdi:account", entity_category=EntityCategory.DIAGNOSTIC),
    SensorEntityDescription(key="customer_address", name="Địa chỉ khách hàng", icon="mdi:map-marker", entity_category=EntityCategory.DIAGNOSTIC),
    SensorEntityDescription(key="customer_phone", name="Điện thoại khách hàng", icon="mdi:phone", entity_category=EntityCategory.DIAGNOSTIC),
    SensorEntityDescription(key="reading_count", name="Số kỳ ghi chỉ số", icon="mdi:counter", entity_category=EntityCategory.DIAGNOSTIC),
    SensorEntityDescription(key="outstanding_latest_vnd", name="Chưa thanh toán kỳ hóa đơn", native_unit_of_measurement="VND", device_class=SensorDeviceClass.MONETARY, icon="mdi:cash-clock"),
    SensorEntityDescription(key="year_usage_m3", name="Nước năm hóa đơn mới nhất", native_unit_of_measurement="m³", device_class=SensorDeviceClass.WATER, icon="mdi:water-check"),
    SensorEntityDescription(key="year_total_vnd", name="Tiền năm hóa đơn mới nhất", native_unit_of_measurement="VND", device_class=SensorDeviceClass.MONETARY, icon="mdi:cash-multiple"),
    SensorEntityDescription(key="year_paid_vnd", name="Đã trả năm hóa đơn mới nhất", native_unit_of_measurement="VND", device_class=SensorDeviceClass.MONETARY, icon="mdi:cash-check"),
    SensorEntityDescription(key="year_outstanding_vnd", name="Chưa trả năm hóa đơn mới nhất", native_unit_of_measurement="VND", device_class=SensorDeviceClass.MONETARY, icon="mdi:cash-alert"),
    SensorEntityDescription(key="previous_year_usage_m3", name="Nước năm hóa đơn trước", native_unit_of_measurement="m³", device_class=SensorDeviceClass.WATER, icon="mdi:water"),
    SensorEntityDescription(key="previous_year_total_vnd", name="Tiền năm hóa đơn trước", native_unit_of_measurement="VND", device_class=SensorDeviceClass.MONETARY, icon="mdi:cash"),
    SensorEntityDescription(key="session_status", name="Trạng thái phiên VIWACO", icon="mdi:shield-check", entity_category=EntityCategory.DIAGNOSTIC),
)


# Three latest *billed periods*, 4 sensors per period, for each customer.
# New unique_ids do not modify any of the v1.1.1 sensor IDs.
RECENT_KEYS = (
    ("usage_m3", "Tiêu thụ", "m³", SensorDeviceClass.WATER, "mdi:water"),
    ("total_vnd", "Tiền nước", "VND", SensorDeviceClass.MONETARY, "mdi:cash"),
    ("previous_m3", "Chỉ số trước", "m³", SensorDeviceClass.WATER, "mdi:water-minus"),
    ("current_m3", "Chỉ số sau", "m³", SensorDeviceClass.WATER, "mdi:water-plus"),
)
RECENT_DESCRIPTIONS = tuple(
    SensorEntityDescription(
        key=f"recent_{slot}_{field}",
        name=f"{title} kỳ {'mới nhất' if slot == 1 else f'trước {slot - 1}'}",
        native_unit_of_measurement=unit,
        device_class=device_class,
        icon=icon,
    )
    for slot in (1, 2, 3)
    for field, title, unit, device_class, icon in RECENT_KEYS
)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities(ViwacoSensor(entry.runtime_data, entry, desc) for desc in (*DESCRIPTIONS, *RECENT_DESCRIPTIONS))


class ViwacoSensor(CoordinatorEntity, SensorEntity):
    """A light-weight sensor for one customer; entire history stays in RAM/API."""
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, description: SensorEntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        # m³ and VND from VIWACO are whole numbers: show 1,614, not 1,614.00.
        # This is presentation-only; Recorder and energy statistics stay numeric.
        if description.native_unit_of_measurement in ("m³", "VND"):
            self._attr_suggested_display_precision = 0
        customer_id = entry.data[CONF_CUSTOMER_ID]
        self._attr_unique_id = f"{customer_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, customer_id)},
            name=entry.options.get(CONF_METER_NAME) or f"VIWACO {customer_id}",
            manufacturer="VIWACO", model="Water meter & billing",
        )

    @property
    def available(self) -> bool:
        if self.entity_description.key == "session_status":
            return True  # Status must remain visible during outage and reauth.
        return self.coordinator.data is not None

    @property
    def native_value(self):
        if self.entity_description.key == "session_status":
            return self.coordinator.session_status
        data = self.coordinator.data
        if not data or not data.invoices or not data.readings:
            return None
        invoice, reading = data.invoices[0], data.readings[0]
        key = self.entity_description.key
        customer_fields = {
            "customer_id": data.customer.customer_id,
            "customer_name": data.customer.name,
            "customer_address": data.customer.address,
            "customer_phone": data.customer.phone,
        }
        if key.startswith("recent_"):
            _, slot_text, field = key.split("_", 2)
            periods = latest_billing_periods(data)
            slot = int(slot_text) - 1
            if slot >= len(periods):
                return None
            period_invoice, period_reading = periods[slot]
            if field in ("usage_m3", "total_vnd"):
                return getattr(period_invoice, field)
            # A missing reading in the billing month must not silently
            # reuse a different month's meter indexes.
            return getattr(period_reading, field) if period_reading else None
        if key in customer_fields:
            return customer_fields[key] or None
        if key == "invoice_count":
            return len(data.invoices)
        if key == "reading_count":
            return len(data.readings)
        if key == "payment_status":
            if invoice.total_vnd > 0 and invoice.paid_vnd >= invoice.total_vnd:
                return "Đã ghi nhận thanh toán"
            if invoice.paid_vnd > 0:
                return "Đã thanh toán một phần"
            return "Chưa ghi nhận thanh toán"
        if key == "outstanding_latest_vnd":
            return max(0, invoice.total_vnd - invoice.paid_vnd)
        if key in ("usage_m3", "total_vnd", "paid_vnd", "period", "payment_date"):
            return getattr(invoice, key)
        meter_fields = {
            "meter_reading_m3": reading.current_m3,
            "previous_reading_m3": reading.previous_m3,
            "reading_usage_m3": reading.usage_m3,
            "reading_date": reading.read_date,
            "reading_period": reading.period,
            "meter_serial": reading.serial,
        }
        if key in meter_fields:
            return meter_fields[key]
        year = invoice.year if not key.startswith("previous_year_") else invoice.year - 1
        invoices = [item for item in data.invoices if item.year == year]
        aggregates = {
            "year_usage_m3": sum(i.usage_m3 for i in invoices),
            "year_total_vnd": sum(i.total_vnd for i in invoices),
            "year_paid_vnd": sum(i.paid_vnd for i in invoices),
            "year_outstanding_vnd": sum(max(0, i.total_vnd - i.paid_vnd) for i in invoices),
            "previous_year_usage_m3": sum(i.usage_m3 for i in invoices),
            "previous_year_total_vnd": sum(i.total_vnd for i in invoices),
        }
        return aggregates.get(key)

    @property
    def extra_state_attributes(self) -> dict:
        if self.entity_description.key == "session_status":
            coordinator = self.coordinator
            return {
                "last_error": coordinator.last_error,
                "last_session_check": coordinator.last_session_check.isoformat() if coordinator.last_session_check else None,
                "last_successful_fetch": coordinator.last_successful_fetch.isoformat() if coordinator.last_successful_fetch else None,
                "cache_saved_at": coordinator.cache_saved_at,
                "note": "valid=phiên hợp lệ; cached=khôi phục từ cache; offline=lỗi kết nối, thay đổi HTML hoặc phiên đang xác minh; expired=lỗi xác thực được xác nhận",
            }
        data = self.coordinator.data
        if data is None or not data.invoices or not data.readings:
            return {}
        invoice, reading = data.invoices[0], data.readings[0]
        key = self.entity_description.key
        if key.startswith("recent_"):
            slot = int(key.split("_", 2)[1]) - 1
            periods = latest_billing_periods(data)
            if slot >= len(periods):
                return {}
            period_invoice, period_reading = periods[slot]
            return {
                "billing_period": period_invoice.period,
                "billing_year": period_invoice.year,
                "billing_month": period_invoice.month,
                "reading_date": period_reading.read_date.isoformat() if period_reading else None,
                "meter_serial": period_reading.serial if period_reading else None,
                "reading_found": period_reading is not None,
                "note": "Dữ liệu theo kỳ hóa đơn, không đo trực tiếp",
            }
        if key == "period":
            return {
                "from_date": invoice.start_date.isoformat() if invoice.start_date else None,
                "to_date": invoice.end_date.isoformat() if invoice.end_date else None,
                "invoice_number": invoice.invoice_number,
                "invoice_url": invoice.invoice_url,
            }
        if key == "meter_reading_m3":
            return {
                "meter_serial": reading.serial,
                "read_date": reading.read_date.isoformat(),
                "reading_type": reading.reading_type,
                "period": reading.period,
                "note": "Đọc định kỳ, không đo theo thời gian thực",
            }
        if key.startswith("year_") or key.startswith("previous_year_"):
            return {"year": invoice.year - (1 if key.startswith("previous_") else 0)}
        return {}
