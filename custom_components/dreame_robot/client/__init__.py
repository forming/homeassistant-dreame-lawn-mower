"""Protocol client for Dreame and MOVA robotic lawn mowers.

Free of Home Assistant imports so it can be tested and reused standalone.
"""

from .cloud import DreameCloud
from .device import DeviceSnapshot, DreameDevice
from .exceptions import (
    DreameApiError,
    DreameAuthError,
    DreameCommandRejectedError,
    DreameConnectionError,
    DreameError,
)
from .models import DeviceDescriptor, MapScene, MapSummary, Polygon, VectorMap
from .render import render_scene

__all__ = [
    "DeviceDescriptor",
    "DeviceSnapshot",
    "DreameApiError",
    "DreameAuthError",
    "DreameCloud",
    "DreameCommandRejectedError",
    "DreameConnectionError",
    "DreameDevice",
    "DreameError",
    "MapScene",
    "MapSummary",
    "Polygon",
    "VectorMap",
    "render_scene",
]
