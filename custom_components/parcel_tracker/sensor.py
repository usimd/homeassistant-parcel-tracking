"""Sensor platform for Parcel Tracker integration."""

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_CARRIER,
    ATTR_DESCRIPTION,
    ATTR_ETA,
    ATTR_ETA_TIMEFRAME,
    ATTR_LAST_API_UPDATE,
    ATTR_PREFERENCE_URL,
    ATTR_REGISTERED_AT,
    ATTR_REGISTERED_BY,
    ATTR_TRACKING_NUMBER,
    ATTR_TRACKING_URL,
    CARRIER_PREFERENCE_URLS,
    DOMAIN,
    SIGNAL_NEW_PARCEL,
    SIGNAL_REMOVE_PARCEL,
)
from .coordinator import ParcelTrackerCoordinator
from .store import ParcelData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Parcel Tracker sensors from a config entry."""
    coordinator: ParcelTrackerCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Create sensors for existing parcels
    entities = [
        ParcelSensor(coordinator, entry, tn)
        for tn in coordinator.store.get_all_tracking_numbers()
    ]
    async_add_entities(entities)

    # Listen for new parcels
    @callback
    def async_add_parcel(tracking_number: str) -> None:
        """Add a new parcel sensor entity."""
        async_add_entities([ParcelSensor(coordinator, entry, tracking_number)])

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_NEW_PARCEL, async_add_parcel)
    )

    # Listen for parcel removal
    @callback
    def async_remove_parcel(tracking_number: str) -> None:
        """Handle parcel removal (entity removes itself via availability)."""
        coordinator.async_set_updated_data(coordinator.store.parcels)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_REMOVE_PARCEL, async_remove_parcel)
    )


class ParcelSensor(CoordinatorEntity[ParcelTrackerCoordinator], SensorEntity):
    """Sensor entity for a tracked parcel."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ParcelTrackerCoordinator,
        entry: ConfigEntry,
        tracking_number: str,
    ) -> None:
        """Initialize the parcel sensor."""
        super().__init__(coordinator)
        self._tracking_number = tracking_number
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{tracking_number}"
        self._attr_icon = "mdi:package-variant"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Parcel Tracker",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _parcel(self) -> ParcelData | None:
        """Return parcel data from store."""
        return self.coordinator.store.get(self._tracking_number)

    @property
    def available(self) -> bool:
        """Return True if parcel still exists in store."""
        return self._parcel is not None

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        parcel = self._parcel
        if parcel and parcel.description:
            return f"{parcel.carrier} - {parcel.description}"
        if parcel:
            suffix = parcel.tracking_number[-6:]
            return f"{parcel.carrier} {suffix}"
        return f"Parcel {self._tracking_number[-6:]}"

    @property
    def native_value(self) -> str | None:
        """Return the state (delivery status)."""
        parcel = self._parcel
        if parcel:
            return parcel.status
        return None

    @property
    def extra_state_attributes(self) -> dict:
        """Return the state attributes."""
        parcel = self._parcel
        if not parcel:
            return {}

        attrs = {
            ATTR_CARRIER: parcel.carrier,
            ATTR_TRACKING_NUMBER: parcel.tracking_number,
            ATTR_REGISTERED_AT: parcel.registered_at,
        }
        if parcel.eta:
            attrs[ATTR_ETA] = parcel.eta
        elif self.hass:
            # Preserve manually overridden ETA if upstream did not provide one.
            entity_id = self.entity_id or getattr(self, "_attr_entity_id", None)
            existing_state = self.hass.states.get(entity_id) if entity_id else None
            if existing_state and ATTR_ETA in existing_state.attributes:
                attrs[ATTR_ETA] = existing_state.attributes[ATTR_ETA]
        if parcel.eta_timeframe:
            attrs[ATTR_ETA_TIMEFRAME] = parcel.eta_timeframe
        if parcel.registered_by:
            attrs[ATTR_REGISTERED_BY] = parcel.registered_by
        if parcel.last_api_update:
            attrs[ATTR_LAST_API_UPDATE] = parcel.last_api_update
        if parcel.tracking_url:
            attrs[ATTR_TRACKING_URL] = parcel.tracking_url
        if parcel.description:
            attrs[ATTR_DESCRIPTION] = parcel.description

        # Deep link to carrier delivery preferences
        pref_url = CARRIER_PREFERENCE_URLS.get(parcel.carrier, "").format(
            tracking_number=parcel.tracking_number
        )
        if pref_url:
            attrs[ATTR_PREFERENCE_URL] = pref_url

        return attrs
