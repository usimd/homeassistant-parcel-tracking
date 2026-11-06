"""Test the parcel_tracker integration setup."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components import parcel_tracker
from custom_components.parcel_tracker import _add_parcel, _handle_webhook
from custom_components.parcel_tracker.const import (
    CONF_API_KEY,
    CONF_CLEANUP_DAYS,
    DOMAIN,
    STATUS_DELIVERED,
    WEBHOOK_ID,
)
from custom_components.parcel_tracker.store import ParcelData


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
async def test_cleanup_removes_entity_registry_entry(hass: HomeAssistant) -> None:
    """Test that auto cleanup removes the parcel and its entity registry entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Parcel Tracker",
        data={CONF_API_KEY: "test_ship24_key"},
        options={CONF_CLEANUP_DAYS: 0},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)

    parcel_tracking_number = "TRACK123"
    delivered_at = (datetime.now() - timedelta(days=1)).isoformat()
    from custom_components.parcel_tracker.store import ParcelStore
    from custom_components.parcel_tracker.coordinator import ParcelTrackerCoordinator

    store = ParcelStore(hass)
    store._parcels = {
        parcel_tracking_number: ParcelData(
            tracking_number=parcel_tracking_number,
            carrier="DHL",
            status=STATUS_DELIVERED,
            delivered_at=delivered_at,
        )
    }
    store.async_save = AsyncMock()

    api = AsyncMock()

    coordinator = ParcelTrackerCoordinator(hass, api, store, entry)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    registry = er.async_get(hass)
    entity = registry.async_get_or_create(
        Platform.SENSOR,
        DOMAIN,
        f"{entry.entry_id}_{parcel_tracking_number}",
        suggested_object_id="parcel_track123",
        config_entry=entry,
    )
    assert registry.async_get(entity.entity_id) is not None

    await coordinator._cleanup_delivered_parcels()

    assert parcel_tracking_number not in coordinator.store.parcels
    assert registry.async_get(entity.entity_id) is None


@pytest.mark.integration
@pytest.mark.parametrize("allow_external", [False, True])
@pytest.mark.parametrize("push_secret", ["", "ship24-test-secret"])
async def test_webhook_registered(
    hass: HomeAssistant, allow_external, push_secret
) -> None:
    """Test that the integration registers a webhook on setup."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Parcel Tracker",
        data={CONF_API_KEY: "test_key"},
        options={
            "webhook_allow_external": allow_external,
            "ship24_webhook_secret": push_secret,
        },
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

        original_id = entry.data["webhook_id"]
        push_id = entry.data["ship24_webhook_id"]
        assert push_id != original_id
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert original_id not in hass.data["webhook"]
        assert push_id not in hass.data["webhook"]
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.data["webhook_id"] == original_id
        assert entry.data["ship24_webhook_id"] == push_id

    webhook_id = entry.data["webhook_id"]
    assert len(webhook_id) >= 32
    assert webhook_id != WEBHOOK_ID
    assert WEBHOOK_ID not in hass.data["webhook"]
    assert hass.data["webhook"][webhook_id]["local_only"] is not allow_external
    assert entry.data[CONF_API_KEY] == "test_key"
    assert (push_id in hass.data["webhook"]) is bool(push_secret)
    if push_secret:
        assert hass.data["webhook"][push_id]["local_only"] is False


@pytest.mark.integration
async def test_webhook_registers_gls_short_tracking_number(
    hass: HomeAssistant, mock_store
) -> None:
    """Test registering an eight-character GLS number from a .eu URL."""
    tracking_url = "https://gls-group.eu/DE/de/paketverfolgung?match=ZPXW6MM0"
    coordinator = MagicMock()
    coordinator.store = mock_store
    coordinator.async_request_refresh = AsyncMock()
    hass.data[DOMAIN] = {"test_entry": coordinator}
    request = MagicMock()
    request.json = AsyncMock(return_value={"url": tracking_url})

    response = await _handle_webhook(hass, WEBHOOK_ID, request)

    assert response.status == 200
    parcel = mock_store.add.call_args.args[0]
    assert parcel.tracking_number == "ZPXW6MM0"
    assert parcel.carrier == "GLS"
    assert parcel.tracking_url == tracking_url
    mock_store.async_save.assert_awaited_once()
    coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.integration
async def test_add_accepts_unsupported_url_with_explicit_number(
    hass, mock_store
) -> None:
    coordinator = MagicMock()
    coordinator.store = mock_store
    coordinator.async_request_refresh = AsyncMock()
    success = await _add_parcel(
        hass,
        coordinator,
        tracking_number="TRACK123",
        tracking_url="https://tools.usps.com/?tLabels=TRACK123",
        carrier="USPS",
        courier_code="us-post",
        shipping_date="2026-05-01",
        restrict_courier=True,
    )
    assert success is True
    parcel = mock_store.add.call_args.args[0]
    assert parcel.courier_code == "us-post"
    assert parcel.shipping_date == "2026-05-01"
    assert parcel.restrict_courier is True


@pytest.mark.integration
async def test_webhook_accepts_explicit_number_for_unsupported_url(
    hass, mock_store
) -> None:
    coordinator = MagicMock()
    coordinator.store = mock_store
    coordinator.async_request_refresh = AsyncMock()
    hass.data[DOMAIN] = {"test_entry": coordinator}
    request = MagicMock()
    request.json = AsyncMock(
        return_value={
            "url": "https://tools.usps.com/?tLabels=TRACK123",
            "tracking_number": "TRACK123",
            "courier_code": "us-post",
        }
    )
    response = await _handle_webhook(hass, WEBHOOK_ID, request)
    assert response.status == 200
    assert mock_store.add.call_args.args[0].courier_code == "us-post"


@pytest.mark.parametrize("body", [[], {"url": ["bad"]}, {"tracking_number": ""}])
async def test_webhook_rejects_invalid_payload(hass, body) -> None:
    from aiohttp import web

    request = MagicMock()
    request.json = AsyncMock(return_value=body)
    with pytest.raises(web.HTTPBadRequest):
        await _handle_webhook(hass, WEBHOOK_ID, request)


@pytest.fixture
def ship24_receiver(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "test_key", "ship24_webhook_id": "push-id"},
        options={"ship24_webhook_secret": "ship24-test-secret"},
    )
    coordinator = MagicMock()
    coordinator.entry = entry
    coordinator.async_process_ship24_updates = AsyncMock()
    hass.data[DOMAIN] = {entry.entry_id: coordinator}
    return coordinator


def push_request(body, authorization="Bearer ship24-test-secret"):
    request = MagicMock()
    request.headers = {"Authorization": authorization}
    request.json = AsyncMock(return_value=body)
    return request


def push_tracking():
    return {
        "tracker": {"trackerId": "tracker-1", "trackingNumber": "TRACK123"},
        "shipment": {"statusMilestone": "in_transit"},
        "events": [{"occurrenceDatetime": "2026-11-06T12:00:00+00:00"}],
    }


@pytest.mark.parametrize("authorization", ["", "Bearer wrong", "Basic test"])
async def test_ship24_webhook_rejects_invalid_secret(
    hass, ship24_receiver, authorization
):
    request = push_request({"trackings": [push_tracking()]}, authorization)
    response = await parcel_tracker._handle_ship24_webhook(hass, "push-id", request)
    assert response.status == 401
    request.json.assert_not_awaited()
    ship24_receiver.async_process_ship24_updates.assert_not_awaited()


async def test_ship24_webhook_accepts_authenticated_batch(hass, ship24_receiver):
    tracking = push_tracking()
    request = push_request({"trackings": [tracking]})
    response = await parcel_tracker._handle_ship24_webhook(hass, "push-id", request)
    assert response.status == 200
    ship24_receiver.async_process_ship24_updates.assert_awaited_once_with([tracking])


@pytest.mark.parametrize("body", [[], {}, {"trackings": "bad"}, {"trackings": [{}]}])
async def test_ship24_webhook_rejects_malformed_batch(hass, ship24_receiver, body):
    response = await parcel_tracker._handle_ship24_webhook(
        hass, "push-id", push_request(body)
    )
    assert response.status == 400
    ship24_receiver.async_process_ship24_updates.assert_not_awaited()


async def test_ship24_webhook_validates_entire_batch_before_applying(
    hass, ship24_receiver
):
    request = push_request({"trackings": [push_tracking(), {}]})
    response = await parcel_tracker._handle_ship24_webhook(hass, "push-id", request)
    assert response.status == 400
    ship24_receiver.async_process_ship24_updates.assert_not_awaited()


async def test_ship24_webhook_does_not_accept_registration_endpoint(
    hass, ship24_receiver
):
    response = await parcel_tracker._handle_ship24_webhook(
        hass, "registration-id", push_request({})
    )
    assert response.status == 404


async def test_ship24_authentication_status_survives_ha_router(hass, ship24_receiver):
    from homeassistant.components import webhook

    webhook.async_register(
        hass,
        DOMAIN,
        "Ship24 test",
        "push-id",
        parcel_tracker._handle_ship24_webhook,
        allowed_methods=["POST"],
        local_only=False,
    )
    request = push_request({}, "Bearer wrong")
    request.method = "POST"
    response = await webhook.async_handle_webhook(hass, "push-id", request)
    assert response.status == 401
    ship24_receiver.async_process_ship24_updates.assert_not_awaited()


async def test_ship24_storage_failure_returns_retryable_status(hass, ship24_receiver):
    ship24_receiver.async_process_ship24_updates.side_effect = OSError(
        "storage unavailable"
    )
    response = await parcel_tracker._handle_ship24_webhook(
        hass, "push-id", push_request({"trackings": [push_tracking()]})
    )
    assert response.status == 503


@pytest.mark.parametrize(
    "authorization, expected_status",
    [
        ("Bearer ship24-test-secret", 200),
        ("Bearer wrong", 401),
    ],
)
async def test_ship24_http_endpoint(
    hass, ship24_receiver, hass_client, authorization, expected_status
):
    from homeassistant.components import webhook
    from homeassistant.setup import async_setup_component

    await async_setup_component(hass, "webhook", {})
    webhook.async_register(
        hass,
        DOMAIN,
        "Ship24 test",
        "push-id",
        parcel_tracker._handle_ship24_webhook,
        allowed_methods=["POST"],
        local_only=False,
    )
    client = await hass_client()
    response = await client.post(
        "/api/webhook/push-id",
        json={"trackings": []},
        headers={"Authorization": authorization},
    )
    assert response.status == expected_status


async def test_ship24_webhook_rejects_non_numeric_event_order(hass, ship24_receiver):
    tracking = push_tracking()
    tracking["events"][0]["order"] = "invalid"
    response = await parcel_tracker._handle_ship24_webhook(
        hass, "push-id", push_request({"trackings": [tracking]})
    )
    assert response.status == 400
    ship24_receiver.async_process_ship24_updates.assert_not_awaited()
