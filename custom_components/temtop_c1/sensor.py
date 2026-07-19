"""Sensor entities for the Temtop C1+."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import (
    CONNECTION_BLUETOOTH,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .coordinator import TemtopC1ConfigEntry, TemtopC1Coordinator
from .protocol import TemtopSensorReading

# Keep entities available (serving the last good reading) for this long
# after the most recent successful poll, even if subsequent polls fail.
# BLE polls can miss for a number of reasons (device asleep, transient
# adapter glitch, contention with other BLE devices), and going
# `unavailable` on every blip is noisy. 15 min = ~15 natural retries at
# the default 60 s scan interval.
STALE_TOLERANCE = timedelta(minutes=15)

# The C1+ only exposes a 4-bar battery gauge (payload byte 20), not a true
# percentage. We map bars to a percentage deliberately rather than
# linearly: a single remaining bar reports 10 % - below Home Assistant's
# default low-battery alert threshold - so the user is nudged to recharge
# before the device dies. The upper bars stay roughly linear.
_BARS_TO_PERCENT = {0: 0, 1: 10, 2: 50, 3: 75, 4: 100}


def _battery_percent(bars: int | None) -> int | None:
    """Map the device's 0-4 bar gauge to a percentage, or None if unknown."""
    if bars is None:
        return None
    # Fall back to a clamped linear estimate for any unexpected bar count.
    return _BARS_TO_PERCENT.get(bars, max(0, min(100, bars * 25)))


@dataclass(frozen=True, kw_only=True)
class TemtopSensorEntityDescription(SensorEntityDescription):
    """SensorEntityDescription with a function that pulls the value off a reading."""

    value_fn: Callable[[TemtopSensorReading], StateType]


SENSOR_DESCRIPTIONS: tuple[TemtopSensorEntityDescription, ...] = (
    TemtopSensorEntityDescription(
        key="co2",
        translation_key="co2",
        device_class=SensorDeviceClass.CO2,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
        suggested_display_precision=0,
        value_fn=lambda r: r.co2_ppm,
    ),
    TemtopSensorEntityDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda r: r.temperature_c,
    ),
    TemtopSensorEntityDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        value_fn=lambda r: r.humidity_pct,
    ),
    # The C1+ reports a 4-bar battery gauge at payload byte 20. We surface
    # it as a percentage via a deliberate, non-linear map (see
    # _battery_percent) so a single remaining bar trips HA's low-battery
    # alerts. Reports None (unavailable) if a frame lacks the battery byte.
    TemtopSensorEntityDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda r: _battery_percent(r.battery_bars),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TemtopC1ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Temtop C1+ sensor entities for a config entry."""
    coordinator = entry.runtime_data
    address = entry.unique_id
    assert address is not None
    # Normalise the MAC the same way HA's Bluetooth integration does
    # when it auto-creates the device entry from the discovery flow.
    # Without this, the entities attach to a *second* device entry that
    # doesn't merge with the discovery-created tile, so the device page
    # appears to have no entities.
    address = format_mac(address)
    async_add_entities(
        TemtopC1Sensor(coordinator, description, address, entry.title)
        for description in SENSOR_DESCRIPTIONS
    )


class TemtopC1Sensor(CoordinatorEntity[TemtopC1Coordinator], SensorEntity):
    """A single Temtop C1+ sensor reading exposed as an HA entity."""

    _attr_has_entity_name = True
    entity_description: TemtopSensorEntityDescription

    def __init__(
        self,
        coordinator: TemtopC1Coordinator,
        description: TemtopSensorEntityDescription,
        address: str,
        title: str,
    ) -> None:
        """Initialise the sensor entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{address}_{description.key}"
        # Use `connections` only - matches the pattern in airthings_ble and
        # eq3btsmart and lets HA merge into the existing device entry that
        # the Bluetooth discovery flow created.
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, address)},
            name=title,
            manufacturer="Temtop",
            model="C1+",
        )

    @property
    def available(self) -> bool:
        """Stay available while the last good reading is within tolerance.

        The default `CoordinatorEntity.available` flips to False after a
        single failed poll. For a battery-powered BLE device, transient
        failures are routine - keep serving the last good reading until
        we've been failing for longer than `STALE_TOLERANCE`.
        """
        if self.coordinator.last_update_success:
            return True
        last_ok = self.coordinator.last_ok
        if last_ok is None or self.coordinator.data is None:
            return False
        return dt_util.utcnow() - last_ok < STALE_TOLERANCE

    @property
    def native_value(self) -> StateType:
        """Pull the value out of the most recent coordinator reading."""
        data = self.coordinator.data
        if data is None:
            return None
        return self.entity_description.value_fn(data)
