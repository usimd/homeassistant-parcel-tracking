"""Test the parcel_tracker integration setup."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import CONF_API_KEY, DOMAIN


@pytest.mark.integration
async def test_setup_entry(hass: HomeAssistant) -> None:
    """Test successful setup of config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Parcel Tracker",
        data={CONF_API_KEY: "test_ship24_key"},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.parcel_tracker.Ship24Api") as mock_api_cls,
        patch("custom_components.parcel_tracker.ParcelStore") as mock_store_cls,
    ):
        mock_api = mock_api_cls.return_value
        mock_api.test_connection = AsyncMock(return_value=True)

        mock_store = mock_store_cls.return_value
        mock_store.async_load = AsyncMock()
        mock_store.parcels = {}
        mock_store.get_all_tracking_numbers = lambda: []

        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert DOMAIN in hass.data
    assert entry.entry_id in hass.data[DOMAIN]


@pytest.mark.integration
async def test_setup_entry_connection_fails(hass: HomeAssistant) -> None:
    """Test setup succeeds even when Ship24 API is unreachable (uses cached data)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Parcel Tracker",
        data={CONF_API_KEY: "bad_key"},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.parcel_tracker.Ship24Api") as mock_api_cls,
        patch("custom_components.parcel_tracker.ParcelStore") as mock_store_cls,
    ):
        mock_api = mock_api_cls.return_value
        mock_api.test_connection = AsyncMock(return_value=False)

        mock_store = mock_store_cls.return_value
        mock_store.async_load = AsyncMock()
        mock_store.parcels = {}
        mock_store.get_all_tracking_numbers = lambda: []

        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Entry should still be loaded — coordinator handles retries
    assert entry.entry_id in hass.data.get(DOMAIN, {})


@pytest.mark.integration
async def test_unload_entry(hass: HomeAssistant) -> None:
    """Test unloading config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Parcel Tracker",
        data={CONF_API_KEY: "test_ship24_key"},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.parcel_tracker.Ship24Api") as mock_api_cls,
        patch("custom_components.parcel_tracker.ParcelStore") as mock_store_cls,
    ):
        mock_api = mock_api_cls.return_value
        mock_api.test_connection = AsyncMock(return_value=True)

        mock_store = mock_store_cls.return_value
        mock_store.async_load = AsyncMock()
        mock_store.parcels = {}
        mock_store.get_all_tracking_numbers = lambda: []

        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.entry_id in hass.data[DOMAIN]

        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.entry_id not in hass.data.get(DOMAIN, {})


@pytest.mark.integration
async def test_webhook_registered(hass: HomeAssistant) -> None:
    """Test that the integration registers a webhook on setup."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Parcel Tracker",
        data={CONF_API_KEY: "test_key"},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.parcel_tracker.Ship24Api") as mock_api_cls,
        patch("custom_components.parcel_tracker.ParcelStore") as mock_store_cls,
    ):
        mock_api = mock_api_cls.return_value
        mock_api.test_connection = AsyncMock(return_value=True)

        mock_store = mock_store_cls.return_value
        mock_store.async_load = AsyncMock()
        mock_store.parcels = {}
        mock_store.get_all_tracking_numbers = lambda: []

        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert "parcel_tracker_register" in hass.data["webhook"]
