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
async def test_track_hints_courier_and_sends_shipping_date(hass) -> None:
    """Allow carrier handoffs while sending an explicit shipping date."""
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
    assert "settings" not in payload
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


@pytest.mark.integration
async def test_track_forwards_url_name_and_explicit_restriction(hass) -> None:
    api = Ship24Api(hass, "test_key")
    response = AsyncMock()
    response.status = 200
    response.json.return_value = {"data": {"trackings": []}}
    with patch.object(
        api._session, "post", new=AsyncMock(return_value=response)
    ) as post:
        await api.track(
            "TRACK123",
            courier_code="us-post",
            courier_name="USPS",
            tracking_url="https://tools.usps.com/?tLabels=TRACK123",
            restrict_courier=True,
        )
    assert post.await_args.kwargs["json"] == {
        "trackingNumber": "TRACK123",
        "courierCode": ["us-post"],
        "courierName": "USPS",
        "trackingUrl": "https://tools.usps.com/?tLabels=TRACK123",
        "settings": {"restrictTrackingToCourierCode": True},
    }


@pytest.mark.integration
async def test_courier_catalog_is_cached_and_resolves_event_names(hass) -> None:
    api = Ship24Api(hass, "test_key")
    catalog_response = AsyncMock()
    catalog_response.status = 200
    catalog_response.json.return_value = {
        "data": {"couriers": [{"courierCode": "us-post", "courierName": "USPS"}]}
    }
    tracking_response = AsyncMock()
    tracking_response.status = 200
    tracking_response.json.return_value = {
        "data": {
            "trackings": [
                {
                    "tracker": {"trackerId": "tracker-1", "trackingNumber": "TRACK123"},
                    "shipment": {"statusMilestone": "available_for_pickup"},
                    "events": [
                        {"courierCode": "us-post", "status": "Ready for collection"}
                    ],
                }
            ]
        }
    }
    with (
        patch.object(
            api._session, "get", new=AsyncMock(return_value=catalog_response)
        ) as get,
        patch.object(
            api._session, "post", new=AsyncMock(return_value=tracking_response)
        ),
    ):
        first = await api.track("TRACK123")
        second = await api.track("TRACK123")
    assert first.courier_name == "USPS"
    assert second.courier_code == "us-post"
    assert first.status == "available_for_pickup"
    get.assert_awaited_once()


@pytest.mark.integration
async def test_get_results_uses_shared_parser_and_catalog(hass) -> None:
    api = Ship24Api(hass, "test_key")
    response = AsyncMock()
    response.status = 200
    response.json.return_value = {
        "data": {
            "trackings": [
                {
                    "tracker": {
                        "trackerId": "tracker-1",
                        "trackingNumber": "TRACK123",
                        "courierCode": ["us-post"],
                    },
                    "shipment": {"statusMilestone": "in_transit", "delivery": None},
                    "events": [],
                }
            ]
        }
    }
    catalog = AsyncMock()
    catalog.status = 200
    catalog.json.return_value = {
        "data": {"couriers": [{"courierCode": "us-post", "courierName": "USPS"}]}
    }
    with patch.object(
        api._session, "get", new=AsyncMock(side_effect=[response, catalog])
    ):
        info = await api.get_results("tracker-1")
    assert info.tracking_number == "TRACK123"
    assert info.courier_name == "USPS"
    assert info.eta is None
