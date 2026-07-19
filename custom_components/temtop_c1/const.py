"""Constants for the Temtop C1+ BLE integration."""

from __future__ import annotations

DOMAIN = "temtop_c1"

# Device name advertised over BLE. The full local name looks like
# "C1+_90521305427690180507".
DEVICE_LOCAL_NAME_PREFIX = "C1+"

# Active-connection poll interval. The device pushes a 0xE1 sensor frame
# roughly every 10 s once connected, but we don't want to hold the link
# open continuously - the device is battery-powered. 60 s strikes a
# balance between data freshness and battery drain.
DEFAULT_SCAN_INTERVAL_SECONDS = 60

# Custom GATT service used by the Temtop C1+. The vendor uses one
# notify+write characteristic pair to carry their framed protocol.
SERVICE_UUID = "00010203-0405-0607-0809-0a0b0c0d1910"
NOTIFY_CHAR_UUID = "00010203-0405-0607-0809-0a0b0c0d2b10"
WRITE_CHAR_UUID = "00010203-0405-0607-0809-0a0b0c0d2b11"

# Framing magic words.
MAGIC_TO_DEVICE = bytes.fromhex("5AA5")
MAGIC_FROM_DEVICE = bytes.fromhex("D5C8")

# Opcode that asks the device for a snapshot - device responds with a
# 0x80 frame whose payload mirrors the periodic 0xE1 push (with a 0x00
# subcommand byte and a slightly shorter trailing constants block).
OPCODE_SNAPSHOT_REQUEST = 0x80
OPCODE_SNAPSHOT_RESPONSE = 0x80
OPCODE_PERIODIC_PUSH = 0xE1

# Token used in the iOS app's writes. Appears to be device-bound; we
# learn the real token from the device's first notification and only
# fall back to this if the device doesn't offer one in time.
DEFAULT_TOKEN_HEX = "5A340D052A4C5A120507"
