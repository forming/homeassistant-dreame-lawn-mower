"""Fixtures that stand in for a real mower on the vendor cloud."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dreame_robot.client import DeviceSnapshot, DreameDevice
from custom_components.dreame_robot.client.device import MAINTENANCE_ITEMS, _decode_map_batch
from custom_components.dreame_robot.client.models import RuntimeTelemetry, TaskTelemetry
from custom_components.dreame_robot.const import DOMAIN
from tests.fixture_data import (
    MOCK_CONFIG_ENTRY_DATA,
    MOCK_DESCRIPTOR,
    build_batch_payload,
)

COMMANDS = (
    "start_mowing",
    "pause",
    "stop",
    "dock",
    "locate",
    "clear_warning",
    "mow_zones",
    "mow_spots",
    "mow_contours",
    "mow_point",
    "go_to",
    "switch_map",
    "remote_control",
    "remote_control_stop",
    "set_volume",
    "set_rain_protection",
    "set_charging_period",
    "set_voice_prompts",
    "reset_maintenance",
    "install_firmware",
)


class FakeDevice(DreameDevice):
    """A device that answers from canned data instead of the cloud.

    Every command it receives is recorded in :attr:`commands` so tests can assert
    on what the Home Assistant layer asked the mower to do.
    """

    def __init__(self, descriptor, username, password, **kwargs) -> None:
        super().__init__(descriptor, username, password, **kwargs)
        self.commands: list[tuple[str, tuple, dict]] = []
        self.batch: dict[str, str] = build_batch_payload()
        self.properties: dict[str, Any] = {
            "2.1": 1,
            "2.2": -1,
            "3.1": 82,
            "3.2": True,
            "4.1": True,
            "4.17": False,
            "4.23": 0,
            "4.2": 42,
            "4.3": 61.5,
            "4.63": 35.0,
            "12.2": 5120,
            "12.4": 2310.5,
            "4.14": "SN-12345678",
        }
        self.settings_data: dict[str, Any] = {
            "VOL": {"value": 40},
            "WRP": {"value": 1, "time": 6, "sen": 3},
            "BAT": {"value": [1, 60, 1140]},
            "VOICE": {"value": [1, 1, 0, 1]},
        }
        self.maintenance_data: list[int] = [0, 15000, 3300]
        self.ota_data: dict[str, Any] = {
            "current_version": "4.3.6_0320",
            "latest_version": "4.3.7_0101",
            "update_available": True,
        }
        self.fail_polls = False
        for name in COMMANDS:
            setattr(self, name, self._recorder(name))

    def _recorder(self, name: str):
        """Return a stand-in for one device command that records its call."""

        def call(*args, **kwargs):
            self.commands.append((name, args, kwargs))
            return {"r": 0, "d": {}}

        return call

    # -- network-free overrides --------------------------------------------

    def connect(self) -> None:
        """Pretend login and broker discovery both succeeded."""
        self._available = True
        self._connected = True

    def disconnect(self) -> None:
        """Pretend the push channel closed."""
        self._connected = False

    def poll(self, *, refresh_map: bool | None = None) -> DeviceSnapshot:
        """Return a snapshot built from the canned values."""
        if self.fail_polls:
            from custom_components.dreame_robot.client.exceptions import (
                DreameConnectionError,
            )

            raise DreameConnectionError("cloud unreachable")
        with self._lock:
            self._properties.update(self.properties)
            self._available = True
            if not self._maps or refresh_map is not False:
                self._maps = _decode_map_batch(self.batch)
                self._maps_fetched_at = time.monotonic()
            self._settings = self.settings_data
            self._maintenance = self.maintenance()
            self._ota = dict(self.ota_data)
        return self.snapshot()

    def maintenance(self):
        """Return remaining life per counter, from the canned values."""
        items = []
        for key, name, index, total in MAINTENANCE_ITEMS:
            used = self.maintenance_data[index]
            percent = round(max(0.0, (total - used) / total * 100), 1)
            items.append(
                {
                    "key": key,
                    "name": name,
                    "used_minutes": used,
                    "total_minutes": total,
                    "remaining_minutes": max(0, total - used),
                    "remaining_percent": percent,
                    "due": percent <= 0,
                    "warning": percent <= 20.0,
                }
            )
        return tuple(items)

    def push_runtime(self, x: int, y: int, heading: float) -> None:
        """Inject a runtime pose as if it had arrived over MQTT."""
        with self._lock:
            self._runtime = RuntimeTelemetry(x=x, y=y, heading=heading)
            self._runtime_task = TaskTelemetry(
                region_id=1,
                task_id=2,
                progress_percent=50.0,
                current_area_sqm=20.0,
                total_area_sqm=40.0,
            )
            self._available = True

    def push_property(self, key: str, value: Any) -> None:
        """Inject a property value as if it had arrived over MQTT."""
        with self._lock:
            self._properties[key] = value
            self._available = True


@pytest.fixture
def fake_device() -> FakeDevice:
    """Return a network-free device client."""
    return FakeDevice(
        MOCK_DESCRIPTOR,
        MOCK_CONFIG_ENTRY_DATA["username"],
        MOCK_CONFIG_ENTRY_DATA["password"],
    )


@pytest.fixture
def mock_entry() -> MockConfigEntry:
    """Return an unsaved config entry for the mocked mower."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Back garden",
        data=MOCK_CONFIG_ENTRY_DATA,
        options={},
        unique_id="1234567890",
    )


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant, mock_entry: MockConfigEntry, fake_device: FakeDevice
) -> MockConfigEntry:
    """Set up the integration with the fake device injected."""
    mock_entry.add_to_hass(hass)
    with patch("custom_components.dreame_robot.DreameDevice", return_value=fake_device):
        assert await hass.config_entries.async_setup(mock_entry.entry_id)
        await hass.async_block_till_done()
    return mock_entry


@pytest.fixture
def mowers(hass: HomeAssistant, setup_integration: MockConfigEntry) -> list[str]:
    """Return the unique ids of the mower entities."""
    return [
        state.entity_id
        for state in hass.states.async_all()
        if state.entity_id.endswith("_mower")
    ]
