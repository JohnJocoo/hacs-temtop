"""DataUpdateCoordinator for the Temtop C1+ BLE sensor."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

from bleak.backends.device import BLEDevice
from bleak_retry_connector import close_stale_connections_by_address

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DEFAULT_SCAN_INTERVAL_SECONDS, DOMAIN
from .protocol import (
    TemtopProtocolError,
    TemtopSensorReading,
    async_read_one_snapshot,
)

_LOGGER = logging.getLogger(__name__)

type TemtopC1ConfigEntry = ConfigEntry[TemtopC1Coordinator]


class TemtopC1Coordinator(DataUpdateCoordinator[TemtopSensorReading]):
    """Connect, read one snapshot, disconnect — on a fixed interval."""

    ble_device: BLEDevice
    config_entry: TemtopC1ConfigEntry
    last_ok: datetime | None = None

    def __init__(self, hass: HomeAssistant, entry: TemtopC1ConfigEntry) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL_SECONDS),
        )

    async def _async_setup(self) -> None:
        """Resolve the BLE device once when the entry is set up."""
        address = self.config_entry.unique_id
        assert address is not None

        await close_stale_connections_by_address(address)

        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, address, connectable=True
        )
        if ble_device is None:
            raise ConfigEntryNotReady(
                f"Could not find Temtop C1+ device with address {address}"
            )
        self.ble_device = ble_device

    async def _async_update_data(self) -> TemtopSensorReading:
        """Fetch one sensor snapshot from the device."""
        # Re-resolve the BLE device each poll so we pick up advertising
        # data refreshes from HA's Bluetooth manager (RSSI, new path, ...).
        address = self.config_entry.unique_id
        assert address is not None

        # Reclaim any connection slot left occupied by a prior half-open
        # connection before we try to connect again. Without this, a poll
        # whose disconnect didn't fully clean up can leave the adapter's
        # single slot busy, so every subsequent poll fails with
        # "out of connection slots" until HA eventually reaps it.
        await close_stale_connections_by_address(address)

        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, address, connectable=True
        )
        if ble_device is not None:
            self.ble_device = ble_device

        try:
            reading = await async_read_one_snapshot(self.ble_device)
        except TemtopProtocolError as err:
            raise UpdateFailed(str(err)) from err
        except Exception as err:  # noqa: BLE001 -- surface BLE errors uniformly
            raise UpdateFailed(f"Error talking to Temtop C1+: {err}") from err
        self.last_ok = dt_util.utcnow()
        return reading
