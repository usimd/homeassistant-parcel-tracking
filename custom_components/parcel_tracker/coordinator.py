"""Data update coordinator for Parcel Tracker integration."""

from datetime import datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import Ship24Api
from .const import (
    CARRIER_URL_PATTERNS,
    CONF_CLEANUP_DAYS,
    CONF_DHL_API_KEY,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_CLEANUP_DAYS,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    EVENT_STATUS_CHANGED,
    SIGNAL_REMOVE_PARCEL,
    STATUS_DELIVERED,
    STATUS_OUT_FOR_DELIVERY,
    STATUS_REGISTERED,
)
from .dhl_api import DhlApi, is_dhl_parcel
from .store import ParcelData, ParcelStore

_LOGGER = logging.getLogger(__name__)


class ParcelTrackerCoordinator(DataUpdateCoordinator[dict[str, ParcelData]]):
    """Coordinator to manage fetching parcel data from Ship24 API."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: Ship24Api,
        store: ParcelStore,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        self.api = api
        self.store = store
        self.entry = entry

        # Optional DHL API for enrichment
        dhl_key = entry.options.get(CONF_DHL_API_KEY, "")
        self.dhl_api: DhlApi | None = DhlApi(hass, dhl_key) if dhl_key else None

        scan_interval_hours = entry.options.get(
            CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=scan_interval_hours),
            config_entry=entry,
        )

    async def _async_update_data(self) -> dict[str, ParcelData]:
        """Fetch tracking data from Ship24 API."""
        try:
            now_iso = datetime.now().isoformat()

            for tn, parcel in list(self.store.parcels.items()):
                # If the parcel is still registered with no events, clear the
                # tracker_id so the next call re-creates the tracker with a
                # courier code hint — this recovers stuck Ship24 auto-detection.
                if (
                    parcel.tracker_id
                    and parcel.status == STATUS_REGISTERED
                    and parcel.carrier in CARRIER_URL_PATTERNS
                ):
                    _LOGGER.debug(
                        "Parcel %s stuck on registered with known carrier %s — "
                        "retrying track() with courier hint",
                        tn,
                        parcel.carrier,
                    )
                    parcel.tracker_id = None

                # Use stored tracker_id for subsequent calls (faster)
                if parcel.tracker_id:
                    info = await self.api.get_results(parcel.tracker_id)
                else:
                    courier_hint = CARRIER_URL_PATTERNS[parcel.carrier][2] if parcel.carrier in CARRIER_URL_PATTERNS else None
                    info = await self.api.track(tn, courier_hint)

                if info is None:
                    continue

                # Store tracker_id for future lookups
                if info.tracker_id and not parcel.tracker_id:
                    parcel.tracker_id = info.tracker_id

                old_status = parcel.status

                # Update parcel data from API
                parcel.status = info.status
                parcel.last_api_update = now_iso

                if info.eta:
                    parcel.eta = info.eta

                # Update carrier from API detection if we didn't know it
                if info.courier_name and parcel.carrier == "Unknown":
                    parcel.carrier = info.courier_name

                # Track when parcel was delivered
                if info.status == STATUS_DELIVERED and parcel.delivered_at is None:
                    parcel.delivered_at = now_iso

                # Fire event on status change
                if old_status != info.status:
                    from .const import CARRIER_PREFERENCE_URLS

                    preference_url = CARRIER_PREFERENCE_URLS.get(
                        parcel.carrier, ""
                    ).format(tracking_number=tn)

                    self.hass.bus.async_fire(
                        EVENT_STATUS_CHANGED,
                        {
                            "tracking_number": tn,
                            "carrier": parcel.carrier,
                            "old_status": old_status,
                            "new_status": info.status,
                            "eta": parcel.eta,
                            "preference_url": preference_url,
                            "tracking_url": parcel.tracking_url or "",
                        },
                    )

            # Enrich DHL parcels with delivery time window
            await self._enrich_dhl_parcels()

            # Auto-cleanup delivered parcels
            await self._cleanup_delivered_parcels()

            # Clean up orphaned unavailable entities
            await self.async_cleanup_unavailable_entities()

            # Persist changes
            await self.store.async_save()

            return self.store.parcels
        except Exception as err:
            _LOGGER.error("Error fetching parcel tracking data: %s", err)
            raise UpdateFailed(f"Error communicating with Ship24 API: {err}") from err

    async def _enrich_dhl_parcels(self) -> None:
        """Enrich DHL parcels with delivery time window and status from DHL API.
        
        DHL API is often more current than Ship24. If DHL shows delivered
        but Ship24 is stuck at out_for_delivery, trust DHL.
        """
        if not self.dhl_api:
            return

        for tn, parcel in list(self.store.parcels.items()):
            if parcel.status == STATUS_DELIVERED:
                continue
            if not is_dhl_parcel(parcel.carrier):
                continue

            dhl_info = await self.dhl_api.get_details(tn)
            if dhl_info is None:
                continue

            # If DHL shows delivered but Ship24 shows out_for_delivery,
            # upgrade to delivered (DHL is usually more current)
            if (
                dhl_info.status_code == "delivered"
                and parcel.status == STATUS_OUT_FOR_DELIVERY
            ):
                _LOGGER.info(
                    "DHL shows delivered for %s, upgrading from out_for_delivery",
                    tn,
                )
                parcel.status = STATUS_DELIVERED
                if parcel.delivered_at is None:
                    parcel.delivered_at = datetime.now().isoformat()
            
            # Update ETA only if DHL provides one and we don't have one yet
            if dhl_info.eta_date and not parcel.eta:
                parcel.eta = dhl_info.eta_date
                _LOGGER.debug("DHL ETA for %s: %s", tn, dhl_info.eta_date)
            
            # Always update timeframe (don't skip if eta exists)
            if dhl_info.eta_timeframe_from and dhl_info.eta_timeframe_to:
                parcel.eta_timeframe = (
                    f"{dhl_info.eta_timeframe_from} – {dhl_info.eta_timeframe_to}"
                )
            elif dhl_info.eta_timeframe_from or dhl_info.eta_timeframe_to:
                parcel.eta_timeframe = (
                    dhl_info.eta_timeframe_from or dhl_info.eta_timeframe_to
                )

    async def _cleanup_delivered_parcels(self) -> None:
        """Remove parcels that have been delivered for more than N days."""
        cleanup_days = self.entry.options.get(CONF_CLEANUP_DAYS, DEFAULT_CLEANUP_DAYS)
        now = datetime.now()
        to_remove: list[str] = []

        for tn, parcel in self.store.parcels.items():
            if parcel.status == STATUS_DELIVERED and parcel.delivered_at:
                delivered_at = datetime.fromisoformat(parcel.delivered_at)
                if (now - delivered_at) > timedelta(days=cleanup_days):
                    to_remove.append(tn)

        for tn in to_remove:
            _LOGGER.info(
                "Auto-removing delivered parcel %s (delivered > %d days ago)",
                tn,
                cleanup_days,
            )
            await self.async_remove_parcel(tn, save=False)

    async def async_cleanup_unavailable_entities(self) -> None:
        """Remove orphaned unavailable sensor entities from the registry.
        
        This cleans up entities whose parcels were removed but whose entity
        registry entries still exist.
        """
        entity_registry = er.async_get(self.hass)
        stored_tracking_numbers = set(self.store.get_all_tracking_numbers())
        
        for entity in list(entity_registry.entities.values()):
            if entity.platform != DOMAIN or entity.domain != Platform.SENSOR:
                continue
            # Entity unique_id format is "<entry_id>_<tracking_number>"
            if "_" not in entity.unique_id:
                continue
            entry_id, tracking_number = entity.unique_id.rsplit("_", 1)
            if entry_id != self.entry.entry_id:
                continue
            if tracking_number not in stored_tracking_numbers:
                _LOGGER.debug(
                    "Removing orphaned entity %s for tracking number %s",
                    entity.entity_id,
                    tracking_number,
                )
                entity_registry.async_remove(entity.entity_id)

    async def async_remove_parcel(
        self, tracking_number: str, *, save: bool = True
    ) -> bool:
        """Remove a tracked parcel and delete the associated entity."""
        parcel = self.store.remove(tracking_number)
        if parcel is None:
            return False

        entity_registry = er.async_get(self.hass)
        for entry_id in self.hass.data.get(DOMAIN, {}):
            unique_id = f"{entry_id}_{tracking_number}"
            entity_id = entity_registry.async_get_entity_id(
                Platform.SENSOR, DOMAIN, unique_id
            )
            if entity_id:
                entity_registry.async_remove(entity_id)

        async_dispatcher_send(self.hass, SIGNAL_REMOVE_PARCEL, tracking_number)

        if save:
            await self.store.async_save()

        _LOGGER.info("Removed parcel %s from tracking", tracking_number)
        return True
