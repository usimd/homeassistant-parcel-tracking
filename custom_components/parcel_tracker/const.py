"""Constants for the Parcel Tracker integration."""

from typing import Final

DOMAIN: Final = "parcel_tracker"

# Configuration
CONF_API_KEY: Final = "api_key"
CONF_CLEANUP_DAYS: Final = "cleanup_days"
CONF_SCAN_INTERVAL_HOURS: Final = "scan_interval_hours"

# Defaults
DEFAULT_CLEANUP_DAYS: Final = 3
DEFAULT_SCAN_INTERVAL_HOURS: Final = 2

# Services
SERVICE_ADD: Final = "add"
SERVICE_REMOVE: Final = "remove"

# Service fields
ATTR_TRACKING_NUMBER: Final = "tracking_number"
ATTR_TRACKING_URL: Final = "tracking_url"
ATTR_CARRIER: Final = "carrier"
ATTR_DESCRIPTION: Final = "description"
ATTR_REGISTERED_BY: Final = "registered_by"
ATTR_REGISTERED_AT: Final = "registered_at"
ATTR_ETA: Final = "eta"
ATTR_LAST_API_UPDATE: Final = "last_api_update"
ATTR_STATUS: Final = "status"
ATTR_PREFERENCE_URL: Final = "preference_url"

# Events
EVENT_STATUS_CHANGED: Final = "parcel_tracker.status_changed"
EVENT_PARCEL_ADDED: Final = "parcel_tracker.parcel_added"

# Dispatcher signals
SIGNAL_NEW_PARCEL: Final = f"{DOMAIN}_new_parcel"
SIGNAL_REMOVE_PARCEL: Final = f"{DOMAIN}_remove_parcel"

# Storage
STORAGE_KEY: Final = DOMAIN
STORAGE_VERSION: Final = 1

# Webhook
WEBHOOK_ID: Final = "parcel_tracker_register"

# Parcel statuses
STATUS_REGISTERED: Final = "registered"
STATUS_IN_TRANSIT: Final = "in_transit"
STATUS_OUT_FOR_DELIVERY: Final = "out_for_delivery"
STATUS_DELIVERED: Final = "delivered"
STATUS_FAILED_ATTEMPT: Final = "failed_attempt"
STATUS_EXCEPTION: Final = "exception"
STATUS_UNKNOWN: Final = "unknown"

# Ship24 statusMilestone mapping
SHIP24_STATUS_MAP: Final = {
    "pending": STATUS_REGISTERED,
    "info_received": STATUS_REGISTERED,
    "in_transit": STATUS_IN_TRANSIT,
    "out_for_delivery": STATUS_OUT_FOR_DELIVERY,
    "failed_attempt": STATUS_FAILED_ATTEMPT,
    "available_for_pickup": STATUS_DELIVERED,
    "delivered": STATUS_DELIVERED,
    "exception": STATUS_EXCEPTION,
}

# Carrier delivery preference URLs (deep links to set Abstellgenehmigung etc.)
CARRIER_PREFERENCE_URLS: Final = {
    "DHL": "https://www.dhl.de/de/privatkunden/pakete-empfangen/verfolgen.html?piececode={tracking_number}",
    "DPD": "https://www.dpd.com/de/de/empfangen/paketankuendigung/",
    "Hermes": "https://www.myhermes.de/empfangen/sendungsverfolgung/sendungsinformation#{tracking_number}",
    "GLS": "https://gls-group.com/DE/de/empfangen/flexdeliveryservice",
    "UPS": "https://www.ups.com/de/de/services/tracking/mychoice.page",
    "FedEx": "https://www.fedex.com/de-de/delivery-manager.html",
    "Amazon": "https://www.amazon.de/gp/css/order-history",
}

# Carrier tracking URL templates
CARRIER_TRACKING_URLS: Final = {
    "DHL": "https://www.dhl.de/de/privatkunden/dhl-sendungsverfolgung.html?piececode={tracking_number}",
    "DPD": "https://tracking.dpd.de/status/de_DE/parcel/{tracking_number}",
    "Hermes": "https://www.myhermes.de/empfangen/sendungsverfolgung/sendungsinformation#{tracking_number}",
    "GLS": "https://gls-group.com/DE/de/paketverfolgung?match={tracking_number}",
    "UPS": "https://www.ups.com/track?tracknum={tracking_number}",
    "FedEx": "https://www.fedex.com/fedextrack/?trknbr={tracking_number}",
    "Amazon": "https://www.amazon.de/progress-tracker/package/{tracking_number}",
}

# URL patterns for carrier auto-detection
CARRIER_URL_PATTERNS: Final = {
    "DHL": (r"dhl\.de|nolp\.dhl\.de", r"[0-9]{12,20}"),
    "DPD": (r"dpd\.de|tracking\.dpd", r"[0-9]{14}"),
    "Hermes": (r"myhermes\.de|hermesworld", r"[0-9]{14,16}"),
    "GLS": (r"gls-group\.com|gls-pakete", r"[A-Z0-9]{11,14}"),
    "UPS": (r"ups\.com", r"1Z[A-Z0-9]{16}"),
    "FedEx": (r"fedex\.com", r"[0-9]{12,22}"),
    "Amazon": (r"amazon\.de/progress-tracker", r"[A-Z0-9]{12,}"),
}
