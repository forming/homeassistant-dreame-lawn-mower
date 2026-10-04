"""Services exposed by the Dreame Robot integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_CONTOUR_IDS,
    ATTR_ENTRY_ID,
    ATTR_ITEM,
    ATTR_MAP_INDEX,
    ATTR_ROTATION,
    ATTR_SPOT_IDS,
    ATTR_VELOCITY,
    ATTR_X,
    ATTR_Y,
    ATTR_ZONE_IDS,
    DOMAIN,
)
from .coordinator import DreameCoordinator
from .entity import run_on

_LOGGER = logging.getLogger(__name__)

#: Manual drive uses the vendor's -1000..1000 scale on both axes.
REMOTE_LIMIT = 1000

SERVICE_MOW_ZONES: str = "mow_zones"
SERVICE_MOW_SPOTS: str = "mow_spots"
SERVICE_MOW_EDGES: str = "mow_edges"
SERVICE_GO_TO: str = "go_to"
SERVICE_MOW_POINT: str = "mow_point"
SERVICE_SWITCH_MAP: str = "switch_map"
SERVICE_REMOTE_CONTROL: str = "remote_control"
SERVICE_STOP: str = "stop_mowing"
SERVICE_RESET_MAINTENANCE: str = "reset_maintenance"

MAINTENANCE_KEYS: dict[str, str] = {
    "blade": "blade",
    "brush": "brush",
    "robot": "robot",
}


def _bounded_int(limit: int = REMOTE_LIMIT) -> Callable[[Any], int]:
    """Return a validator for an integer in the vendor's remote-drive range."""
    return vol.All(
        vol.Coerce(int),
        vol.Range(min=-limit, max=limit),
    )


def _contour_ids(value: Any) -> list[list[int]]:
    """Validate contour ids given as ``[edge, index]`` pairs."""
    if not isinstance(value, list) or not value:
        raise vol.Invalid("At least one contour id pair is required.")
    pairs: list[list[int]] = []
    for item in value:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or any(isinstance(v, bool) or not isinstance(v, int) for v in item)
        ):
            raise vol.Invalid("Each contour id must be a two-item list of integers.")
        pairs.append([item[0], item[1]])
    return pairs


def _id_list(value: Any) -> list[int]:
    """Validate a non-empty list of non-negative map identifiers."""
    if not isinstance(value, list) or not value:
        raise vol.Invalid("At least one id is required.")
    ids: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise vol.Invalid("Map identifiers must be non-negative integers.")
        ids.append(item)
    return ids


SCHEMAS: dict[str, vol.Schema] = {
    SERVICE_MOW_ZONES: vol.Schema(
        {
            vol.Optional(ATTR_ENTRY_ID): cv.string,
            vol.Required(ATTR_ZONE_IDS): _id_list,
        }
    ),
    SERVICE_MOW_SPOTS: vol.Schema(
        {
            vol.Optional(ATTR_ENTRY_ID): cv.string,
            vol.Required(ATTR_SPOT_IDS): _id_list,
        }
    ),
    SERVICE_MOW_EDGES: vol.Schema(
        {
            vol.Optional(ATTR_ENTRY_ID): cv.string,
            vol.Required(ATTR_CONTOUR_IDS): _contour_ids,
        }
    ),
    SERVICE_GO_TO: vol.Schema(
        {
            vol.Optional(ATTR_ENTRY_ID): cv.string,
            vol.Required(ATTR_X): vol.Coerce(int),
            vol.Required(ATTR_Y): vol.Coerce(int),
        }
    ),
    SERVICE_MOW_POINT: vol.Schema(
        {
            vol.Optional(ATTR_ENTRY_ID): cv.string,
            vol.Required(ATTR_X): vol.Coerce(int),
            vol.Required(ATTR_Y): vol.Coerce(int),
            vol.Optional("passes", default=1): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=5)
            ),
        }
    ),
    SERVICE_SWITCH_MAP: vol.Schema(
        {
            vol.Optional(ATTR_ENTRY_ID): cv.string,
            vol.Required(ATTR_MAP_INDEX): vol.All(vol.Coerce(int), vol.Range(min=0)),
        }
    ),
    SERVICE_REMOTE_CONTROL: vol.Schema(
        {
            vol.Optional(ATTR_ENTRY_ID): cv.string,
            vol.Required(ATTR_VELOCITY): _bounded_int(),
            vol.Required(ATTR_ROTATION): _bounded_int(),
        }
    ),
    SERVICE_STOP: vol.Schema({vol.Optional(ATTR_ENTRY_ID): cv.string}),
    SERVICE_RESET_MAINTENANCE: vol.Schema(
        {
            vol.Optional(ATTR_ENTRY_ID): cv.string,
            vol.Required(ATTR_ITEM): vol.In(MAINTENANCE_KEYS),
        }
    ),
}


async def async_register(hass: HomeAssistant) -> None:
    """Register every service once."""
    if hass.services.has_service(DOMAIN, SERVICE_MOW_ZONES):
        return
    handlers: dict[str, Callable[[ServiceCall], Any]] = {
        SERVICE_MOW_ZONES: _mow_zones,
        SERVICE_MOW_SPOTS: _mow_spots,
        SERVICE_MOW_EDGES: _mow_edges,
        SERVICE_GO_TO: _go_to,
        SERVICE_MOW_POINT: _mow_point,
        SERVICE_SWITCH_MAP: _switch_map,
        SERVICE_REMOTE_CONTROL: _remote_control,
        SERVICE_STOP: _stop,
        SERVICE_RESET_MAINTENANCE: _reset_maintenance,
    }
    for name, schema in SCHEMAS.items():
        hass.services.async_register(DOMAIN, name, handlers[name], schema=schema)


def _loaded(hass: HomeAssistant) -> dict[str, DreameCoordinator]:
    """Return every currently loaded coordinator, keyed by entry id."""
    return {
        entry.entry_id: entry.runtime_data
        for entry in hass.config_entries.async_loaded_entries(DOMAIN)
    }


async def _mow_zones(call: ServiceCall) -> None:
    """Mow the given lawn zones."""
    ids = call.data[ATTR_ZONE_IDS]
    await run_on(_loaded(call.hass), call.data.get(ATTR_ENTRY_ID), "mow_zones", ids)


async def _mow_spots(call: ServiceCall) -> None:
    """Mow the given spot areas."""
    ids = call.data[ATTR_SPOT_IDS]
    await run_on(_loaded(call.hass), call.data.get(ATTR_ENTRY_ID), "mow_spots", ids)


async def _mow_edges(call: ServiceCall) -> None:
    """Mow the given map edges."""
    pairs = call.data[ATTR_CONTOUR_IDS]
    await run_on(_loaded(call.hass), call.data.get(ATTR_ENTRY_ID), "mow_contours", pairs)


async def _go_to(call: ServiceCall) -> None:
    """Drive the mower to a native map coordinate."""
    await run_on(
        _loaded(call.hass),
        call.data.get(ATTR_ENTRY_ID),
        "go_to",
        call.data[ATTR_X],
        call.data[ATTR_Y],
    )


async def _mow_point(call: ServiceCall) -> None:
    """Mow a small patch centred on a native map coordinate."""
    await run_on(
        _loaded(call.hass),
        call.data.get(ATTR_ENTRY_ID),
        "mow_point",
        call.data[ATTR_X],
        call.data[ATTR_Y],
        call.data["passes"],
    )


async def _switch_map(call: ServiceCall) -> None:
    """Make the mower work on a different stored map."""
    await run_on(
        _loaded(call.hass),
        call.data.get(ATTR_ENTRY_ID),
        "switch_map",
        call.data[ATTR_MAP_INDEX],
    )


async def _remote_control(call: ServiceCall) -> None:
    """Drive the mower manually for one step."""
    await run_on(
        _loaded(call.hass),
        call.data.get(ATTR_ENTRY_ID),
        "remote_control",
        call.data[ATTR_VELOCITY],
        call.data[ATTR_ROTATION],
    )


async def _stop(call: ServiceCall) -> None:
    """Stop the current task."""
    await run_on(_loaded(call.hass), call.data.get(ATTR_ENTRY_ID), "stop")


async def _reset_maintenance(call: ServiceCall) -> None:
    """Zero one maintenance counter."""
    item = MAINTENANCE_KEYS[call.data[ATTR_ITEM]]
    await run_on(
        _loaded(call.hass),
        call.data.get(ATTR_ENTRY_ID),
        "reset_maintenance",
        item,
    )
