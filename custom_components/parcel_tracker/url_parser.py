"""URL parser for carrier auto-detection."""

import re
from urllib.parse import SplitResult, parse_qsl, quote, unquote, urlsplit

from .const import (
    CARRIER_CODE_ALIASES,
    CARRIER_DOMAINS,
    CARRIER_PREFERENCE_URLS,
    CARRIER_TRACKING_URLS,
)

TRACKING_PARAMETERS = (
    "piececode",
    "idc",
    "parcel",
    "parcelnumber",
    "shipmentid",
    "trackingnumber",
    "trackingid",
    "tracknum",
    "tracknums",
    "inquirynumber",
    "trknbr",
    "match",
    "id",
)
IGNORED_PARAMETER_PREFIXES = ("utm_", "wt_")
TOKEN_SEPARATORS = re.compile(r"[/?&=#,;\s]+")
TRACKING_TOKEN = re.compile(r"(?=[A-Za-z0-9]*[0-9])[A-Za-z0-9]{8,35}")


def _tokens(*values: str) -> list[str]:
    return [token for value in values for token in TOKEN_SEPARATORS.split(value)]


def _candidates(parsed: SplitResult) -> list[str]:
    query = [
        (key.lower(), value)
        for key, value in parse_qsl(parsed.query)
        if not key.lower().startswith(IGNORED_PARAMETER_PREFIXES)
    ]
    known = sorted(
        (item for item in query if item[0] in TRACKING_PARAMETERS),
        key=lambda item: TRACKING_PARAMETERS.index(item[0]),
    )
    return [
        *_tokens(*(value for _, value in known)),
        *_tokens(unquote(parsed.fragment)),
        *reversed(_tokens(unquote(parsed.path))),
        *_tokens(*(value for key, value in query if key not in TRACKING_PARAMETERS)),
    ]


def parse_tracking_url(url: str) -> tuple[str | None, str | None]:
    """Extract a carrier hint and tracking number from a known carrier's URL.

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

    carrier = next(
        (
            name
            for name, (domain_pattern, _) in CARRIER_DOMAINS.items()
            if re.fullmatch(domain_pattern, hostname, re.IGNORECASE)
        ),
        None,
    )
    if carrier is None:
        return None, None
    number = next(
        (token for token in _candidates(parsed) if TRACKING_TOKEN.fullmatch(token)),
        None,
    )
    return (carrier, number) if number else (None, None)


def _carrier_key(carrier: str, courier_code: str | None) -> str:
    if courier_code and courier_code.lower() in CARRIER_CODE_ALIASES:
        return CARRIER_CODE_ALIASES[courier_code.lower()]
    return next(
        (name for name in CARRIER_DOMAINS if name.casefold() == carrier.casefold()),
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
