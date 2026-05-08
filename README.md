# Home Assistant Parcel Tracking Integration

[![Tests](https://github.com/usimd/homeassistant-parcel-tracking/actions/workflows/test.yaml/badge.svg)](https://github.com/usimd/homeassistant-parcel-tracking/actions/workflows/test.yaml)
[![codecov](https://codecov.io/gh/usimd/homeassistant-parcel-tracking/graph/badge.svg)](https://codecov.io/gh/usimd/homeassistant-parcel-tracking)
[![License: MIT](https://img.shields.io/github/license/usimd/homeassistant-parcel-tracking)](LICENSE)
[![HACS](https://github.com/usimd/homeassistant-parcel-tracking/actions/workflows/hacs.yaml/badge.svg)](https://github.com/usimd/homeassistant-parcel-tracking/actions/workflows/hacs.yaml)

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

## Services

### `parcel_tracker.add`

Register a new parcel for tracking.

```yaml
# From tracking URL (carrier auto-detected)
action: parcel_tracker.add
data:
  tracking_url: "https://www.dhl.de/de/privatkunden/dhl-sendungsverfolgung.html?piececode=1234567890123456"
  description: "New keyboard"

# From tracking number
action: parcel_tracker.add
data:
  tracking_number: "1234567890123456"
  carrier: "DHL"
```

### `parcel_tracker.remove`

```yaml
action: parcel_tracker.remove
data:
  tracking_number: "1234567890123456"
```

## Events

### `parcel_tracker.parcel_added`

Fired when a new parcel is registered. Includes the carrier's preference URL for delivery options.

### `parcel_tracker.status_changed`

Fired on every status transition.

```yaml
event_data:
  tracking_number: "1234567890123456"
  carrier: "DHL"
  old_status: "in_transit"
  new_status: "out_for_delivery"
  eta: "2026-05-08"
  preference_url: "https://www.dhl.de/..."
  tracking_url: "https://www.dhl.de/..."
```

## Example Automations

<details>
<summary><b>Notify to set delivery preferences (Abstellgenehmigung)</b></summary>

When a new parcel is registered, send a notification with a direct link to set your drop-off preference on the carrier's website:

```yaml
automation:
  - alias: "Notify to set delivery drop-off"
    triggers:
      - trigger: event
        event_type: parcel_tracker.parcel_added
    conditions:
      - condition: template
        value_template: "{{ trigger.event.data.preference_url != '' }}"
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: "📦 New parcel registered"
          message: >
            {{ trigger.event.data.carrier }} parcel added.
            Set your Abstellgenehmigung now!
          data:
            url: "{{ trigger.event.data.preference_url }}"
            actions:
              - action: URI
                title: "Set drop-off location"
                uri: "{{ trigger.event.data.preference_url }}"
```

</details>

<details>
<summary><b>Notify parcel in transit</b></summary>

```yaml
automation:
  - alias: "Notify parcel in transit"
    triggers:
      - trigger: event
        event_type: parcel_tracker.status_changed
        event_data:
          new_status: in_transit
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: "📦 Parcel on the way!"
          message: "{{ trigger.event.data.carrier }} parcel is in transit (ETA: {{ trigger.event.data.eta }})"
          data:
            url: "{{ trigger.event.data.tracking_url }}"
```

</details>

<details>
<summary><b>Webhook: register parcel from shared URL</b></summary>

Receive shared tracking URLs from the Android HTTP Shortcuts app:

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

</details>

<details>
<summary><b>Open door for parcel delivery</b></summary>

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

</details>

## Entity Model

Each tracked parcel becomes a sensor entity:

- **State**: `registered` | `in_transit` | `out_for_delivery` | `delivered` | `failed_attempt` | `exception` | `unknown`
- **Attributes**: `carrier`, `tracking_number`, `eta`, `registered_by`, `registered_at`, `last_api_update`, `tracking_url`, `preference_url`, `description`

## Configuration Options

Via UI (Settings → Integrations → Parcel Tracker → Configure):

| Option | Default | Description |
|--------|---------|-------------|
| Cleanup days | 3 | Days after delivery before auto-removal (1-30) |
| Scan interval | 2h | How often to poll Ship24 for updates (1-12h) |

## Supported Carriers

<details>
<summary><b>Carrier preference links</b></summary>

| Carrier | Preference Page |
|---------|----------------|
| DHL | Sendungsverfolgung → Empfangsoptionen |
| DPD | Paketankündigung |
| Hermes | Sendungsinformation |
| GLS | FlexDeliveryService |
| UPS | My Choice |
| FedEx | Delivery Manager |
| Amazon | Order History |

</details>

<details>
<summary><b>URL auto-detection patterns</b></summary>

| Carrier | URL Pattern |
|---------|-------------|
| DHL | `dhl.de`, `nolp.dhl.de` |
| DPD | `dpd.de`, `tracking.dpd` |
| Hermes | `myhermes.de`, `hermesworld` |
| GLS | `gls-group.com`, `gls-pakete` |
| UPS | `ups.com` |
| FedEx | `fedex.com` |
| Amazon | `amazon.de/progress-tracker` |

</details>

## Development

```bash
# Run tests
uv run pytest tests/ -v

# Lint
uv run ruff check . && uv run ruff format --check .
```

## Dependencies

- Home Assistant 2024.1+
- Ship24 API key (free plan: https://dashboard.ship24.com)
- HTTP Shortcuts app on Android phones (for share sheet integration)
