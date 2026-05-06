# Home Assistant Parcel Tracking Integration

Custom Home Assistant integration for household parcel tracking with automatic door opener support.

## Problem

Multiple family members receive parcels from various carriers (DHL, DPD, Hermes, GLS, UPS, Amazon Logistics). When nobody is home, deliveries fail. We want to:

1. Track all household parcels in HA with their delivery status and ETA
2. Automatically open the front door when the doorbell rings on a delivery day
3. (Phase 2) Automatically set delivery preferences via carrier APIs (e.g. DHL Abstellgenehmigung)

## Architecture

```
Family member gets tracking link (email, vendor site, SMS)
        |
        v
Share on phone --> HTTP Shortcuts app --> POST to HA webhook
        |
        v
HA webhook automation --> calls parcel_tracker.add service
        |
        v
Integration parses carrier + tracking number
        |
        v
Polls 17track API periodically --> updates status + ETA
        |
        v
Delivery day: doorbell rings --> automation opens door
        |
        v
Status = delivered --> auto-cleanup after N days
```

## Component Structure

```
custom_components/parcel_tracker/
├── __init__.py          # Integration setup, storage, service registration
├── manifest.json        # Integration metadata, dependencies
├── sensor.py            # One sensor entity per tracked parcel
├── config_flow.py       # UI config flow (17track API key)
├── const.py             # Constants, defaults
├── coordinator.py       # DataUpdateCoordinator for API polling
├── api.py               # 17track API client
├── strings.json         # UI strings
└── translations/
    └── en.json
```

## Entity Model

Each tracked parcel becomes a sensor entity:

- **Entity ID**: `sensor.parcel_{carrier}_{tracking_number_suffix}`
- **State**: `registered` | `in_transit` | `out_for_delivery` | `delivered` | `expired` | `unknown`
- **Attributes**:
  - `carrier` — DHL, DPD, Hermes, GLS, UPS, Amazon, etc.
  - `tracking_number` — full tracking number
  - `eta` — estimated delivery date (YYYY-MM-DD), updated from API
  - `registered_by` — which device/user shared the URL
  - `registered_at` — timestamp of registration
  - `last_api_update` — timestamp of last successful API poll
  - `tracking_url` — direct link to carrier tracking page
  - `description` — optional user-provided label ("new keyboard", etc.)

## Services

### `parcel_tracker.add`

Register a new parcel for tracking.

```yaml
# From tracking number + carrier
action: parcel_tracker.add
data:
  tracking_number: "1234567890123456"
  carrier: "DHL"              # optional if auto-detectable
  description: "New keyboard"  # optional

# From tracking URL (carrier auto-detected)
action: parcel_tracker.add
data:
  tracking_url: "https://www.dhl.de/de/privatkunden/dhl-sendungsverfolgung.html?piececode=1234567890123456"
  description: "New keyboard"
```

### `parcel_tracker.remove`

Remove a parcel from tracking.

```yaml
action: parcel_tracker.remove
data:
  tracking_number: "1234567890123456"
```

## Events

### `parcel_tracker.status_changed`

Fired on every status transition. Useful for notifications and automations.

```yaml
event_data:
  tracking_number: "1234567890123456"
  carrier: "DHL"
  old_status: "in_transit"
  new_status: "out_for_delivery"
  eta: "2026-05-08"
```

## Lifecycle Management

| Phase | Trigger | Action |
|-------|---------|--------|
| Register | Webhook / service call | Create sensor entity, initial API poll |
| Track | Polling interval (2-4h) | Update status + ETA from 17track API |
| React | Status transition | Fire event, update entity |
| Cleanup | N days after `delivered` | Auto-remove entity (configurable, default: 3 days) |
| Persist | HA restart | Restore from `.storage/parcel_tracker` |

## Tracking API

**17track** (https://api.17track.net) — universal tracking aggregator.

- Free tier: 100 queries/day (sufficient for household use)
- Covers: DHL, DPD, Hermes, GLS, UPS, FedEx, Amazon Logistics, and 1500+ carriers
- Returns: status, sub-status, location, timestamps, estimated delivery
- API key required (free registration)

## URL Parsing (Carrier Auto-Detection)

```python
CARRIER_PATTERNS = {
    "DHL":    (r"dhl\.de|nolp\.dhl\.de", r"[0-9]{12,20}"),
    "DPD":    (r"dpd\.de|tracking\.dpd",  r"[0-9]{14}"),
    "Hermes": (r"myhermes\.de|hermesworld", r"[0-9]{14,16}"),
    "GLS":    (r"gls-group\.com|gls-pakete", r"[A-Z0-9]{11,14}"),
    "UPS":    (r"ups\.com",               r"1Z[A-Z0-9]{16}"),
    "Amazon": (r"amazon\.de/progress-tracker", r"[A-Z0-9]{12,}"),
}
```

## Webhook Integration

HA automation to receive shared URLs:

```yaml
alias: Register Parcel from Shared URL
triggers:
  - trigger: webhook
    webhook_id: register_parcel
    allowed_methods: [POST]
    local_only: false
actions:
  - action: parcel_tracker.add
    data:
      tracking_url: "{{ trigger.data.url | default(trigger.data.text, '') }}"
      registered_by: "{{ trigger.data.device | default('unknown') }}"
```

Android share sheet integration via **HTTP Shortcuts** app (F-Droid / Play Store):
- Name: "Track Parcel"
- Method: POST
- URL: `https://<ha-external-url>/api/webhook/register_parcel`
- Body: `{"url": "{share_text}", "device": "<phone-name>"}`

## Door Opener Automation

```yaml
alias: Open door for parcel delivery
triggers:
  - entity_id: binary_sensor.doorbell_bell_signal
    to: "on"
    trigger: state
conditions:
  - condition: template
    value_template: >
      {{ states.sensor
         | selectattr('entity_id', 'match', 'sensor.parcel_.*')
         | selectattr('state', 'in', ['in_transit', 'out_for_delivery'])
         | selectattr('attributes.eta', 'eq', now().strftime('%Y-%m-%d'))
         | list | count > 0 }}
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.doorbell_door_opener
```

## Phase 2: DHL Abstellgenehmigung

Automatically set drop-off permission via DHL Paket DE API when a DHL parcel is registered:

- DHL Developer Portal: https://developer.dhl.com
- API: Shipment Tracking + Delivery Preferences
- Trigger: `parcel_tracker.status_changed` event with `carrier: DHL`
- Action: REST call to set preferred drop-off location

## Configuration

```yaml
# configuration.yaml (or via UI config flow)
parcel_tracker:
  api_key: !secret 17track_api_key
  poll_interval: 180          # minutes between API polls (default: 180)
  cleanup_days: 3             # days after delivery to remove entity (default: 3)
  auto_detect_carrier: true   # attempt carrier detection from tracking number format
```

## Development

```bash
# Clone into HA custom_components
ln -s /path/to/this/repo/custom_components/parcel_tracker \
      /path/to/ha-config/custom_components/parcel_tracker

# Restart HA
ha core restart
```

## Dependencies

- Home Assistant 2024.1+
- 17track API key (free tier: https://api.17track.net)
- HTTP Shortcuts app on Android phones (for share sheet integration)
