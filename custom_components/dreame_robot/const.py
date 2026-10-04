"""Constants for the Dreame Robot integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "dreame_robot"
PLATFORMS: Final[list[str]] = [
    "binary_sensor",
    "button",
    "image",
    "lawn_mower",
    "number",
    "select",
    "sensor",
    "switch",
    "update",
]

CONF_ACCOUNT_TYPE: Final = "account_type"
CONF_REGION: Final = "region"
CONF_DID: Final = "did"
CONF_MAC: Final = "mac"
CONF_MODEL: Final = "model"
CONF_DEVICE_NAME: Final = "device_name"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_MAP_ROTATION: Final = "map_rotation"

DEFAULT_SCAN_INTERVAL: Final = 60
MIN_SCAN_INTERVAL: Final = 15
MAX_SCAN_INTERVAL: Final = 300

#: Display rotation of the rendered map, in degrees clockwise.
MAP_ROTATION_CHOICES: Final[list[int]] = [0, 90, 180, 270]
DEFAULT_MAP_ROTATION: Final[int] = 0

ATTR_ZONE_IDS: Final = "zone_ids"
ATTR_SPOT_IDS: Final = "spot_ids"
ATTR_CONTOUR_IDS: Final = "contour_ids"
ATTR_X: Final = "x"
ATTR_Y: Final = "y"
ATTR_VELOCITY: Final = "velocity"
ATTR_ROTATION: Final = "rotation"
ATTR_MAP_INDEX: Final = "map_index"
ATTR_ITEM: Final = "item"
ATTR_ENTRY_ID: Final = "entry_id"

MAP_JSON_URL: Final = "/api/dreame_robot/{entry_id}/map.json"
MAP_CARD_FILENAME: Final = "dreame-robot-map-card.js"

#: Voice prompt groups, in the order the device expects them.
VOICE_PROMPT_GROUPS: Final[tuple[tuple[str, str], ...]] = (
    ("general", "General"),
    ("working", "Working"),
    ("special", "Special status"),
    ("fault", "Fault"),
)

#: Mowing heights in centimetres, per model family.
HEIGHT_LIMITS_TALL: Final[tuple[float, float, float]] = (3.0, 7.0, 10.0)
HEIGHT_LIMITS_DEFAULT: Final[tuple[float, float, float]] = (3.0, 7.0, 7.0)
HEIGHT_STEP_CM: Final = 0.5
