"""Temtop C1+ BLE protocol: framing, parsing, and one-shot snapshot read.

The protocol was reverse-engineered from an iOS HCI capture plus the
user's LCD ground-truth values, with the following stable findings:

  * Outbound frames: ``5A A5 LL CC <token[10]> <payload>``
  * Inbound  frames: ``D5 C8 LL CC <token[10]> <payload>``
  * ``LL`` is ``len(token) + len(payload)``; ``CC`` is the opcode.
  * ``payload[0]`` = subcommand (0x20 for periodic E1 push, 0x00 for
    snapshot reply to 0x80).
  * Sensor layout inside the payload (BE, tenths of the displayed unit):

        bytes 10-11  ->  temperature_C * 10
        bytes 12-13  ->  humidity_pct  * 10
        bytes 16-17  ->  CO2 ppm
        byte  20     ->  battery level in bars (0-4), direct integer

    The battery byte sits at the same offset in both the 0xE1 push and
    the (shorter) 0x80 snapshot reply. Confirmed against the LCD gauge at
    three levels: 0x04 full, 0x03 at 3/4, 0x02 at 2/4.

  * The trailing byte is a sum checksum:
    ``chk = (length + opcode + sum(token + payload[:-1])) mod 256``.

The device pushes a 0xE1 frame every ~10 s once connected, and replies
to ``0x80`` immediately with a snapshot of the same fields. We use the
0x80 path here so that one connect/read/disconnect cycle gives us
fresh sensor data without having to wait through a push interval.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import establish_connection

from .const import (
    DEFAULT_TOKEN_HEX,
    MAGIC_TO_DEVICE,
    NOTIFY_CHAR_UUID,
    OPCODE_PERIODIC_PUSH,
    OPCODE_SNAPSHOT_REQUEST,
    OPCODE_SNAPSHOT_RESPONSE,
    WRITE_CHAR_UUID,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_TOKEN = bytes.fromhex(DEFAULT_TOKEN_HEX)

# How long to wait for a sensor frame after subscribing + sending 0x80.
# The device is fast in practice (<1 s) but allow generous headroom for
# a flaky link.
READ_TIMEOUT_SECONDS = 12.0


class TemtopProtocolError(Exception):
    """Raised when a frame from the device can't be parsed."""


@dataclass(slots=True)
class TemtopSensorReading:
    """One decoded sensor snapshot from the Temtop C1+."""

    co2_ppm: int
    temperature_c: float
    humidity_pct: float
    # Battery gauge in bars (0-4) as reported at payload byte 20, or None
    # if the frame was too short to contain it. The bars->percentage
    # policy lives in the sensor layer, not here.
    battery_bars: int | None = None
    # The device's clock value from the same frame. Don't rely on this -
    # the C1+ RTC on the test unit was observed stuck at a wrong time.
    device_time: str | None = None


def _build_frame(opcode: int, payload: bytes, token: bytes) -> bytes:
    """Build a 5AA5 outbound frame. Mirrors the iOS app's wire format."""
    body = token + payload
    if len(body) > 0xFF:
        raise ValueError("body too long")
    return MAGIC_TO_DEVICE + bytes([len(body), opcode]) + body


def _validate_checksum(raw: bytes) -> bool:
    """True iff the trailing byte matches the protocol's sum checksum."""
    if len(raw) < 5:
        return False
    length = raw[2]
    opcode = raw[3]
    body = raw[4:]
    if not body:
        return False
    expected = (length + opcode + sum(body[:-1])) & 0xFF
    return expected == body[-1]


def parse_sensor_frame(raw: bytes) -> TemtopSensorReading | None:
    """Parse a Temtop notification into sensor values.

    Returns ``None`` for frames that aren't sensor snapshots
    (e.g. setting/info replies). Raises :class:`TemtopProtocolError`
    for malformed sensor frames so the coordinator can surface the
    problem instead of silently swallowing bad data.
    """
    if len(raw) < 4 + 10 + 1:
        return None

    length = raw[2]
    opcode = raw[3]
    body = raw[4:]
    if len(body) != length:
        # framing mismatch -- not a frame we should try to interpret
        return None

    payload = body[10:]
    if opcode not in (OPCODE_PERIODIC_PUSH, OPCODE_SNAPSHOT_RESPONSE):
        return None

    # Sensor frames need at least 18 bytes of payload (up to and
    # including the CO2 field at offset 16-17).
    if len(payload) < 18:
        return None

    if not _validate_checksum(raw):
        raise TemtopProtocolError(
            f"checksum mismatch on op=0x{opcode:02X} frame"
        )

    temperature_c = round(int.from_bytes(payload[10:12], "big") / 10.0, 1)
    humidity_pct = round(int.from_bytes(payload[12:14], "big") / 10.0, 1)
    co2_ppm = int.from_bytes(payload[16:18], "big")

    # Battery bars live at payload byte 20 in both frame types. The 0x80
    # snapshot reply carries it right before its checksum; guard the
    # length so a short/truncated frame yields None rather than an error.
    battery_bars = payload[20] if len(payload) > 20 else None

    device_time: str | None = None
    try:
        year = int.from_bytes(payload[1:3], "big")
        month, day, hour, minute, second = payload[3:8]
        # Only emit a timestamp if it's at all plausible - the device
        # RTC may be unset/wrong.
        if 2020 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31:
            device_time = (
                f"{year:04d}-{month:02d}-{day:02d}T"
                f"{hour:02d}:{minute:02d}:{second:02d}"
            )
    except (ValueError, IndexError):  # pragma: no cover - defensive
        pass

    return TemtopSensorReading(
        co2_ppm=co2_ppm,
        temperature_c=temperature_c,
        humidity_pct=humidity_pct,
        battery_bars=battery_bars,
        device_time=device_time,
    )


async def async_read_one_snapshot(ble_device: BLEDevice) -> TemtopSensorReading:
    """Connect, request a snapshot, decode, disconnect.

    Designed to be called from a ``DataUpdateCoordinator`` on a fixed
    interval. Uses :func:`bleak_retry_connector.establish_connection`
    so transient BLE errors get retried for us.
    """
    reading: TemtopSensorReading | None = None
    reading_event = asyncio.Event()
    parse_error: Exception | None = None
    learned_token: bytes | None = None
    token_event = asyncio.Event()

    def _on_notify(_handle: int, data: bytearray) -> None:
        nonlocal reading, parse_error, learned_token
        raw = bytes(data)
        # Capture the token from any well-formed frame, even one we
        # don't fully decode. Lets the next outbound write echo it
        # back unchanged (the device appears to expect this).
        if learned_token is None and len(raw) >= 14 and _validate_checksum(raw):
            learned_token = raw[4:14]
            token_event.set()
        try:
            decoded = parse_sensor_frame(raw)
        except TemtopProtocolError as err:
            parse_error = err
            reading_event.set()
            return
        if decoded is not None:
            reading = decoded
            reading_event.set()

    async def _connect() -> BleakClient:
        return await establish_connection(
            BleakClient,
            ble_device,
            name=ble_device.name or ble_device.address,
            max_attempts=3,
        )

    client = await _connect()
    try:
        await client.start_notify(NOTIFY_CHAR_UUID, _on_notify)
        # Wait briefly for any push to land first - this gives us the
        # real device-specific token before we send anything.
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(token_event.wait(), timeout=2.0)

        token = learned_token or DEFAULT_TOKEN
        frame = _build_frame(OPCODE_SNAPSHOT_REQUEST, b"", token=token)
        await client.write_gatt_char(WRITE_CHAR_UUID, frame, response=False)

        try:
            await asyncio.wait_for(reading_event.wait(), timeout=READ_TIMEOUT_SECONDS)
        except asyncio.TimeoutError as err:
            raise TemtopProtocolError(
                "timeout waiting for sensor frame from device"
            ) from err
    finally:
        with contextlib.suppress(Exception):
            await client.stop_notify(NOTIFY_CHAR_UUID)
        with contextlib.suppress(Exception):
            await client.disconnect()

    if parse_error is not None:
        raise parse_error
    if reading is None:
        raise TemtopProtocolError(
            "no sensor frame received from device within timeout"
        )
    return reading
