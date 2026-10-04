"""Sensor entities for the Dreame Robot integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    DEGREE,
    PERCENTAGE,
    EntityCategory,
    UnitOfArea,
    UnitOfLength,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import DeviceSnapshot
from .coordinator import DreameCoordinator
from .entity import DreameEntity

UNIT_SQM = UnitOfArea.SQUARE_METERS


@dataclass(frozen=True, kw_only=True)
class DreameSensorDescription(SensorEntityDescription):
    """Describe one sensor exposed for a mower."""

    value: Callable[[DeviceSnapshot], Any]


SENSORS: tuple[DreameSensorDescription, ...] = (
    DreameSensorDescription(
        key="state_name",
        translation_key="state_name",
        device_class=SensorDeviceClass.ENUM,
        options=sorted(
            {
                "charging",
                "charging_completed",
                "charging_paused_high_temperature",
                "charging_paused_low_temperature",
                "human_following",
                "idle",
                "mapping",
                "monitoring",
                "mowing",
                "paused",
                "remote_control",
                "repositioning",
                "returning",
                "second_mowing",
                "shortcut",
                "spot_mowing",
                "station_cleaning",
                "upgrading",
                "waiting_for_task",
            }
        ),
        value=lambda s: s.state or "unknown",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DreameSensorDescription(
        key="task_status",
        name="Task Status",
        value=lambda s: s.task_status or "unknown",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DreameSensorDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda s: s.battery_level,
    ),
    DreameSensorDescription(
        key="mowing_mode",
        name="Mowing Mode",
        value=lambda s: s.mowing_mode,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DreameSensorDescription(
        key="session_time",
        translation_key="session_time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda s: s.session_minutes,
    ),
    DreameSensorDescription(
        key="session_area",
        translation_key="session_area",
        native_unit_of_measurement=UNIT_SQM,
        device_class=SensorDeviceClass.AREA,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda s: s.session_area_sqm,
    ),
    DreameSensorDescription(
        key="progress",
        translation_key="progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda s: s.progress_percent,
    ),
    DreameSensorDescription(
        key="total_mowing_time",
        translation_key="total_mowing_time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s: s.total_minutes,
    ),
    DreameSensorDescription(
        key="total_mowed_area",
        translation_key="total_mowed_area",
        native_unit_of_measurement=UNIT_SQM,
        device_class=SensorDeviceClass.AREA,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s: s.total_area_sqm,
    ),
    DreameSensorDescription(
        key="error",
        translation_key="error",
        value=lambda s: s.error.name if s.error and s.error.tier == "error" else "none",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DreameSensorDescription(
        key="status_notice",
        translation_key="status_notice",
        value=lambda s: s.error.name if s.error and s.error.tier != "error" else "none",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DreameSensorDescription(
        key="position_x",
        translation_key="position_x",
        native_unit_of_measurement=UnitOfLength.CENTIMETERS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value=lambda s: s.runtime.x if s.runtime else None,
    ),
    DreameSensorDescription(
        key="position_y",
        translation_key="position_y",
        native_unit_of_measurement=UnitOfLength.CENTIMETERS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value=lambda s: s.runtime.y if s.runtime else None,
    ),
    DreameSensorDescription(
        key="heading",
        translation_key="heading",
        native_unit_of_measurement=DEGREE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value=lambda s: s.runtime.heading if s.runtime else None,
    ),
    DreameSensorDescription(
        key="map_count",
        translation_key="map_count",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s: len(s.maps),
    ),
    DreameSensorDescription(
        key="zone_count",
        translation_key="zone_count",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s: _count(s, "zones"),
    ),
    DreameSensorDescription(
        key="serial_number",
        translation_key="serial_number",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value=lambda s: s.serial_number,
    ),
    DreameSensorDescription(
        key="firmware_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value=lambda s: s.descriptor.firmware,
    ),
)


def _count(snapshot: DeviceSnapshot, kind: str) -> int | None:
    """Count map entities of one kind on the current map."""
    vector_map = snapshot.maps.get(snapshot.current_map_index + 1) if snapshot.maps else None
    return len(getattr(vector_map, kind)) if vector_map else None


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the sensor platform."""
    coordinator: DreameCoordinator = entry.runtime_data
    async_add_entities(
        DreameSensor(coordinator, description, description.key) for description in SENSORS
    )


class DreameSensor(DreameEntity, SensorEntity):
    """A readable value from the mower snapshot."""

    entity_description: DreameSensorDescription

    def __init__(
        self,
        coordinator: DreameCoordinator,
        description: DreameSensorDescription,
        unique_suffix: str,
    ) -> None:
        super().__init__(coordinator, description, unique_suffix)

    @property
    def native_value(self) -> Any:
        """Return the current sensor value."""
        snapshot = self.snapshot
        return None if snapshot is None else self.entity_description.value(snapshot)

    @property
    def available(self) -> bool:
        """Return whether the underlying value exists right now."""
        if not super().available:
            return False
        return self.native_value is not None
