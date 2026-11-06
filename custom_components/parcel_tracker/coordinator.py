"""Data update coordinator for Parcel Tracker integration."""

from datetime import datetime, timedelta
import logging
from asyncio import Lock

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import Ship24Api, TrackingInfo
from .const import (
    CARRIER_URL_PATTERNS,
    CONF_CLEANUP_DAYS,
    CONF_DESTINATION_COUNTRY_CODE,
    CONF_DESTINATION_POST_CODE,
    CONF_DHL_API_KEY,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_CLEANUP_DAYS,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    EVENT_STATUS_CHANGED,
    SIGNAL_REMOVE_PARCEL,
    STATUS_DELIVERED,
    STATUS_IN_TRANSIT,
    STATUS_EXCEPTION,
    STATUS_REGISTERED,
    STATUS_UNKNOWN,
)
from .dhl_api import DhlApi, is_dhl_parcel
from .store import ParcelData, ParcelStore
from .url_parser import build_preference_url, build_tracking_url

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
        self._update_lock = Lock()

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
        """Serialize polling with incoming Ship24 push updates."""
        async with self._update_lock:
            return await self._async_poll_data()

    async def _async_poll_data(self) -> dict[str, ParcelData]:
        """Fetch tracking data from Ship24 API."""
        try:
            old_statuses = {
                tn: parcel.status for tn, parcel in self.store.parcels.items()
            }
            destination_country_code, destination_post_code = (
                self._get_home_destination_metadata()
            )

            for tn, parcel in list(self.store.parcels.items()):
                if parcel.status == STATUS_DELIVERED:
                    continue

                if parcel.tracker_id:
                    info = await self.api.get_results(parcel.tracker_id)
                else:
                    if parcel.tracking_request is None:
                        courier_hint = parcel.courier_code
                        if not courier_hint and parcel.carrier in CARRIER_URL_PATTERNS:
                            courier_hint = CARRIER_URL_PATTERNS[parcel.carrier][2]
                        elif not courier_hint and parcel.carrier != "Unknown":
                            couriers = await self.api.get_couriers()
                            for code, courier in couriers.items():
                                if parcel.carrier.casefold() in (
                                    code.casefold(),
                                    (courier.get("courierName") or "").casefold(),
                                ):
                                    courier_hint = code
                                    break
                        parcel.tracking_request = {
                            "tracking_number": tn,
                            "courier_code": courier_hint,
                            "courier_name": parcel.carrier
                            if parcel.carrier != "Unknown"
                            else None,
                            "tracking_url": parcel.tracking_url,
                            "destination_country_code": destination_country_code,
                            "destination_post_code": destination_post_code,
                            "shipping_date": parcel.shipping_date,
                            "restrict_courier": parcel.restrict_courier,
                        }
                        await self.store.async_save()
                    info = await self.api.track(**parcel.tracking_request)

                if info is None:
                    continue

                if info.tracker_id and not parcel.tracker_id:
                    parcel.tracker_id = info.tracker_id

                self._apply_ship24_info(parcel, info)

            await self._enrich_dhl_parcels()

            for tn, parcel in list(self.store.parcels.items()):
                self._finish_status_update(parcel, old_statuses.get(tn, parcel.status))

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

    def _apply_ship24_info(self, parcel: ParcelData, info: TrackingInfo) -> None:
        if parcel.status == STATUS_DELIVERED:
            return
        parcel.last_api_update = dt_util.utcnow().isoformat()
        comparison = self._compare_event_times(
            info.latest_event_time, parcel.latest_event_time
        )
        if comparison == -1 and info.status != STATUS_DELIVERED:
            return
        if (
            comparison == 0
            and parcel.status_source == "ship24"
            and info.latest_event_order is not None
            and parcel.latest_event_order is not None
            and info.latest_event_order < parcel.latest_event_order
            and info.status != STATUS_DELIVERED
        ):
            return
        if info.courier_code:
            parcel.courier_code = info.courier_code
        if info.courier_name:
            parcel.carrier = info.courier_name
        if not parcel.tracking_url:
            parcel.tracking_url = build_tracking_url(
                parcel.carrier, parcel.tracking_number, parcel.courier_code
            )
        if info.status != STATUS_UNKNOWN and (
            info.status == STATUS_DELIVERED
            or (
                comparison != -1
                and (
                    parcel.status_source != "dhl"
                    or comparison == 1
                    or (not parcel.latest_event_time and info.latest_event_time)
                )
            )
        ):
            parcel.status = info.status
            parcel.status_source = "ship24"
            parcel.latest_event_time = info.latest_event_time
            parcel.latest_event_description = info.latest_event_description
            parcel.latest_event_order = info.latest_event_order
            if info.eta:
                parcel.eta = info.eta

    def _finish_status_update(self, parcel: ParcelData, old_status: str) -> None:
        if parcel.status == STATUS_DELIVERED and parcel.delivered_at is None:
            parcel.delivered_at = dt_util.utcnow().isoformat()
        if old_status != parcel.status:
            self.hass.bus.async_fire(
                EVENT_STATUS_CHANGED,
                {
                    "tracking_number": parcel.tracking_number,
                    "carrier": parcel.carrier,
                    "courier_code": parcel.courier_code,
                    "old_status": old_status,
                    "new_status": parcel.status,
                    "status_source": parcel.status_source,
                    "eta": parcel.eta,
                    "preference_url": build_preference_url(
                        parcel.carrier, parcel.tracking_number, parcel.courier_code
                    ),
                    "tracking_url": parcel.tracking_url or "",
                },
            )

    async def async_process_ship24_updates(self, trackings: list[dict]) -> None:
        """Apply authenticated push observations only to existing tracker IDs."""
        async with self._update_lock:
            parcels_by_tracker = {
                parcel.tracker_id: parcel
                for parcel in self.store.parcels.values()
                if parcel.tracker_id
            }
            snapshots: dict[str, dict] = {}
            try:
                for tracking in trackings:
                    tracker = tracking["tracker"]
                    parcel = parcels_by_tracker.get(tracker["trackerId"])
                    if (
                        parcel is None
                        or parcel.tracking_number != tracker["trackingNumber"]
                        or parcel.status == STATUS_DELIVERED
                    ):
                        continue
                    snapshots.setdefault(parcel.tracking_number, parcel.to_dict())
                    info = await self.api.parse_tracking(
                        tracking, use_cached_couriers=True
                    )
                    self._apply_ship24_info(parcel, info)
                    if (
                        parcel.status == STATUS_DELIVERED
                        and parcel.delivered_at is None
                    ):
                        parcel.delivered_at = dt_util.utcnow().isoformat()
                if not snapshots:
                    return
                await self.store.async_save(verify=True)
            except Exception:
                for tracking_number, snapshot in snapshots.items():
                    parcel = self.store.get(tracking_number)
                    if parcel is not None:
                        for attribute, value in snapshot.items():
                            setattr(parcel, attribute, value)
                raise
            for tracking_number, snapshot in snapshots.items():
                parcel = self.store.get(tracking_number)
                if parcel is not None:
                    self._finish_status_update(parcel, snapshot["status"])
            self.data = self.store.parcels
            self.last_update_success = True
            self.last_exception = None
            self.async_update_listeners()

    def _get_home_destination_metadata(self) -> tuple[str | None, str | None]:
        """Get destination country/post code for Ship24 requests.

        Explicit options override Home Assistant home data.
        """
        country = self.entry.options.get(CONF_DESTINATION_COUNTRY_CODE, None)
        postal_code = self.entry.options.get(CONF_DESTINATION_POST_CODE, None)

        if isinstance(country, str):
            country = country.strip().upper() or None
        if isinstance(postal_code, str):
            postal_code = postal_code.strip() or None

        if country and postal_code:
            return country, postal_code

        if not country:
            country = getattr(self.hass.config, "country", None)
        if not postal_code:
            postal_code = getattr(self.hass.config, "postal_code", None)

        home_state = self.hass.states.get("zone.home")
        if home_state:
            if not country:
                country = home_state.attributes.get("country")
            if not postal_code:
                for key in (
                    "postal_code",
                    "postcode",
                    "post_code",
                    "zip",
                    "zip_code",
                ):
                    value = home_state.attributes.get(key)
                    if value:
                        postal_code = value
                        break

        if isinstance(country, str):
            country = country.strip().upper() or None
        if isinstance(postal_code, str):
            postal_code = postal_code.strip() or None

        return country, postal_code

    async def _enrich_dhl_parcels(self) -> None:
        """Merge direct DHL status and delivery estimates before emitting events."""
        if not self.dhl_api:
            return

        for tn, parcel in list(self.store.parcels.items()):
            if parcel.status == STATUS_DELIVERED:
                continue
            if not is_dhl_parcel(parcel.carrier, parcel.courier_code):
                continue

            dhl_info = await self.dhl_api.get_details(tn)
            if dhl_info is None:
                continue

            parcel.last_api_update = dt_util.utcnow().isoformat()
            status = {
                "pre-transit": STATUS_REGISTERED,
                "transit": STATUS_IN_TRANSIT,
                "delivered": STATUS_DELIVERED,
                "failure": STATUS_EXCEPTION,
            }.get(dhl_info.status_code or "")
            comparison = self._compare_event_times(
                dhl_info.latest_event_time, parcel.latest_event_time
            )
            if status is not None and (
                status == STATUS_DELIVERED
                or (
                    comparison != -1
                    and (
                        comparison == 1
                        or parcel.status in (STATUS_REGISTERED, STATUS_UNKNOWN)
                    )
                )
            ):
                parcel.status = status
                parcel.status_source = "dhl"
                parcel.latest_event_time = dhl_info.latest_event_time
                parcel.latest_event_description = dhl_info.latest_event_description
                parcel.latest_event_order = None

            if dhl_info.eta_date:
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

    @staticmethod
    def _compare_event_times(candidate: str | None, current: str | None) -> int | None:
        """Compare event times only when both have compatible timezone information."""
        if not candidate or not current:
            return None
        try:
            candidate_time = datetime.fromisoformat(candidate)
            current_time = datetime.fromisoformat(current)
            return (candidate_time > current_time) - (candidate_time < current_time)
        except (ValueError, TypeError):
            return None

    async def _cleanup_delivered_parcels(self) -> None:
        """Remove parcels that have been delivered for more than N days."""
        cleanup_days = self.entry.options.get(CONF_CLEANUP_DAYS, DEFAULT_CLEANUP_DAYS)
        now = dt_util.utcnow()
        to_remove: list[str] = []

        for tn, parcel in self.store.parcels.items():
            if parcel.status == STATUS_DELIVERED and parcel.delivered_at:
                delivered_at = dt_util.as_utc(
                    datetime.fromisoformat(parcel.delivered_at)
                )
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
