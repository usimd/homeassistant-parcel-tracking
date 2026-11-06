"""The Parcel Tracker integration."""

import logging
from datetime import date
from secrets import token_urlsafe
from typing import Any, cast
from urllib.parse import urlsplit

from aiohttp import web
import voluptuous as vol

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .api import Ship24Api
from .const import (
    ATTR_CARRIER,
    ATTR_COURIER_CODE,
    ATTR_SHIPPING_DATE,
    ATTR_RESTRICT_COURIER,
    ATTR_DESCRIPTION,
    ATTR_REGISTERED_BY,
    ATTR_TRACKING_NUMBER,
    ATTR_TRACKING_URL,
    CONF_API_KEY,
    CONF_WEBHOOK_ID,
    CONF_WEBHOOK_ALLOW_EXTERNAL,
    DOMAIN,
    EVENT_PARCEL_ADDED,
    SERVICE_ADD,
    SERVICE_REMOVE,
    SIGNAL_NEW_PARCEL,
    WEBHOOK_ID,
)
from .coordinator import ParcelTrackerCoordinator
from .store import ParcelData, ParcelStore
from .url_parser import build_preference_url, build_tracking_url, parse_tracking_url

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


def _validate_tracking_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme in ("http", "https") and parsed.hostname:
            return value
    except ValueError:
        pass
    raise vol.Invalid("Expected an HTTP(S) tracking URL")


SERVICE_ADD_SCHEMA = vol.Schema(
    vol.All(
        {
            vol.Optional(ATTR_TRACKING_NUMBER): vol.All(
                str, str.strip, vol.Match(r"^[a-zA-Z0-9_./-]{5,50}$")
            ),
            vol.Optional(ATTR_TRACKING_URL): vol.All(
                str, str.strip, vol.Length(min=1, max=1000), _validate_tracking_url
            ),
            vol.Optional(ATTR_CARRIER): str,
            vol.Optional(ATTR_COURIER_CODE): str,
            vol.Optional(ATTR_SHIPPING_DATE): vol.All(
                str, vol.Coerce(date.fromisoformat), lambda value: value.isoformat()
            ),
            vol.Optional(ATTR_RESTRICT_COURIER): bool,
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
    _LOGGER.debug("async_setup_entry starting for %s", entry.entry_id)

    api = Ship24Api(hass, entry.data[CONF_API_KEY])

    # Load persistent parcel store
    store = ParcelStore(hass)
    await store.async_load()
    _LOGGER.debug("Store loaded, %d parcels", len(store.parcels))

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
        _LOGGER.debug("Services registered")

    webhook_id = entry.data.get(CONF_WEBHOOK_ID)
    if not webhook_id or webhook_id == WEBHOOK_ID:
        webhook_id = token_urlsafe(32)
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_WEBHOOK_ID: webhook_id}
        )
    webhook.async_unregister(hass, WEBHOOK_ID)
    if webhook_id not in hass.data.get("webhook", {}):
        webhook.async_register(
            hass,
            DOMAIN,
            "Parcel Tracker",
            webhook_id,
            _handle_webhook,
            allowed_methods=["POST"],
            local_only=not entry.options.get(CONF_WEBHOOK_ALLOW_EXTERNAL, False),
        )

    # Set up options flow listener
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _LOGGER.debug("async_setup_entry complete")
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
            courier_code=call.data.get(ATTR_COURIER_CODE),
            shipping_date=call.data.get(ATTR_SHIPPING_DATE),
            restrict_courier=call.data.get(ATTR_RESTRICT_COURIER, False),
            description=call.data.get(ATTR_DESCRIPTION),
            registered_by=call.data.get(ATTR_REGISTERED_BY),
        )

    async def handle_remove(call: ServiceCall) -> None:
        """Handle the remove parcel service call."""
        coordinator = _get_coordinator(hass)
        tracking_number = call.data[ATTR_TRACKING_NUMBER]

        if not await coordinator.async_remove_parcel(tracking_number):
            _LOGGER.warning("Parcel %s not found", tracking_number)
            return

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
    courier_code: str | None = None,
    shipping_date: str | None = None,
    restrict_courier: bool = False,
    description: str | None = None,
    registered_by: str | None = None,
) -> bool:
    """Add a parcel for tracking. Returns True if successful."""
    # Parse tracking URL if provided
    if tracking_url:
        parsed_carrier, parsed_number = parse_tracking_url(tracking_url)
        if not carrier and parsed_carrier:
            carrier = parsed_carrier
        if not tracking_number and parsed_number:
            tracking_number = parsed_number
        elif not tracking_number:
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
        tracking_url = build_tracking_url(carrier, tracking_number, courier_code)

    # Create and store parcel data
    parcel = ParcelData(
        tracking_number=tracking_number,
        carrier=carrier,
        description=description,
        registered_by=registered_by,
        tracking_url=tracking_url,
        courier_code=courier_code,
        shipping_date=shipping_date,
        restrict_courier=restrict_courier,
    )
    coordinator.store.add(parcel)
    await coordinator.store.async_save()

    # Signal sensor platform to create entity
    async_dispatcher_send(hass, SIGNAL_NEW_PARCEL, tracking_number)

    # Fire event for automations
    preference_url = build_preference_url(carrier, tracking_number, courier_code)
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
) -> web.Response:
    """Handle incoming webhook with a shared tracking URL."""
    try:
        data = await request.json()
    except (ValueError, KeyError):
        raise web.HTTPBadRequest(text="Invalid JSON")

    if not isinstance(data, dict):
        raise web.HTTPBadRequest(text="Expected a JSON object")
    registration: dict[str, Any] = {
        key: data[key]
        for key in (
            ATTR_TRACKING_NUMBER,
            ATTR_TRACKING_URL,
            ATTR_CARRIER,
            ATTR_COURIER_CODE,
            ATTR_SHIPPING_DATE,
            ATTR_RESTRICT_COURIER,
            ATTR_DESCRIPTION,
        )
        if key in data
    }
    if ATTR_TRACKING_URL not in registration and (data.get("url") or data.get("text")):
        registration[ATTR_TRACKING_URL] = data.get("url") or data.get("text")
    registration[ATTR_REGISTERED_BY] = data.get("device") or "webhook"
    try:
        registration = cast(dict[str, Any], SERVICE_ADD_SCHEMA(registration))
    except vol.Invalid as err:
        raise web.HTTPBadRequest(text="Invalid parcel registration data") from err

    try:
        coordinator = _get_coordinator(hass)
    except ValueError:
        raise web.HTTPServiceUnavailable(text="Integration not ready")

    success = await _add_parcel(hass, coordinator, **registration)

    if success:
        return web.json_response({"status": "ok"})
    raise web.HTTPUnprocessableEntity(text="Could not register parcel")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        webhook_id = entry.data.get(CONF_WEBHOOK_ID)
        if webhook_id:
            webhook.async_unregister(hass, webhook_id)
        hass.data[DOMAIN].pop(entry.entry_id)

        # Remove services if no more entries
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_ADD)
            hass.services.async_remove(DOMAIN, SERVICE_REMOVE)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
