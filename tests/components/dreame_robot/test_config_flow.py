"""Tests for the Dreame Robot config flow."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest
from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dreame_robot.client.exceptions import (
    DreameAuthError,
    DreameConnectionError,
)
from custom_components.dreame_robot.config_flow import error_key
from custom_components.dreame_robot.const import DOMAIN
from tests.fixture_data import MOCK_DESCRIPTOR

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

CREDENTIALS = {
    "account_type": "dreame",
    "region": "eu",
    "username": "user@example.com",
    "password": "hunter2",
}


def _discovery(*devices, error: Exception | None = None):
    """Patch discovery to return canned devices or raise."""

    async def _run(_username, _password, _region, _account_type):
        if error is not None:
            raise error
        return list(devices)

    return patch("custom_components.dreame_robot.config_flow.async_discover_devices", _run)


async def test_single_mower_creates_the_entry_immediately(hass: HomeAssistant):
    """One mower on the account needs no second step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"

    with _discovery(MOCK_DESCRIPTOR):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
        await hass.async_block_till_done()

    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Back garden (Dreame A2)"
    assert result["data"]["did"] == "1234567890"
    assert result["data"]["model"] == "dreame.mower.g2408"
    assert result["data"]["region"] == "eu"


async def test_multiple_mowers_ask_which_one(hass: HomeAssistant):
    """Two mowers on the account produce a picker."""
    other = replace(MOCK_DESCRIPTOR, did="9999", name="Front lawn")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with _discovery(MOCK_DESCRIPTOR, other):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "device"

    with _discovery(MOCK_DESCRIPTOR, other):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"device": other.did}
        )
    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"]["did"] == "9999"


async def test_bad_credentials_show_cannot_auth(hass: HomeAssistant):
    """A rejected password surfaces the auth error, not a crash."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with _discovery(error=DreameAuthError("wrong password")):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_auth"}


async def test_network_failure_shows_cannot_connect(hass: HomeAssistant):
    """An unreachable cloud is reported as a connection problem."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with _discovery(error=DreameConnectionError("dns lookup failed")):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    assert result["errors"] == {"base": "cannot_connect"}


async def test_account_without_mowers_reports_none(hass: HomeAssistant):
    """Signing in but finding no mowers is its own message."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with _discovery():
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    assert result["errors"] == {"base": "no_devices"}


async def test_same_mower_is_not_added_twice(hass: HomeAssistant):
    """Re-adding a mower aborts instead of creating a duplicate entry."""
    MockConfigEntry(domain=DOMAIN, data=CREDENTIALS, unique_id="1234567890").add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with _discovery(MOCK_DESCRIPTOR):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_stored_credentials(hass: HomeAssistant):
    """Re-authentication rewrites the credentials and reloads the entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**CREDENTIALS, "did": "1234567890", "model": "dreame.mower.g2408"},
        unique_id="1234567890",
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    with _discovery(MOCK_DESCRIPTOR):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**CREDENTIALS, "username": "new@example.com", "password": "newpass"},
        )
        await hass.async_block_till_done()

    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["username"] == "new@example.com"
    assert entry.data["password"] == "newpass"


async def test_options_flow_stores_polling_and_rotation(hass: HomeAssistant):
    """The options form validates and stores both settings."""
    entry = MockConfigEntry(domain=DOMAIN, data=CREDENTIALS, unique_id="x")
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 120, "map_rotation": 180}
    )
    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert entry.options == {"scan_interval": 120, "map_rotation": 180}


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (DreameAuthError("wrong password"), "cannot_auth"),
        (DreameConnectionError("connection refused"), "cannot_connect"),
        (DreameConnectionError("dns lookup failed"), "cannot_connect"),
        (ValueError("Unsupported region: xx"), "invalid_region"),
        (DreameAuthError("unsupported account type"), "invalid_region"),
    ],
)
def test_error_keys_are_classified(error, expected):
    """Client errors map onto stable, translated config-flow error keys."""
    assert error_key(error) == expected
