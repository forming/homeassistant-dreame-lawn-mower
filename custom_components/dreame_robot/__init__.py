"""The Dreame Robot integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr

from .client import DeviceDescriptor, DreameDevice
from .client.exceptions import DreameAuthError, DreameError
from .config_flow import CONF_PASSWORD, CONF_USERNAME, stored_credentials
from .const import CONF_DID, CONF_MAC, CONF_MODEL, CONF_SCAN_INTERVAL, DOMAIN, PLATFORMS
from .coordinator import DreameCoordinator
from .map_view import MapJsonView
from .services import async_register

_LOGGER = logging.getLogger(__name__)

type DreameConfigEntry = ConfigEntry[DreameCoordinator]


def _descriptor(entry: ConfigEntry) -> DeviceDescriptor:
    """Rebuild the device descriptor stored in a config entry."""
    data = entry.data
    return DeviceDescriptor(
        did=str(data.get(CONF_DID, "")),
        model=str(data.get(CONF_MODEL, "")),
        mac=str(data.get(CONF_MAC, "")),
        name=str(data.get("device_name") or ""),
        host="",
        uid="",
        account_type=str(data.get("account_type", "dreame")),
        region=str(data.get("region", "eu")),
    )


async def async_setup_entry(hass: HomeAssistant, entry: DreameConfigEntry) -> bool:
    """Set up one mower from a config entry."""
    credentials = stored_credentials(entry)
    device = DreameDevice(
        _descriptor(entry),
        credentials[CONF_USERNAME],
        credentials[CONF_PASSWORD],
    )
    coordinator = DreameCoordinator(hass, entry, device)
    entry.runtime_data = coordinator

    try:
        await hass.async_add_executor_job(device.connect)
    except DreameAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except DreameError as err:
        _LOGGER.error("Could not reach the Dreame cloud for %s: %s", entry.title, err)
        return False

    await coordinator.async_config_entry_first_refresh()

    registry = dr.async_get(hass)
    registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device.descriptor.unique_id)},
        name=device.descriptor.title,
        manufacturer="Dreame" if device.descriptor.account_type == "dreame" else "MOVA",
        model=device.descriptor.display_model,
        sw_version=device.descriptor.firmware or None,
        serial_number=device.descriptor.mac or None,
        connections={(dr.CONNECTION_NETWORK_MAC, device.descriptor.mac)}
        if device.descriptor.mac
        else None,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_register(hass)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # The view resolves entries by id, so one registration serves every mower.
    if not hass.http.app.router.named_resources().get(MapJsonView.name):
        hass.http.register_view(MapJsonView())
    return True


async def _async_update_listener(hass: HomeAssistant, entry: DreameConfigEntry) -> None:
    """Apply option changes without a reload where possible."""
    coordinator = entry.runtime_data
    if CONF_SCAN_INTERVAL in entry.options:
        coordinator.apply_scan_interval(entry.options[CONF_SCAN_INTERVAL])
    if "map_rotation" in entry.options:
        coordinator.set_rotation(entry.options["map_rotation"])


async def async_unload_entry(hass: HomeAssistant, entry: DreameConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await hass.async_add_executor_job(entry.runtime_data.device.disconnect)
    return unloaded


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: DreameConfigEntry, device_entry: Any
) -> bool:
    """Refuse device removal from the UI; the mower lives in the cloud."""
    return False
