"""The Parcel Tracker integration."""

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers import entity_registry as er

from .api import Ship24Api
from .const import (
    ATTR_CARRIER,
    ATTR_DESCRIPTION,
    ATTR_REGISTERED_BY,
    ATTR_TRACKING_NUMBER,
    ATTR_TRACKING_URL,
    CARRIER_PREFERENCE_URLS,
    CONF_API_KEY,
    DOMAIN,
    EVENT_PARCEL_ADDED,
    SERVICE_ADD,
    SERVICE_REMOVE,
    SIGNAL_NEW_PARCEL,
    SIGNAL_REMOVE_PARCEL,
)
from .coordinator import ParcelTrackerCoordinator
from .store import ParcelData, ParcelStore
from .url_parser import build_tracking_url, parse_tracking_url

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

SERVICE_ADD_SCHEMA = vol.Schema(
    vol.All(
        {
            vol.Optional(ATTR_TRACKING_NUMBER): str,
            vol.Optional(ATTR_TRACKING_URL): str,
            vol.Optional(ATTR_CARRIER): str,
            vol.Optional(ATTR_DESCRIPTION): str,
            vol.Optional(ATTR_REGISTERED_BY): str,
        },
        vol.Any(
            vol.Schema(
                {vol.Required(ATTR_TRACKING_NUMBER): str},
                extra=vol.ALLOW_EXTRA,
            ),
            vol.Schema(
                {vol.Required(ATTR_TRACKING_URL): str},
                extra=vol.ALLOW_EXTRA,
            ),
        ),
    )
)

SERVICE_REMOVE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TRACKING_NUMBER): str,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Parcel Tracker from a config entry."""
    api = Ship24Api(hass, entry.data[CONF_API_KEY])

    # Verify connection
    if not await api.test_connection():
        raise ConfigEntryNotReady("Cannot connect to Ship24 API")

    # Load persistent parcel store
    store = ParcelStore(hass)
    await store.async_load()

    # Create coordinator
    coordinator = ParcelTrackerCoordinator(hass, api, store, entry)

    # Initial data fetch (don't fail if no parcels yet)
    if store.get_all_tracking_numbers():
        await coordinator.async_config_entry_first_refresh()
    else:
        coordinator.data = store.parcels

    # Store coordinator
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Set up sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services (only once)
    if not hass.services.has_service(DOMAIN, SERVICE_ADD):
        _register_services(hass)

    # Set up options flow listener
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


def _get_coordinator(hass: HomeAssistant) -> ParcelTrackerCoordinator:
    """Get the first available coordinator."""
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise ValueError("Parcel Tracker integration not set up")
    return next(iter(entries.values()))


def _register_services(hass: HomeAssistant) -> None:
    """Register integration services."""

    async def handle_add(call: ServiceCall) -> None:
        """Handle the add parcel service call."""
        coordinator = _get_coordinator(hass)

        tracking_number = call.data.get(ATTR_TRACKING_NUMBER)
        tracking_url = call.data.get(ATTR_TRACKING_URL)
        carrier = call.data.get(ATTR_CARRIER)
        description = call.data.get(ATTR_DESCRIPTION)
        registered_by = call.data.get(ATTR_REGISTERED_BY)

        # Parse tracking URL if provided
        if tracking_url and not tracking_number:
            parsed_carrier, parsed_number = parse_tracking_url(tracking_url)
            if parsed_number:
                tracking_number = parsed_number
                if not carrier and parsed_carrier:
                    carrier = parsed_carrier
            else:
                _LOGGER.error("Could not parse tracking URL: %s", tracking_url)
                return

        if not tracking_number:
            _LOGGER.error("No tracking number provided or parseable from URL")
            return

        # Check for duplicate
        if coordinator.store.get(tracking_number):
            _LOGGER.warning("Parcel %s is already being tracked", tracking_number)
            return

        carrier = carrier or "Unknown"

        # Build tracking URL if not provided
        if not tracking_url:
            tracking_url = build_tracking_url(carrier, tracking_number)

        # Create and store parcel data
        parcel = ParcelData(
            tracking_number=tracking_number,
            carrier=carrier,
            description=description,
            registered_by=registered_by,
            tracking_url=tracking_url,
        )
        coordinator.store.add(parcel)
        await coordinator.store.async_save()

        # Signal sensor platform to create entity
        async_dispatcher_send(hass, SIGNAL_NEW_PARCEL, tracking_number)

        # Fire event for automations (includes preference URL)
        preference_url = CARRIER_PREFERENCE_URLS.get(carrier, "").format(
            tracking_number=tracking_number
        )

        hass.bus.async_fire(
            EVENT_PARCEL_ADDED,
            {
                "tracking_number": tracking_number,
                "carrier": carrier,
                "description": description or "",
                "tracking_url": tracking_url or "",
                "preference_url": preference_url,
            },
        )

        # Trigger a refresh to get initial status
        await coordinator.async_request_refresh()

        _LOGGER.info(
            "Registered parcel %s (%s) for tracking",
            tracking_number,
            carrier,
        )

    async def handle_remove(call: ServiceCall) -> None:
        """Handle the remove parcel service call."""
        coordinator = _get_coordinator(hass)
        tracking_number = call.data[ATTR_TRACKING_NUMBER]

        parcel = coordinator.store.remove(tracking_number)
        if not parcel:
            _LOGGER.warning("Parcel %s not found", tracking_number)
            return

        # Save store
        await coordinator.store.async_save()

        # Remove entity from registry
        entity_registry = er.async_get(hass)
        for entry_id in hass.data.get(DOMAIN, {}):
            unique_id = f"{entry_id}_{tracking_number}"
            entity_id = entity_registry.async_get_entity_id(
                Platform.SENSOR, DOMAIN, unique_id
            )
            if entity_id:
                entity_registry.async_remove(entity_id)

        # Signal removal
        async_dispatcher_send(hass, SIGNAL_REMOVE_PARCEL, tracking_number)

        _LOGGER.info("Removed parcel %s from tracking", tracking_number)

    hass.services.async_register(
        DOMAIN, SERVICE_ADD, handle_add, schema=SERVICE_ADD_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE, handle_remove, schema=SERVICE_REMOVE_SCHEMA
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

        # Remove services if no more entries
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_ADD)
            hass.services.async_remove(DOMAIN, SERVICE_REMOVE)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)
