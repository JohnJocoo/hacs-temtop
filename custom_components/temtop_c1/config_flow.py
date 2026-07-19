"""Config flow for the Temtop C1+ BLE integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import DEVICE_LOCAL_NAME_PREFIX, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _is_temtop(info: BluetoothServiceInfoBleak) -> bool:
    """Return True if a discovered BLE device looks like a Temtop C1+."""
    name = info.name or ""
    return name.startswith(DEVICE_LOCAL_NAME_PREFIX)


class TemtopC1ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a Temtop C1+ config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        # Map of address -> BluetoothServiceInfoBleak for the user-step picker.
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a Bluetooth discovery."""
        _LOGGER.debug("Discovered Temtop candidate: %s", discovery_info)
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        if not _is_temtop(discovery_info):
            return self.async_abort(reason="not_supported")

        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {
            "name": discovery_info.name or discovery_info.address
        }
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered device."""
        assert self._discovery_info is not None
        info = self._discovery_info
        if user_input is not None:
            return self.async_create_entry(
                title=info.name or info.address,
                data={CONF_ADDRESS: info.address},
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders=self.context["title_placeholders"],
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user step (manual device picker)."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            info = self._discovered_devices.get(address)
            title = info.name if info and info.name else address
            return self.async_create_entry(
                title=title,
                data={CONF_ADDRESS: address},
            )

        current_addresses = self._async_current_ids()
        self._discovered_devices = {}
        for info in async_discovered_service_info(self.hass):
            if info.address in current_addresses:
                continue
            if not _is_temtop(info):
                continue
            self._discovered_devices[info.address] = info

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            addr: (info.name or addr)
                            for addr, info in self._discovered_devices.items()
                        }
                    )
                }
            ),
        )
