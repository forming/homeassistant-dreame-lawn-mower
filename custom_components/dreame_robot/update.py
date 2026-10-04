"""Firmware update entity for the Dreame Robot integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import DreameCoordinator
from .entity import build_device_info

#: The mower offers no progress feedback, so an install is assumed to take this
#: long before the UI offers a retry.
INSTALL_ASSUMED_DURATION = timedelta(hours=24)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the update platform."""
    async_add_entities([DreameFirmwareUpdate(entry.runtime_data)])


class DreameFirmwareUpdate(UpdateEntity, CoordinatorEntity[DreameCoordinator]):
    """Firmware availability and installation for one mower."""

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = UpdateEntityFeature.INSTALL
    _attr_entity_category = EntityCategory.CONFIG
    _attr_name = None
    _attr_has_entity_name = True

    def __init__(self, coordinator: DreameCoordinator) -> None:
        super().__init__(coordinator)
        descriptor = coordinator.device.descriptor
        self._attr_unique_id = f"{descriptor.unique_id}_firmware"
        self._attr_device_info = build_device_info(descriptor)
        self._attr_installed_version = descriptor.firmware or None

    @property
    def _ota(self) -> dict[str, object]:
        snapshot = self.coordinator.data
        return dict(snapshot.ota) if snapshot else {}

    @property
    def available(self) -> bool:
        """Only offered once the cloud has reported a firmware version."""
        return super().available and bool(self._ota)

    @property
    def installed_version(self) -> str | None:
        """Return the version the mower is running."""
        return str(self._ota.get("current_version") or "") or self._attr_installed_version

    @property
    def latest_version(self) -> str | None:
        """Return the version the vendor offers."""
        latest = self._ota.get("latest_version")
        return str(latest) if latest else None

    @property
    def in_progress(self) -> bool:
        """Assume an install is still running for a day, since there is no signal."""
        if self.latest_version is None or self.latest_version == self.installed_version:
            return False
        return self.coordinator.data is not None and bool(self._ota.get("installing"))

    async def async_install(self, version: str | None, backup: bool, **kwargs) -> None:
        """Ask the mower to apply its firmware update."""
        await self.hass.async_add_executor_job(self.coordinator.device.install_firmware)
        self._ota["installing"] = True
        self._attr_installed_version = version
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
