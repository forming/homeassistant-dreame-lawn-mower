"""Button entities for the Dreame Robot integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import DreameCoordinator
from .entity import DreameEntity


@dataclass(frozen=True, kw_only=True)
class DreameButtonDescription(ButtonEntityDescription):
    """Describe one pressable action on a mower."""

    command: str
    args: tuple[object, ...] = ()


BUTTONS: tuple[DreameButtonDescription, ...] = (
    DreameButtonDescription(
        key="stop",
        translation_key="stop",
        icon="mdi:stop-circle-outline",
        command="stop",
    ),
    DreameButtonDescription(
        key="locate",
        translation_key="locate",
        icon="mdi:map-marker-radius-outline",
        command="locate",
    ),
    DreameButtonDescription(
        key="clear_warning",
        translation_key="clear_warning",
        icon="mdi:alert-remove-outline",
        command="clear_warning",
        entity_registry_enabled_default=False,
    ),
    DreameButtonDescription(
        key="reset_maintenance_blade",
        translation_key="reset_maintenance_blade",
        icon="mdi:scissors-cutting",
        command="reset_maintenance",
        args=("blade",),
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    DreameButtonDescription(
        key="reset_maintenance_brush",
        translation_key="reset_maintenance_brush",
        icon="mdi:brush",
        command="reset_maintenance",
        args=("brush",),
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    DreameButtonDescription(
        key="reset_maintenance_robot",
        translation_key="reset_maintenance_robot",
        icon="mdi:robot-mower",
        command="reset_maintenance",
        args=("robot",),
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the button platform."""
    coordinator: DreameCoordinator = entry.runtime_data
    async_add_entities(
        DreameButton(coordinator, description, description.key) for description in BUTTONS
    )


class DreameButton(DreameEntity, ButtonEntity):
    """A one-shot action sent to the mower."""

    entity_description: DreameButtonDescription

    async def async_press(self) -> None:
        """Send the button's command to the mower."""
        await self._async_run(self.entity_description.command, *self.entity_description.args)
