# Temtop C1+ — Home Assistant integration

A custom [Home Assistant](https://www.home-assistant.io/) integration for the
**Temtop C1+** air-quality monitor over Bluetooth Low Energy. Installable
through [HACS](https://hacs.xyz/).

The integration connects to the device on a fixed interval, requests a single
sensor snapshot over the vendor's framed GATT protocol, decodes it, and
disconnects — keeping the battery-powered monitor's radio idle between polls.

## Features

- **Auto-discovery** — Home Assistant's Bluetooth panel finds nearby C1+
  monitors by advertised name (`C1+_…`) and offers to add them.
- **CO₂ sensor** — carbon dioxide concentration in ppm.
- **Temperature sensor** — in °C.
- **Humidity sensor** — relative humidity in %.
- **Battery sensor** — the device's 4-bar gauge mapped to a percentage
  (diagnostic). A single remaining bar reports 10 % so Home Assistant's
  low-battery alerts fire before the device dies.
- **Resilient polling** — transient BLE failures (device asleep, adapter
  glitch, contention) don't immediately mark entities unavailable; the last
  good reading is served for up to 15 minutes while retries continue.

## Installation (HACS)

1. In HACS, go to **⋮ → Custom repositories**.
2. Add `https://github.com/JohnJocoo/hacs-temtop` as an **Integration**.
3. Search for **Temtop C1+**, download it, and restart Home Assistant.
4. The monitor should be auto-discovered under **Settings → Devices &
   Services**. If not, add it manually via **Add Integration → Temtop C1+**
   (make sure the device is powered on and in Bluetooth range).

## Manual installation

Copy `custom_components/temtop_c1/` into your Home Assistant
`config/custom_components/` directory and restart Home Assistant.

## Requirements

- Home Assistant 2024.8.0 or newer with a working Bluetooth adapter (the
  [Bluetooth integration](https://www.home-assistant.io/integrations/bluetooth/)).
- Python dependency `bleak-retry-connector` (installed automatically).

## Device contract

| Property        | Value |
|-----------------|-------|
| Advertised name | `C1+_…` |
| Service UUID    | `00010203-0405-0607-0809-0a0b0c0d1910` |
| Notify char     | `00010203-0405-0607-0809-0a0b0c0d2b10` |
| Write char      | `00010203-0405-0607-0809-0a0b0c0d2b11` |
| Outbound frame  | `5A A5 LL CC <token[10]> <payload>` |
| Inbound frame   | `D5 C8 LL CC <token[10]> <payload>` |
| Snapshot opcode | `0x80` (device replies with matching frame) |
| Periodic push   | `0xE1` (roughly every 10 s while connected) |

Sensor values live inside the payload as big-endian tenths: temperature at
bytes 10–11, humidity at bytes 12–13, CO₂ at bytes 16–17, and the battery
bar count at byte 20.

## Notes

- The protocol was reverse-engineered from an iOS HCI capture plus LCD
  ground-truth values. See `custom_components/temtop_c1/protocol.py` for the
  full framing and checksum details.
- The device's on-board clock (RTC) was observed to be unreliable, so the
  integration does not rely on the device's reported timestamp.

## License

See [LICENSE](LICENSE).
