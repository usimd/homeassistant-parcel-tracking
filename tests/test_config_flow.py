"""Test the parcel_tracker config flow."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.parcel_tracker.const import (
    CONF_API_KEY,
    CONF_CLEANUP_DAYS,
    CONF_SCAN_INTERVAL_HOURS,
    DOMAIN,
)


@pytest.mark.integration
async def test_user_flow_show_form(hass: HomeAssistant) -> None:
    """Test initial form is shown for user config flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert CONF_API_KEY in result["data_schema"].schema


@pytest.mark.integration
async def test_user_flow_success(hass: HomeAssistant) -> None:
    """Test successful config flow with valid Ship24 API key."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.parcel_tracker.config_flow.Ship24Api"
    ) as mock_api_cls:
        mock_api = mock_api_cls.return_value
        mock_api.test_connection = AsyncMock(return_value=True)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "valid_ship24_key"},
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Parcel Tracker"
    assert result["data"][CONF_API_KEY] == "valid_ship24_key"


@pytest.mark.integration
async def test_user_flow_invalid_key(hass: HomeAssistant) -> None:
    """Test config flow with invalid Ship24 API key."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.parcel_tracker.config_flow.Ship24Api"
    ) as mock_api_cls:
        mock_api = mock_api_cls.return_value
        mock_api.test_connection = AsyncMock(return_value=False)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "bad_key"},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.integration
async def test_user_flow_already_configured(hass: HomeAssistant) -> None:
    """Test config flow aborts if already configured."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    existing = MockConfigEntry(
        domain=DOMAIN,
        title="Parcel Tracker",
        data={CONF_API_KEY: "existing_key"},
        unique_id=DOMAIN,
    )
    existing.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.parcel_tracker.config_flow.Ship24Api"
    ) as mock_api_cls:
        mock_api = mock_api_cls.return_value
        mock_api.test_connection = AsyncMock(return_value=True)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "new_key"},
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.integration
async def test_options_flow(hass: HomeAssistant) -> None:
    """Test the options flow includes drop-off location."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Parcel Tracker",
        data={CONF_API_KEY: "test_key"},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_CLEANUP_DAYS: 5,
            CONF_SCAN_INTERVAL_HOURS: 4,
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_CLEANUP_DAYS] == 5
    assert result["data"][CONF_SCAN_INTERVAL_HOURS] == 4
