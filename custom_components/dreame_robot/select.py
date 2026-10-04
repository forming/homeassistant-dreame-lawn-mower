"""Select entities for the Dreame Robot integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_MAP_ROTATION, MAP_ROTATION_CHOICES
from .coordinator import DreameCoordinator
from .entity import DreameEntity


def _rotation_labels() -> list[str]:
    """Return the map rotation options as display labels."""
    return [f"{degrees}°" for degrees in MAP_ROTATION_CHOICES]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the select platform."""
    coordinator: DreameCoordinator = entry.runtime_data
    async_add_entities([DreameMapSelect(coordinator), DreameMapRotationSelect(coordinator)])


class DreameMapSelect(DreameEntity, SelectEntity):
    """Choose which stored map the mower should work on."""

    _attr_translation_key = "map"
    _attr_icon = "mdi:map-multiple"

    def __init__(self, coordinator: DreameCoordinator) -> None:
        super().__init__(
            coordinator,
            SelectEntityDescription(key="map", translation_key="map"),
            "map",
        )

    @property
    def _summaries(self):
        return self.coordinator.device.available_maps()

    @property
    def options(self) -> list[str]:
        """Return one label per stored map."""
        return [m.name or f"Map {m.map_index + 1}" for m in self._summaries]

    @property
    def current_option(self) -> str | None:
        """Return the label of the map in use."""
        vector_map = self.coordinator.device.current_map
        if vector_map is None:
            return None
        for summary in self._summaries:
            if summary.map_id == vector_map.map_id:
                return summary.name or f"Map {summary.map_index + 1}"
        return None

    @property
    def available(self) -> bool:
        """Only offer this when the mower has more than one map."""
        return len(self._summaries) > 1

    async def async_select_option(self, option: str) -> None:
        """Tell the mower to switch to the chosen map."""
        match = next(
            (m for m in self._summaries if (m.name or f"Map {m.map_index + 1}") == option),
            None,
        )
        if match is None:
            raise ValueError(f"Unknown map: {option}")
        await self._async_run("switch_map", match.map_index)


class DreameMapRotationSelect(DreameEntity, SelectEntity):
    """Rotate the rendered map without touching the mower."""

    _attr_translation_key = "map_rotation"
    _attr_icon = "mdi:rotate-90-degrees-counterclockwise"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: DreameCoordinator) -> None:
        super().__init__(
            coordinator,
            SelectEntityDescription(key="map_rotation", translation_key="map_rotation"),
            "map_rotation",
        )

    @property
    def options(self) -> list[str]:
        """Return the available rotations."""
        return _rotation_labels()

    @property
    def current_option(self) -> str:
        """Return the active rotation."""
        return f"{self.coordinator.rotation}°"

    async def async_select_option(self, option: str) -> None:
        """Store the rotation as an entry option."""
        degrees = int(option.rstrip("°"))
        self.coordinator.set_rotation(degrees)
        self.hass.config_entries.async_update_entry(
            self.coordinator.config_entry,
            options={**self.coordinator.config_entry.options, CONF_MAP_ROTATION: degrees},
        )
