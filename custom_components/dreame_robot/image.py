"""Image entity rendering the mower's map."""

from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .coordinator import DreameCoordinator
from .entity import build_device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the map image entity."""
    async_add_entities([DreameMapImage(entry.runtime_data)])


class DreameMapImage(ImageEntity, CoordinatorEntity[DreameCoordinator]):
    """A PNG render of the current map, with the mower drawn on it.

    The interactive card polls the JSON endpoint instead; this entity exists so
    the map also works in the standard picture-entity and floorplan cards.
    """

    _attr_translation_key = "map"
    _attr_content_type = "image/png"
    _attr_name = None
    _attr_has_entity_name = True
    # The map must be redrawn as the mower moves, so opt into polling.
    _attr_should_poll = True

    def __init__(self, coordinator: DreameCoordinator) -> None:
        ImageEntity.__init__(self, coordinator.hass)
        CoordinatorEntity.__init__(self, coordinator)
        descriptor = coordinator.device.descriptor
        self._attr_unique_id = f"{descriptor.unique_id}_map"
        self._attr_device_info = build_device_info(descriptor)
        if coordinator.device.current_map is not None:
            self._attr_image_last_updated = dt_util.utcnow()

    @property
    def available(self) -> bool:
        """Return whether a map has been downloaded."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.coordinator.device.current_map is not None
        )

    def image(self) -> bytes | None:
        """Render the map; Home Assistant runs this in an executor job."""
        return self.coordinator.device.map_png()

    def _handle_coordinator_update(self) -> None:
        """Invalidate the cached PNG so the next read re-renders the map."""
        self._cached_image = None
        if self.coordinator.data is not None:
            self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose the projection so other cards can overlay coordinates."""
        vector_map = self.coordinator.device.current_map
        projection = self.coordinator.device.map_projection()
        if vector_map is None or projection is None:
            return {}
        entry_id = self.coordinator.config_entry.entry_id
        return {
            "map_name": vector_map.name,
            "map_id": vector_map.map_id,
            "map_total_area": vector_map.total_area,
            "zone_count": len(vector_map.zones),
            "forbidden_count": len(vector_map.forbidden),
            "spot_count": len(vector_map.spots),
            "rotation": projection.rotation,
            "canvas_width": projection.width,
            "canvas_height": projection.height,
            "map_json_url": f"/api/dreame_robot/{entry_id}/map.json",
        }
