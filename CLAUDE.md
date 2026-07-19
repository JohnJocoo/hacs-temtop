# CLAUDE.md

Guidance for Claude Code (and other agents) working in this repository.

## What this is

A custom Home Assistant integration for the **Temtop C1+** air-quality monitor
over Bluetooth Low Energy. It is distributed through
[HACS](https://hacs.xyz/) and can also be installed manually. The integration
domain is `temtop_c1`.

## Repository layout

```
custom_components/temtop_c1/   # the integration itself
  __init__.py       # entry setup/unload; forwards the sensor platform
  config_flow.py    # Bluetooth discovery + manual picker; unique_id = BLE address
  const.py          # domain, UUIDs, opcodes, framing magic, scan interval
  coordinator.py    # DataUpdateCoordinator: connect → read one snapshot → disconnect
  protocol.py       # BLE framing, checksum, frame parsing, one-shot snapshot read
  sensor.py         # CO₂, temperature, humidity, battery entities
  manifest.json     # HA manifest (domain, requirements, bluetooth matchers)
  strings.json / icons.json
hacs.json           # HACS metadata (repo-root)
README.md           # user-facing docs
```

## Architecture

The device is battery-powered, so the integration does **not** hold a
persistent connection. On each poll the coordinator resolves the current
`BLEDevice` from HA's Bluetooth manager, then `async_read_one_snapshot`
connects (via `bleak_retry_connector.establish_connection`), subscribes to the
notify characteristic, sends a `0x80` snapshot request, decodes the reply, and
disconnects. Default interval is 60 s (`DEFAULT_SCAN_INTERVAL_SECONDS`).

Entities stay available for up to 15 minutes (`STALE_TOLERANCE` in
`sensor.py`) after the last successful read, serving the last good value while
transient BLE failures retry, rather than flapping to `unavailable`.

Device identity is the BLE address: it is the config entry `unique_id`, and
entities attach to the device via `connections={(CONNECTION_BLUETOOTH,
address)}` (using `format_mac`) so they merge into the tile the Bluetooth
discovery flow creates. Do not switch to `identifiers`, or entities land on a
second, empty device.

## Protocol (see `protocol.py` for the authoritative version)

- Outbound frames: `5A A5 LL CC <token[10]> <payload>`
- Inbound frames:  `D5 C8 LL CC <token[10]> <payload>`
- `LL` = `len(token) + len(payload)`; `CC` = opcode.
- Checksum (trailing byte): `(length + opcode + sum(token + payload[:-1])) % 256`.
- Sensor fields (big-endian, tenths of the displayed unit unless noted):
  temperature at payload bytes 10–11, humidity at 12–13, CO₂ ppm at 16–17,
  battery bars (0–4, plain integer) at byte 20.
- The `token` is device-bound; the integration learns it from the device's
  first notification and echoes it back, falling back to `DEFAULT_TOKEN_HEX`.
- The device's RTC was unreliable on the test unit — do not trust
  `device_time`.

The protocol was reverse-engineered from an iOS HCI capture plus LCD
ground-truth values. Treat offsets and the checksum formula as hard-won facts;
changing them needs a fresh capture to confirm.

## Conventions

- Target Home Assistant 2024.8.0+ (see `hacs.json`).
- Follow Home Assistant's integration style: async throughout, typed, entity
  descriptions for sensors, `_attr_has_entity_name = True`.
- Bump `version` in `manifest.json` for each HACS release and tag the commit
  (e.g. `v0.1.1`).
- Keep `documentation`, `issue_tracker`, and `codeowners` in `manifest.json`
  pointing at `github.com/JohnJocoo/hacs-temtop`.

## Validation

The `.github/workflows/validate.yaml` workflow runs HACS validation and
Home Assistant's `hassfest`. Both should pass before tagging a release.
