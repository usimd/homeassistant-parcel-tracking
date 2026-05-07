"""Ship24 Tracking API client.

Ship24 provides universal parcel tracking across 1500+ couriers.
Free plan: 10 shipments/month.

API docs: https://docs.ship24.com
Base URL: https://api.ship24.com/public/v1
Auth: Bearer token in Authorization header
"""

import logging
from dataclasses import dataclass

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

    async def track(self, tracking_number: str) -> TrackingInfo | None:
        """Create tracker (idempotent) and get tracking results.

        Uses POST /trackers/track which creates a tracker if it doesn't exist
        and returns tracking results. Subsequent calls are instant.
        """
        try:
            resp = await self._session.post(
                f"{BASE_URL}/trackers/track",
                headers=self._headers,
                json={"trackingNumber": tracking_number},
            )

            if resp.status != 200:
                _LOGGER.debug(
                    "Ship24 API returned status %s for %s",
                    resp.status,
                    tracking_number,
                )
                return None

            data = await resp.json()
            trackings = data.get("data", {}).get("trackings", [])
            if not trackings:
                return None

            tracking = trackings[0]
            tracker = tracking.get("tracker", {})
            shipment = tracking.get("shipment", {})
            events = tracking.get("events", [])

            # Get status from shipment-level statusMilestone
            status_milestone = shipment.get("statusMilestone", "pending")
            status = SHIP24_STATUS_MAP.get(status_milestone, STATUS_UNKNOWN)

            # Get courier info
            courier_code = None
            courier_name = None
            if events:
                courier_code = events[0].get("courierCode")
                courier_name = events[0].get("courierName")

            # Get ETA
            eta = shipment.get("estimatedDeliveryDate")

            # Latest event
            latest_event_time = None
            latest_event_desc = None
            if events:
                latest_event_time = events[0].get("occurrenceDatetime")
                latest_event_desc = events[0].get("status")

            return TrackingInfo(
                tracking_number=tracking_number,
                tracker_id=tracker.get("trackerId", ""),
                status=status,
                courier_code=courier_code,
                courier_name=courier_name,
                eta=eta,
                latest_event_time=latest_event_time,
                latest_event_description=latest_event_desc,
            )
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
            trackings = data.get("data", {}).get("trackings", [])
            if not trackings:
                return None

            tracking = trackings[0]
            tracker = tracking.get("tracker", {})
            shipment = tracking.get("shipment", {})
            events = tracking.get("events", [])

            status_milestone = shipment.get("statusMilestone", "pending")
            status = SHIP24_STATUS_MAP.get(status_milestone, STATUS_UNKNOWN)

            courier_code = None
            courier_name = None
            if events:
                courier_code = events[0].get("courierCode")
                courier_name = events[0].get("courierName")

            eta = shipment.get("estimatedDeliveryDate")

            latest_event_time = None
            latest_event_desc = None
            if events:
                latest_event_time = events[0].get("occurrenceDatetime")
                latest_event_desc = events[0].get("status")

            return TrackingInfo(
                tracking_number=tracker.get("trackingNumber", ""),
                tracker_id=tracker.get("trackerId", ""),
                status=status,
                courier_code=courier_code,
                courier_name=courier_name,
                eta=eta,
                latest_event_time=latest_event_time,
                latest_event_description=latest_event_desc,
            )
        except Exception:
            _LOGGER.exception("Error getting results for tracker %s", tracker_id)
            return None
