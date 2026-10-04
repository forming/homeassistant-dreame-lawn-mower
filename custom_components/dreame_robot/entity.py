"""Entity base class for the Dreame Robot integration."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import DeviceDescriptor, DeviceSnapshot
from .const import DOMAIN
from .coordinator import DreameCoordinator


def build_device_info(descriptor: DeviceDescriptor) -> DeviceInfo:
    """Return the device registry entry shared by every entity of a mower."""
    return DeviceInfo(
        identifiers={(DOMAIN, descriptor.unique_id)},
        # The device name feeds every entity id, so keep it short and let the
        # model surface in its own registry field instead.
        name=descriptor.name or descriptor.display_model,
        manufacturer="MOVA" if descriptor.account_type == "mova" else "Dreame",
        model=descriptor.display_model,
        sw_version=descriptor.firmware or None,
        serial_number=descriptor.mac or None,
    )


class DreameEntity(CoordinatorEntity[DreameCoordinator]):
    """Shared behaviour for every entity backed by a mower snapshot."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DreameCoordinator,
        description: EntityDescription,
        unique_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device.descriptor.unique_id}_{unique_suffix}"
        self._attr_device_info = build_device_info(coordinator.device.descriptor)

    @property
    def snapshot(self) -> DeviceSnapshot | None:
        """Return the latest device snapshot, if one has been read."""
        return self.coordinator.data

    @property
    def device(self) -> Any:
        """Return the protocol client for this mower."""
        return self.coordinator.device

    async def _async_run(self, command: str, *args: Any, **kwargs: Any) -> None:
        """Run one blocking device command, then refresh the snapshot."""
        await self.hass.async_add_executor_job(getattr(self.device, command), *args, **kwargs)
        await self.coordinator.async_request_refresh()


async def run_on(
    hass_devices: dict[str, DreameCoordinator],
    entry_id: str | None,
    command: str,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Run a device command against one entry, or all of them."""

    if entry_id is None:
        targets = list(hass_devices.values())
    elif entry_id in hass_devices:
        targets = [hass_devices[entry_id]]
    else:
        raise ServiceValidationError(f"Unknown {DOMAIN} entry: {entry_id}")

    loop = asyncio.get_running_loop()
    for coordinator in targets:
        await loop.run_in_executor(None, getattr(coordinator.device, command), *args, **kwargs)
        await coordinator.async_request_refresh()
