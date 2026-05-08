"""Tests for the DHL API client."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.parcel_tracker.dhl_api import DhlApi, DhlTrackingInfo, is_dhl_parcel


def test_is_dhl_parcel_by_carrier() -> None:
    """Test DHL detection by carrier name."""
    assert is_dhl_parcel("DHL") is True
    assert is_dhl_parcel("dhl") is True
    assert is_dhl_parcel("DPD") is False
    assert is_dhl_parcel("Hermes") is False


def test_is_dhl_parcel_by_courier_code() -> None:
    """Test DHL detection by courier code."""
    assert is_dhl_parcel("Unknown", "dhl-group") is True
    assert is_dhl_parcel("Unknown", "dhl-germany") is True
    assert is_dhl_parcel("Unknown", "dhl-express") is True
    assert is_dhl_parcel("Unknown", "dpd") is False
    assert is_dhl_parcel("Unknown", None) is False


@pytest.mark.integration
async def test_dhl_api_test_connection_success(hass) -> None:
    """Test DHL API connection test with valid key."""
    api = DhlApi(hass, "valid_key")

    mock_resp = AsyncMock()
    mock_resp.status = 404  # valid key, shipment not found

    with patch.object(api._session, "get", new=AsyncMock(return_value=mock_resp)):
        result = await api.test_connection()

    assert result is True


@pytest.mark.integration
async def test_dhl_api_test_connection_failure(hass) -> None:
    """Test DHL API connection test with invalid key."""
    api = DhlApi(hass, "bad_key")

    mock_resp = AsyncMock()
    mock_resp.status = 401

    with patch.object(api._session, "get", new=AsyncMock(return_value=mock_resp)):
        result = await api.test_connection()

    assert result is False


@pytest.mark.integration
async def test_dhl_api_get_details_with_eta(hass) -> None:
    """Test fetching DHL details with ETA time window."""
    api = DhlApi(hass, "valid_key")

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={
            "shipments": [
                {
                    "id": "123",
                    "estimatedTimeOfDelivery": {
                        "estimatedFrom": "2026-05-08T10:00:00",
                        "estimatedUntil": "2026-05-08T14:00:00",
                    },
                }
            ]
        }
    )

    with patch.object(api._session, "get", new=AsyncMock(return_value=mock_resp)):
        result = await api.get_details("00340433880800211827")

    assert result is not None
    assert result.eta_date == "2026-05-08T10:00:00"
    assert result.eta_timeframe_from == "2026-05-08T10:00:00"
    assert result.eta_timeframe_to == "2026-05-08T14:00:00"


@pytest.mark.integration
async def test_dhl_api_get_details_no_eta(hass) -> None:
    """Test fetching DHL details without ETA."""
    api = DhlApi(hass, "valid_key")

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={
            "shipments": [
                {
                    "id": "123",
                    "estimatedTimeOfDelivery": {},
                }
            ]
        }
    )

    with patch.object(api._session, "get", new=AsyncMock(return_value=mock_resp)):
        result = await api.get_details("00340433880800211827")

    assert result is None


@pytest.mark.integration
async def test_dhl_api_get_details_not_found(hass) -> None:
    """Test fetching DHL details for unknown shipment."""
    api = DhlApi(hass, "valid_key")

    mock_resp = AsyncMock()
    mock_resp.status = 404

    with patch.object(api._session, "get", new=AsyncMock(return_value=mock_resp)):
        result = await api.get_details("00000000000000000000")

    assert result is None


@pytest.mark.integration
async def test_dhl_api_get_details_exception(hass) -> None:
    """Test DHL API handles exceptions gracefully."""
    api = DhlApi(hass, "valid_key")

    with patch.object(api._session, "get", side_effect=Exception("timeout")):
        result = await api.get_details("00340433880800211827")

    assert result is None
