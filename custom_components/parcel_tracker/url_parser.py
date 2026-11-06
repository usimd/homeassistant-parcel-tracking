"""URL parser for carrier auto-detection."""

import re
from urllib.parse import parse_qs, quote, unquote, urlsplit

from .const import (
    CARRIER_CODE_ALIASES,
    CARRIER_PREFERENCE_URLS,
    CARRIER_TRACKING_URLS,
    CARRIER_URL_PATTERNS,
)

TRACKING_PARAMETERS = {
    "DHL": ("piececode", "id"),
    "DPD": ("parcel", "parcelnumber"),
    "Hermes": ("shipmentid", "trackingnumber"),
    "GLS": ("match", "parcelnumber"),
    "UPS": ("tracknum", "tracknums", "inquiryNumber"),
    "FedEx": ("trknbr", "trackingnumber"),
    "Amazon": ("trackingid",),
}


def parse_tracking_url(url: str) -> tuple[str | None, str | None]:
    """Parse a tracking URL to extract carrier and tracking number.

    Returns:
        Tuple of (carrier, tracking_number) or (None, None) if not recognized.
    """
    try:
        parsed = urlsplit(url.strip())
        hostname = parsed.hostname or ""
    except ValueError:
        return None, None
    if parsed.scheme not in ("http", "https"):
        return None, None

    query = {key.lower(): values for key, values in parse_qs(parsed.query).items()}
    for carrier, (domain_pattern, number_pattern, _) in CARRIER_URL_PATTERNS.items():
        if not re.fullmatch(domain_pattern, hostname, re.IGNORECASE):
            continue
        candidates = [
            value
            for parameter in TRACKING_PARAMETERS[carrier]
            for value in query.get(parameter.lower(), [])
        ]
        if not candidates:
            candidates = [unquote(parsed.fragment)]
            candidates.extend(unquote(parsed.path).split("/"))
        for candidate in candidates:
            if re.fullmatch(number_pattern, candidate, re.IGNORECASE):
                return carrier, candidate
    return None, None


def _carrier_key(carrier: str, courier_code: str | None) -> str:
    if courier_code and courier_code.lower() in CARRIER_CODE_ALIASES:
        return CARRIER_CODE_ALIASES[courier_code.lower()]
    return next(
        (
            name
            for name in CARRIER_URL_PATTERNS
            if name.casefold() == carrier.casefold()
        ),
        carrier,
    )


def build_tracking_url(
    carrier: str, tracking_number: str, courier_code: str | None = None
) -> str | None:
    """Build a tracking URL for a given carrier and tracking number."""
    template = CARRIER_TRACKING_URLS.get(_carrier_key(carrier, courier_code))
    if template:
        return template.format(tracking_number=quote(tracking_number, safe=""))
    return None


def build_preference_url(
    carrier: str, tracking_number: str, courier_code: str | None = None
) -> str:
    """Build a supported carrier's delivery preference link."""
    template = CARRIER_PREFERENCE_URLS.get(_carrier_key(carrier, courier_code), "")
    return template.format(tracking_number=quote(tracking_number, safe=""))
