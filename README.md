# Home Assistant Parcel Tracking Integration

Custom Home Assistant integration for household parcel tracking via Ship24 universal tracking API.

## Features

- Track parcels across **1500+ carriers** (DHL, DPD, Hermes, GLS, UPS, FedEx, Amazon, etc.) with a single API key
- Automatic carrier detection from tracking URLs
- Periodic status polling with configurable interval
- Deep links to carrier delivery preference pages (Abstellgenehmigung, etc.)
- Status change events for automations (door opener, notifications)
- Auto-cleanup of delivered parcels

## Setup

1. Get a free Ship24 API key (10 shipments/month) at https://dashboard.ship24.com
2. Install as custom component in Home Assistant
3. Add integration via UI → enter Ship24 API key

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
Integration parses carrier + tracking number from URL
        |
        v
Polls Ship24 API periodically --> updates status + ETA
        |
        v
Status change --> fires event --> notification with preference deep link
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
├── __init__.py          # Integration setup, service registration
├── manifest.json        # Integration metadata
├── sensor.py            # One sensor entity per tracked parcel
├── config_flow.py       # UI config flow (Ship24 API key)
├── const.py             # Constants, carrier URLs, status maps
├── coordinator.py       # DataUpdateCoordinator for API polling
├── api.py               # Ship24 API client
├── store.py             # Persistent storage
├── url_parser.py        # Carrier auto-detection from URLs
├── services.yaml        # Service definitions
├── strings.json         # UI strings
└── translations/
    └── en.json
```

## Entity Model

Each tracked parcel becomes a sensor entity:

- **State**: `registered` | `in_transit` | `out_for_delivery` | `delivered` | `failed_attempt` | `exception` | `unknown`
- **Attributes**:
  - `carrier` — DHL, DPD, Hermes, GLS, UPS, FedEx, Amazon, etc.
  - `tracking_number` — full tracking number
  - `eta` — estimated delivery date
  - `registered_by` — which device/user shared the URL
  - `registered_at` — timestamp of registration
  - `last_api_update` — timestamp of last successful API poll
  - `tracking_url` — direct link to carrier tracking page
  - `preference_url` — deep link to carrier delivery preferences (Abstellgenehmigung, etc.)
  - `description` — optional user-provided label

## Services

### `parcel_tracker.add`

Register a new parcel for tracking.

```yaml
# From tracking number
action: parcel_tracker.add
data:
  tracking_number: "1234567890123456"
  carrier: "DHL"              # optional — Ship24 auto-detects
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

Fired on every status transition.

```yaml
event_data:
  tracking_number: "1234567890123456"
  carrier: "DHL"
  old_status: "in_transit"
  new_status: "out_for_delivery"
  eta: "2026-05-08"
  preference_url: "https://www.dhl.de/de/privatkunden/pakete-empfangen/verfolgen.html?piececode=1234567890123456"
  tracking_url: "https://www.dhl.de/de/privatkunden/dhl-sendungsverfolgung.html?piececode=1234567890123456"
```

## Delivery Preference Notifications

Each sensor exposes a `preference_url` attribute with a deep link to the carrier's delivery options page. Use this in automations to send actionable notifications:

```yaml
automation:
  - alias: "Notify parcel in transit with delivery preferences"
    triggers:
      - trigger: event
        event_type: parcel_tracker.status_changed
        event_data:
          new_status: in_transit
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: "📦 Parcel on the way!"
          message: "{{ trigger.event.data.carrier }} parcel is in transit"
          data:
            url: "{{ trigger.event.data.preference_url }}"
            actions:
              - action: URI
                title: "Set delivery preferences"
                uri: "{{ trigger.event.data.preference_url }}"
```

Supported carrier preference links:

| Carrier | Preference Page |
|---------|----------------|
| DHL | Sendungsverfolgung → Empfangsoptionen |
| DPD | Paketankündigung |
| Hermes | Sendungsinformation |
| GLS | FlexDeliveryService |
| UPS | My Choice |
| FedEx | Delivery Manager |
| Amazon | Order History |

## Lifecycle Management

| Phase | Trigger | Action |
|-------|---------|--------|
| Register | Webhook / service call | Create sensor, call Ship24 track API |
| Track | Polling interval (default 2h) | Update status + ETA via Ship24 |
| React | Status transition | Fire event, update entity |
| Cleanup | N days after `delivered` | Auto-remove entity (configurable, default: 3 days) |
| Persist | HA restart | Restore from `.storage/parcel_tracker` |

## Tracking API

**Ship24** (https://api.ship24.com) — universal tracking aggregator.

- Free plan: 10 shipments/month (subsequent polls of existing shipments are unlimited)
- Covers: DHL, DPD, Hermes, GLS, UPS, FedEx, Amazon, and 1500+ carriers worldwide
- Returns: status milestones, courier detection, ETA, event history
- API key: https://dashboard.ship24.com/integrations/api-keys

## URL Parsing (Carrier Auto-Detection)

Supported URL patterns for auto-detecting carrier from shared tracking links:

| Carrier | URL Pattern |
|---------|-------------|
| DHL | `dhl.de`, `nolp.dhl.de` |
| DPD | `dpd.de`, `tracking.dpd` |
| Hermes | `myhermes.de`, `hermesworld` |
| GLS | `gls-group.com`, `gls-pakete` |
| UPS | `ups.com` |
| FedEx | `fedex.com` |
| Amazon | `amazon.de/progress-tracker` |

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

## Configuration Options

Via UI (Settings → Integrations → Parcel Tracker → Configure):

| Option | Default | Description |
|--------|---------|-------------|
| Cleanup days | 3 | Days after delivery before auto-removal (1-30) |
| Scan interval | 2h | How often to poll Ship24 for updates (1-12h) |

## Development

```bash
# Clone into HA custom_components
ln -s /path/to/this/repo/custom_components/parcel_tracker \
      /path/to/ha-config/custom_components/parcel_tracker

# Run tests
uv run pytest tests/ -v

# Lint
uv run ruff check . && uv run ruff format --check .
```

## Dependencies

- Home Assistant 2024.1+
- Ship24 API key (free plan: https://dashboard.ship24.com)
- HTTP Shortcuts app on Android phones (for share sheet integration)
