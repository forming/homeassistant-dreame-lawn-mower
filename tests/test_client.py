"""Tests for the protocol client: auth, commands, state and map decoding."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from custom_components.dreame_robot.client.cloud import DreameCloud
from custom_components.dreame_robot.client.device import DreameDevice, _decode_map_batch
from custom_components.dreame_robot.client.exceptions import (
    DreameApiError,
    DreameAuthError,
    DreameCommandRejectedError,
    DreameConnectionError,
)
from custom_components.dreame_robot.client.models import (
    ACTIVITY_DOCKED,
    ACTIVITY_ERROR,
    ACTIVITY_IDLE,
    ACTIVITY_MOWING,
    ACTIVITY_PAUSED,
    ACTIVITY_RETURNING,
    CodeTier,
    MapScene,
    RuntimeTelemetry,
    decode_device_code,
    decode_heartbeat,
    decode_runtime,
    parse_path,
    parse_vector_map,
    resolve_activity,
    state_name,
)
from custom_components.dreame_robot.client.render import build_projection, render_scene
from tests.fixture_data import MAP_SIDE, MOCK_DESCRIPTOR, build_batch_payload

# -- authentication ---------------------------------------------------------


def test_password_hash_matches_vendor_salt():
    """The vendor salts the account password with a fixed literal."""
    assert (
        DreameCloud.hash_password("hunter2")
        == "896f62a2c27e7e4de690def77a795d22"  # md5("hunter2" + salt)
    )


def _cloud() -> DreameCloud:
    cloud = DreameCloud("user@example.com", "hunter2", region="eu")
    cloud._session = MagicMock()
    return cloud


def test_login_posts_salted_form_and_stores_token():
    """Login sends a form body and keeps the access token for later calls."""
    cloud = _cloud()
    cloud._session.post.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "access_token": "at-1",
            "refresh_token": "rt-1",
            "expires_in": 3600,
            "uid": "user-1",
            "tenant_id": "000000",
        },
        **{"raise_for_status": lambda: None},
    )
    cloud.login()

    (url,) = cloud._session.post.call_args.args
    kwargs = cloud._session.post.call_args.kwargs
    assert url.endswith("/dreame-auth/oauth/token")
    assert "grant_type=password" in kwargs["data"]
    assert f"password={DreameCloud.hash_password('hunter2')}" in kwargs["data"]
    assert kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert (cloud.access_token, cloud.refresh_token, cloud.user_id) == (
        "at-1",
        "rt-1",
        "user-1",
    )


def test_login_retries_with_password_when_refresh_token_is_rejected():
    """A dead refresh token must not strand the integration."""
    cloud = _cloud()
    cloud.refresh_token = "stale"
    responses = [
        MagicMock(status_code=200, json=lambda: {"error_description": "invalid refresh token"}),
        MagicMock(status_code=200, json=lambda: {"access_token": "at-2", "expires_in": 60}),
    ]
    cloud._session.post.side_effect = responses
    cloud.login()

    assert cloud.access_token == "at-2"
    assert cloud.refresh_token is None
    assert cloud._session.post.call_count == 2


def test_login_raises_on_hard_failure():
    """A credential rejection surfaces as an auth error, not a crash."""
    cloud = _cloud()
    cloud._session.post.return_value = MagicMock(
        status_code=200, json=lambda: {"error_description": "wrong password"}
    )
    with pytest.raises(DreameAuthError, match="wrong password"):
        cloud.login()


def test_cn_region_adds_rlc_header():
    """Chinese-region requests carry the extra vendor routing header."""
    cloud = DreameCloud("u", "p", region="cn")
    assert cloud._headers(authenticated=False)["Dreame-Rlc"]
    eu = DreameCloud("u", "p", region="eu")._headers(authenticated=False)
    assert "Dreame-Rlc" not in eu


# -- commands ---------------------------------------------------------------


def test_action_builds_send_command_envelope():
    """A command is wrapped in the vendor's doubled-id envelope."""
    cloud = _cloud()
    cloud.access_token = "at"
    cloud._expires_at = float("inf")
    cloud.did = "did-1"
    cloud.host = "mqtt.eu.dreame.tech:8883"
    cloud._post = MagicMock(return_value={"code": 0, "data": {"result": "ok"}})

    assert cloud.action(5, 1) == "ok"
    path, payload = cloud._post.call_args.args
    assert path == "/dreame-iot-com-mqtt/device/sendCommand"
    assert payload["data"]["method"] == "action"
    assert payload["data"]["params"]["siid"] == 5
    assert payload["data"]["params"]["aiid"] == 1
    assert payload["id"] == payload["data"]["id"]


def test_offline_code_is_treated_as_rejection():
    """Code 80001 means the device never answered, which is not success."""
    cloud = _cloud()
    cloud.access_token = "at"
    cloud._expires_at = float("inf")
    cloud.did = "did-1"
    cloud.host = "host:8883"
    cloud._post = MagicMock(return_value={"code": 80001, "data": None})
    with pytest.raises(DreameCommandRejectedError):
        cloud.action(5, 3)


def test_api_error_carries_cloud_code():
    """A non-zero API code keeps the vendor code for diagnostics."""
    cloud = _cloud()
    cloud.access_token = "at"
    cloud._expires_at = float("inf")
    cloud.did = "did-1"
    cloud.host = "host:8883"
    cloud._post = MagicMock(return_value={"code": 10007, "msg": "not ready"})
    with pytest.raises(DreameApiError) as err:
        cloud.action(5, 1)
    assert err.value.code == 10007


def test_reads_retry_but_mutations_do_not():
    """Duplicate writes could apply twice on the device, so they never retry."""
    cloud = _cloud()
    cloud.access_token = "at"
    cloud._expires_at = float("inf")
    cloud.did = "did-1"
    cloud.host = "host:8883"
    cloud._post = MagicMock(return_value={"code": 0, "data": {}})

    cloud.app_action({"m": "g", "t": "CFG"})
    assert cloud._post.call_args.kwargs["retries"] == 2
    cloud.app_action({"m": "s", "t": "VOL", "d": {"value": 10}})
    assert cloud._post.call_args.kwargs["retries"] == 0


def test_401_triggers_reauthentication():
    """An expired token is refreshed transparently on the next attempt."""
    cloud = _cloud()
    cloud.access_token = "stale"
    cloud._expires_at = float("inf")
    cloud.did = "did-1"
    cloud.host = "host:8883"
    cloud.login = MagicMock(
        side_effect=lambda **kw: setattr(cloud, "_expires_at", float("inf"))
    )
    responses = [
        MagicMock(status_code=401, json=lambda: {}),
        MagicMock(status_code=200, json=lambda: {"code": 0, "data": {"result": 1}}),
    ]
    cloud._session.post.side_effect = responses

    assert cloud.app_action({"m": "a", "p": 0, "o": 5}) == 1
    cloud.login.assert_called_once()


def test_list_devices_filters_non_mowers():
    """Only models tagged as mowers are offered in the config flow."""
    cloud = _cloud()
    cloud._ensure_login = lambda: None
    cloud._post = MagicMock(
        return_value={
            "page": {
                "records": [
                    {
                        "did": "1",
                        "model": "dreame.mower.g2408",
                        "mac": "a",
                        "customName": "Mower",
                        "bindDomain": "mqtt.host:8883",
                        "masterUid": "u",
                    },
                    {"did": "2", "model": "dreame.vacuum.s5", "customName": "Vac"},
                ]
            }
        }
    )
    devices = cloud.list_devices()
    assert [d.model for d in devices] == ["dreame.mower.g2408"]


# -- device commands --------------------------------------------------------


def _device() -> DreameDevice:
    device = DreameDevice(MOCK_DESCRIPTOR, "u", "p")
    device._cloud = MagicMock()
    device._cloud.app_action.return_value = {"r": 0, "d": {}}
    return device


def test_zone_mowing_sends_region_ids():
    """Zone mowing uses opcode 102 with a region target list."""
    device = _device()
    device.mow_zones([3, 1])
    payload = device._cloud.app_action.call_args.args[0]
    assert payload == {"m": "a", "p": 0, "o": 102, "d": {"region": [3, 1]}}


def test_edge_mowing_requires_pairs():
    """An edge id without its contour index cannot be sent."""
    device = _device()
    with pytest.raises(ValueError):
        device.mow_contours([[1]])
    device.mow_contours([[1, 0]])
    payload = device._cloud.app_action.call_args.args[0]
    assert payload["d"] == {"edge": [[1, 0]]}


def test_go_to_uses_cruise_point_task():
    """Driving to a point uses the cruise-point custom task."""
    device = _device()
    device.go_to(120, 340)
    siid, aiid, params = device._cloud.action.call_args.args
    assert (siid, aiid) == (4, 1)
    assert params[0] == {"piid": 1, "value": 23}
    assert json.loads(params[1]["value"]) == {"tpoint": [[120, 340, 0, 0]]}


def test_negative_map_ids_are_rejected():
    """Map identifiers arrive from user input, so they are validated."""
    device = _device()
    with pytest.raises(ValueError):
        device.mow_zones([-1])


def test_rejected_task_raises():
    """A non-zero app result code is reported, not swallowed."""
    device = _device()
    device._cloud.app_action.return_value = {"r": 7, "d": {}}
    with pytest.raises(DreameCommandRejectedError, match="zone mowing"):
        device.mow_zones([1])


def test_remote_control_clamps_and_encodes():
    """Manual drive steps are clamped and use the vendor's JSON property."""
    device = _device()
    device.remote_control(9999, -9999)
    siid, piid, value = device._cloud.set_property.call_args.args
    assert (siid, piid) == (4, 15)
    assert json.loads(value) == {"spdv": 1000, "spdw": -1000, "audio": "false", "random": 0}


def test_settings_are_indexed_by_record_type():
    """CFG records arrive positionally and are keyed by their type tag."""
    device = _device()
    device._cloud.app_action.return_value = {
        "r": 0,
        "d": [{"t": "VOL", "d": {"value": 40}}, {"t": "WRP", "d": [1, 6, 3]}],
    }
    assert device.refresh_settings() == {"VOL": {"value": 40}, "WRP": [1, 6, 3]}


def test_maintenance_remaining_is_derived_from_used_minutes():
    """Counters report minutes used against a fixed interval."""
    device = _device()
    device._cloud.app_action.return_value = {"r": 0, "d": [0, 15000, 3300]}
    items = device.refresh_maintenance()
    assert [item["key"] for item in items] == ["blade", "brush", "robot"]
    assert items[0]["remaining_minutes"] == 6000
    assert items[1]["remaining_percent"] == 50.0
    assert items[2]["warning"] is True


# -- state decoding ---------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "expected"),
    [(1, ACTIVITY_MOWING), (2, ACTIVITY_DOCKED), (3, ACTIVITY_PAUSED), (5, ACTIVITY_RETURNING)],
)
def test_state_codes_map_to_activity(code, expected):
    """Known state codes collapse onto Home Assistant activities."""
    assert resolve_activity(state_name(code)) == expected


def test_mapping_state_counts_as_mowing():
    """An active mapping run is work in progress, not an idle mower."""
    assert resolve_activity("mapping") == ACTIVITY_MOWING


def test_error_code_outranks_state():
    """A confirmed fault is never masked by a stale activity field."""
    assert resolve_activity("mowing", error_tier=CodeTier.ERROR) == ACTIVITY_ERROR


def test_returning_with_charging_is_docked():
    """The state field lags when the mower is already back on the dock."""
    assert resolve_activity("returning", charging=True) == ACTIVITY_DOCKED


def test_unknown_state_falls_back_to_idle():
    """An unrecognised code must not invent a mowing activity."""
    assert resolve_activity("teleporting") == ACTIVITY_IDLE


def test_model_specific_state_overrides():
    """Some models reuse codes 15/16/19 for repositioning."""
    assert state_name(19, "mova.mower.g2583") == "repositioning"
    assert state_name(19, "mova.mower.g2529f") == "repositioning"
    # Unclaimed on models that never documented it.
    assert state_name(19, "dreame.mower.g2408") is None
    assert state_name(16, "mova.mower.g2583") == "repositioning"


def test_device_code_tiers():
    """Fault severity decides whether an activity becomes an error."""
    assert decode_device_code(4).tier == CodeTier.ERROR
    assert decode_device_code(28).tier == CodeTier.ATTENTION
    assert decode_device_code(46).tier == CodeTier.INFO
    assert decode_device_code(-1) is None


def test_unknown_device_code_is_named_not_guessed():
    """An unrecognised code is reported, never invented."""
    decoded = decode_device_code(9999)
    assert decoded.name == "unknown_device_code_9999"
    assert decoded.tier == CodeTier.ATTENTION


def test_a2_override_reclassifies_lift_code():
    """Model-specific firmware overrides win over the shared table."""
    assert decode_device_code(0, "dreame.mower.g2408").name == "robot_lifted"
    assert decode_device_code(0, "dreame.mower.p2255").name == "no_device_code"


# -- framed payloads --------------------------------------------------------


def test_heartbeat_decodes_battery_and_task():
    """The 20-byte heartbeat carries battery, docking and task state."""
    raw = [0xCE, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x80 + 80, 0x05, 0x23, 0x00, 0, 0, 0, 0, 0xCE]
    result = decode_heartbeat(raw)
    assert result["battery_level"] == 80
    assert result["charging"] is True
    assert result["docked"] is True
    assert result["task_status"] == "mowing"


def test_heartbeat_rejects_bad_frame():
    """A payload without the frame markers is not a heartbeat."""
    assert decode_heartbeat([0, 1, 2, 3]) == {}


def test_runtime_pose_uses_overlapping_20_bit_fields():
    """The pose packs x and y into six overlapping bytes, in centimetres."""
    b0, b1, b2, b3, b4 = 0x40, 0x23, 0x01, 0x00, 0x00
    raw = [0xCE, b0, b1, b2, b3, b4, 0x80, *([0] * 5), 0xCE]
    decoded = decode_runtime(raw)
    assert decoded is not None
    telemetry, task = decoded
    # x_raw = (b2 << 28) | (b1 << 20) | (b0 << 12) = 0x12340000, >> 12 = 0x12340.
    assert telemetry.x == 0x12340 * 10
    assert telemetry.y == 0
    assert task is None


def test_runtime_task_block_decodes_progress():
    """A 33-byte runtime frame carries the mission progress block."""
    raw = [0xCE] + [0] * 32
    raw[-1] = 0xCE
    raw[22:32] = [2, 1, 50, 0, 100, 0, 0, 25, 0, 0]
    _, task = decode_runtime(raw)
    assert task.region_id == 2
    assert task.progress_percent == 5.0
    assert task.total_area_sqm == 1.0
    assert task.current_area_sqm == 0.25


def test_non_runtime_frame_is_ignored():
    """A heartbeat-length payload is not treated as runtime telemetry."""
    assert decode_runtime([0xCE] * 20) is None


# -- map decoding -----------------------------------------------------------


def test_batch_chunks_reassemble_into_both_maps():
    """Chunked keys join in numeric order and split at the info offset."""
    maps = _decode_map_batch(build_batch_payload())
    assert sorted(maps) == [1, 2]
    assert maps[1].name == "Front lawn"
    assert maps[2].name == "Side lawn"
    assert maps[1].total_area == 128.4


def test_map_ids_are_index_plus_one():
    """Home Assistant keys entities by a stable one-based map id."""
    maps = _decode_map_batch(build_batch_payload())
    assert maps[1].map_index == 0
    assert maps[2].map_index == 1


def test_newest_generation_wins_for_a_reused_index():
    """Re-created maps reuse their index, so the last record must win."""
    stale = dict(MAP_SIDE, name="Side lawn (old)")
    fresh = dict(MAP_SIDE, name="Side lawn")
    raw = json.dumps([json.dumps(stale), json.dumps(fresh)], separators=(",", ":"))
    maps = _decode_map_batch({"MAP.0": raw, "MAP.info": "999"})
    assert maps[2].name == "Side lawn"


def test_polygon_collections_are_unwrapped():
    """Zones, forbidden areas and spot areas all use the Map wrapper."""
    raw = json.loads(
        json.dumps(
            {
                "mapIndex": 0,
                "mowingAreas": {
                    "dataType": "Map",
                    "value": [[7, {"name": "A", "path": [[0, 0], [10, 0], [10, 10]]}]],
                },
                "forbiddenAreas": {
                    "dataType": "Map",
                    "value": [[8, {"name": "F", "path": [[0, 0], [5, 0], [5, 5]]}]],
                },
                "spotAreas": {
                    "dataType": "Map",
                    "value": [[9, {"name": "S", "path": [[0, 0], [3, 0], [3, 3]]}]],
                },
            }
        )
    )
    vector_map = parse_vector_map(raw)
    assert [p.id for p in vector_map.zones] == [7]
    assert [p.id for p in vector_map.forbidden] == [8]
    assert [p.id for p in vector_map.spots] == [9]


def test_circle_shape_expands_to_36_points():
    """A circle arrives as a bounding box and is expanded at parse time."""
    raw = {
        "mapIndex": 0,
        "forbiddenAreas": {
            "dataType": "Map",
            "value": [[1, {"shapeType": 3, "path": [[0, 0], [100, 100]]}]],
        },
    }
    circle = parse_vector_map(raw).forbidden[0]
    assert circle.shape == 3
    assert len(circle.points) == 36
    assert circle.points[0] == (100, 50)  # angle 0 points due east


def test_contour_keys_accept_both_shapes():
    """Contour keys appear as ``[edge, index]`` or ``"edge,index"``."""
    raw = {
        "mapIndex": 0,
        "contours": {
            "dataType": "Map",
            "value": [
                ["1,0", {"path": [[0, 0], [10, 0]]}],
                [[2, 3], {"path": [[0, 0], [0, 10]]}],
            ],
        },
    }
    contours = parse_vector_map(raw).contours
    assert [c.name for c in contours] == ["Edge 1.0", "Edge 2.3"]


def test_boundary_covers_every_geometry():
    """The map boundary is the bounding box of all drawn geometry."""
    maps = _decode_map_batch(build_batch_payload())
    x1, y1, x2, y2 = maps[1].boundary
    assert (x1, y1, x2, y2) == (0, 0, 1900, 1100)


def test_path_trail_respects_the_discontinuity_sentinel():
    """The trail blob marks a gap with a sentinel pair and uses decimetres."""
    segments = parse_path("[[10,20],[30,40],[32767,-32768],[50,60]]")
    assert segments == (((100, 200), (300, 400)), ((500, 600),))


def test_garbage_batch_payload_yields_no_maps():
    """Undecodable map text must not raise out of the poll cycle."""
    assert _decode_map_batch({"MAP.0": "not json", "MAP.info": "8"}) == {}


# -- network plumbing -------------------------------------------------------


def test_http_failure_becomes_connection_error():
    """A transport failure surfaces as a typed client error."""
    cloud = _cloud()
    cloud._ensure_login = lambda: None
    with (
        patch.object(requests.Session, "post", side_effect=requests.ConnectionError("boom")),
        pytest.raises(DreameConnectionError),
    ):
        cloud.list_devices()


# -- coordinate encodings ---------------------------------------------------


def test_paths_accept_both_coordinate_encodings():
    """Firmware writes ``{"x", "y"}`` objects; older payloads use pairs."""
    pairs = parse_vector_map(
        {
            "mapIndex": 0,
            "mowingAreas": {
                "dataType": "Map",
                "value": [[1, {"path": [[0, 0], [100, 0], [100, 100]]}]],
            },
        }
    )
    objects = parse_vector_map(
        {
            "mapIndex": 0,
            "mowingAreas": {
                "dataType": "Map",
                "value": [
                    [1, {"path": [{"x": 0, "y": 0}, {"x": 100, "y": 0}, {"x": 100, "y": 100}]}]
                ],
            },
        }
    )
    assert pairs.zones[0].points == objects.zones[0].points == ((0, 0), (100, 0), (100, 100))


def test_cruise_points_are_read_from_the_map_wrapper():
    """Cruise points are id/point pairs inside the shared Map envelope."""
    vector_map = parse_vector_map(
        {
            "mapIndex": 0,
            "mowingAreas": {
                "dataType": "Map",
                "value": [[1, {"path": [[0, 0], [10, 0], [10, 10]]}]],
            },
            "cruisePoints": {
                "dataType": "Map",
                "value": [[1, {"x": 5, "y": 6}], [2, {"x": 7, "y": 8}]],
            },
        }
    )
    assert vector_map.points == ((5, 6), (7, 8))


def test_circle_bbox_is_taken_from_all_corners():
    """A circle may arrive as two corners or four; both must give a real circle."""

    def pond(path):
        return parse_vector_map(
            {
                "mapIndex": 0,
                "forbiddenAreas": {
                    "dataType": "Map",
                    "value": [[1, {"shapeType": 3, "path": path}]],
                },
            }
        ).forbidden[0]

    two_corners = pond([[400, 400], [700, 700]])
    four_corners = pond([[400, 400], [700, 400], [700, 700], [400, 700]])
    assert len(two_corners.points) == len(four_corners.points) == 36
    assert two_corners.center == four_corners.center == (550.0, 550.0)
    xs = [p[0] for p in two_corners.points]
    ys = [p[1] for p in two_corners.points]
    assert (min(xs), max(xs)) == (400, 700)
    assert (min(ys), max(ys)) == (400, 700)


def test_non_finite_map_geometry_is_rejected():
    """A path full of non-numbers must not produce a phantom zone."""
    vector_map = parse_vector_map(
        {
            "mapIndex": 0,
            "mowingAreas": {
                "dataType": "Map",
                "value": [[1, {"path": [["a", "b"], [None, 1]]}]],
            },
        }
    )
    assert vector_map.zones == ()


# -- rendering --------------------------------------------------------------


def test_render_produces_a_png():
    """The map renderer emits a valid PNG for a map with geometry."""
    maps = _decode_map_batch(build_batch_payload())
    png = render_scene(MapScene(vector_map=maps[1], runtime=RuntimeTelemetry(900, 500, 45)))
    assert png is not None
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_render_returns_nothing_without_geometry():
    """An empty map must not produce a blank image."""
    empty = parse_vector_map({"mapIndex": 0, "name": "Empty"})
    assert render_scene(MapScene(vector_map=empty)) is None


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_projection_round_trips_at_every_rotation(rotation):
    """The card inverts the projection, so the round trip must be lossless."""
    maps = _decode_map_batch(build_batch_payload())
    projection = build_projection(maps[1], rotation)
    assert projection.rotation == rotation
    for native in ((0, 0), (1900, 1100), (600, 400)):
        x, y = projection.point(*native)
        back = projection.inverse(x, y)
        assert abs(back[0] - native[0]) < 1
        assert abs(back[1] - native[1]) < 1
