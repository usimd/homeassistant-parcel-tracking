"""DHL Shipment Tracking API client.

Optional enrichment source for DHL parcels. Provides estimated delivery
time windows that Ship24 does not surface.

API docs: https://developer.dhl.com/api-reference/shipment-tracking
Base URL: https://api-eu.dhl.com/track/shipments
Auth: DHL-API-Key header
"""

import logging
from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

DHL_BASE_URL = "https://api-eu.dhl.com/track/shipments"

# DHL courier codes that Ship24 uses for DHL shipments
DHL_COURIER_CODES = {"dhl-group", "dhl", "dhl-germany", "dhl-express"}


@dataclass
class DhlTrackingInfo:
    """Enrichment data from DHL API."""

    eta_date: str | None = None
    eta_timeframe_from: str | None = None
    eta_timeframe_to: str | None = None


def is_dhl_parcel(carrier: str, courier_code: str | None = None) -> bool:
    """Check if a parcel is handled by DHL."""
    if carrier.upper() == "DHL":
        return True
    if courier_code and courier_code.lower() in DHL_COURIER_CODES:
        return True
    return False


class DhlApi:
    """Client for the DHL Shipment Tracking API."""

    def __init__(self, hass: HomeAssistant, api_key: str) -> None:
        """Initialize the API client."""
        self._hass = hass
        self._api_key = api_key
        self._session = async_get_clientsession(hass)

    async def test_connection(self) -> bool:
        """Test the API connection with a dummy tracking number."""
        try:
            resp = await self._session.get(
                DHL_BASE_URL,
                headers={
                    "DHL-API-Key": self._api_key,
                    "Accept": "application/json",
                },
                params={"trackingNumber": "0000000000"},
            )
            body = await resp.text()
            _LOGGER.debug(
                "DHL API test_connection status=%s body=%s", resp.status, body
            )
            # 401/403 = bad key; anything else means the key is valid
            return resp.status not in (401, 403)
        except Exception:
            _LOGGER.exception("Error testing DHL API connection")
            return False

    async def get_details(self, tracking_number: str) -> DhlTrackingInfo | None:
        """Get tracking details from DHL API."""
        try:
            resp = await self._session.get(
                DHL_BASE_URL,
                headers={
                    "DHL-API-Key": self._api_key,
                    "Accept": "application/json",
                },
                params={"trackingNumber": tracking_number, "language": "en"},
            )

            if resp.status != 200:
                _LOGGER.debug(
                    "DHL API returned status %s for %s", resp.status, tracking_number
                )
                return None

            data = await resp.json()
            _LOGGER.debug("DHL API response for %s: %s", tracking_number, data)

            shipments = data.get("shipments", [])
            if not shipments:
                return None

            shipment = shipments[0]
            etod = shipment.get("estimatedTimeOfDelivery", {})

            if not etod:
                return None

            return DhlTrackingInfo(
                eta_date=etod.get("estimatedFrom") or etod.get("estimatedUntil"),
                eta_timeframe_from=etod.get("estimatedFrom"),
                eta_timeframe_to=etod.get("estimatedUntil"),
            )
        except Exception:
            _LOGGER.exception("Error getting DHL details for %s", tracking_number)
            return None
