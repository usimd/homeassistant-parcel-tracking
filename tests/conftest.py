"""Fixtures for parcel_tracker integration tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import CONF_API_KEY, DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for all tests."""
    yield


@pytest.fixture(name="mock_config_entry")
def mock_config_entry_fixture() -> MockConfigEntry:
    """Return a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Parcel Tracker",
        data={CONF_API_KEY: "test_ship24_api_key"},
        unique_id=DOMAIN,
    )


@pytest.fixture(name="mock_ship24_api")
def mock_ship24_api_fixture():
    """Return a mocked Ship24Api."""
    mock = MagicMock()
    mock.test_connection = AsyncMock(return_value=True)
    mock.track = AsyncMock(return_value=None)
    mock.get_results = AsyncMock(return_value=None)
    return mock


@pytest.fixture(name="mock_store")
def mock_store_fixture():
    """Return a mocked ParcelStore."""
    mock = MagicMock()
    mock.async_load = AsyncMock()
    mock.async_save = AsyncMock()
    mock.parcels = {}
    mock.get_all_tracking_numbers = MagicMock(return_value=[])
    mock.get = MagicMock(return_value=None)
    mock.add = MagicMock()
    mock.remove = MagicMock(return_value=None)
    return mock
