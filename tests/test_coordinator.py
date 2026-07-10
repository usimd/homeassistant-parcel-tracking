"""Tests for coordinator destination metadata behavior."""

from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import (
    CONF_API_KEY,
    CONF_DESTINATION_COUNTRY_CODE,
    CONF_DESTINATION_POST_CODE,
    DOMAIN,
)
from custom_components.parcel_tracker.coordinator import ParcelTrackerCoordinator
from custom_components.parcel_tracker.store import ParcelStore


@pytest.mark.unit
async def test_destination_metadata_uses_options_override(hass) -> None:
    """Use explicit options over Home Assistant home config/state values."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Parcel Tracker",
        data={CONF_API_KEY: "test_key"},
        options={
            CONF_DESTINATION_COUNTRY_CODE: "de",
            CONF_DESTINATION_POST_CODE: " 10115 ",
        },
    )

    api = AsyncMock()
    store = ParcelStore(hass)
    coordinator = ParcelTrackerCoordinator(hass, api, store, entry)

    hass.config.country = "FR"
    hass.states.async_set("zone.home", "zoning", {"country": "AT", "postcode": "99999"})

    country, post_code = coordinator._get_home_destination_metadata()

    assert country == "DE"
    assert post_code == "10115"


@pytest.mark.unit
async def test_destination_metadata_falls_back_to_home_config_and_zone(hass) -> None:
    """Use HA config/zone.home metadata when no explicit options are provided."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Parcel Tracker",
        data={CONF_API_KEY: "test_key"},
        options={},
    )

    api = AsyncMock()
    store = ParcelStore(hass)
    coordinator = ParcelTrackerCoordinator(hass, api, store, entry)

    hass.config.country = "de"
    hass.states.async_set("zone.home", "zoning", {"postal_code": "80331"})

    country, post_code = coordinator._get_home_destination_metadata()

    assert country == "DE"
    assert post_code == "80331"
