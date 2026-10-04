"""High-level mower client: state polling, commands, settings and map access."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .cloud import DreameCloud
from .const import (
    ACTION_CLEAR_WARNING,
    ACTION_DOCK,
    ACTION_LOCATE,
    ACTION_PAUSE,
    ACTION_START_MOWING,
    ACTION_STOP,
    MAP_CHUNK_PREFIX,
    MAP_PATH_PREFIX,
    OP_MOW_EDGE,
    OP_MOW_SPOT,
    OP_MOW_ZONE,
    POLL_PROPERTIES,
    PROP_BATTERY,
    PROP_CHARGING,
    PROP_CLEANED_AREA,
    PROP_CLEANING_TIME,
    PROP_ERROR,
    PROP_MOWING_MODE,
    PROP_MOWING_PROGRESS,
    PROP_PAUSED,
    PROP_RAW_STATUS,
    PROP_REMOTE_CONTROL,
    PROP_RUNTIME_STATUS,
    PROP_SERIAL,
    PROP_STARTED,
    PROP_STATE,
    PROP_TASK_STATUS,
    PROP_TOTAL_MOWED_AREA,
    PROP_TOTAL_MOWING_TIME,
)
from .exceptions import DreameCommandRejectedError
from .models import (
    ACTIVITY_DOCKED,
    DeviceCode,
    DeviceDescriptor,
    MapScene,
    MapSummary,
    RuntimeTelemetry,
    TaskTelemetry,
    VectorMap,
    decode_device_code,
    decode_heartbeat,
    decode_runtime,
    normalize_bytes,
    parse_vector_map,
    resolve_activity,
    state_name,
)
from .mqtt import RealtimeClient
from .render import build_projection, render_scene

_LOGGER = logging.getLogger(__name__)

#: How long a downloaded map stays fresh. Geometry only changes when the user
#: edits it in the app, so this can be generous.
MAP_TTL_SECONDS = 600.0
#: Settings, maintenance and OTA change only when the user opens the app.
SETTINGS_TTL_SECONDS = 300.0
OTA_TTL_SECONDS = 3600.0
#: The batch payload also carries mowing history and preferences; ask only for
#: the map keys so the response stays small.
MAP_BATCH_PREFIXES = (MAP_CHUNK_PREFIX, MAP_PATH_PREFIX)

START_CUSTOM_STATUS_SPOT = 20
START_CUSTOM_STATUS_CRUISE_POINT = 23
START_CUSTOM_SIID = 4
START_CUSTOM_AIID = 1
START_CUSTOM_PIID_STATUS = 1
START_CUSTOM_PIID_PARAMS = 10

MAINTENANCE_ITEMS: tuple[tuple[str, str, int, int], ...] = (
    ("blade", "Blade", 0, 6000),
    ("brush", "Cleaning Brush", 1, 30000),
    ("robot", "Robot Maintenance", 2, 3600),
)
MAINTENANCE_WARNING_PERCENT = 20.0


@dataclass(slots=True)
class DeviceSnapshot:
    """Everything the Home Assistant layer renders from."""

    descriptor: DeviceDescriptor
    available: bool = False
    connected: bool = False
    state_code: int | None = None
    state: str | None = None
    activity: str = ACTIVITY_DOCKED
    error: DeviceCode | None = None
    battery_level: int | None = None
    charging: bool = False
    docked: bool = False
    started: bool = False
    paused: bool = False
    task_status: str | None = None
    mowing_mode: str | None = None
    session_minutes: int | None = None
    session_area_sqm: float | None = None
    progress_percent: float | None = None
    total_minutes: int | None = None
    total_area_sqm: float | None = None
    serial_number: str | None = None
    runtime: RuntimeTelemetry | None = None
    task: TaskTelemetry | None = None
    settings: Mapping[str, Any] = field(default_factory=dict)
    maintenance: tuple[Mapping[str, Any], ...] = ()
    properties: Mapping[str, Any] = field(default_factory=dict)
    maps: Mapping[int, VectorMap] = field(default_factory=dict)
    current_map_index: int | None = None
    ota: Mapping[str, Any] = field(default_factory=dict)
    observed_at: float = 0.0


class DreameDevice:
    """Owns the cloud session, the push channel and the decoded device state."""

    def __init__(
        self,
        descriptor: DeviceDescriptor,
        username: str,
        password: str,
        *,
        on_update: Callable[[], None] | None = None,
    ) -> None:
        self.descriptor = descriptor
        self._username = username
        self._password = password
        self.on_update = on_update
        self._lock = threading.RLock()

        self._cloud = DreameCloud(
            username,
            password,
            region=descriptor.region,
            account_type=descriptor.account_type,
        )
        self._realtime: RealtimeClient | None = None
        self._properties: dict[str, Any] = {}
        self._runtime: RuntimeTelemetry | None = None
        self._runtime_task: TaskTelemetry | None = None
        self._heartbeat: dict[str, Any] = {}
        self._maps: dict[int, VectorMap] = {}
        self._trail: tuple[tuple[tuple[int, int], ...], ...] = ()
        self._maps_fetched_at = 0.0
        self._settings: Mapping[str, Any] = {}
        self._settings_at = 0.0
        self._maintenance: tuple[Mapping[str, Any], ...] = ()
        self._maintenance_at = 0.0
        self._ota: Mapping[str, Any] = {}
        self._ota_at = 0.0
        self._available = False
        self._connected = False
        self._rotation = 0
        self._extra: dict[str, Any] = {}

    # -- lifecycle ----------------------------------------------------------

    def connect(self) -> None:
        """Log in, learn the broker, and start the push channel."""
        self._cloud.login()
        self._cloud.attach(self.descriptor)
        if self._cloud.host and self._cloud.uid:
            self._realtime = RealtimeClient(
                self._cloud.host,
                self._cloud.did,
                self._cloud.uid,
                self._cloud.model,
                self.descriptor.region,
                self._cloud.user_id,
                self._cloud.access_token or "",
                on_message=self._on_push,
                on_state=self._on_push_state,
            )
            try:
                self._realtime.start()
            except Exception:  # noqa: BLE001 - polling still works without push
                _LOGGER.warning("Push channel unavailable, falling back to polling")
                self._realtime = None

    def disconnect(self) -> None:
        """Stop the push channel."""
        if self._realtime:
            self._realtime.stop()
            self._realtime = None
        self._connected = False

    def _on_push_state(self, connected: bool) -> None:
        with self._lock:
            changed = connected != self._connected
            self._connected = connected
        if connected and changed and self.on_update:
            self.on_update()

    def _on_push(self, payload: Mapping[str, Any]) -> None:
        """Fold one ``properties_changed`` push into the local caches."""
        if payload.get("method") != "properties_changed":
            return
        params = payload.get("params")
        if not isinstance(params, Sequence):
            return
        with self._lock:
            for param in params:
                if not isinstance(param, Mapping):
                    continue
                siid, piid = param.get("siid"), param.get("piid")
                if not isinstance(siid, int) or not isinstance(piid, int):
                    continue
                key = f"{siid}.{piid}"
                self._properties[key] = param.get("value")
                if key == PROP_RUNTIME_STATUS:
                    decoded = normalize_bytes(param.get("value"))
                    if decoded and (result := decode_runtime(decoded)) is not None:
                        self._runtime = result[0]
                        self._runtime_task = result[1]
                elif key == PROP_RAW_STATUS:
                    self._heartbeat = decode_heartbeat(param.get("value"))
            self._available = True
        if self.on_update:
            self.on_update()

    # -- reads --------------------------------------------------------------

    def poll(self, *, refresh_map: bool | None = None) -> DeviceSnapshot:
        """Read device state, refreshing the map when it has gone stale."""
        try:
            values = self._cloud.get_properties(list(POLL_PROPERTIES))
        except Exception:
            # Push updates keep flowing even when a poll fails, so keep whatever
            # the last good read produced instead of dropping every entity.
            if not self._available and not self._properties:
                raise
        else:
            with self._lock:
                self._properties.update(values)
                self._available = True

        now = time.monotonic()
        stale_map = now - self._maps_fetched_at > MAP_TTL_SECONDS
        if refresh_map or (refresh_map is None and stale_map):
            self._refresh_map()
        if now - self._settings_at > SETTINGS_TTL_SECONDS:
            try:
                self.refresh_settings()
            except Exception:  # noqa: BLE001 - settings are optional metadata
                _LOGGER.debug("Settings read failed", exc_info=True)
        if now - self._maintenance_at > SETTINGS_TTL_SECONDS:
            try:
                self.refresh_maintenance()
            except Exception:  # noqa: BLE001 - maintenance is optional metadata
                _LOGGER.debug("Maintenance read failed", exc_info=True)
        if now - self._ota_at > OTA_TTL_SECONDS:
            self.refresh_ota()

        return self.snapshot()

    def _refresh_map(self) -> None:
        try:
            batch = self._cloud.get_batch_data(list(MAP_BATCH_PREFIXES))
        except Exception:  # noqa: BLE001 - a missing map must not kill polling
            _LOGGER.debug("Map download failed", exc_info=True)
            self._maps_fetched_at = time.monotonic()
            return
        decoded = _decode_map_batch(batch)
        if decoded:
            self._maps = decoded
        self._maps_fetched_at = time.monotonic()

    def snapshot(self) -> DeviceSnapshot:
        """Build the immutable view the Home Assistant layer reads."""
        with self._lock:
            properties = dict(self._properties)
            heartbeat = dict(self._heartbeat)
            maps = dict(self._maps)
            runtime = self._runtime
            task = self._runtime_task
            available = self._available
            connected = self._connected

        state_code = _as_int(properties.get(PROP_STATE))
        state = state_name(state_code, self.descriptor.model)
        error = decode_device_code(properties.get(PROP_ERROR), self.descriptor.model)
        docked = _as_bool(properties.get(PROP_CHARGING)) or heartbeat.get("docked", False)
        charging = _as_bool(properties.get(PROP_CHARGING)) or bool(heartbeat.get("charging"))
        paused = _as_bool(properties.get(PROP_PAUSED))
        task_status = self._task_status(properties, heartbeat)

        battery = _as_int(properties.get(PROP_BATTERY))
        if battery is None:
            battery = heartbeat.get("battery_level")

        progress = task.progress_percent if task else None
        if progress is None:
            progress = _as_float(properties.get(PROP_MOWING_PROGRESS))

        return DeviceSnapshot(
            descriptor=self.descriptor,
            available=available,
            connected=connected,
            state_code=state_code,
            state=state,
            activity=resolve_activity(
                state,
                error_tier=error.tier if error else None,
                docked=bool(docked),
                charging=charging,
                paused=paused,
            ),
            error=error,
            battery_level=battery,
            charging=charging,
            docked=bool(docked),
            started=_as_bool(properties.get(PROP_STARTED)),
            paused=paused,
            task_status=task_status,
            mowing_mode=_mowing_mode(properties.get(PROP_MOWING_MODE)),
            session_minutes=_as_int(properties.get(PROP_CLEANING_TIME)),
            session_area_sqm=_as_float(properties.get(PROP_CLEANED_AREA)),
            progress_percent=progress,
            total_minutes=_as_int(properties.get(PROP_TOTAL_MOWING_TIME)),
            total_area_sqm=_as_float(properties.get(PROP_TOTAL_MOWED_AREA)),
            serial_number=_as_str(properties.get(PROP_SERIAL)) or self.descriptor.firmware,
            runtime=runtime,
            task=task,
            settings=self._settings,
            maintenance=self._maintenance,
            properties=properties,
            maps=maps,
            current_map_index=current.map_index if (current := _current_map(maps)) else None,
            ota=self._ota,
            observed_at=time.time(),
        )

    def _task_status(
        self, properties: Mapping[str, Any], heartbeat: Mapping[str, Any]
    ) -> str | None:
        """Return the device's own task status when it publishes one."""
        raw = properties.get(PROP_TASK_STATUS)
        if isinstance(raw, str):
            try:
                decoded = json.loads(raw)
            except ValueError:
                decoded = None
            if isinstance(decoded, Mapping):
                name = decoded.get("t")
                if isinstance(name, str):
                    return name.lower()
        return heartbeat.get("task_status")

    # -- map ----------------------------------------------------------------

    @property
    def current_map(self) -> VectorMap | None:
        """Return the map the mower is working on."""
        with self._lock:
            maps = self._maps
        return _current_map(maps)

    def available_maps(self) -> tuple[MapSummary, ...]:
        """Return every map this mower stores."""
        with self._lock:
            return tuple(
                MapSummary(m.map_id, m.map_index, m.name, m.total_area)
                for m in sorted(self._maps.values(), key=lambda m: m.map_index)
            )

    def scene(self) -> MapScene | None:
        """Return the current map plus live pose and trail."""
        vector_map = self.current_map
        if vector_map is None or not vector_map.usable:
            return None
        with self._lock:
            runtime = self._runtime
            trail = self._trail or (runtime.track if runtime else ())
        return MapScene(
            vector_map=vector_map,
            runtime=runtime,
            trail=trail,
            rotation=self._rotation,
        )

    def map_png(self) -> bytes | None:
        """Render the current map to PNG bytes."""
        scene = self.scene()
        return render_scene(scene) if scene else None

    def map_projection(self):
        """Return the projection the map card should use for coordinates."""
        vector_map = self.current_map
        return build_projection(vector_map, self._rotation) if vector_map else None

    def set_rotation(self, degrees: int) -> None:
        """Set the display rotation of the rendered map."""
        self._rotation = degrees % 360 if degrees % 90 == 0 else 0

    # -- mowing commands ----------------------------------------------------

    def start_mowing(self) -> Any:
        """Start or resume mowing the whole lawn."""
        return self._action(ACTION_START_MOWING)

    def pause(self) -> Any:
        """Pause the current task."""
        return self._action(ACTION_PAUSE)

    def stop(self) -> Any:
        """Stop the current task."""
        return self._action(ACTION_STOP)

    def dock(self) -> Any:
        """Send the mower back to its station."""
        return self._action(ACTION_DOCK)

    def clear_warning(self) -> Any:
        """Acknowledge a latched warning on the mower."""
        return self._action(ACTION_CLEAR_WARNING)

    def locate(self) -> Any:
        """Make the mower beep so it can be located by ear."""
        return self._action(ACTION_LOCATE)

    def mow_zones(self, zone_ids: Sequence[int]) -> Any:
        """Mow one or more saved lawn zones."""
        return self._task(OP_MOW_ZONE, "region", [_positive(i) for i in zone_ids], "zone")

    def mow_spots(self, spot_ids: Sequence[int]) -> Any:
        """Mow one or more saved spot areas."""
        return self._task(OP_MOW_SPOT, "area", [_positive(i) for i in spot_ids], "spot")

    def mow_contours(self, contour_ids: Sequence[Sequence[int]]) -> Any:
        """Mow saved map edges given as ``(edge, index)`` pairs."""
        pairs = [[_positive(p[0]), _positive(p[1])] for p in contour_ids if len(p) >= 2]
        if not pairs:
            raise ValueError("At least one (edge, index) pair is required.")
        return self._task(OP_MOW_EDGE, "edge", pairs, "edge")

    def mow_point(self, x: int, y: int, repeats: int = 1) -> Any:
        """Mow a roughly 1.5 m² patch centred on a map coordinate."""
        return self._start_custom(
            START_CUSTOM_STATUS_SPOT,
            {"points": [[int(x), int(y), max(1, min(int(repeats), 5))]]},
        )

    def go_to(self, x: int, y: int) -> Any:
        """Drive to a map coordinate without mowing."""
        return self._start_custom(
            START_CUSTOM_STATUS_CRUISE_POINT, {"tpoint": [[int(x), int(y), 0, 0]]}
        )

    def switch_map(self, map_index: int) -> Any:
        """Make the mower work on a different stored map."""
        return self._app_action({"m": "s", "t": "MAPC", "d": {"index": _positive(map_index)}})

    def remote_control(self, velocity: int, rotation: int, *, prompt: bool = False) -> Any:
        """Drive the mower manually for one step.

        Velocity and rotation use the vendor's -1000..1000 scale.
        """
        payload = json.dumps(
            {
                "spdv": _clamp(velocity, -1000, 1000),
                "spdw": _clamp(rotation, -1000, 1000),
                "audio": "true" if prompt else "false",
                "random": 0,
            },
            separators=(",", ":"),
        )
        return self._cloud.set_property(*_sids(PROP_REMOTE_CONTROL), payload)

    def remote_control_stop(self) -> Any:
        """Release the manual drive command."""
        return self.remote_control(0, 0)

    # -- settings -----------------------------------------------------------

    @property
    def settings(self) -> Mapping[str, Any]:
        """Return the last decoded CFG settings record set."""
        return self._settings

    @property
    def maintenance(self) -> tuple[Mapping[str, Any], ...]:
        """Return remaining life for each maintenance counter."""
        return self._maintenance

    def refresh_maintenance(self) -> tuple[Mapping[str, Any], ...]:
        """Re-read and cache the CMS maintenance counters."""
        values = _as_list(self._app_get("CMS"))
        items: list[Mapping[str, Any]] = []
        for key, name, index, total in MAINTENANCE_ITEMS:
            used = _as_int(values[index]) if index < len(values) else None
            remaining = None if used is None else max(0, total - used)
            percent = None if used is None else round(max(0.0, (total - used) / total * 100), 1)
            items.append(
                {
                    "key": key,
                    "name": name,
                    "used_minutes": used,
                    "total_minutes": total,
                    "remaining_minutes": remaining,
                    "remaining_percent": percent,
                    "due": bool(percent is not None and percent <= 0),
                    "warning": bool(
                        percent is not None and percent <= MAINTENANCE_WARNING_PERCENT
                    ),
                }
            )
        self._maintenance = tuple(items)
        self._maintenance_at = time.monotonic()
        return self._maintenance

    def refresh_settings(self) -> Mapping[str, Any]:
        """Re-read and cache the CFG settings records."""
        result: dict[str, Any] = {}
        for record in _records(self._app_get("CFG")):
            key = record.get("t")
            if isinstance(key, str):
                result[key] = record.get("d", record.get("value"))
        self._settings = result
        self._settings_at = time.monotonic()
        return self._settings

    @property
    def ota_status(self) -> Mapping[str, Any]:
        """Return the last read firmware update status."""
        return self._ota

    def refresh_ota(self) -> Mapping[str, Any]:
        """Re-read firmware update availability."""
        try:
            data = self._cloud.get_ota_status()
        except Exception:  # noqa: BLE001 - OTA is optional metadata
            _LOGGER.debug("Firmware status unavailable", exc_info=True)
            self._ota_at = time.monotonic()
            return self._ota

        if isinstance(data, Mapping):
            latest = data.get("latestVersion") or data.get("newVersion") or {}
            current = data.get("currentVersion") or {}
            target = latest.get("version") if isinstance(latest, Mapping) else None
            self._ota = {
                "current_version": str(current.get("version") or self.descriptor.firmware),
                "latest_version": str(target) if target else None,
                "update_available": bool(target) and str(target) != self.descriptor.firmware,
            }
        self._ota_at = time.monotonic()
        return self._ota

    def set_volume(self, value: int) -> Any:
        """Set the voice prompt volume."""
        return self._app_set("VOL", {"value": _clamp(int(value), 0, 100)})

    def set_voice_prompts(self, flags: Mapping[str, bool]) -> Any:
        """Enable or disable the four voice prompt groups."""
        order = ("general", "working", "special", "fault")
        return self._app_set(
            "VOICE", {"value": [int(bool(flags.get(name, False))) for name in order]}
        )

    def set_rain_protection(self, enabled: bool, delay_hours: int, sensitivity: int) -> Any:
        """Configure the after-rain delay."""
        return self._app_set(
            "WRP",
            {
                "value": int(bool(enabled)),
                "time": _clamp(int(delay_hours), 0, 24),
                "sen": _clamp(int(sensitivity), 0, 5),
            },
        )

    def set_charging_period(self, enabled: bool, start_minutes: int, end_minutes: int) -> Any:
        """Restrict charging to a daily window, in minutes after midnight."""
        return self._app_set(
            "BAT",
            {
                "type": "charging",
                "value": [
                    int(bool(enabled)),
                    _clamp(int(start_minutes), 0, 1439),
                    _clamp(int(end_minutes), 0, 1439),
                ],
            },
        )

    def reset_maintenance(self, key: str) -> Any:
        """Zero one maintenance counter, preserving the others."""
        target = next((i for i, item in enumerate(MAINTENANCE_ITEMS) if item[0] == key), None)
        if target is None:
            raise ValueError(f"Unknown maintenance item: {key}")
        values = list(_as_list(self._app_get("CMS")))
        while len(values) < len(MAINTENANCE_ITEMS):
            values.append(0)
        values[target] = 0
        return self._app_set("CMS", {"value": values})

    def install_firmware(self) -> Any:
        """Ask the mower to apply an available firmware update."""
        return self._cloud.install_firmware()

    # -- plumbing -----------------------------------------------------------

    def _action(self, mapping: Mapping[str, int]) -> Any:
        return self._cloud.action(mapping["siid"], mapping["aiid"])

    def _app_get(self, kind: str) -> Any:
        return _app_data(self._cloud.app_action({"m": "g", "t": kind}))

    def _app_set(self, kind: str, data: Mapping[str, Any]) -> Any:
        response = self._cloud.app_action({"m": "s", "t": kind, "d": dict(data)})
        _raise_for_app_result(response, f"setting {kind}")
        return response

    def _task(self, opcode: int, key: str, values: list[Any], label: str) -> Any:
        if not values:
            raise ValueError(f"At least one {label} id is required.")
        response = self._cloud.app_action({"m": "a", "p": 0, "o": opcode, "d": {key: values}})
        _raise_for_app_result(response, f"{label} mowing")
        return response

    def _start_custom(self, status: int, params: Mapping[str, Any]) -> Any:
        payload = [
            {"piid": START_CUSTOM_PIID_STATUS, "value": status},
            {
                "piid": START_CUSTOM_PIID_PARAMS,
                "value": json.dumps(params, separators=(",", ":")),
            },
        ]
        response = self._cloud.action(START_CUSTOM_SIID, START_CUSTOM_AIID, payload)
        _raise_for_app_result(response, f"custom task {status}")
        return response

    @property
    def available(self) -> bool:
        """Return whether the last read or push succeeded."""
        return self._available

    @property
    def connected(self) -> bool:
        """Return whether the push channel is up."""
        return self._connected


# --------------------------------------------------------------------------
# Batch payload decoding
# --------------------------------------------------------------------------


def _decode_map_batch(batch: Mapping[str, Any]) -> dict[int, VectorMap]:
    """Reassemble the chunked map payload into parsed maps.

    Each map record is a JSON array of JSON strings, and ``MAP.info`` holds a
    character offset splitting the primary map from any extras.
    """
    raw = _reassemble(batch, MAP_CHUNK_PREFIX)
    if not raw:
        return {}
    parts = _split(raw, batch.get(f"{MAP_CHUNK_PREFIX}.info"))
    records: list[str] = []
    for part in parts:
        try:
            decoded = json.loads(part)
        except ValueError:
            continue
        if isinstance(decoded, list):
            records.extend(item for item in decoded if isinstance(item, str))

    objects: list[dict[str, Any]] = []
    for record in records:
        try:
            parsed = json.loads(record)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            objects.append(parsed)
    if not objects:
        return {}

    # Re-created maps reuse their index, so the newest record must win.
    by_index: dict[int, dict[str, Any]] = {}
    for obj in objects:
        index = obj.get("mapIndex")
        by_index[int(index) if isinstance(index, int) else len(by_index)] = obj
    available = tuple(
        MapSummary(
            map_id=(int(obj.get("mapIndex", i)) + 1),
            map_index=int(obj.get("mapIndex", i)),
            name=str(obj.get("name") or ""),
            total_area=float(obj.get("totalArea") or 0.0),
        )
        for i, obj in sorted(by_index.items())
    )
    return {
        int(obj.get("mapIndex", i)) + 1: parse_vector_map(obj, available=available)
        for i, obj in by_index.items()
    }


def _reassemble(batch: Mapping[str, Any], prefix: str) -> str:
    """Join ``<prefix>.<n>`` chunks in numeric order."""
    chunks: list[tuple[int, str]] = []
    marker = f"{prefix}."
    for key, value in batch.items():
        if not isinstance(key, str) or not key.startswith(marker):
            continue
        suffix = key[len(marker) :]
        if not suffix.isdigit() or not isinstance(value, str):
            continue
        chunks.append((int(suffix), value))
    chunks.sort(key=lambda item: item[0])
    return "".join(text for _, text in chunks)


def _split(raw: str, info: Any) -> list[str]:
    """Split the joined payload at the character offset in ``<prefix>.info``."""
    offset = _as_int(info)
    if offset is not None and 0 < offset < len(raw):
        return [raw[:offset].strip(), raw[offset:].strip()]
    return [raw.strip()]


def _current_map(maps: Mapping[int, VectorMap]) -> VectorMap | None:
    """Return the newest stored map, which is the one the mower works on."""
    return maps[max(maps)] if maps else None


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def _app_data(response: Any) -> Any:
    """Return the payload of an app-bridge response.

    Responses use ``r`` for the result code and ``d`` for the data, and ``d``
    may itself nest another ``r``/``d`` pair.
    """
    if not isinstance(response, Mapping):
        return None
    data = response.get("d")
    if isinstance(data, Mapping) and "r" in data and "d" in data:
        data = data.get("d")
    return data


def _raise_for_app_result(response: Any, what: str) -> None:
    if not isinstance(response, Mapping):
        return
    code = response.get("r")
    nested = response.get("d")
    if isinstance(nested, Mapping):
        code = nested.get("r", code)
    if isinstance(code, int) and code != 0:
        raise DreameCommandRejectedError(f"Device rejected {what} (code {code})")


def _records(raw: Any) -> list[Mapping[str, Any]]:
    """Normalize a CFG/CMS payload into a list of records."""
    if isinstance(raw, Mapping):
        raw = raw.get("value") or raw.get("list") or []
    return [item for item in _as_list(raw) if isinstance(item, Mapping)]


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    if isinstance(value, Mapping):
        return list(value.values())
    return []


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "on", "yes")
    return False


def _as_str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def _sids(key: str) -> tuple[int, int]:
    """Split a ``"siid.piid"`` property key into its two numbers."""
    siid, _, piid = key.partition(".")
    return int(siid), int(piid)


def _positive(value: int) -> int:
    number = int(value)
    if number < 0:
        raise ValueError("Map identifiers must not be negative.")
    return number


def _mowing_mode(value: Any) -> str | None:
    """Name the ``4.23`` mowing-mode code."""
    modes = {
        0: "standard",
        1: "efficient",
        2: "edge_first",
        3: "zone",
        4: "spot",
        5: "custom",
    }
    number = _as_int(value)
    return modes.get(number) if number is not None else None
