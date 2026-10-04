"""Constants for the Dreame cloud and MQTT protocol."""

from __future__ import annotations

from typing import Final

# --- Cloud endpoints -------------------------------------------------------

CLOUD_HOSTS: Final[dict[str, str]] = {
    "dreame": "iot.dreame.tech",
    "mova": "iot.mova-tech.com",
}

CLOUD_PORT: Final[int] = 13267

REGIONS: Final[list[str]] = ["eu", "us", "cn", "ru", "sg"]


TENANT_IDS: Final[dict[str, str]] = {"dreame": "000000", "mova": "000002"}

# Public vendor client credentials the mobile app presents to the cloud.
CLIENT_BASIC_AUTH: Final[str] = "Basic ZHJlYW1lX2FwcHYxOkFQXmR2QHpAU1FZVnhOODg="
USER_AGENTS: Final[dict[str, str]] = {
    "dreame": "Dreame_Smarthome/1.5.59 (iPhone; iOS 16.0; Scale/3.00)",
    "mova": "Mova_Smarthome/1.5.59 (iPhone; iOS 16.0; Scale/3.00)",
}
# Only sent for the Chinese region.
CN_RLC_HEADER: Final[str] = "1c80b3787b2266776bcdc481f37d8fa42ba10a30af81a6df-1"
PASSWORD_SALT: Final[str] = "RAylYC%fmSKp7%Tq"

AUTH_PATH: Final[str] = "/dreame-auth/oauth/token"
DEVICE_LIST_PATH: Final[str] = "/dreame-user-iot/iotuserbind/device/listV2"
DEVICE_INFO_PATH: Final[str] = "/dreame-user-iot/iotuserbind/device/info"
DEVICE_PERMIT_PATH: Final[str] = "/dreame-user-iot/iotuserbind/queryDevicePermit"
PROPS_PATH: Final[str] = "/dreame-user-iot/iotstatus/props"
BATCH_DATA_PATH: Final[str] = "/dreame-user-iot/iotuserdata/getDeviceData"
OTA_STATUS_PATH: Final[str] = "/dreame-user-iot/iotuserbind/checkDeviceVersion"
OTA_UPDATE_PATH: Final[str] = "/dreame-user-iot/iotuserbind/manualFirmwareUpdate"

API_CODE_OK: Final[int] = 0
# Returned when the cloud accepted the command but the device did not answer
# in time. Treated as "unknown outcome", never as success.
API_CODE_DEVICE_OFFLINE: Final[int] = 80001

DEFAULT_TIMEOUT: Final[float] = 20.0
READ_RETRY_DELAYS: Final[tuple[float, ...]] = (0.25, 1.0)

# --- MQTT ------------------------------------------------------------------

MQTT_KEEPALIVE: Final[int] = 50
MQTT_RECONNECT_DELAY_MIN: Final[int] = 1
MQTT_RECONNECT_DELAY_MAX: Final[int] = 15

# --- App action bridge -----------------------------------------------------
#
# Everything the mobile app plugin talks to goes through a single MIoT-style
# action: method "action", siid 2, aiid 50, with a single {"m", ...} payload.
# "m" is the verb: g = get, s = set, a = action.

APP_ACTION_SIID: Final[int] = 2
APP_ACTION_AIID: Final[int] = 50

# Action opcodes ("o") on the app bridge.
OP_MOW_ZONE: Final[int] = 102
OP_MOW_SPOT: Final[int] = 103
OP_MOW_EDGE: Final[int] = 101

# --- Legacy MIoT actions ---------------------------------------------------
#
# Older firmware (A1 generation) exposes mowing as plain siid/aiid actions
# instead of the app bridge.

ACTION_START_MOWING: Final[dict[str, int]] = {"siid": 5, "aiid": 1}
ACTION_STOP: Final[dict[str, int]] = {"siid": 5, "aiid": 2}
ACTION_DOCK: Final[dict[str, int]] = {"siid": 5, "aiid": 3}
ACTION_PAUSE: Final[dict[str, int]] = {"siid": 5, "aiid": 4}
ACTION_CLEAR_WARNING: Final[dict[str, int]] = {"siid": 4, "aiid": 3}
ACTION_LOCATE: Final[dict[str, int]] = {"siid": 7, "aiid": 1}

# --- Realtime property keys ------------------------------------------------
#
# Cloud property reads and MQTT push messages both address properties as
# "siid.piid".

PROP_RAW_STATUS: Final[str] = "1.1"
PROP_RUNTIME_STATUS: Final[str] = "1.4"
PROP_STATE: Final[str] = "2.1"
PROP_ERROR: Final[str] = "2.2"
PROP_TASK_STATUS: Final[str] = "2.50"
PROP_BATTERY: Final[str] = "3.1"
PROP_CHARGING: Final[str] = "3.2"
PROP_STARTED: Final[str] = "4.1"
PROP_MOWING_MODE: Final[str] = "4.23"
PROP_CLEANING_TIME: Final[str] = "4.2"
PROP_CLEANED_AREA: Final[str] = "4.3"
PROP_SERIAL: Final[str] = "4.14"
PROP_REMOTE_CONTROL: Final[str] = "4.15"
PROP_PAUSED: Final[str] = "4.17"
PROP_MOWING_PROGRESS: Final[str] = "4.63"
PROP_TOTAL_MOWING_TIME: Final[str] = "12.2"
PROP_TOTAL_MOWED_AREA: Final[str] = "12.4"

# Properties polled every coordinator cycle. Keep this list small: each key is
# a separate cloud round trip inside one request.
POLL_PROPERTIES: Final[tuple[str, ...]] = (
    PROP_STATE,
    PROP_ERROR,
    PROP_BATTERY,
    PROP_CHARGING,
    PROP_STARTED,
    PROP_PAUSED,
    PROP_MOWING_MODE,
    PROP_CLEANING_TIME,
    PROP_CLEANED_AREA,
    PROP_MOWING_PROGRESS,
    PROP_TASK_STATUS,
    PROP_TOTAL_MOWING_TIME,
    PROP_TOTAL_MOWED_AREA,
)

# --- Frame decoding --------------------------------------------------------

FRAME_MARKER: Final[int] = 0xCE
HEARTBEAT_LENGTH: Final[int] = 20
RUNTIME_BLOB_LENGTHS: Final[tuple[int, ...]] = (13, 22, 33, 44)
RUNTIME_TASK_OFFSET: Final[int] = 22

DOCKING_STATES: Final[dict[int, str]] = {
    0: "in_station",
    1: "out_of_station",
    2: "docking_paused",
    3: "docking_finished",
    4: "docking_failed",
    5: "docking_in_base",
}

TASK_SUBSTATE_BASE: Final[int] = 33
TASK_STATUSES: Final[dict[int, str]] = {
    0: "idle",
    1: "starting",
    2: "mowing",
    3: "paused",
    4: "finished",
    5: "failed",
    6: "exit",
    7: "returning_to_dock",
}
MOWING_MAIN_STATE: Final[int] = 4
INACTIVE_TASK_STATUSES: Final[frozenset[str]] = frozenset(
    {"idle", "finished", "failed", "exit"}
)

# --- Map -------------------------------------------------------------------

# Map geometry arrives as vector polygons in centimetres inside the cloud batch
# payload, chunked over "<prefix>.<n>" string keys with "<prefix>.info" holding
# a character offset.
MAP_CHUNK_PREFIX: Final[str] = "MAP"
MAP_PATH_PREFIX: Final[str] = "M_PATH"
PATH_SENTINEL: Final[tuple[int, int]] = (32767, -32768)

SHAPE_RECTANGLE: Final[int] = 2
SHAPE_CIRCLE: Final[int] = 3
CIRCLE_SEGMENTS: Final[int] = 36
