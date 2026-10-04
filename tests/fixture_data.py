"""Shared fixtures for the Dreame Robot integration tests."""

from __future__ import annotations

import json
from typing import Any

import pytest

from custom_components.dreame_robot.client.models import DeviceDescriptor

MOCK_CONFIG_ENTRY_DATA: dict[str, Any] = {
    "account_type": "dreame",
    "region": "eu",
    "did": "1234567890",
    "mac": "aa:bb:cc:dd:ee:ff",
    "model": "dreame.mower.g2408",
    "name": "Back garden",
    "host": "mqtt.eu.dreame.tech:8883",
    "username": "user@example.com",
    "password": "hunter2",
}

MOCK_DESCRIPTOR = DeviceDescriptor(
    did="1234567890",
    model="dreame.mower.g2408",
    mac="aa:bb:cc:dd:ee:ff",
    name="Back garden",
    host="mqtt.eu.dreame.tech:8883",
    uid="master-uid-1",
    account_type="dreame",
    region="eu",
    firmware="4.3.6_0320",
)


def PTS(coords: list[list[int]]) -> list[dict[str, int]]:
    """Build a path in the ``{"x": ..., "y": ...}`` form firmware writes."""
    return [{"x": c[0], "y": c[1]} for c in coords]


# A two-map batch payload shaped like the real cloud response: each map record
# is a JSON array of JSON strings, split at the character offset in MAP.info.
MAP_FRONT = {
    "mapIndex": 0,
    "name": "Front lawn",
    "totalArea": 128.4,
    "currentMapId": 2,
    "mowingAreas": {
        "dataType": "Map",
        "value": [
            [
                1,
                {
                    "name": "Zone A",
                    "area": 84.2,
                    "path": PTS([[0, 0], [1200, 0], [1200, 900], [0, 900]]),
                },
            ],
            [
                2,
                {
                    "name": "Zone B",
                    "area": 44.2,
                    "path": PTS([[1300, 0], [1900, 0], [1900, 700], [1300, 700]]),
                },
            ],
        ],
    },
    "forbiddenAreas": {
        "dataType": "Map",
        "value": [
            [
                1,
                {
                    "name": "Pond",
                    "shapeType": 3,
                    "path": PTS([[400, 400], [700, 400], [700, 700], [400, 700]]),
                },
            ]
        ],
    },
    "spotAreas": {
        "dataType": "Map",
        "value": [
            [1, {"name": "Under tree", "path": PTS([[1500, 900], [1700, 900], [1700, 1100]])}]
        ],
    },
    "paths": {"dataType": "Map", "value": [[1, {"path": [[1200, 450], [1300, 350]]}]]},
    "contours": {
        "dataType": "Map",
        "value": [
            ["1,0", {"path": PTS([[0, 0], [1900, 0], [1900, 1100], [0, 1100], [0, 0]])}],
            [2, {"path": PTS([[0, 0], [0, 400]])}],
        ],
    },
    "cruisePoints": {
        "dataType": "Map",
        "value": [[1, {"x": 800, "y": 200}], [2, {"x": 1600, "y": 500}]],
    },
}

MAP_SIDE = {
    "mapIndex": 1,
    "name": "Side lawn",
    "totalArea": 41.0,
    "mowingAreas": {
        "dataType": "Map",
        "value": [
            [
                1,
                {
                    "name": "Side",
                    "area": 41.0,
                    "path": PTS([[0, 0], [600, 0], [600, 500], [0, 500]]),
                },
            ]
        ],
    },
}


def build_batch_payload() -> dict[str, str]:
    """Return a chunked batch payload holding both fixture maps."""
    primary = json.dumps([json.dumps(MAP_FRONT, separators=(",", ":"))], separators=(",", ":"))
    secondary = json.dumps([json.dumps(MAP_SIDE, separators=(",", ":"))], separators=(",", ":"))
    raw = primary + secondary
    chunks = [raw[i : i + 64] for i in range(0, len(raw), 64)]
    payload = {f"MAP.{i}": chunk for i, chunk in enumerate(chunks)}
    payload["MAP.info"] = str(len(primary))
    payload["M_PATH.0"] = "[[100,200],[300,400],[32767,-32768],[500,600]]"
    payload["M_PATH.info"] = "0"
    return payload


@pytest.fixture
def descriptor() -> DeviceDescriptor:
    """Return the mocked cloud device descriptor."""
    return MOCK_DESCRIPTOR


@pytest.fixture
def map_batch() -> dict[str, str]:
    """Return the mocked chunked batch map payload."""
    return build_batch_payload()
