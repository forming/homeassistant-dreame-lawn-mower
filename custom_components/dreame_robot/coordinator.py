"""Data update coordinator for the Dreame Robot integration."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import DeviceSnapshot, DreameDevice
from .const import (
    CONF_MAP_ROTATION,
    CONF_SCAN_INTERVAL,
    DEFAULT_MAP_ROTATION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

#: Push messages arrive from the MQTT thread. Several usually land together, so
#: they are coalesced into one coordinator update.
PUSH_DEBOUNCE_SECONDS = 0.5
#: How long a stale snapshot stays readable after the cloud starts failing.
STALE_GRACE_SECONDS = 300.0


class DreameCoordinator(DataUpdateCoordinator[DeviceSnapshot]):
    """Polls the mower and publishes push updates onto the event loop."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device: DreameDevice) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.device = device
        self._push_lock = asyncio.Lock()
        self._push_pending = False
        self.last_failure: str | None = None
        self.last_success_at: float | None = None
        self._rotation: int = 0
        self.stale_since: float | None = None
        self.set_rotation(entry.options.get(CONF_MAP_ROTATION, DEFAULT_MAP_ROTATION))
        device.on_update = self._handle_push

    # -- polling ------------------------------------------------------------

    async def _async_update_data(self) -> DeviceSnapshot:
        """Read device state, keeping the last good data while the cloud is down."""
        try:
            snapshot = await self.hass.async_add_executor_job(self.device.poll)
        except Exception as err:  # noqa: BLE001 - reported through UpdateFailed
            now = time.monotonic()
            self.last_failure = str(err)
            self.stale_since = self.stale_since or now
            if self.data is not None and now - self.stale_since < STALE_GRACE_SECONDS:
                _LOGGER.debug("Keeping last known mower data after a failed poll: %s", err)
                return self.data
            raise UpdateFailed(f"Could not reach the Dreame cloud: {err}") from err

        self.last_failure = None
        self.stale_since = None
        self.last_success_at = time.monotonic()
        return snapshot

    # -- push ---------------------------------------------------------------

    def _handle_push(self) -> None:
        """Bridge a push notification from the MQTT thread onto the loop."""
        self.hass.loop.call_soon_threadsafe(self._schedule_push)

    def _schedule_push(self) -> None:
        if self._push_pending:
            return
        self._push_pending = True
        self.hass.async_create_task(self._async_push(), f"{DOMAIN}-push-update")

    async def _async_push(self) -> None:
        """Publish the cached snapshot; push handling performs no I/O."""
        async with self._push_lock:
            self._push_pending = False
            try:
                snapshot = self.device.snapshot()
            except Exception:  # noqa: BLE001 - never kill the push loop
                _LOGGER.debug("Ignoring push update failure", exc_info=True)
                return
        self.async_set_updated_data(snapshot)

    # -- options ------------------------------------------------------------

    @property
    def rotation(self) -> int:
        """Return the configured map display rotation in degrees."""
        return self._rotation

    def set_rotation(self, degrees: int) -> None:
        """Apply the configured map display rotation."""
        self._rotation = degrees if degrees in (0, 90, 180, 270) else 0
        self.device.set_rotation(self._rotation)

    def apply_scan_interval(self, seconds: int) -> None:
        """Apply a new polling interval without reloading the entry."""
        self.update_interval = timedelta(seconds=seconds)
