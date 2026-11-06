"""Tests for coordinator destination metadata behavior."""

from unittest.mock import AsyncMock, MagicMock, patch
from asyncio import Event, create_task, gather

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import (
    CONF_API_KEY,
    CONF_DESTINATION_COUNTRY_CODE,
    CONF_DESTINATION_POST_CODE,
    DOMAIN,
    EVENT_STATUS_CHANGED,
    STATUS_DELIVERED,
    STATUS_IN_TRANSIT,
    STATUS_REGISTERED,
)
from custom_components.parcel_tracker.api import Ship24Api, TrackingInfo
from custom_components.parcel_tracker.coordinator import ParcelTrackerCoordinator
from custom_components.parcel_tracker.dhl_api import DhlTrackingInfo
from custom_components.parcel_tracker.store import ParcelData, ParcelStore


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


@pytest.mark.parametrize("ship24_available", [True, False])
async def test_dhl_delivery_emits_one_final_transition(hass, ship24_available) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "test_key"})
    api = AsyncMock()
    info = TrackingInfo(
        "TRACK123",
        "tracker-1",
        STATUS_IN_TRANSIT,
        "dhl-germany",
        "DHL Germany",
        None,
        "2026-05-08T09:00:00+00:00",
        "In transit",
    )
    api.get_results.return_value = info if ship24_available else None
    store = ParcelStore(hass)
    parcel = ParcelData(
        tracking_number="TRACK123",
        carrier="DHL Germany",
        tracker_id="tracker-1",
        status=STATUS_IN_TRANSIT,
    )
    parcel.courier_code = "dhl-germany"
    store.add(parcel)
    store.async_save = AsyncMock()
    coordinator = ParcelTrackerCoordinator(hass, api, store, entry)
    coordinator.dhl_api = AsyncMock()
    coordinator.dhl_api.get_details.return_value = DhlTrackingInfo(
        status_code="delivered"
    )

    with patch.object(type(hass.bus), "async_fire") as fire:
        await coordinator._async_update_data()
        await coordinator._async_update_data()

    assert parcel.status == STATUS_DELIVERED
    assert parcel.status_source == "dhl"
    assert parcel.delivered_at is not None
    events = [
        call for call in fire.call_args_list if call.args[0] == EVENT_STATUS_CHANGED
    ]
    assert len(events) == 1
    assert events[0].args[1]["old_status"] == STATUS_IN_TRANSIT
    assert events[0].args[1]["new_status"] == STATUS_DELIVERED
    assert events[0].args[1]["status_source"] == "dhl"


async def test_registered_tracker_is_reused(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "test_key"})
    api = AsyncMock()
    api.get_results.return_value = None
    store = ParcelStore(hass)
    store.add(ParcelData("TRACK123", "DHL", tracker_id="tracker-1"))
    store.async_save = AsyncMock()
    coordinator = ParcelTrackerCoordinator(hass, api, store, entry)
    await coordinator._async_update_data()
    api.get_results.assert_awaited_once_with("tracker-1")
    api.track.assert_not_awaited()


async def test_creation_retries_keep_original_metadata(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "test_key"},
        options={
            CONF_DESTINATION_COUNTRY_CODE: "DE",
            CONF_DESTINATION_POST_CODE: "80331",
        },
    )
    entry.add_to_hass(hass)
    api = AsyncMock()
    api.track.return_value = None
    store = ParcelStore(hass)
    parcel = ParcelData(
        "TRACK123", "DHL", tracking_url="https://www.dhl.de/?piececode=TRACK123"
    )
    store.add(parcel)
    store.async_save = AsyncMock()
    coordinator = ParcelTrackerCoordinator(hass, api, store, entry)
    await coordinator._async_update_data()
    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_DESTINATION_COUNTRY_CODE: "FR",
            CONF_DESTINATION_POST_CODE: "75001",
        },
    )
    parcel.carrier = "DHL Germany"
    await coordinator._async_update_data()
    assert api.track.await_args_list[0] == api.track.await_args_list[1]
    request = api.track.await_args_list[0].kwargs
    assert request["destination_post_code"] == "80331"
    assert request["tracking_url"] == parcel.tracking_url
    assert request.get("shipping_date") is None


@pytest.mark.parametrize("event_time", [None, "2026-05-07T09:00:00+00:00"])
async def test_stale_ship24_result_does_not_regress_status(hass, event_time) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "test_key"})
    api = AsyncMock()
    api.get_results.return_value = TrackingInfo(
        "TRACK123",
        "tracker-1",
        STATUS_REGISTERED,
        None,
        None,
        None,
        event_time,
        "Registered",
    )
    store = ParcelStore(hass)
    parcel = ParcelData(
        "TRACK123", "DHL", status=STATUS_IN_TRANSIT, tracker_id="tracker-1"
    )
    parcel.latest_event_time = "2026-05-08T09:00:00+00:00"
    parcel.status_source = "dhl"
    store.add(parcel)
    store.async_save = AsyncMock()
    coordinator = ParcelTrackerCoordinator(hass, api, store, entry)
    with patch.object(type(hass.bus), "async_fire") as fire:
        await coordinator._async_update_data()
    assert parcel.status == STATUS_IN_TRANSIT
    fire.assert_not_called()


async def test_catalog_name_resolves_carrier_outside_url_adapters(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "test_key"})
    api = AsyncMock()
    api.get_couriers.return_value = {
        "us-post": {"courierName": "USPS", "requiredFields": None}
    }
    api.track.return_value = TrackingInfo(
        "TRACK123",
        "tracker-1",
        STATUS_IN_TRANSIT,
        "us-post",
        "USPS",
        None,
        None,
        None,
    )
    store = ParcelStore(hass)
    parcel = ParcelData(
        "TRACK123", "usps", tracking_url="https://tools.usps.com/?tLabels=TRACK123"
    )
    store.add(parcel)
    store.async_save = AsyncMock()
    coordinator = ParcelTrackerCoordinator(hass, api, store, entry)
    await coordinator._async_update_data()
    assert api.track.await_args.kwargs["courier_code"] == "us-post"
    assert api.track.await_args.kwargs["tracking_url"] == parcel.tracking_url
    assert parcel.courier_code == "us-post"
    assert parcel.carrier == "USPS"
    assert parcel.tracker_id == "tracker-1"


@pytest.mark.parametrize("provider", ["ship24", "dhl"])
async def test_confirmed_delivery_overrides_older_event_time(hass, provider) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "test_key"})
    api = AsyncMock()
    api.get_results.return_value = None
    store = ParcelStore(hass)
    parcel = ParcelData(
        "TRACK123",
        "DHL",
        status=STATUS_IN_TRANSIT,
        tracker_id="tracker-1",
        status_source="dhl",
        latest_event_time="2026-05-08T12:00:00+00:00",
    )
    store.add(parcel)
    store.async_save = AsyncMock()
    coordinator = ParcelTrackerCoordinator(hass, api, store, entry)
    if provider == "ship24":
        api.get_results.return_value = TrackingInfo(
            "TRACK123",
            "tracker-1",
            STATUS_DELIVERED,
            None,
            None,
            None,
            "2026-05-08T11:00:00+00:00",
            "Delivered",
        )
    else:
        coordinator.dhl_api = AsyncMock()
        coordinator.dhl_api.get_details.return_value = DhlTrackingInfo(
            status_code="delivered", latest_event_time="2026-05-08T11:00:00+00:00"
        )
    await coordinator._async_update_data()
    assert parcel.status == STATUS_DELIVERED
    assert parcel.delivered_at is not None


async def test_undated_dhl_status_allows_later_ship24_event(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "test_key"})
    api = AsyncMock()
    api.get_results.side_effect = [
        None,
        TrackingInfo(
            "TRACK123",
            "tracker-1",
            "out_for_delivery",
            None,
            None,
            None,
            "2026-05-08T12:00:00+00:00",
            "Out for delivery",
        ),
    ]
    store = ParcelStore(hass)
    parcel = ParcelData("TRACK123", "DHL", tracker_id="tracker-1")
    store.add(parcel)
    store.async_save = AsyncMock()
    coordinator = ParcelTrackerCoordinator(hass, api, store, entry)
    coordinator.dhl_api = AsyncMock()
    coordinator.dhl_api.get_details.return_value = DhlTrackingInfo(
        status_code="transit"
    )
    await coordinator._async_update_data()
    assert parcel.status_source == "dhl"
    await coordinator._async_update_data()
    assert parcel.status == "out_for_delivery"
    assert parcel.status_source == "ship24"


@pytest.fixture
async def push_coordinator(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "test_key"})
    store = ParcelStore(hass)
    store.add(ParcelData("TRACK123", "Unknown", tracker_id="tracker-1"))
    store.async_save = AsyncMock()
    return ParcelTrackerCoordinator(hass, Ship24Api(hass, "test_key"), store, entry)


def tracking_update(status, event_time, tracker_id="tracker-1"):
    return {
        "tracker": {"trackerId": tracker_id, "trackingNumber": "TRACK123"},
        "shipment": {"statusMilestone": status},
        "events": [{"status": status, "occurrenceDatetime": event_time}],
    }


async def test_push_updates_existing_parcel_and_notifies_sensors(push_coordinator):
    coordinator = push_coordinator
    parcel = coordinator.store.get("TRACK123")
    listener = MagicMock()
    coordinator.async_add_listener(listener)
    update = tracking_update("delivered", "2026-11-06T12:00:00+00:00")
    with patch.object(type(coordinator.hass.bus), "async_fire") as fire:
        await coordinator.async_process_ship24_updates([update])
    assert parcel.status == STATUS_DELIVERED
    assert parcel.status_source == "ship24"
    assert parcel.delivered_at is not None
    assert coordinator.data["TRACK123"] is parcel
    coordinator.store.async_save.assert_awaited_once()
    listener.assert_called_once()
    event = next(
        call for call in fire.call_args_list if call.args[0] == EVENT_STATUS_CHANGED
    )
    assert event.args[1]["new_status"] == STATUS_DELIVERED


async def test_duplicate_and_out_of_order_pushes_do_not_repeat_transitions(
    push_coordinator,
):
    coordinator = push_coordinator
    newer = tracking_update("out_for_delivery", "2026-11-06T12:00:00+00:00")
    older = tracking_update("in_transit", "2026-11-06T09:00:00+00:00")
    with patch.object(type(coordinator.hass.bus), "async_fire") as fire:
        await coordinator.async_process_ship24_updates([newer])
        await coordinator.async_process_ship24_updates([newer, older])
    assert coordinator.store.get("TRACK123").status == "out_for_delivery"
    events = [
        call for call in fire.call_args_list if call.args[0] == EVENT_STATUS_CHANGED
    ]
    assert len(events) == 1


async def test_push_ignores_unknown_tracker_without_registering_parcels(
    push_coordinator,
):
    coordinator = push_coordinator
    update = tracking_update("delivered", "2026-11-06T12:00:00+00:00", "other-tracker")
    await coordinator.async_process_ship24_updates([update])
    assert len(coordinator.store.parcels) == 1
    assert coordinator.store.get("TRACK123").status == STATUS_REGISTERED
    coordinator.store.async_save.assert_not_awaited()


async def test_push_does_not_make_outbound_provider_requests(push_coordinator):
    coordinator = push_coordinator
    update = tracking_update("in_transit", "2026-11-06T12:00:00+00:00")
    update["events"][0]["courierCode"] = "us-post"
    with patch.object(coordinator.api._session, "get", new=AsyncMock()) as get:
        await coordinator.async_process_ship24_updates([update])
    get.assert_not_awaited()
    assert coordinator.store.get("TRACK123").courier_code == "us-post"


async def test_failed_push_save_can_be_retried_without_losing_transition(
    push_coordinator,
):
    coordinator = push_coordinator
    coordinator.store.async_save.side_effect = [OSError("storage unavailable"), None]
    update = tracking_update("delivered", "2026-11-06T12:00:00+00:00")
    with patch.object(type(coordinator.hass.bus), "async_fire") as fire:
        with pytest.raises(OSError):
            await coordinator.async_process_ship24_updates([update])
        assert coordinator.store.get("TRACK123").status == STATUS_REGISTERED
        fire.assert_not_called()
        await coordinator.async_process_ship24_updates([update])
    assert coordinator.store.get("TRACK123").status == STATUS_DELIVERED
    events = [
        call for call in fire.call_args_list if call.args[0] == EVENT_STATUS_CHANGED
    ]
    assert len(events) == 1


async def test_push_preserves_periodic_reconciliation_schedule(push_coordinator):
    coordinator = push_coordinator
    coordinator.async_add_listener(MagicMock())
    scheduled_poll = coordinator._unsub_refresh
    assert scheduled_poll is not None
    await coordinator.async_process_ship24_updates(
        [tracking_update("in_transit", "2026-11-06T12:00:00+00:00")]
    )
    assert coordinator._unsub_refresh is scheduled_poll


async def test_push_waits_for_inflight_poll(push_coordinator):
    coordinator = push_coordinator
    poll_started = Event()
    release_poll = Event()
    push_started = Event()

    async def delayed_results(tracker_id):
        poll_started.set()
        await release_poll.wait()
        return TrackingInfo(
            "TRACK123",
            tracker_id,
            STATUS_IN_TRANSIT,
            None,
            None,
            None,
            "2026-11-06T09:00:00+00:00",
            "In transit",
        )

    async def deliver_push():
        push_started.set()
        await coordinator.async_process_ship24_updates(
            [tracking_update("delivered", "2026-11-06T12:00:00+00:00")]
        )

    with patch.object(coordinator.api, "get_results", new=delayed_results):
        poll = create_task(coordinator._async_update_data())
        await poll_started.wait()
        push = create_task(deliver_push())
        try:
            await push_started.wait()
            assert coordinator.store.get("TRACK123").status == STATUS_REGISTERED
        finally:
            release_poll.set()
            await gather(poll, push)
    assert coordinator.store.get("TRACK123").status == STATUS_DELIVERED


async def test_stale_push_cannot_replace_current_courier(push_coordinator):
    coordinator = push_coordinator
    current = tracking_update("out_for_delivery", "2026-11-06T12:00:00+00:00")
    current["events"][0]["courierCode"] = "dhl-germany"
    stale = tracking_update("in_transit", "2026-11-06T09:00:00+00:00")
    stale["events"][0]["courierCode"] = "us-post"
    await coordinator.async_process_ship24_updates([current, stale])
    assert coordinator.store.get("TRACK123").courier_code == "dhl-germany"


async def test_equal_timestamp_push_uses_event_order(push_coordinator):
    coordinator = push_coordinator
    newer = tracking_update("out_for_delivery", "2026-11-06T12:00:00+00:00")
    newer["events"][0]["order"] = 2
    older = tracking_update("in_transit", "2026-11-06T12:00:00+00:00")
    older["events"][0]["order"] = 1
    with patch.object(type(coordinator.hass.bus), "async_fire") as fire:
        await coordinator.async_process_ship24_updates([newer])
        await coordinator.async_process_ship24_updates([older])
    assert coordinator.store.get("TRACK123").status == "out_for_delivery"
    events = [
        call for call in fire.call_args_list if call.args[0] == EVENT_STATUS_CHANGED
    ]
    assert len(events) == 1


async def test_push_state_survives_verified_storage_roundtrip(push_coordinator):
    coordinator = push_coordinator
    coordinator.store.async_save = ParcelStore.async_save.__get__(coordinator.store)
    update = tracking_update("out_for_delivery", "2026-11-06T12:00:00+00:00")
    update["events"][0]["order"] = 2
    await coordinator.async_process_ship24_updates([update])
    restored = ParcelStore(coordinator.hass)
    await restored.async_load()
    assert restored.get("TRACK123").status == "out_for_delivery"
    assert restored.get("TRACK123").latest_event_order == 2
