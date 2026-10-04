"""Value objects and pure decoding tables for the Dreame client."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Final

from .const import (
    CIRCLE_SEGMENTS,
    DOCKING_STATES,
    FRAME_MARKER,
    HEARTBEAT_LENGTH,
    INACTIVE_TASK_STATUSES,
    MOWING_MAIN_STATE,
    PATH_SENTINEL,
    RUNTIME_BLOB_LENGTHS,
    RUNTIME_TASK_OFFSET,
    SHAPE_CIRCLE,
    SHAPE_RECTANGLE,
    TASK_STATUSES,
    TASK_SUBSTATE_BASE,
)

# --------------------------------------------------------------------------
# Devices
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DeviceDescriptor:
    """A mower as advertised by the cloud device list."""

    did: str
    model: str
    mac: str
    name: str
    host: str
    uid: str
    account_type: str = "dreame"
    region: str = "eu"
    firmware: str = ""

    @property
    def display_model(self) -> str:
        """Return the friendly product name for this model id."""
        return MODEL_NAMES.get(self.model, self.model)

    @property
    def unique_id(self) -> str:
        """Return a stable identifier for the config entry."""
        return self.did or self.mac or self.model

    @property
    def title(self) -> str:
        """Return the config entry title."""
        name = self.name or self.display_model
        if self.display_model and self.display_model not in name:
            return f"{name} ({self.display_model})"
        return name

    @property
    def short_model(self) -> str:
        """Return the trailing model segment, e.g. ``g2408``."""
        parts = self.model.split(".")
        return parts[-1] if parts else self.model


MODEL_NAMES: Final[dict[str, str]] = {
    "dreame.mower.p2255": "Dreame A1",
    "dreame.mower.g2422": "Dreame A1 Pro",
    "dreame.mower.g2540d": "Dreame A1 Pro 2000",
    "dreame.mower.g2408": "Dreame A2",
    "dreame.mower.g2568d": "Dreame A2 3000",
    "dreame.mower.g2541e": "Dreame A3 AWD Pro 3500",
    "dreame.mower.q2501a": "Dreame A3 AWD 1000",
    "dreame.mower.g3255": "Dreame A3",
    "mova.mower.g2405a": "MOVA 600",
    "mova.mower.g2405b": "MOVA 600 Kit",
    "mova.mower.g2405c": "MOVA 1000",
    "mova.mower.g2420a": "VIAX 250",
    "mova.mower.g2552": "VIAX 250",
    "mova.mower.g2420b": "VIAX 300",
    "mova.mower.g2583": "VIAX 500",
    "mova.mower.g2529b": "LiDAX Ultra 800",
    "mova.mower.g2529c": "LiDAX Ultra 1000",
    "mova.mower.g2529f": "LiDAX Ultra 2000",
    "mova.mower.g2584a": "LiDAX Ultra 2000 AWD",
}

#: Models with an electronic cutting-height actuator. Everything else uses a
#: manual height dial and gets no height entity at all.
TALL_HEIGHT_MODELS: Final[frozenset[str]] = frozenset(
    {
        "dreame.mower.q2501a",
        "dreame.mower.g2541e",
        "mova.mower.g2529b",
        "mova.mower.g2529c",
        "mova.mower.g2529f",
        "mova.mower.g2584a",
    }
)
DEFAULT_HEIGHT_MODELS: Final[frozenset[str]] = frozenset(
    {
        "dreame.mower.p2255",
        "dreame.mower.g2422",
        "dreame.mower.g2540d",
        "dreame.mower.g2408",
        "dreame.mower.g2568d",
        "dreame.mower.g3255",
    }
)

#: Models whose firmware reuses state codes 15/16/19 for repositioning instead
#: of the charging-temperature meanings seen elsewhere.
STATE_OVERRIDES: Final[dict[str, dict[int, str]]] = {
    "mova.mower.g2583": {15: "repositioning", 16: "repositioning", 19: "repositioning"},
    "mova.mower.g2529c": {19: "repositioning"},
    "mova.mower.g2529f": {19: "repositioning"},
    "mova.mower.g2584a": {19: "repositioning"},
}

#: Models that report an onboard camera usable for person detection.
PERSON_DETECTION_MODELS: Final[frozenset[str]] = frozenset(
    {"dreame.mower.q2501a", "mova.mower.g2529b", "mova.mower.g2529f"}
)


# --------------------------------------------------------------------------
# State decoding
# --------------------------------------------------------------------------


class MowingState(IntEnum):
    """Raw ``2.1`` mower state codes, as the Dreamehome app defines them."""

    MOWING = 1
    IDLE = 2
    PAUSED = 3
    PAUSED_DUE_TO_ERROR = 4
    RETURNING = 5
    CHARGING = 6
    MAPPING = 11
    CHARGING_COMPLETED = 13
    UPGRADING = 14
    CHARGING_PAUSED_HIGH_TEMPERATURE = 15
    CHARGING_PAUSED_LOW_TEMPERATURE = 16
    REMOTE_CONTROL = 23
    SMART_CHARGING = 24
    SECOND_MOWING = 25
    HUMAN_FOLLOWING = 26
    SPOT_MOWING = 27
    WAITING_FOR_TASK = 29
    STATION_CLEANING = 30
    PAUSED_AT_POINT = 75
    SHORTCUT = 97
    MONITORING = 98
    MONITORING_PAUSED = 99
    CHARGING_PAUSED_HIGH_TEMPERATURE_MIOT = 115
    CHARGING_PAUSED_LOW_TEMPERATURE_MIOT = 116
    REPOSITIONING_MIOT = 119


STATE_NAMES: Final[dict[int, str]] = {
    MowingState.MOWING: "mowing",
    MowingState.IDLE: "idle",
    MowingState.PAUSED: "paused",
    MowingState.PAUSED_DUE_TO_ERROR: "paused",
    MowingState.RETURNING: "returning",
    MowingState.CHARGING: "charging",
    MowingState.MAPPING: "mapping",
    MowingState.CHARGING_COMPLETED: "charging_completed",
    MowingState.UPGRADING: "upgrading",
    MowingState.CHARGING_PAUSED_HIGH_TEMPERATURE: "charging_paused_high_temperature",
    MowingState.CHARGING_PAUSED_LOW_TEMPERATURE: "charging_paused_low_temperature",
    MowingState.REMOTE_CONTROL: "remote_control",
    MowingState.SMART_CHARGING: "smart_charging",
    MowingState.SECOND_MOWING: "second_mowing",
    MowingState.HUMAN_FOLLOWING: "human_following",
    MowingState.SPOT_MOWING: "spot_mowing",
    MowingState.WAITING_FOR_TASK: "waiting_for_task",
    MowingState.STATION_CLEANING: "station_cleaning",
    MowingState.PAUSED_AT_POINT: "paused",
    MowingState.SHORTCUT: "shortcut",
    MowingState.MONITORING: "monitoring",
    MowingState.MONITORING_PAUSED: "monitoring_paused",
    MowingState.CHARGING_PAUSED_HIGH_TEMPERATURE_MIOT: ("charging_paused_high_temperature"),
    MowingState.CHARGING_PAUSED_LOW_TEMPERATURE_MIOT: "charging_paused_low_temperature",
    MowingState.REPOSITIONING_MIOT: "repositioning",
}

#: Normalized activity values the Home Assistant layer consumes.
ACTIVITY_MOWING: Final[str] = "mowing"
ACTIVITY_DOCKED: Final[str] = "docked"
ACTIVITY_PAUSED: Final[str] = "paused"
ACTIVITY_RETURNING: Final[str] = "returning"
ACTIVITY_ERROR: Final[str] = "error"
ACTIVITY_IDLE: Final[str] = "idle"

_ACTIVITY_BY_STATE: Final[dict[str, str]] = {
    "mowing": ACTIVITY_MOWING,
    "remote_control": ACTIVITY_MOWING,
    "second_mowing": ACTIVITY_MOWING,
    "human_following": ACTIVITY_MOWING,
    "spot_mowing": ACTIVITY_MOWING,
    "shortcut": ACTIVITY_MOWING,
    "monitoring": ACTIVITY_MOWING,
    "mapping": ACTIVITY_MOWING,
    "repositioning": ACTIVITY_MOWING,
    "paused": ACTIVITY_PAUSED,
    "monitoring_paused": ACTIVITY_PAUSED,
    "returning": ACTIVITY_RETURNING,
    "idle": ACTIVITY_DOCKED,
    "charging": ACTIVITY_DOCKED,
    "smart_charging": ACTIVITY_DOCKED,
    "charging_completed": ACTIVITY_DOCKED,
    "waiting_for_task": ACTIVITY_DOCKED,
    "station_cleaning": ACTIVITY_DOCKED,
    "upgrading": ACTIVITY_DOCKED,
    "charging_paused_high_temperature": ACTIVITY_DOCKED,
    "charging_paused_low_temperature": ACTIVITY_DOCKED,
}


def state_name(code: object, model: str = "") -> str | None:
    """Return the state name for a raw ``2.1`` code."""
    if isinstance(code, bool) or not isinstance(code, int):
        return None
    overrides = STATE_OVERRIDES.get(model)
    if overrides and code in overrides:
        return overrides[code]
    return STATE_NAMES.get(code)


def resolve_activity(
    state: str | None,
    *,
    error_tier: str | None = None,
    docked: bool = False,
    charging: bool = False,
    paused: bool = False,
) -> str:
    """Collapse device state and fault flags into one activity value.

    A confirmed fault outranks everything. ``returning`` reported together with
    an explicit dock or charge flag means the state field simply lags, so the
    mower is docked.
    """
    if error_tier == "error":
        return ACTIVITY_ERROR
    if state in ("returning",) and (docked or charging):
        return ACTIVITY_DOCKED
    activity = _ACTIVITY_BY_STATE.get(state or "")
    if activity is not None:
        return activity
    if paused:
        return ACTIVITY_PAUSED
    if docked or charging:
        return ACTIVITY_DOCKED
    return ACTIVITY_IDLE


# --------------------------------------------------------------------------
# Device codes
# --------------------------------------------------------------------------


class CodeTier:
    """Severity tiers for a mower device code."""

    ERROR: Final[str] = "error"
    ATTENTION: Final[str] = "attention"
    ALERT: Final[str] = "alert"
    INFO: Final[str] = "info"


@dataclass(frozen=True, slots=True)
class DeviceCode:
    """A decoded ``2.2`` device code."""

    code: int
    name: str
    tier: str


#: Cross-model registry. Model families override individual entries where
#: firmware renumbers or re-tiers a code.
_DEVICE_CODES: Final[dict[int, tuple[str, str]]] = {
    0: ("no_device_code", CodeTier.INFO),
    1: ("robot_tilted", CodeTier.ERROR),
    2: ("mower_stuck", CodeTier.ERROR),
    3: ("path_to_station_too_narrow", CodeTier.ERROR),
    4: ("left_drive_wheel_error", CodeTier.ERROR),
    5: ("right_drive_wheel_error", CodeTier.ERROR),
    6: ("blade_height_motor_error", CodeTier.ERROR),
    7: ("blade_disc_blocked", CodeTier.ERROR),
    8: ("blade_disc_side_motor_error", CodeTier.ERROR),
    9: ("bumper_error", CodeTier.ERROR),
    10: ("charging_error", CodeTier.ERROR),
    11: ("battery_temperature_too_high", CodeTier.ERROR),
    12: ("lidar_blocked", CodeTier.ERROR),
    13: ("lidar_temperature_too_high", CodeTier.ERROR),
    14: ("lidar_temperature_too_low", CodeTier.ERROR),
    15: ("lidar_temperature_high_altitude", CodeTier.ERROR),
    16: ("lidar_dirty", CodeTier.ERROR),
    17: ("lidar_error", CodeTier.ERROR),
    18: ("location_signal_weak", CodeTier.ERROR),
    19: ("location_lost", CodeTier.ERROR),
    20: ("sensor_error", CodeTier.ERROR),
    21: ("mower_in_no_go_zone", CodeTier.ERROR),
    22: ("mower_outside_map", CodeTier.ERROR),
    23: ("emergency_stop_pressed", CodeTier.ERROR),
    24: ("battery_critically_low", CodeTier.ERROR),
    25: ("map_file_damaged", CodeTier.ERROR),
    26: ("mower_too_far_from_map", CodeTier.ERROR),
    27: ("human_detected", CodeTier.ATTENTION),
    28: ("blades_worn", CodeTier.ATTENTION),
    29: ("station_brush_worn", CodeTier.ATTENTION),
    30: ("maintenance_due", CodeTier.ATTENTION),
    31: ("returning_to_station_failed", CodeTier.ALERT),
    32: ("docking_failed", CodeTier.ALERT),
    33: ("positioning_failed", CodeTier.ALERT),
    34: ("task_start_failed", CodeTier.ALERT),
    35: ("mowing_blocked", CodeTier.ALERT),
    36: ("mow_area_unreachable", CodeTier.ALERT),
    37: ("path_blocked", CodeTier.ERROR),
    38: ("camera_dirty", CodeTier.ALERT),
    39: ("camera_error", CodeTier.ALERT),
    40: ("camera_blocked", CodeTier.ALERT),
    41: ("camera_temperature_high", CodeTier.ALERT),
    42: ("charging_paused_high_temperature", CodeTier.ALERT),
    43: ("charging_paused_low_temperature", CodeTier.ALERT),
    44: ("boundary_detection_stopped", CodeTier.ALERT),
    45: ("boundary_detection_failed", CodeTier.ALERT),
    46: ("mowing_completed", CodeTier.INFO),
    47: ("new_map_created", CodeTier.INFO),
    48: ("task_completed", CodeTier.INFO),
    49: ("some_zones_unreachable", CodeTier.INFO),
    50: ("mowing_started", CodeTier.INFO),
    51: ("patrol_started", CodeTier.INFO),
    52: ("point_and_go_started", CodeTier.INFO),
    53: ("scheduled_mowing_started", CodeTier.INFO),
    54: ("low_battery_returning", CodeTier.INFO),
    55: ("mowing_suspended_by_weather", CodeTier.INFO),
    56: ("mowing_suspended_by_schedule", CodeTier.INFO),
    57: ("mowing_suspended_by_frost", CodeTier.INFO),
    58: ("mowing_suspended_by_low_light", CodeTier.INFO),
    59: ("mowing_suspended_by_temperature", CodeTier.INFO),
    60: ("mowing_suspended_by_rain", CodeTier.INFO),
    61: ("do_not_disturb_active", CodeTier.INFO),
    62: ("do_not_disturb_pending", CodeTier.INFO),
    63: ("zone_skipped", CodeTier.INFO),
    64: ("zone_interrupted", CodeTier.INFO),
    65: ("task_timeout", CodeTier.INFO),
    66: ("charging_skipped", CodeTier.INFO),
    67: ("mowing_resumed", CodeTier.INFO),
    68: ("station_not_connected", CodeTier.INFO),
    69: ("returning_to_station", CodeTier.INFO),
    70: ("mowing_resumed_after_pause", CodeTier.INFO),
    71: ("idle_timeout_returning", CodeTier.INFO),
    72: ("pause_timeout_returning", CodeTier.INFO),
    73: ("top_cover_open", CodeTier.ERROR),
}

_DEVICE_CODE_OVERRIDES: Final[dict[str, dict[int, tuple[str, str]]]] = {
    "dreame.mower.g2408": {
        0: ("robot_lifted", CodeTier.ERROR),
        16: ("scheduled_mowing_suspended_low_light", CodeTier.INFO),
        27: ("human_detected", CodeTier.ATTENTION),
        47: ("task_cancelled", CodeTier.INFO),
        59: ("battery_temperature_too_low", CodeTier.ERROR),
        80: ("lidar_cooling", CodeTier.INFO),
    },
    "mova.mower.g2583": {
        27: ("human_detected", CodeTier.ATTENTION),
        78: ("outside_operating_hours_low_light_returning", CodeTier.INFO),
    },
}


def decode_device_code(code: object, model: str = "") -> DeviceCode | None:
    """Return the decoded device code, or ``None`` when the mower is healthy.

    ``-1`` is the vendor's "no code" sentinel. ``0`` is a real code that some
    firmware families repurpose, so overrides are consulted before the table.
    """
    if isinstance(code, bool) or not isinstance(code, int) or code == -1:
        return None
    entry = _DEVICE_CODE_OVERRIDES.get(model, {}).get(code) or _DEVICE_CODES.get(code)
    if entry is None:
        return DeviceCode(code, f"unknown_device_code_{code}", CodeTier.ATTENTION)
    return DeviceCode(code, entry[0], entry[1])


# --------------------------------------------------------------------------
# Framed byte payloads
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuntimeTelemetry:
    """Live pose, heading and travel trail decoded from property ``1.4``."""

    x: int
    y: int
    heading: float
    track: tuple[tuple[tuple[int, int], ...], ...] = ()


@dataclass(frozen=True, slots=True)
class TaskTelemetry:
    """Mission progress decoded from the runtime payload tail block."""

    region_id: int
    task_id: int
    progress_percent: float | None
    current_area_sqm: float
    total_area_sqm: float


def normalize_bytes(value: object) -> tuple[int, ...] | None:
    """Coerce a property value into a tuple of byte-sized integers."""
    raw: object = value
    if isinstance(raw, str):
        text = raw.strip()
        if not (text.startswith("[") and text.endswith("]")):
            return None
        import json

        try:
            raw = json.loads(text)
        except ValueError:
            return None
    if isinstance(raw, (bytes, bytearray)):
        return tuple(raw)
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return None
    if not raw or not all(isinstance(v, int) and not isinstance(v, bool) for v in raw):
        return None
    if not all(0 <= v <= 255 for v in raw):
        return None
    return tuple(raw)


def decode_runtime(
    raw: Sequence[int],
) -> tuple[RuntimeTelemetry, TaskTelemetry | None] | None:
    """Decode the runtime pose, travel trail and mission block.

    The pose packs two signed 20-bit centimetre coordinates into six overlapping
    bytes; the trail is a run of signed 16-bit deltas relative to that pose.
    Returns ``None`` for frame shapes that are not runtime payloads.
    """
    data = tuple(raw)
    pose = _decode_pose(data)
    return None if pose is None else (pose, _decode_task_block(data))


def _decode_pose(data: tuple[int, ...]) -> RuntimeTelemetry | None:
    if len(data) not in RUNTIME_BLOB_LENGTHS or data[0] != FRAME_MARKER:
        return None
    b0, b1, b2, b3, b4, b5 = data[1:7]
    x = _sign_extend32(((b2 << 28) | (b1 << 20) | (b0 << 12)) & 0xFFFFFFFF) >> 12
    y = _sign_extend32(((b4 << 24) | (b3 << 16) | (b2 << 8)) & 0xFFFFFFFF) >> 12
    return RuntimeTelemetry(
        x=x * 10,
        y=y * 10,
        heading=round(b5 / 255.0 * 360.0, 1),
        track=_decode_track(data, x * 10, y * 10),
    )


def _decode_track(
    data: tuple[int, ...], x: int, y: int
) -> tuple[tuple[tuple[int, int], ...], ...]:
    chunks: list[tuple[int, int]] = []
    if len(data) == 44 and data[-1] == FRAME_MARKER:
        chunks = [(7, 15), (32, 11)]
    elif len(data) in (22, 33) and data[-1] == FRAME_MARKER:
        chunks = [(7, 15)]
    if not chunks:
        return ()

    segments: list[tuple[tuple[int, int], ...]] = []
    current: list[tuple[int, int]] = []
    for offset, length in chunks:
        if len(data) < offset + length:
            continue
        cursor = offset + 3
        for _ in range((length - 3) // 4):
            if cursor + 4 > len(data):
                break
            dx = _signed_int16(data[cursor], data[cursor + 1])
            dy = _signed_int16(data[cursor + 2], data[cursor + 3])
            cursor += 4
            if abs(dx) > 32766 and abs(dy) > 32766:
                if current:
                    segments.append(tuple(current))
                    current = []
                continue
            current.append((x + dx * 10, y + dy * 10))
    if current:
        segments.append(tuple(current))
    return tuple(segments)


def _decode_task_block(data: tuple[int, ...]) -> TaskTelemetry | None:
    if len(data) not in (33, 44) or data[-1] != FRAME_MARKER:
        return None
    o = RUNTIME_TASK_OFFSET
    percent_raw = data[o + 2] | (data[o + 3] << 8)
    total_raw = data[o + 4] | (data[o + 5] << 8) | (data[o + 6] << 16)
    current_raw = data[o + 7] | (data[o + 8] << 8) | (data[o + 9] << 16)
    percent = round(percent_raw / 10.0, 1) if 0 <= percent_raw <= 1000 else None
    return TaskTelemetry(
        region_id=data[o],
        task_id=data[o + 1],
        progress_percent=percent,
        current_area_sqm=round(current_raw / 100.0, 2),
        total_area_sqm=round(total_raw / 100.0, 2),
    )


def _sign_extend32(value: int) -> int:
    return value - 0x100000000 if value & 0x80000000 else value


def _signed_int16(low: int, high: int) -> int:
    value = low | (high << 8)
    return value - 0x10000 if value & 0x8000 else value


def decode_heartbeat(value: object) -> dict[str, Any]:
    """Decode the ``1.1`` heartbeat into battery, docking and task fields."""
    raw = normalize_bytes(value)
    if raw is None or len(raw) < 2 or raw[0] != FRAME_MARKER or raw[-1] != FRAME_MARKER:
        return {}
    result: dict[str, Any] = {}
    if len(raw) > 11:
        battery = raw[11]
        charging = battery >= 128
        level = battery - 128 if charging else battery
        if level <= 100:
            result["battery_level"] = level
            result["charging"] = charging
    if len(raw) == HEARTBEAT_LENGTH:
        result["docking_state"] = DOCKING_STATES.get((raw[14] & 0x1C) >> 2)
        result["docked"] = (raw[14] & 0x1C) >> 2 == 0
        main = (raw[12] & 0x0F) - 1
        status = (
            "idle"
            if main != MOWING_MAIN_STATE
            else TASK_STATUSES.get(raw[13] - TASK_SUBSTATE_BASE)
        )
        result["task_status"] = status
        result["task_resumable"] = status == "paused"
    return result


def task_session_active(task_status: str | None) -> bool | None:
    """Return whether a mowing session is currently running."""
    if task_status is None:
        return None
    return task_status not in INACTIVE_TASK_STATUSES


# --------------------------------------------------------------------------
# Vector map
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Polygon:
    """A closed area on the map, in native centimetres."""

    id: int
    points: tuple[tuple[int, int], ...]
    name: str = ""
    kind: str = "zone"
    area: float = 0.0
    shape: int = 0
    angle: float = 0.0

    @property
    def center(self) -> tuple[float, float]:
        """Return the centroid of the polygon."""
        if not self.points:
            return (0.0, 0.0)
        return (
            sum(p[0] for p in self.points) / len(self.points),
            sum(p[1] for p in self.points) / len(self.points),
        )


@dataclass(frozen=True, slots=True)
class MapPath:
    """A navigation corridor between areas."""

    id: int
    points: tuple[tuple[int, int], ...]
    name: str = ""


@dataclass(frozen=True, slots=True)
class MapSummary:
    """A discoverable map without its geometry."""

    map_id: int
    map_index: int
    name: str
    total_area: float


@dataclass(frozen=True, slots=True)
class VectorMap:
    """The full parsed vector map for one lawn."""

    map_id: int
    map_index: int
    name: str
    total_area: float
    boundary: tuple[int, int, int, int]
    zones: tuple[Polygon, ...] = ()
    forbidden: tuple[Polygon, ...] = ()
    spots: tuple[Polygon, ...] = ()
    paths: tuple[MapPath, ...] = ()
    contours: tuple[Polygon, ...] = ()
    points: tuple[tuple[int, int], ...] = ()
    available: tuple[MapSummary, ...] = ()
    obstacles: tuple[Mapping[str, Any], ...] = ()

    @property
    def usable(self) -> bool:
        """Return whether this map carries drawable geometry."""
        return bool(self.zones or self.forbidden or self.paths or self.spots)


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _entries(value: object, *, int_key: bool = True) -> tuple[tuple[object, Any], ...]:
    """Unwrap the ``{"dataType": "Map", "value": [[key, obj], ...]}`` wrapper."""
    if not isinstance(value, Mapping) or value.get("dataType") != "Map":
        return ()
    items = value.get("value")
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes, bytearray)):
        return ()
    result: list[tuple[object, Any]] = []
    for item in items:
        if not isinstance(item, Sequence) or isinstance(item, (str, bytes, bytearray)):
            continue
        if len(item) < 2:
            continue
        key = _coerce_int(item[0]) if int_key else item[0]
        if int_key and key is None:
            continue
        result.append((key, item[1]))
    return tuple(result)


def _coordinate(item: object) -> tuple[int, int] | None:
    """Read one coordinate.

    Firmware writes paths as ``{"x": ..., "y": ...}`` objects; older payloads
    use bare ``[x, y]`` pairs. Both are accepted.
    """
    if isinstance(item, Mapping):
        x, y = _coerce_int(item.get("x")), _coerce_int(item.get("y"))
    elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
        if len(item) < 2:
            return None
        x, y = _coerce_int(item[0]), _coerce_int(item[1])
    else:
        return None
    return (x, y) if x is not None and y is not None else None


def _points(value: object) -> tuple[tuple[int, int], ...]:
    """Read a polyline of coordinates."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    result: list[tuple[int, int]] = []
    for item in value:
        if (point := _coordinate(item)) is not None:
            result.append(point)
    return tuple(result)


def _point_collection(value: object) -> tuple[tuple[int, int], ...]:
    """Read a ``Map``-wrapped collection of single points."""
    result: list[tuple[int, int]] = []
    for _, item in _entries(value, int_key=False):
        if (point := _coordinate(item)) is not None:
            result.append(point)
    return tuple(result)


def _resolve_shape(
    points: tuple[tuple[int, int], ...], shape: int, angle: float
) -> tuple[tuple[int, int], ...]:
    """Expand the compact circle and rotated-rectangle shapes to polygons."""
    if shape == SHAPE_CIRCLE and len(points) >= 2:
        # A circle arrives as its bounding box. Taking the extremes works for
        # both the two-corner and four-corner encodings.
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        rx, ry = (max(xs) - min(xs)) / 2, (max(ys) - min(ys)) / 2
        return tuple(
            (
                round(cx + rx * math.cos(2 * math.pi * i / CIRCLE_SEGMENTS)),
                round(cy + ry * math.sin(2 * math.pi * i / CIRCLE_SEGMENTS)),
            )
            for i in range(CIRCLE_SEGMENTS)
        )
    if shape == SHAPE_RECTANGLE and angle and points:
        cx = sum(p[0] for p in points) / len(points)
        cy = sum(p[1] for p in points) / len(points)
        radians = math.radians(-angle)
        cos, sin = math.cos(radians), math.sin(radians)
        return tuple(
            (
                round(cx + (x - cx) * cos - (y - cy) * sin),
                round(cy + (x - cx) * sin + (y - cy) * cos),
            )
            for x, y in points
        )
    return points


def _polygons(value: object, kind: str) -> tuple[Polygon, ...]:
    result: list[Polygon] = []
    for key, raw in _entries(value):
        if not isinstance(raw, Mapping):
            continue
        shape = _coerce_int(raw.get("shapeType")) or 0
        angle = float(raw.get("angle") or 0.0)
        pts = _resolve_shape(_points(raw.get("path")), shape, angle)
        if len(pts) < 2:
            continue
        result.append(
            Polygon(
                id=int(key),
                points=pts,
                name=str(raw.get("name") or ""),
                kind=kind,
                area=float(raw.get("area") or 0.0),
                shape=shape,
                angle=angle,
            )
        )
    return tuple(result)


def _contour_key(value: object) -> tuple[int, int]:
    """Contour keys arrive as ``[edge, index]`` or ``"edge,index"``."""
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        parts = [_coerce_int(v) for v in value[:2]]
    elif isinstance(value, str):
        parts = [_coerce_int(part) for part in value.split(",")[:2]]
    else:
        parts = []
    parts = [p for p in parts if p is not None]
    while len(parts) < 2:
        parts.append(0)
    return (parts[0], parts[1])


def _contours(value: object) -> tuple[Polygon, ...]:
    result: list[Polygon] = []
    for key, raw in _entries(value, int_key=False):
        if not isinstance(raw, Mapping):
            continue
        pts = _points(raw.get("path"))
        if len(pts) < 2:
            continue
        edge, index = _contour_key(key)
        result.append(
            Polygon(
                id=index,
                points=pts,
                name=f"Edge {edge}.{index}",
                kind="contour",
                shape=_coerce_int(raw.get("shapeType")) or 0,
                angle=float(raw.get("angle") or 0.0),
            )
        )
    return tuple(result)


def _paths(value: object) -> tuple[MapPath, ...]:
    result: list[MapPath] = []
    for key, raw in _entries(value):
        pts = _points(raw.get("path")) if isinstance(raw, Mapping) else _points(raw)
        if len(pts) < 2:
            continue
        result.append(MapPath(id=int(key), points=pts))
    return tuple(result)


def parse_vector_map(
    raw: Mapping[str, Any], *, available: Sequence[MapSummary] = ()
) -> VectorMap:
    """Parse one decoded vector-map object into a :class:`VectorMap`."""
    map_index = _coerce_int(raw.get("mapIndex")) or 0
    zones = _polygons(raw.get("mowingAreas"), "zone")
    forbidden = _polygons(raw.get("forbiddenAreas"), "forbidden")
    spots = _polygons(raw.get("spotAreas"), "spot")
    paths = _paths(raw.get("paths"))
    contours = _contours(raw.get("contours"))
    points = _point_collection(raw.get("cruisePoints"))
    obstacles = tuple(
        item
        for _, item in _entries(raw.get("obstacles"), int_key=False)
        if isinstance(item, Mapping)
    )

    polygons = (*zones, *forbidden, *spots, *contours)
    all_points = [p for poly in polygons for p in poly.points]
    all_points.extend(p for path in paths for p in path.points)
    all_points.extend(points)
    if all_points:
        xs = [p[0] for p in all_points]
        ys = [p[1] for p in all_points]
        boundary = (min(xs), min(ys), max(xs), max(ys))
    else:
        boundary = (0, 0, 1, 1)

    return VectorMap(
        map_id=map_index + 1,
        map_index=map_index,
        name=str(raw.get("name") or ""),
        total_area=float(raw.get("totalArea") or 0.0),
        boundary=boundary,
        zones=zones,
        forbidden=forbidden,
        spots=spots,
        paths=paths,
        contours=contours,
        points=points,
        available=tuple(available),
        obstacles=obstacles,
    )


def parse_path(raw: str) -> tuple[tuple[tuple[int, int], ...], ...]:
    """Parse an ``M_PATH`` trail blob into polylines of centimetre points.

    The trail uses decimetres and marks a discontinuity with ``(32767, -32768)``.
    """
    import re

    pairs = [
        (int(m.group(1)), int(m.group(2))) for m in re.finditer(r"\[(-?\d+),(-?\d+)\]", raw)
    ]
    segments: list[tuple[tuple[int, int], ...]] = []
    current: list[tuple[int, int]] = []
    for pair in pairs:
        if pair == PATH_SENTINEL:
            if current:
                segments.append(tuple(current))
                current = []
            continue
        current.append((pair[0] * 10, pair[1] * 10))
    if current:
        segments.append(tuple(current))
    return tuple(segments)


@dataclass(slots=True)
class MapScene:
    """Everything the renderer and the map card need for one frame."""

    vector_map: VectorMap
    runtime: RuntimeTelemetry | None = None
    trail: tuple[tuple[tuple[int, int], ...], ...] = ()
    rotation: int = 0
    extra: dict[str, Any] = field(default_factory=dict)
