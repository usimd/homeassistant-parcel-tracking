"""The Parcel Tracker integration."""

import logging

import voluptuous as vol

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
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
    WEBHOOK_ID,
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

    # Load persistent parcel store
    store = ParcelStore(hass)
    await store.async_load()

    # Create coordinator
    coordinator = ParcelTrackerCoordinator(hass, api, store, entry)

    # Initial data fetch — coordinator handles API errors via its retry mechanism
    if store.get_all_tracking_numbers():
        try:
            await coordinator.async_config_entry_first_refresh()
        except Exception:
            _LOGGER.warning("Initial API fetch failed; will retry on next interval")
            coordinator.data = store.parcels
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

    # Register webhook (skip if already registered from a previous setup)
    if WEBHOOK_ID not in hass.data.get("webhook", {}):
        webhook.async_register(
            hass,
            DOMAIN,
            "Parcel Tracker",
            WEBHOOK_ID,
            _handle_webhook,
            allowed_methods=["POST"],
            local_only=False,
        )

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
        await _add_parcel(
            hass,
            coordinator,
            tracking_number=call.data.get(ATTR_TRACKING_NUMBER),
            tracking_url=call.data.get(ATTR_TRACKING_URL),
            carrier=call.data.get(ATTR_CARRIER),
            description=call.data.get(ATTR_DESCRIPTION),
            registered_by=call.data.get(ATTR_REGISTERED_BY),
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


async def _add_parcel(
    hass: HomeAssistant,
    coordinator: ParcelTrackerCoordinator,
    *,
    tracking_number: str | None = None,
    tracking_url: str | None = None,
    carrier: str | None = None,
    description: str | None = None,
    registered_by: str | None = None,
) -> bool:
    """Add a parcel for tracking. Returns True if successful."""
    # Parse tracking URL if provided
    if tracking_url and not tracking_number:
        parsed_carrier, parsed_number = parse_tracking_url(tracking_url)
        if parsed_number:
            tracking_number = parsed_number
            if not carrier and parsed_carrier:
                carrier = parsed_carrier
        else:
            _LOGGER.error("Could not parse tracking URL: %s", tracking_url)
            return False

    if not tracking_number:
        _LOGGER.error("No tracking number provided or parseable from URL")
        return False

    # Check for duplicate
    if coordinator.store.get(tracking_number):
        _LOGGER.warning("Parcel %s is already being tracked", tracking_number)
        return False

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

    # Fire event for automations
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

    _LOGGER.info("Registered parcel %s (%s) for tracking", tracking_number, carrier)
    return True


async def _handle_webhook(
    hass: HomeAssistant, webhook_id: str, request
) -> None:
    """Handle incoming webhook with a shared tracking URL."""
    from aiohttp import web

    try:
        data = await request.json()
    except (ValueError, KeyError):
        raise web.HTTPBadRequest(text="Invalid JSON")

    tracking_url = data.get("url") or data.get("text") or ""
    registered_by = data.get("device") or "webhook"
    description = data.get("description")

    if not tracking_url:
        raise web.HTTPBadRequest(text="Missing 'url' or 'text' field")

    try:
        coordinator = _get_coordinator(hass)
    except ValueError:
        raise web.HTTPServiceUnavailable(text="Integration not ready")

    success = await _add_parcel(
        hass,
        coordinator,
        tracking_url=tracking_url,
        description=description,
        registered_by=registered_by,
    )

    if success:
        return web.json_response({"status": "ok"})
    raise web.HTTPUnprocessableEntity(text="Could not register parcel")


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
