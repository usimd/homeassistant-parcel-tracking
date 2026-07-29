"""Tests for the Ship24 API client."""

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.parcel_tracker.api import Ship24Api


@pytest.mark.integration
async def test_track_includes_destination_metadata_when_provided(hass) -> None:
    """Include destination fields in payload when provided."""
    api = Ship24Api(hass, "test_key")

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={
            "data": {
                "trackings": [
                    {
                        "tracker": {"trackerId": "tracker-1"},
                        "shipment": {"statusMilestone": "pending", "delivery": {}},
                        "events": [],
                    }
                ]
            }
        }
    )

    with patch.object(
        api._session, "post", new=AsyncMock(return_value=mock_resp)
    ) as post:
        await api.track(
            "TRACK123",
            courier_code="gls-de",
            destination_country_code="DE",
            destination_post_code="80331",
        )

    payload = post.await_args.kwargs["json"]
    assert payload["trackingNumber"] == "TRACK123"
    assert payload["courierCode"] == ["gls-de"]
    assert payload["destinationCountryCode"] == "DE"
    assert payload["destinationPostCode"] == "80331"


@pytest.mark.integration
async def test_track_omits_destination_metadata_when_missing(hass) -> None:
    """Do not include destination fields in payload when not provided."""
    api = Ship24Api(hass, "test_key")

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={
            "data": {
                "trackings": [
                    {
                        "tracker": {"trackerId": "tracker-1"},
                        "shipment": {"statusMilestone": "pending", "delivery": {}},
                        "events": [],
                    }
                ]
            }
        }
    )

    with patch.object(
        api._session, "post", new=AsyncMock(return_value=mock_resp)
    ) as post:
        await api.track("TRACK123", courier_code="dhl-group")

    payload = post.await_args.kwargs["json"]
    assert payload["trackingNumber"] == "TRACK123"
    assert payload["courierCode"] == ["dhl-group"]
    assert "destinationCountryCode" not in payload
    assert "destinationPostCode" not in payload


@pytest.mark.integration
async def test_track_locks_courier_and_sends_shipping_date(hass) -> None:
    """Restrict tracking to known courier and include shipping date hint."""
    api = Ship24Api(hass, "test_key")

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={
            "data": {
                "trackings": [
                    {
                        "tracker": {"trackerId": "tracker-1"},
                        "shipment": {"statusMilestone": "pending", "delivery": {}},
                        "events": [],
                    }
                ]
            }
        }
    )

    with patch.object(
        api._session, "post", new=AsyncMock(return_value=mock_resp)
    ) as post:
        await api.track(
            "TRACK123",
            courier_code="gls-de",
            shipping_date="2026-07-20",
        )

    payload = post.await_args.kwargs["json"]
    assert payload["courierCode"] == ["gls-de"]
    assert payload["settings"] == {"restrictTrackingToCourierCode": True}
    assert payload["shippingDate"] == "2026-07-20"


@pytest.mark.integration
async def test_track_omits_settings_and_shipping_date_when_absent(hass) -> None:
    """Do not restrict tracking or send shipping date when unknown."""
    api = Ship24Api(hass, "test_key")

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={
            "data": {
                "trackings": [
                    {
                        "tracker": {"trackerId": "tracker-1"},
                        "shipment": {"statusMilestone": "pending", "delivery": {}},
                        "events": [],
                    }
                ]
            }
        }
    )

    with patch.object(
        api._session, "post", new=AsyncMock(return_value=mock_resp)
    ) as post:
        await api.track("TRACK123")

    payload = post.await_args.kwargs["json"]
    assert "settings" not in payload
    assert "shippingDate" not in payload
