"""Persistent storage for tracked parcels."""

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION, STATUS_REGISTERED

_LOGGER = logging.getLogger(__name__)


@dataclass
class ParcelData:
    """Data for a single tracked parcel."""

    tracking_number: str
    carrier: str
    status: str = STATUS_REGISTERED
    eta: str | None = None
    eta_timeframe: str | None = None
    description: str | None = None
    registered_by: str | None = None
    registered_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_api_update: str | None = None
    tracking_url: str | None = None
    delivered_at: str | None = None
    tracker_id: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ParcelData":
        """Create from dictionary."""
        # Filter to only known fields
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


class ParcelStore:
    """Manages persistent storage for parcels."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the parcel store."""
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._parcels: dict[str, ParcelData] = {}

    @property
    def parcels(self) -> dict[str, ParcelData]:
        """Return all tracked parcels."""
        return self._parcels

    async def async_load(self) -> None:
        """Load parcels from storage."""
        data = await self._store.async_load()
        if data and "parcels" in data:
            self._parcels = {
                tn: ParcelData.from_dict(p) for tn, p in data["parcels"].items()
            }
            _LOGGER.debug("Loaded %d parcels from storage", len(self._parcels))

    async def async_save(self) -> None:
        """Save parcels to storage."""
        await self._store.async_save(
            {"parcels": {tn: p.to_dict() for tn, p in self._parcels.items()}}
        )

    def add(self, parcel: ParcelData) -> None:
        """Add a parcel to the store."""
        self._parcels[parcel.tracking_number] = parcel

    def remove(self, tracking_number: str) -> ParcelData | None:
        """Remove a parcel from the store."""
        return self._parcels.pop(tracking_number, None)

    def get(self, tracking_number: str) -> ParcelData | None:
        """Get a parcel by tracking number."""
        return self._parcels.get(tracking_number)

    def get_all_tracking_numbers(self) -> list[str]:
        """Return all tracking numbers."""
        return list(self._parcels.keys())
