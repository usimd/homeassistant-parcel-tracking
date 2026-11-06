<p align="center">
  <img src="icon.png" alt="Parcel Tracker" width="128">
</p>

<h1 align="center">Home Assistant Parcel Tracking</h1>

<p align="center">
  <a href="https://github.com/usimd/homeassistant-parcel-tracking/actions/workflows/test.yaml"><img src="https://github.com/usimd/homeassistant-parcel-tracking/actions/workflows/test.yaml/badge.svg" alt="Tests"></a>
  <a href="https://codecov.io/gh/usimd/homeassistant-parcel-tracking"><img src="https://codecov.io/gh/usimd/homeassistant-parcel-tracking/graph/badge.svg" alt="codecov"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/usimd/homeassistant-parcel-tracking" alt="License: Apache 2.0"></a>
  <a href="https://github.com/usimd/homeassistant-parcel-tracking/actions/workflows/hacs.yaml"><img src="https://github.com/usimd/homeassistant-parcel-tracking/actions/workflows/hacs.yaml/badge.svg" alt="HACS"></a>
</p>

<p align="center">
  Custom Home Assistant integration for household parcel tracking via Ship24 universal tracking API.
</p>

## Features

- One sensor per parcel, with status, carrier, delivery estimates, and tracking links.
- Ship24 carrier detection and cached courier-name lookup.
- Optional direct DHL status updates and delivery time windows.
- Status-change events for automations and automatic cleanup after delivery.
- Registration through Home Assistant actions or a private webhook.

## Installation

Requires Home Assistant 2025.10 or newer and a [Ship24 API key](https://dashboard.ship24.com). API quotas and pricing depend on your Ship24 plan.

### HACS

1. [Install HACS](https://www.hacs.xyz/docs/use/download/download/) if needed.
2. Open **HACS**, then its menu and **Custom repositories**.
3. Add `https://github.com/usimd/homeassistant-parcel-tracking` with type **Integration**.
4. Search for **Parcel Tracker** in HACS and download it.
5. Restart Home Assistant.
6. Go to **Settings > Devices & services > Add integration**, select **Parcel Tracker**, and enter your Ship24 API key.

### Manual

Copy `custom_components/parcel_tracker` into your Home Assistant configuration's `custom_components` directory, restart Home Assistant, and add the integration as above.

## Configuration

Open **Settings > Devices & services > Parcel Tracker > Configure**.

| Option | Default | Purpose |
| --- | --- | --- |
| DHL API key | Not set | Optional [DHL Shipment Tracking API](https://developer.dhl.com/api-reference/shipment-tracking) access |
| Destination country / postal code | Home location, if available | Improve Ship24 matching |
| Polling interval | 2 hours | Poll Ship24 and optional DHL tracking; configurable from 1 to 12 hours |
| Cleanup days | 3 | Remove delivered parcels after 1 to 30 days |
| External registration webhook | Disabled | Allow registration through your external Home Assistant URL |

## Register a Parcel

Use **Developer tools > Actions** or an automation:

```yaml
action: parcel_tracker.add
data:
  tracking_url: "https://www.dhl.de/de/privatkunden/dhl-sendungsverfolgung.html?piececode=1234567890123456"
  description: "Keyboard"
```

URL extraction supports common DHL, DPD, Hermes, GLS, UPS, FedEx, and Amazon Germany links. Ship24 tracking supports many more carriers: provide the tracking number for an unsupported URL. The original URL and optional carrier name are forwarded to Ship24.

```yaml
action: parcel_tracker.add
data:
  tracking_number: "9400111202544843610364"
  carrier: "USPS"
  courier_code: "us-post"
  description: "Replacement part"
```

`courier_code` is an optional Ship24 code and takes precedence over the carrier name. Carrier names are matched against Ship24's cached catalog when possible. Omit both to let Ship24 detect the carrier.

Optional `shipping_date` must be the actual shipment date in `YYYY-MM-DD` format; leave it out if unknown. `restrict_courier: true` disables tracking through additional carriers, so leave it off for shipments with carrier handoffs. Creation metadata is preserved across retries; existing trackers are reused rather than automatically recreated.

Remove a parcel with:

```yaml
action: parcel_tracker.remove
data:
  tracking_number: "9400111202544843610364"
```

## Phone Sharing

The integration's **Configure** dialog shows your private `/api/webhook/<random-id>` path. Configure Android [HTTP Shortcuts](https://github.com/Waboodoo/HTTP-Shortcuts) or iOS Shortcuts to POST JSON to that path on your Home Assistant URL:

```json
{"url": "<tracking-url>", "device": "my-phone", "description": "Keyboard"}
```

The webhook also accepts `tracking_number`, `courier_code`, `carrier`, `shipping_date`, and `restrict_courier`. For unsupported URLs, include `tracking_number`.

Keep the URL private: anyone who has it and can reach the endpoint can register parcels. Local network access is enabled by default; enable external access explicitly when needed.

## Sensors and Automations

Each parcel appears under the integration as a sensor. States are `registered`, `in_transit`, `out_for_delivery`, `available_for_pickup`, `delivered`, `failed_attempt`, `exception`, and `unknown`. Ready-for-pickup parcels are not treated as delivered or automatically cleaned up.

Attributes include `tracking_number`, `carrier`, `courier_code`, `description`, `eta`, `eta_timeframe`, `tracking_url`, `preference_url`, `registered_at`, `registered_by`, `last_api_update`, `status_source`, `latest_event_time`, and `latest_event_description`, when available. Carrier preference links are available for the supported URL adapters, not every Ship24 carrier.

- `parcel_tracker.parcel_added` fires on registration.
- `parcel_tracker.status_changed` fires once per final observed status transition after provider results are merged. Its payload includes `tracking_number`, `carrier`, `courier_code`, `old_status`, `new_status`, `status_source`, `eta`, `tracking_url`, and `preference_url`.

```yaml
alias: Parcel delivered
triggers:
  - trigger: event
    event_type: parcel_tracker.status_changed
    event_data:
      new_status: delivered
actions:
  - action: notify.mobile_app_your_phone
    data:
      message: "{{ trigger.event.data.carrier }} parcel delivered"
```

## Dashboard

Add parcel sensors to any built-in Entities card, or use this automatic list. It shows the carrier, status, tracking number, and ETA; tapping a row opens the tracking page.

Install [auto-entities](https://github.com/thomasloven/lovelace-auto-entities) and [template-entity-row](https://github.com/thomasloven/lovelace-template-entity-row) through HACS, then add a **Manual** dashboard card:

```yaml
type: custom:auto-entities
card:
  type: entities
  title: Parcels
  show_header_toggle: false
filter:
  include:
    - integration: parcel_tracker
      domain: sensor
      options:
        type: custom:template-entity-row
        state: "{{ state_attr(config.entity, 'carrier') }}: {{ states(config.entity) | replace('_', ' ') | title }}"
        secondary: >
          {{ state_attr(config.entity, 'tracking_number') }}
          {% if state_attr(config.entity, 'eta') %}
            - ETA {{ state_attr(config.entity, 'eta') }}
          {% endif %}
        tap_action: >
          {{ {'action': 'url', 'url_path': state_attr(config.entity, 'tracking_url')} | to_json
             if state_attr(config.entity, 'tracking_url')
             else {'action': 'more-info'} | to_json }}
  exclude:
    - state: unavailable
sort:
  method: state
show_empty: false
```

## Limitations

- Tracking is polled, not realtime. Ship24's upstream delay remains even if you shorten the polling interval. Ship24 push webhooks are not implemented.
- Direct DHL results can confirm delivery before Ship24. Other conflicting states use comparable event timestamps when available. Delivered parcels are no longer polled.
- `last_api_update` records a successful fetch, not the time of the carrier's last scan. Use `latest_event_time` to judge tracking freshness.
- Dates, delivery estimates, and carrier coverage depend on the upstream provider.

## Development

```bash
uv sync --dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
```
