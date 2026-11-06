"""Ship24 Tracking API client.

Ship24 provides universal parcel tracking across 1500+ couriers.
Free plan: 10 shipments/month.

API docs: https://docs.ship24.com
Base URL: https://api.ship24.com/public/v1
Auth: Bearer token in Authorization header
"""

import logging
from dataclasses import dataclass
from time import monotonic

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import SHIP24_STATUS_MAP, STATUS_UNKNOWN

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://api.ship24.com/public/v1"


@dataclass
class TrackingInfo:
    """Tracking information from Ship24 API."""

    tracking_number: str
    tracker_id: str
    status: str
    courier_code: str | None
    courier_name: str | None
    eta: str | None
    latest_event_time: str | None
    latest_event_description: str | None


class Ship24Api:
    """Client for the Ship24 Tracking API."""

    def __init__(self, hass: HomeAssistant, api_key: str) -> None:
        """Initialize the API client."""
        self._hass = hass
        self._api_key = api_key
        self._session = async_get_clientsession(hass)
        self._couriers: dict[str, dict] = {}
        self._couriers_checked_at: float | None = None
        self._couriers_cache_seconds = 300

    @property
    def _headers(self) -> dict[str, str]:
        """Return request headers."""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json; charset=utf-8",
        }

    async def test_connection(self) -> bool:
        """Test the API connection by listing trackers."""
        try:
            resp = await self._session.get(
                f"{BASE_URL}/trackers",
                headers=self._headers,
                params={"limit": 1},
            )
            # 401 = bad key, 200 = good
            return resp.status == 200
        except Exception:
            _LOGGER.exception("Error testing Ship24 API connection")
            return False

    async def track(
        self,
        tracking_number: str,
        courier_code: str | None = None,
        destination_country_code: str | None = None,
        destination_post_code: str | None = None,
        shipping_date: str | None = None,
        *,
        tracking_url: str | None = None,
        courier_name: str | None = None,
        restrict_courier: bool = False,
    ) -> TrackingInfo | None:
        """Create tracker (idempotent) and get tracking results.

        Uses POST /trackers/track which creates a tracker if it doesn't exist
        and returns tracking results. Subsequent calls are instant.
        Pass courier_code to hint Ship24 about the carrier when auto-detection fails.
        Repeated creation requests must use the original metadata to avoid
        creating another tracker. Only supply a known, actual shipping date.
        """
        try:
            payload: dict = {"trackingNumber": tracking_number}
            if courier_code:
                payload["courierCode"] = [courier_code]
            if courier_code and restrict_courier:
                payload["settings"] = {"restrictTrackingToCourierCode": True}
            if courier_name:
                payload["courierName"] = courier_name
            if tracking_url:
                payload["trackingUrl"] = tracking_url
            if destination_country_code:
                payload["destinationCountryCode"] = destination_country_code
            if destination_post_code:
                payload["destinationPostCode"] = destination_post_code
            if shipping_date:
                payload["shippingDate"] = shipping_date
            resp = await self._session.post(
                f"{BASE_URL}/trackers/track",
                headers=self._headers,
                json=payload,
            )

            if resp.status not in (200, 201):
                _LOGGER.debug(
                    "Ship24 API returned status %s for %s",
                    resp.status,
                    tracking_number,
                )
                return None

            data = await resp.json()
            return await self._parse_results(data, tracking_number)
        except Exception:
            _LOGGER.exception("Error tracking parcel %s via Ship24", tracking_number)
            return None

    async def get_results(self, tracker_id: str) -> TrackingInfo | None:
        """Get tracking results for an existing tracker by ID."""
        try:
            resp = await self._session.get(
                f"{BASE_URL}/trackers/{tracker_id}/results",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                },
            )

            if resp.status != 200:
                return None

            data = await resp.json()
            return await self._parse_results(data)
        except Exception:
            _LOGGER.exception("Error getting results for tracker %s", tracker_id)
            return None

    async def get_couriers(self) -> dict[str, dict]:
        """Return cached courier metadata, retaining it during API outages."""
        now = monotonic()
        if (
            self._couriers_checked_at is not None
            and now - self._couriers_checked_at < self._couriers_cache_seconds
        ):
            return self._couriers
        self._couriers_checked_at = now
        self._couriers_cache_seconds = 300
        try:
            response = await self._session.get(
                f"{BASE_URL}/couriers", headers=self._headers
            )
            if response.status != 200:
                return self._couriers
            data = await response.json()
            self._couriers = {
                courier["courierCode"]: courier
                for courier in (data.get("data") or {}).get("couriers", [])
                if courier.get("courierCode") and not courier.get("isDeprecated")
            }
            self._couriers_cache_seconds = 86400
        except Exception:
            _LOGGER.warning("Unable to refresh Ship24 courier catalog", exc_info=True)
        return self._couriers

    async def _parse_results(
        self, data: dict, tracking_number: str | None = None
    ) -> TrackingInfo | None:
        """Normalize tracking responses from both Ship24 endpoints."""
        trackings = (data.get("data") or {}).get("trackings") or []
        if not trackings:
            return None
        tracking = trackings[0]
        tracker = tracking.get("tracker") or {}
        shipment = tracking.get("shipment") or {}
        events = tracking.get("events") or []
        latest_event = events[0] if events else {}
        codes = tracker.get("courierCode") or []
        if isinstance(codes, str):
            codes = [codes]
        courier_code = latest_event.get("courierCode") or (codes[0] if codes else None)
        courier_name = None
        if courier_code:
            couriers = await self.get_couriers()
            courier_name = couriers.get(courier_code, {}).get("courierName")
        courier_name = courier_name or tracker.get("courierName")
        delivery = shipment.get("delivery") or {}
        eta = delivery.get("estimatedDeliveryDate")
        courier_eta = delivery.get("courierEstimatedDeliveryDate") or {}
        if isinstance(courier_eta, dict):
            eta = courier_eta.get("to") or courier_eta.get("from") or eta
        return TrackingInfo(
            tracking_number=tracking_number or tracker.get("trackingNumber", ""),
            tracker_id=tracker.get("trackerId", ""),
            status=SHIP24_STATUS_MAP.get(
                shipment.get("statusMilestone", "pending"), STATUS_UNKNOWN
            ),
            courier_code=courier_code,
            courier_name=courier_name,
            eta=eta,
            latest_event_time=latest_event.get("occurrenceDatetime"),
            latest_event_description=latest_event.get("status"),
        )
