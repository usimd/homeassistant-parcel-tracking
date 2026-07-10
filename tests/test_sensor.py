"""Tests for parcel sensor entity behavior."""

from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import ATTR_ETA, DOMAIN
from custom_components.parcel_tracker.sensor import ParcelSensor
from custom_components.parcel_tracker.store import ParcelData


@pytest.mark.unit
async def test_extra_state_attributes_preserve_existing_eta(hass) -> None:
    """Keep existing ETA attribute when parcel has no API ETA."""
    tracking_number = "TRACK123"
    parcel = ParcelData(tracking_number=tracking_number, carrier="DHL", eta=None)

    coordinator = MagicMock()
    coordinator.store.get.return_value = parcel

    entry = MockConfigEntry(domain=DOMAIN, title="Parcel Tracker")
    sensor = ParcelSensor(coordinator, entry, tracking_number)
    sensor.hass = hass
    entity_id = "sensor.parcel_track123"
    sensor._attr_entity_id = entity_id

    hass.states.async_set(entity_id, "in_transit", {ATTR_ETA: "2026-07-12"})

    attrs = sensor.extra_state_attributes

    assert attrs[ATTR_ETA] == "2026-07-12"


@pytest.mark.unit
async def test_extra_state_attributes_use_parcel_eta_when_available(hass) -> None:
    """Use parcel ETA from API/store when available."""
    tracking_number = "TRACK123"
    parcel = ParcelData(tracking_number=tracking_number, carrier="DHL", eta="2026-07-13")

    coordinator = MagicMock()
    coordinator.store.get.return_value = parcel

    entry = MockConfigEntry(domain=DOMAIN, title="Parcel Tracker")
    sensor = ParcelSensor(coordinator, entry, tracking_number)
    sensor.hass = hass
    entity_id = "sensor.parcel_track123"
    sensor._attr_entity_id = entity_id

    hass.states.async_set(entity_id, "in_transit", {ATTR_ETA: "2026-07-12"})

    attrs = sensor.extra_state_attributes

    assert attrs[ATTR_ETA] == "2026-07-13"
