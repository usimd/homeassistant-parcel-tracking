"""Data update coordinator for Parcel Tracker integration."""

from datetime import datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import Ship24Api
from .const import (
    CONF_CLEANUP_DAYS,
    CONF_DHL_API_KEY,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_CLEANUP_DAYS,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    EVENT_STATUS_CHANGED,
    STATUS_DELIVERED,
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
                # Use stored tracker_id for subsequent calls (faster)
                if parcel.tracker_id:
                    info = await self.api.get_results(parcel.tracker_id)
                else:
                    info = await self.api.track(tn)

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

            # Persist changes
            await self.store.async_save()

            return self.store.parcels
        except Exception as err:
            _LOGGER.error("Error fetching parcel tracking data: %s", err)
            raise UpdateFailed(f"Error communicating with Ship24 API: {err}") from err

    async def _enrich_dhl_parcels(self) -> None:
        """Enrich DHL parcels with delivery time window from DHL API."""
        if not self.dhl_api:
            return

        for tn, parcel in list(self.store.parcels.items()):
            if parcel.status == STATUS_DELIVERED:
                continue
            if not is_dhl_parcel(parcel.carrier):
                continue
            # Only call DHL if Ship24 didn't provide an ETA
            if parcel.eta:
                continue

            dhl_info = await self.dhl_api.get_details(tn)
            if dhl_info is None:
                continue

            if dhl_info.eta_date:
                parcel.eta = dhl_info.eta_date
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
            self.store.remove(tn)
