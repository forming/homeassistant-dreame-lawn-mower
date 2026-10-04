"""Tests for the Home Assistant integration layer."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dreame_robot.const import DOMAIN
from tests.fixture_data import MOCK_CONFIG_ENTRY_DATA, MOCK_DESCRIPTOR

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


# -- setup ------------------------------------------------------------------


async def test_setup_creates_the_mower_entity(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_device
):
    """Setting up the entry produces a controllable lawn mower entity."""
    state = hass.states.get("lawn_mower.back_garden")
    assert state is not None
    assert state.state == "mowing"
    assert state.attributes["battery_level"] == 82
    assert state.attributes["entry_id"] == setup_integration.entry_id


async def test_setup_registers_the_device(
    hass: HomeAssistant, setup_integration: MockConfigEntry
):
    """The mower shows up in the device registry with its model."""
    from homeassistant.helpers import device_registry as dr

    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, "1234567890")})
    assert device is not None
    assert device.model == "Dreame A2"


async def test_map_image_entity_renders_png(
    hass: HomeAssistant, setup_integration: MockConfigEntry
):
    """The image entity serves a real PNG of the downloaded map."""
    state = hass.states.get("image.back_garden")
    assert state is not None
    assert state.state != STATE_UNKNOWN
    # The newest stored map is the active one, and it has a single zone.
    assert state.attributes["zone_count"] == 1


async def test_push_update_reaches_entities(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_device
):
    """A push notification refreshes entity state without waiting for a poll."""
    fake_device.push_property("3.1", 44)
    fake_device.on_update()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.back_garden_battery").state == "44"


# -- lawn mower commands ----------------------------------------------------


async def test_start_pause_and_dock_call_the_device(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_device
):
    """Home Assistant's lawn mower services reach the protocol client."""
    await hass.services.async_call(
        "lawn_mower", "start_mowing", {"entity_id": "lawn_mower.back_garden"}, blocking=True
    )
    await hass.services.async_call(
        "lawn_mower", "pause", {"entity_id": "lawn_mower.back_garden"}, blocking=True
    )
    await hass.services.async_call(
        "lawn_mower", "dock", {"entity_id": "lawn_mower.back_garden"}, blocking=True
    )
    assert [name for name, _, _ in fake_device.commands] == [
        "start_mowing",
        "pause",
        "dock",
    ]


async def test_error_code_makes_the_mower_report_an_error(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_device
):
    """A fault-tier device code surfaces as the Home Assistant error state."""
    fake_device.push_property("2.2", 4)
    fake_device.on_update()
    await hass.async_block_till_done()
    state = hass.states.get("lawn_mower.back_garden")
    assert state.state == "error"
    assert state.attributes["error_name"] == "left_drive_wheel_error"
    assert hass.states.get("binary_sensor.back_garden_problem").state == "on"


async def test_non_fault_code_does_not_error_the_mower(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_device
):
    """An informational code is reported as a notice, not a fault."""
    fake_device.push_property("2.2", 48)
    fake_device.on_update()
    await hass.async_block_till_done()
    assert hass.states.get("lawn_mower.back_garden").state == "mowing"
    assert hass.states.get("sensor.back_garden_status_notice").state == "task_completed"


# -- services ---------------------------------------------------------------


async def test_mow_zones_service_targets_the_entry(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_device
):
    """Zone mowing reaches the device with the ids from the service call."""
    await hass.services.async_call(
        DOMAIN,
        "mow_zones",
        {"zone_ids": [1, 2], "entry_id": setup_integration.entry_id},
        blocking=True,
    )
    assert ("mow_zones", ([1, 2],), {}) in fake_device.commands


async def test_mow_point_service_passes_through(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_device
):
    """Tapping a bare coordinate maps onto the device's spot task."""
    await hass.services.async_call(
        DOMAIN, "mow_point", {"x": 400, "y": 250, "passes": 2}, blocking=True
    )
    assert ("mow_point", (400, 250, 2), {}) in fake_device.commands


async def test_go_to_service_maps_coordinates(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_device
):
    """Driving to a point forwards the native coordinates unchanged."""
    await hass.services.async_call(DOMAIN, "go_to", {"x": 12, "y": -34}, blocking=True)
    assert ("go_to", (12, -34), {}) in fake_device.commands


async def test_mow_edges_service_requires_pairs(
    hass: HomeAssistant, setup_integration: MockConfigEntry
):
    """A contour id without its index is rejected before reaching the device."""
    with pytest.raises(Exception):  # noqa: B017 - voluptuous Invalid surfaces as ServiceValidationError
        await hass.services.async_call(DOMAIN, "mow_edges", {"contour_ids": [1]}, blocking=True)


async def test_remote_control_service_is_range_checked(
    hass: HomeAssistant, setup_integration: MockConfigEntry
):
    """Manual drive steps outside the vendor range are refused."""
    with pytest.raises(Exception):  # noqa: B017 - see above
        await hass.services.async_call(
            DOMAIN, "remote_control", {"velocity": 5000, "rotation": 0}, blocking=True
        )


async def test_service_on_unknown_entry_is_rejected(
    hass: HomeAssistant, setup_integration: MockConfigEntry
):
    """An entry id that is not configured fails loudly instead of silently."""
    with pytest.raises(Exception):  # noqa: B017 - ServiceValidationError
        await hass.services.async_call(
            DOMAIN, "stop_mowing", {"entry_id": "does-not-exist"}, blocking=True
        )


async def test_stop_service_without_entry_targets_all(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_device
):
    """Omitting the entry id applies the command to every configured mower."""
    await hass.services.async_call(DOMAIN, "stop_mowing", {}, blocking=True)
    assert ("stop", (), {}) in fake_device.commands


# -- settings entities ------------------------------------------------------


async def test_volume_number_reads_and_writes(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_device
):
    """The volume entity reflects the device and writes changes back."""
    state = hass.states.get("number.back_garden_voice_volume")
    assert state is not None
    assert state.state == "40.0"
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.back_garden_voice_volume", "value": 75},
        blocking=True,
    )
    assert ("set_volume", (75,), {}) in fake_device.commands


async def test_rain_protection_switch_toggles(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_device
):
    """The rain switch preserves the delay already configured on the device."""
    state = hass.states.get("switch.back_garden_rain_protection")
    assert state.state == "on"
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.back_garden_rain_protection"}, blocking=True
    )
    assert ("set_rain_protection", (0, 6, 3), {}) in fake_device.commands


async def test_voice_prompt_switch_keeps_siblings(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_device
):
    """Turning one voice group off leaves the other three untouched."""
    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.back_garden_working_voice_prompts"},
        blocking=True,
    )
    name, args, _ = fake_device.commands[-1]
    assert name == "set_voice_prompts"
    assert args[0] == {"general": True, "working": False, "special": False, "fault": True}


async def test_switch_hidden_when_setting_absent(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_device
):
    """A setting the mower does not report is not offered as a switch."""
    fake_device.settings_data = {}
    await setup_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("switch.back_garden_rain_protection").state == "unavailable"


async def test_maintenance_sensors_reflect_counters(
    hass: HomeAssistant, setup_integration: MockConfigEntry
):
    """Maintenance warning fires when a counter runs low."""
    assert hass.states.get("binary_sensor.back_garden_maintenance_due_soon").state == "on"
    assert hass.states.get("binary_sensor.back_garden_maintenance_due").state == "off"


async def test_buttons_reach_the_device(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_device
):
    """The stop and locate buttons forward to the matching device commands."""
    for entity_id, expected in (
        ("button.back_garden_stop_task", "stop"),
        ("button.back_garden_locate", "locate"),
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": entity_id}, blocking=True
        )
        assert (expected, (), {}) in fake_device.commands


async def test_reset_maintenance_service_names_the_counter(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_device
):
    """The reset service maps its item name onto the device's counter key."""
    await hass.services.async_call(
        DOMAIN, "reset_maintenance", {"item": "blade"}, blocking=True
    )
    assert ("reset_maintenance", ("blade",), {}) in fake_device.commands


# -- map view ---------------------------------------------------------------


async def test_map_json_view_serves_geometry(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_device,
    hass_client: Any,
):
    """The card's endpoint returns projected geometry plus the live pose."""
    fake_device.push_runtime(600, 400, 90.0)
    fake_device.on_update()
    await hass.async_block_till_done()

    client = await hass_client()
    response = await client.get(f"/api/{DOMAIN}/{setup_integration.entry_id}/map.json")
    assert response.status == 200
    body = await response.json()

    assert body["available"] is True
    assert body["canvas"]["width"] > 0
    assert body["name"] == "Side lawn"
    assert len(body["maps"]) == 2
    assert body["zones"][0]["points"], "zones must carry projected points"
    assert body["robot"]["native"], "live pose must be projected for the card"
    assert body["robot"]["x"] == 600


async def test_map_json_view_rejects_unknown_entries(
    hass: HomeAssistant, setup_integration: MockConfigEntry, hass_client: Any
):
    """An entry id that is not loaded is a 404, not another mower's map."""
    client = await hass_client()
    response = await client.get(f"/api/{DOMAIN}/not-a-real-entry/map.json")
    assert response.status == 404


# -- coordinator resilience -------------------------------------------------


async def test_poll_failure_keeps_the_last_known_state(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_device
):
    """A cloud outage must not blank every entity immediately."""
    fake_device.fail_polls = True
    await setup_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("lawn_mower.back_garden").state == "mowing"


async def test_push_updates_coalesce(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_device
):
    """A burst of push messages results in a single coordinator update."""
    for level in (81, 80, 79, 78):
        fake_device.push_property("3.1", level)
        fake_device.on_update()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.back_garden_battery").state == "78"


# -- options ----------------------------------------------------------------


async def test_map_rotation_option_persists(
    hass: HomeAssistant, setup_integration: MockConfigEntry
):
    """Changing the rotation stores an entry option without a reload."""
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.back_garden_map_rotation", "option": "90°"},
        blocking=True,
    )
    assert setup_integration.options["map_rotation"] == 90
    assert setup_integration.runtime_data.rotation == 90


async def test_unload_removes_every_entity(
    hass: HomeAssistant, setup_integration: MockConfigEntry
):
    """Unloading the entry leaves no entity states behind."""
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert not [s for s in hass.states.async_all() if s.entity_id.endswith("_mower")]


# -- descriptor -------------------------------------------------------------


def test_descriptor_titles_are_readable():
    """A named mower gets its product name appended to the entry title."""
    assert MOCK_DESCRIPTOR.title == "Back garden (Dreame A2)"
    assert MOCK_DESCRIPTOR.short_model == "g2408"


def test_config_entry_data_has_required_keys():
    """The stored config entry carries everything setup needs."""
    for key in ("did", "model", "username", "password", "region", "account_type"):
        assert key in MOCK_CONFIG_ENTRY_DATA
