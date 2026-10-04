"""Lawn mower entity for the Dreame Robot integration."""

from __future__ import annotations

from homeassistant.components.lawn_mower import (
    LawnMowerActivity,
    LawnMowerEntity,
    LawnMowerEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import DreameCoordinator
from .entity import build_device_info

#: Home Assistant has five activities; the mower's richer states collapse here.
ACTIVITY_MAP = {
    "mowing": LawnMowerActivity.MOWING,
    "paused": LawnMowerActivity.PAUSED,
    "returning": LawnMowerActivity.RETURNING,
    "error": LawnMowerActivity.ERROR,
    "docked": LawnMowerActivity.DOCKED,
    "idle": LawnMowerActivity.DOCKED,
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the lawn mower entity."""
    async_add_entities([DreameLawnMower(entry.runtime_data)])


class DreameLawnMower(LawnMowerEntity, CoordinatorEntity[DreameCoordinator]):
    """The primary control surface for one mower."""

    _attr_name = None
    _attr_has_entity_name = True
    _attr_supported_features = (
        LawnMowerEntityFeature.START_MOWING
        | LawnMowerEntityFeature.PAUSE
        | LawnMowerEntityFeature.DOCK
    )

    def __init__(self, coordinator: DreameCoordinator) -> None:
        super().__init__(coordinator)
        descriptor = coordinator.device.descriptor
        self._attr_unique_id = f"{descriptor.unique_id}_mower"
        self._attr_device_info = build_device_info(descriptor)

    @property
    def activity(self) -> LawnMowerActivity | None:
        """Return the current activity."""
        snapshot = self.coordinator.data
        if snapshot is None:
            return None
        return ACTIVITY_MAP.get(snapshot.activity, LawnMowerActivity.DOCKED)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose the detail the five Home Assistant activities cannot carry."""
        snapshot = self.coordinator.data
        if snapshot is None:
            return {}
        attributes: dict[str, object] = {
            # The map card resolves its own endpoint from this.
            "entry_id": self.coordinator.config_entry.entry_id,
            "state": snapshot.state,
            "state_code": snapshot.state_code,
            "task_status": snapshot.task_status,
            "mowing_mode": snapshot.mowing_mode,
            "battery_level": snapshot.battery_level,
            "charging": snapshot.charging,
            "docked": snapshot.docked,
            "error_code": snapshot.error.code if snapshot.error else None,
            "error_name": snapshot.error.name if snapshot.error else None,
            "error_tier": snapshot.error.tier if snapshot.error else None,
            "session_minutes": snapshot.session_minutes,
            "session_area_sqm": snapshot.session_area_sqm,
            "progress_percent": snapshot.progress_percent,
            "total_minutes": snapshot.total_minutes,
            "total_area_sqm": snapshot.total_area_sqm,
            "push_connected": snapshot.connected,
            "last_failure": self.coordinator.last_failure,
        }
        if snapshot.runtime:
            attributes["position_x"] = snapshot.runtime.x
            attributes["position_y"] = snapshot.runtime.y
            attributes["heading"] = snapshot.runtime.heading
        if snapshot.task:
            attributes["task_region_id"] = snapshot.task.region_id
            attributes["task_total_area_sqm"] = snapshot.task.total_area_sqm
            attributes["task_current_area_sqm"] = snapshot.task.current_area_sqm
        vector_map = self.coordinator.device.current_map
        if vector_map:
            attributes["map_name"] = vector_map.name
            attributes["map_total_area"] = vector_map.total_area
            attributes["zone_ids"] = [p.id for p in vector_map.zones]
            attributes["spot_ids"] = [p.id for p in vector_map.spots]
        attributes["map_ids"] = [m.map_id for m in self.coordinator.device.available_maps()]
        return attributes

    async def async_start_mowing(self) -> None:
        """Start or resume mowing the whole lawn."""
        await self._async_run("start_mowing")

    async def async_pause(self) -> None:
        """Pause the current task."""
        await self._async_run("pause")

    async def async_dock(self) -> None:
        """Send the mower back to its station."""
        await self._async_run("dock")

    async def _async_run(self, command: str) -> None:
        await self.hass.async_add_executor_job(getattr(self.coordinator.device, command))
        await self.coordinator.async_request_refresh()
