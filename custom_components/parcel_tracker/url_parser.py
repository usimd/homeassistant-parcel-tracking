"""URL parser for carrier auto-detection."""

import re

from .const import CARRIER_TRACKING_URLS, CARRIER_URL_PATTERNS


def parse_tracking_url(url: str) -> tuple[str | None, str | None]:
    """Parse a tracking URL to extract carrier and tracking number.

    Returns:
        Tuple of (carrier, tracking_number) or (None, None) if not recognized.
    """
    for carrier, (domain_pattern, number_pattern, _) in CARRIER_URL_PATTERNS.items():
        if re.search(domain_pattern, url, re.IGNORECASE):
            match = re.search(number_pattern, url)
            if match:
                return carrier, match.group(0)
    return None, None


def build_tracking_url(carrier: str, tracking_number: str) -> str | None:
    """Build a tracking URL for a given carrier and tracking number."""
    template = CARRIER_TRACKING_URLS.get(carrier)
    if template:
        return template.format(tracking_number=tracking_number)
    return None
