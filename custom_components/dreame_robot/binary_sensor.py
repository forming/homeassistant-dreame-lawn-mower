"""Binary sensor entities for the Dreame Robot integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import DeviceSnapshot
from .coordinator import DreameCoordinator
from .entity import DreameEntity


@dataclass(frozen=True, kw_only=True)
class DreameBinarySensorDescription(BinarySensorEntityDescription):
    """Describe one binary sensor exposed for a mower."""

    value: Callable[[DeviceSnapshot, DreameCoordinator], bool]


BINARY_SENSORS: tuple[DreameBinarySensorDescription, ...] = (
    DreameBinarySensorDescription(
        key="problem",
        translation_key="problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value=lambda s, _c: s.activity == "error",
    ),
    DreameBinarySensorDescription(
        key="connectivity",
        translation_key="connectivity",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value=lambda s, _c: s.available,
    ),
    DreameBinarySensorDescription(
        key="push_connected",
        translation_key="push_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s, _c: s.connected,
    ),
    DreameBinarySensorDescription(
        key="charging",
        translation_key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value=lambda s, _c: s.charging,
    ),
    DreameBinarySensorDescription(
        key="docked",
        translation_key="docked",
        value=lambda s, _c: s.docked,
    ),
    DreameBinarySensorDescription(
        key="mowing",
        translation_key="mowing",
        value=lambda s, _c: s.activity == "mowing",
    ),
    DreameBinarySensorDescription(
        key="paused",
        translation_key="paused",
        value=lambda s, _c: s.activity == "paused",
    ),
    DreameBinarySensorDescription(
        key="returning",
        translation_key="returning",
        value=lambda s, _c: s.activity == "returning",
    ),
    DreameBinarySensorDescription(
        key="task_active",
        translation_key="task_active",
        device_class=BinarySensorDeviceClass.RUNNING,
        value=lambda s, _c: s.activity in ("mowing", "returning"),
    ),
    DreameBinarySensorDescription(
        key="rain_delay",
        translation_key="rain_delay",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s, _c: _flag(s.settings.get("WRP"), 3),
    ),
    DreameBinarySensorDescription(
        key="maintenance_due",
        translation_key="maintenance_due",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value=lambda s, _c: any(item.get("due") for item in s.maintenance),
    ),
    DreameBinarySensorDescription(
        key="maintenance_warning",
        translation_key="maintenance_warning",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s, _c: any(item.get("warning") for item in s.maintenance),
    ),
    DreameBinarySensorDescription(
        key="firmware_update_available",
        translation_key="firmware_update_available",
        device_class=BinarySensorDeviceClass.UPDATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value=lambda s, _c: bool(s.ota.get("update_available")),
    ),
)


def _flag(value: Any, index: int) -> bool:
    """Read one boolean slot out of a settings record."""
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, list) and len(value) > index:
        return bool(value[index])
    return False


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the binary sensor platform."""
    coordinator: DreameCoordinator = entry.runtime_data
    async_add_entities(
        DreameBinarySensor(coordinator, description, description.key)
        for description in BINARY_SENSORS
    )


class DreameBinarySensor(DreameEntity, BinarySensorEntity):
    """An on/off value derived from the mower snapshot."""

    entity_description: DreameBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Return whether the condition currently holds."""
        snapshot = self.snapshot
        if snapshot is None:
            return None
        return self.entity_description.value(snapshot, self.coordinator)
