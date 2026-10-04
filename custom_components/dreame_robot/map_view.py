"""HTTP view serving map geometry to the Lovelace map card."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntryState

from .const import DOMAIN
from .coordinator import DreameCoordinator

_LOGGER = logging.getLogger(__name__)

#: Geometry above this many points is refused so a corrupt map cannot stall the
#: event loop while it is serialized.
MAX_POINTS = 20000


class MapJsonView(HomeAssistantView):
    """Serve the current map, live pose and travel trail as JSON.

    One view handles every configured mower; the entry id selects which. That
    keeps registration idempotent across entry setup and unload.
    """

    requires_auth = True
    name = f"api:{DOMAIN}:map"
    url = f"/api/{DOMAIN}/{{entry_id}}/map.json"

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        """Return the map payload for one mower."""
        entry = request.app["hass"].config_entries.async_get_entry(entry_id)
        if entry is None or entry.state is not ConfigEntryState.LOADED:
            raise web.HTTPNotFound()
        coordinator: DreameCoordinator = entry.runtime_data

        snapshot = coordinator.data
        if snapshot is None:
            raise web.HTTPServiceUnavailable(text="No mower data yet")

        device = coordinator.device
        vector_map = device.current_map
        projection = device.map_projection()
        scene = device.scene()

        payload: dict[str, Any] = {
            "entry_id": entry_id,
            "title": snapshot.descriptor.title,
            "model": snapshot.descriptor.display_model,
            "activity": snapshot.activity,
            "battery_level": snapshot.battery_level,
            "charging": snapshot.charging,
            "error": snapshot.error.name if snapshot.error else None,
            "error_tier": snapshot.error.tier if snapshot.error else None,
            "available": bool(
                vector_map is not None and vector_map.usable and snapshot.available
            ),
            "rotation": projection.rotation if projection else 0,
        }

        if vector_map is not None and projection is not None:
            payload.update(
                {
                    "canvas": {"width": projection.width, "height": projection.height},
                    "projection": projection.as_dict(),
                    "boundary": list(vector_map.boundary),
                    "name": vector_map.name,
                    "total_area": vector_map.total_area,
                    "zones": [_polygon(projection, p) for p in vector_map.zones],
                    "forbidden": [_polygon(projection, p) for p in vector_map.forbidden],
                    "spots": [_polygon(projection, p) for p in vector_map.spots],
                    "contours": [_polygon(projection, p) for p in vector_map.contours],
                    "paths": [
                        {"id": path.id, "points": _points(projection, path.points)}
                        for path in vector_map.paths
                    ],
                    "points": _points(projection, vector_map.points),
                    "maps": [
                        {
                            "id": m.map_id,
                            "index": m.map_index,
                            "name": m.name,
                            "total_area": m.total_area,
                        }
                        for m in device.available_maps()
                    ],
                }
            )
            if scene and scene.runtime:
                payload["robot"] = {
                    "x": scene.runtime.x,
                    "y": scene.runtime.y,
                    "heading": scene.runtime.heading,
                    "native": list(projection.point(scene.runtime.x, scene.runtime.y)),
                }
            if scene:
                payload["trail"] = [
                    _points(projection, segment) for segment in scene.trail if len(segment) > 1
                ]

        return self.json(payload)


def _points(projection, points) -> list[list[int]]:
    """Project a polyline to canvas pixels."""
    if len(points) > MAX_POINTS:
        # The mower, not the caller, produced this geometry. Fail loudly instead
        # of letting a corrupt map lock up the event loop while serializing.
        _LOGGER.error(
            "Map geometry has %d points, refusing to serve more than %d",
            len(points),
            MAX_POINTS,
        )
        raise web.HTTPInternalServerError(text="Map geometry is too large to serve")
    return [[x, y] for x, y in projection.polygon(points)]


def _polygon(projection, poly) -> dict[str, Any]:
    """Project one map polygon, keeping its native id for follow-up commands."""
    return {
        "id": poly.id,
        "kind": poly.kind,
        "name": poly.name or str(poly.id),
        "area": poly.area,
        "native_center": [round(poly.center[0]), round(poly.center[1])],
        "points": _points(projection, poly.points),
    }
