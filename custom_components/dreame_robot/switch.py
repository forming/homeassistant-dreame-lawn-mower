"""Switch entities for the Dreame Robot integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import DeviceSnapshot
from .const import VOICE_PROMPT_GROUPS
from .coordinator import DreameCoordinator
from .entity import DreameEntity


def _slots(record: Any) -> list[Any]:
    """Return a settings record's payload list, whatever wrapper it arrived in."""
    if isinstance(record, dict):
        record = record.get("value")
    return list(record) if isinstance(record, list) else []


def _voice_flags(snapshot: DeviceSnapshot) -> dict[str, bool]:
    """Return each voice prompt group and whether it is enabled."""
    flags = _slots(snapshot.settings.get("VOICE"))
    return {
        name: bool(flags[index]) if index < len(flags) else False
        for index, (name, _) in enumerate(VOICE_PROMPT_GROUPS)
    }


def _write_voice(coordinator: DreameCoordinator, group: str, enabled: bool) -> None:
    """Return the full voice prompt payload with one group changed."""
    snapshot = coordinator.data
    flags = _voice_flags(snapshot) if snapshot else {}
    flags[group] = enabled
    return {name: flags.get(name, False) for name, _ in VOICE_PROMPT_GROUPS}


async def _async_write_rain(coordinator: DreameCoordinator, enabled: bool) -> None:
    """Persist the rain-protection toggle, keeping the delay already configured."""
    record = coordinator.data.settings.get("WRP") if coordinator.data else {}
    record = record if isinstance(record, dict) else {}
    await _run(
        coordinator,
        "set_rain_protection",
        enabled,
        int(record.get("time") or 6),
        int(record.get("sen", 3)),
    )


async def _async_write_charging(coordinator: DreameCoordinator, enabled: bool) -> None:
    """Persist the charging-window toggle, keeping its configured hours."""
    slots = _slots(coordinator.data.settings.get("BAT")) if coordinator.data else []
    start = int(slots[1]) if len(slots) > 1 else 0
    end = int(slots[2]) if len(slots) > 2 else 1439
    await _run(coordinator, "set_charging_period", enabled, start, end)


async def _async_write_voice(coordinator: DreameCoordinator, group: str, enabled: bool) -> None:
    """Persist one voice prompt toggle, keeping the other three as they are."""
    await _run(coordinator, "set_voice_prompts", _write_voice(coordinator, group, enabled))


async def _run(coordinator: DreameCoordinator, command: str, *args) -> None:
    """Run a device write, then refresh."""
    await coordinator.hass.async_add_executor_job(getattr(coordinator.device, command), *args)
    await coordinator.async_request_refresh()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the switch platform."""
    coordinator: DreameCoordinator = entry.runtime_data
    async_add_entities(
        [
            DreameRainSwitch(coordinator),
            DreameChargingWindowSwitch(coordinator),
            *(DreameVoiceSwitch(coordinator, group) for group, _ in VOICE_PROMPT_GROUPS),
        ]
    )


class _SettingSwitch(DreameEntity, SwitchEntity):
    """A mower setting gated on the device actually reporting its record."""

    _setting_key: str

    _setting_key: str = ""  # CFG record tag this switch depends on

    def __init__(
        self,
        coordinator: DreameCoordinator,
        description: SwitchEntityDescription,
        unique_suffix: str,
    ) -> None:
        super().__init__(coordinator, description, unique_suffix)

    @property
    def available(self) -> bool:
        """Hide the switch when the mower does not report this setting."""
        snapshot = self.snapshot
        return (
            super().available
            and snapshot is not None
            and (self._setting_key in snapshot.settings)
        )


class DreameRainSwitch(_SettingSwitch):
    """After-rain protection."""

    _setting_key = "WRP"

    _attr_translation_key = "rain_protection"
    _attr_icon = "mdi:weather-rainy"

    def __init__(self, coordinator: DreameCoordinator) -> None:
        super().__init__(
            coordinator,
            SwitchEntityDescription(key="rain_protection", translation_key="rain_protection"),
            "rain_protection",
        )

    @property
    def is_on(self) -> bool | None:
        snapshot = self.snapshot
        record = snapshot.settings.get("WRP") if snapshot else None
        return bool(record.get("value")) if isinstance(record, dict) else None

    async def async_turn_on(self, **kwargs) -> None:
        """Enable rain protection."""
        await _async_write_rain(self.coordinator, True)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable rain protection."""
        await _async_write_rain(self.coordinator, False)


class DreameChargingWindowSwitch(_SettingSwitch):
    """Restrict charging to a configured daily window."""

    _attr_translation_key = "charging_period"
    _attr_icon = "mdi:power-plug-outline"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _setting_key = "BAT"

    def __init__(self, coordinator: DreameCoordinator) -> None:
        super().__init__(
            coordinator,
            SwitchEntityDescription(key="charging_period", translation_key="charging_period"),
            "charging_period",
        )

    @property
    def is_on(self) -> bool | None:
        slots = _slots(self.snapshot.settings.get("BAT")) if self.snapshot else []
        return bool(slots[0]) if slots else None

    async def async_turn_on(self, **kwargs) -> None:
        """Enable the charging window."""
        await _async_write_charging(self.coordinator, True)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable the charging window."""
        await _async_write_charging(self.coordinator, False)


class DreameVoiceSwitch(_SettingSwitch):
    """One group of voice prompts."""

    _setting_key = "VOICE"

    def __init__(self, coordinator: DreameCoordinator, group: str) -> None:
        super().__init__(
            coordinator,
            SwitchEntityDescription(
                key=f"voice_prompt_{group}", translation_key=f"voice_prompt_{group}"
            ),
            f"voice_prompt_{group}",
        )
        self._group = group
        self._attr_icon = "mdi:account-voice"

    @property
    def is_on(self) -> bool | None:
        snapshot = self.snapshot
        return None if snapshot is None else _voice_flags(snapshot)[self._group]

    async def async_turn_on(self, **kwargs) -> None:
        """Enable this voice prompt group."""
        await _async_write_voice(self.coordinator, self._group, True)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable this voice prompt group."""
        await _async_write_voice(self.coordinator, self._group, False)
