"""Config flow for the Dreame Robot integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .client import DeviceDescriptor, DreameCloud
from .client.exceptions import DreameError
from .const import (
    CONF_ACCOUNT_TYPE,
    CONF_DEVICE_NAME,
    CONF_DID,
    CONF_MAC,
    CONF_MAP_ROTATION,
    CONF_MODEL,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    DEFAULT_MAP_ROTATION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAP_ROTATION_CHOICES,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_DEVICE = "device"

ACCOUNT_LABELS: dict[str, str] = {"dreame": "Dreamehome", "mova": "MOVAhome"}
REGION_LABELS: dict[str, str] = {
    "eu": "Europe",
    "us": "United States",
    "cn": "China",
    "ru": "Russia",
    "sg": "Singapore",
}


def credential_schema(defaults: Mapping[str, Any] | None = None) -> vol.Schema:
    """Return the account-credential form, echoing any known values."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_ACCOUNT_TYPE, default=defaults.get(CONF_ACCOUNT_TYPE, "dreame")
            ): SelectSelector(
                SelectSelectorConfig(
                    options=list(ACCOUNT_LABELS),
                    translation_key=CONF_ACCOUNT_TYPE,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_REGION, default=defaults.get(CONF_REGION, "eu")): SelectSelector(
                SelectSelectorConfig(
                    options=list(REGION_LABELS),
                    translation_key=CONF_REGION,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): str,
        }
    )


async def async_discover_devices(
    username: str, password: str, region: str, account_type: str
) -> list[DeviceDescriptor]:
    """Log in once and return every mower bound to the account."""
    cloud = DreameCloud(username, password, region, account_type)
    return await _executor(cloud.list_devices)


def error_key(err: Exception) -> str:
    """Map a client error onto a config-flow error key."""
    message = str(err).lower()
    if "region" in message or "unsupported" in message:
        return "invalid_region"
    if any(
        word in message
        for word in ("connect", "dns", "host", "network", "ssl", "timeout", "timed out")
    ):
        return "cannot_connect"
    return "cannot_auth"


async def _executor(func, *args):
    """Run a blocking client call off the event loop."""
    return await asyncio.get_running_loop().run_in_executor(None, lambda: func(*args))


class DreameConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle account sign-in and mower selection."""

    VERSION = 1

    def __init__(self) -> None:
        self._devices: list[DeviceDescriptor] = []
        self._credentials: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Collect credentials and discover the account's mowers."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._devices = await async_discover_devices(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    user_input[CONF_REGION],
                    user_input[CONF_ACCOUNT_TYPE],
                )
            except ValueError as err:
                _LOGGER.warning("Rejected configuration: %s", err)
                errors["base"] = "invalid_region"
            except DreameError as err:
                _LOGGER.debug("Cloud sign-in failed: %s", err)
                errors["base"] = error_key(err)
            else:
                if not self._devices:
                    errors["base"] = "no_devices"
                else:
                    self._credentials = user_input
                    if len(self._devices) == 1:
                        return await self._create_entry(self._devices[0])
                    return await self.async_step_device()

        return self.async_show_form(
            step_id="user", data_schema=credential_schema(), errors=errors
        )

    async def async_step_device(self, user_input: dict[str, Any] | None = None):
        """Pick one mower when the account has several."""
        if user_input is not None:
            chosen = next(
                (d for d in self._devices if d.unique_id == user_input[CONF_DEVICE]), None
            )
            if chosen is not None:
                return await self._create_entry(chosen)

        titles: dict[str, str] = {}
        for device in self._devices:
            title = device.title
            if title in titles.values():
                title = f"{title} - {device.unique_id}"
            titles[device.unique_id] = title
        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DEVICE, default=self._devices[0].unique_id
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": uid, "label": label} for uid, label in titles.items()
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def _create_entry(self, device: DeviceDescriptor):
        """Store one mower as a config entry."""
        await self.async_set_unique_id(device.unique_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=device.title,
            data={
                CONF_ACCOUNT_TYPE: self._credentials[CONF_ACCOUNT_TYPE],
                CONF_REGION: self._credentials[CONF_REGION],
                CONF_DID: device.did,
                CONF_MAC: device.mac,
                CONF_MODEL: device.model,
                CONF_DEVICE_NAME: device.name,
                CONF_USERNAME: self._credentials[CONF_USERNAME],
                CONF_PASSWORD: self._credentials[CONF_PASSWORD],
            },
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]):
        """Re-ask for credentials after the cloud rejects the stored session."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        """Verify fresh credentials, then reload the existing entry."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                devices = await async_discover_devices(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    user_input[CONF_REGION],
                    user_input[CONF_ACCOUNT_TYPE],
                )
            except ValueError as err:
                _LOGGER.warning("Rejected configuration: %s", err)
                errors["base"] = "invalid_region"
            except DreameError as err:
                errors["base"] = error_key(err)
            else:
                if not any(d.did == entry.data.get(CONF_DID) for d in devices):
                    errors["base"] = "no_devices"
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={
                            CONF_ACCOUNT_TYPE: user_input[CONF_ACCOUNT_TYPE],
                            CONF_REGION: user_input[CONF_REGION],
                            CONF_USERNAME: user_input[CONF_USERNAME],
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                        },
                    )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=credential_schema(
                {
                    CONF_ACCOUNT_TYPE: entry.data.get(CONF_ACCOUNT_TYPE),
                    CONF_REGION: entry.data.get(CONF_REGION),
                    CONF_USERNAME: entry.data.get(CONF_USERNAME),
                }
            ),
            errors=errors,
            description_placeholders={"name": entry.title},
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> DreameOptionsFlow:
        """Return the options flow."""
        return DreameOptionsFlow()


class DreameOptionsFlow(OptionsFlow):
    """Polling interval and map display options."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Show and store the integration options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    ),
                    vol.Required(
                        CONF_MAP_ROTATION,
                        default=options.get(CONF_MAP_ROTATION, DEFAULT_MAP_ROTATION),
                    ): vol.In(MAP_ROTATION_CHOICES),
                }
            ),
        )


def stored_credentials(entry: ConfigEntry) -> dict[str, str]:
    """Return the credential fields stored in a config entry."""
    return {
        CONF_USERNAME: entry.data.get(CONF_USERNAME, ""),
        CONF_PASSWORD: entry.data.get(CONF_PASSWORD, ""),
        CONF_REGION: entry.data.get(CONF_REGION, "eu"),
        CONF_ACCOUNT_TYPE: entry.data.get(CONF_ACCOUNT_TYPE, "dreame"),
    }


__all__ = [
    "DreameConfigFlow",
    "DreameOptionsFlow",
    "async_discover_devices",
    "credential_schema",
    "stored_credentials",
    "error_key",
]
