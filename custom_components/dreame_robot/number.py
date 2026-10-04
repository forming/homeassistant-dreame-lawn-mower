"""Number entities for the Dreame Robot integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import (
    DEFAULT_MAX_VALUE,
    DEFAULT_MIN_VALUE,
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import DreameCoordinator
from .entity import DreameEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the number platform."""
    coordinator: DreameCoordinator = entry.runtime_data
    async_add_entities([DreameVolume(coordinator), DreameRainDelay(coordinator)])


class DreameVolume(DreameEntity, NumberEntity):
    """Voice prompt volume."""

    _attr_translation_key = "voice_volume"
    _attr_icon = "mdi:volume-high"
    _attr_native_min_value = DEFAULT_MIN_VALUE
    _attr_native_max_value = DEFAULT_MAX_VALUE
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = NumberDeviceClass.VOLUME
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: DreameCoordinator) -> None:
        super().__init__(
            coordinator,
            EntityDescription(key="voice_volume", translation_key="voice_volume"),
            "volume",
        )

    @property
    def available(self) -> bool:
        """Only offered when the mower reports a volume setting."""
        snapshot = self.snapshot
        return super().available and snapshot is not None and "VOL" in snapshot.settings

    @property
    def native_value(self) -> float | None:
        """Return the configured volume."""
        snapshot = self.snapshot
        if snapshot is None:
            return None
        value = snapshot.settings.get("VOL")
        if isinstance(value, dict):
            value = value.get("value")
        return float(value) if isinstance(value, int | float) else None

    async def async_set_native_value(self, value: float) -> None:
        """Write the new volume to the mower."""
        await self._async_run("set_volume", int(value))


class DreameRainDelay(DreameEntity, NumberEntity):
    """Hours the mower waits after rain before resuming."""

    _attr_translation_key = "rain_delay_hours"
    _attr_icon = "mdi:weather-pouring"
    _attr_native_min_value = 0
    _attr_native_max_value = 24
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "h"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: DreameCoordinator) -> None:
        super().__init__(
            coordinator,
            EntityDescription(key="rain_delay_hours", translation_key="rain_delay_hours"),
            "rain_delay",
        )

    @property
    def available(self) -> bool:
        """Only offered when the mower reports the rain-protection setting."""
        snapshot = self.snapshot
        return super().available and snapshot is not None and "WRP" in snapshot.settings

    @property
    def native_value(self) -> float | None:
        """Return the configured delay in hours."""
        record = self._record
        hours = record.get("time")
        return float(hours) if isinstance(hours, int | float) else None

    @property
    def _record(self) -> dict[str, Any]:
        """Return the raw rain-protection record, whatever shape it arrived in."""
        snapshot = self.snapshot
        record = snapshot.settings.get("WRP") if snapshot else None
        if isinstance(record, dict):
            return record
        if isinstance(record, list) and len(record) > 1:
            sensitivity = record[2] if len(record) > 2 else 3
            return {"value": record[0], "time": record[1], "sen": sensitivity}
        return {}

    async def async_set_native_value(self, value: float) -> None:
        """Write the new delay, preserving the enabled flag and sensitivity."""
        record = self._record
        await self._async_run(
            "set_rain_protection",
            int(bool(record.get("value"))),
            int(value),
            int(record.get("sen", 3)),
        )
