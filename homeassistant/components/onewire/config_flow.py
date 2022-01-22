"""Config flow for 1-Wire component."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TYPE
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntry, DeviceRegistry

from .const import (
    CONF_MOUNT_DIR,
    CONF_TYPE_OWSERVER,
    CONF_TYPE_SYSBUS,
    DEFAULT_OWSERVER_HOST,
    DEFAULT_OWSERVER_PORT,
    DEFAULT_SYSBUS_MOUNT_DIR,
    DOMAIN,
)
from .model import OWServerDeviceDescription
from .onewirehub import CannotConnect, InvalidPath, OneWireHub

DATA_SCHEMA_USER = vol.Schema(
    {vol.Required(CONF_TYPE): vol.In([CONF_TYPE_OWSERVER, CONF_TYPE_SYSBUS])}
)
DATA_SCHEMA_OWSERVER = vol.Schema(
    {
        vol.Required(CONF_HOST, default=DEFAULT_OWSERVER_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_OWSERVER_PORT): int,
    }
)
DATA_SCHEMA_MOUNTDIR = vol.Schema(
    {
        vol.Required(CONF_MOUNT_DIR, default=DEFAULT_SYSBUS_MOUNT_DIR): str,
    }
)


_LOGGER = logging.getLogger(__name__)


async def validate_input_owserver(
    hass: HomeAssistant, data: dict[str, Any]
) -> dict[str, str]:
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA_OWSERVER with values provided by the user.
    """

    hub = OneWireHub(hass)

    host = data[CONF_HOST]
    port = data[CONF_PORT]
    # Raises CannotConnect exception on failure
    await hub.connect(host, port)

    # Return info that you want to store in the config entry.
    return {"title": host}


async def validate_input_mount_dir(
    hass: HomeAssistant, data: dict[str, Any]
) -> dict[str, str]:
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA_MOUNTDIR with values provided by the user.
    """
    hub = OneWireHub(hass)

    mount_dir = data[CONF_MOUNT_DIR]

    # Raises InvalidDir exception on failure
    await hub.check_mount_dir(mount_dir)

    # Return info that you want to store in the config entry.
    return {"title": mount_dir}


class OneWireFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle 1-Wire config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize 1-Wire config flow."""
        self.onewire_config: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle 1-Wire config flow start.

        Let user manually input configuration.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            self.onewire_config.update(user_input)
            if CONF_TYPE_OWSERVER == user_input[CONF_TYPE]:
                return await self.async_step_owserver()
            if CONF_TYPE_SYSBUS == user_input[CONF_TYPE]:
                return await self.async_step_mount_dir()

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA_USER,
            errors=errors,
        )

    async def async_step_owserver(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle OWServer configuration."""
        errors = {}
        if user_input:
            # Prevent duplicate entries
            self._async_abort_entries_match(
                {
                    CONF_TYPE: CONF_TYPE_OWSERVER,
                    CONF_HOST: user_input[CONF_HOST],
                    CONF_PORT: user_input[CONF_PORT],
                }
            )

            self.onewire_config.update(user_input)

            try:
                info = await validate_input_owserver(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=info["title"], data=self.onewire_config
                )

        return self.async_show_form(
            step_id="owserver",
            data_schema=DATA_SCHEMA_OWSERVER,
            errors=errors,
        )

    async def async_step_mount_dir(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle SysBus configuration."""
        errors = {}
        if user_input:
            # Prevent duplicate entries
            await self.async_set_unique_id(
                f"{CONF_TYPE_SYSBUS}:{user_input[CONF_MOUNT_DIR]}"
            )
            self._abort_if_unique_id_configured()

            self.onewire_config.update(user_input)

            try:
                info = await validate_input_mount_dir(self.hass, user_input)
            except InvalidPath:
                errors["base"] = "invalid_path"
            else:
                return self.async_create_entry(
                    title=info["title"], data=self.onewire_config
                )

        return self.async_show_form(
            step_id="mount_dir",
            data_schema=DATA_SCHEMA_MOUNTDIR,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return OnewireOptionsFlowHandler(config_entry)


class OnewireOptionsFlowHandler(OptionsFlow):
    """Handle OneWire Config options."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize OneWire Network options flow."""
        self.config_entry = config_entry
        self.options = dict(config_entry.options)
        self.controller: OneWireHub
        self.device_list_ds18b20: list[str] = []
        self.current_device: str = ""
        self.devices_to_configure_ds18b20: list[str] = []
        self.device_registry: DeviceRegistry | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        self.controller = self.hass.data[DOMAIN][self.config_entry.entry_id]
        # Comment: This list could also be a list of entities instead of devices.
        #          Perhaps that would be  easier for the user because that enables use of descriptive names
        self.device_registry = dr.async_get(self.hass)

        if self.controller.devices:
            self.device_list_ds18b20 = [
                x.id
                for x in self.controller.devices
                if isinstance(x, OWServerDeviceDescription) and x.type == "DS18B20"
            ]
        _LOGGER.info(
            "\n---- STEP_INIT ----\n -- Options: %s \n -- User_input: %s",
            self.options,
            user_input,
        )
        for device_id in self.device_list_ds18b20:
            device = self.device_registry.async_get_device({(DOMAIN, device_id)})
            if not device:
                break
            _LOGGER.info(
                "\n---- STEP_INIT ----\n -- Device : %s -- %s -- %s",
                device_id,
                device.name_by_user,
                device.id,
            )

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return await self.async_step_device_selection(user_input=None)

    async def async_step_device_selection(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select what devices to configure."""

        if user_input is not None:
            _LOGGER.info(
                "\n---- STEP_DEVICE_SELECTION ----\n -- Options: %s\n --  User input: %s",
                self.options,
                user_input,
            )
            self._update_options_dict(user_input)
            if self.options["clear_device_config"]:
                self.options = {}
            else:
                _LOGGER.info(
                    "\n---- STEP_DEVICE_SELECTION (In ELSE) ----\n -- Options: %s",
                    self.options,
                )
                self.devices_to_configure_ds18b20 = self.options[
                    "ds18b20_device_selection"
                ].copy()
                if self.devices_to_configure_ds18b20:
                    return await self.async_step_ds1820b_device_config(user_input=None)
            return await self._update_options()

        return self.async_show_form(
            step_id="device_selection",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "clear_device_config",
                        default=False,
                    ): bool,
                    vol.Optional(
                        "ds18b20_device_selection",
                        default=self._get_current_ds18b20_config_selection(),
                        description="Multiselect with list of devices to choose from",
                    ): cv.multi_select(
                        {device: False for device in self._get_device_list_with_names()}
                    ),
                }
            ),
        )

    async def async_step_ds1820b_device_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Config options for DS18B20 device."""
        if user_input is not None:
            self._update_ds18b20_config_option(self.current_device, user_input)
            if len(self.devices_to_configure_ds18b20) > 0:
                return await self.async_step_ds1820b_device_config(user_input=None)
            return await self._update_options()
        self.current_device = self.devices_to_configure_ds18b20.pop()
        return self.async_show_form(
            step_id="ds1820b_device_config",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "sensor_precision",
                        default=self._get_default_ds18b20_config_option(
                            self.current_device
                        ),
                    ): vol.In(["Default", "9 Bits", "10 Bits", "11 Bits", "12 Bits"]),
                }
            ),
            description_placeholders={
                "sens_id": self._get_device_long_name_from_id(self.current_device)
            },
        )

    async def _update_options(self) -> FlowResult:
        """Update config entry options."""
        _LOGGER.info(
            "\n---- UPDATE_OPTIONS  ----\n -- Options: %s",
            self.options,
        )
        return self.async_create_entry(title="", data=self.options)

    def _get_device_list_with_names(self) -> list[str]:
        possible_devices = self.device_list_ds18b20
        name_list: list[str] = []
        for device_id in possible_devices:
            name_list.append(self._get_device_long_name_from_id(device_id))
        return name_list

    def _get_device_long_name_from_id(self, current_device: str) -> str:
        device: DeviceEntry | None
        if self.device_registry:
            device = self.device_registry.async_get_device({(DOMAIN, current_device)})
        else:
            _LOGGER.error("No device registry in config flow, this is a fatal error")
        if device and device.name_by_user:
            return f"{device.name_by_user} ({current_device})"
        return current_device

    def _get_device_id_from_long_name(self, device_name: str) -> str:
        if "(" in device_name:
            return device_name.split("(")[1].replace(")", "")
        return device_name

    def _get_current_ds18b20_config_selection(self) -> list[str] | None:
        possible_devices = self.device_list_ds18b20
        selected_entries = self.options.get("ds18b20_device_selection")
        _LOGGER.info(
            "\n---- CURRENT_DS18B20_CONFIG_SELECTION  ----\n -- selected_entries: %s\n -- possible_devices: %s",
            selected_entries,
            possible_devices,
        )
        if selected_entries is None:
            return []
        return [
            device
            for device in self._get_device_list_with_names()
            if self._get_device_id_from_long_name(device) in selected_entries
        ]

    def _get_default_ds18b20_config_option(self, device: str) -> str:
        """Get default value for DS18B20 type config."""
        _LOGGER.info(
            "\n---- GET_DEFAULT_DS18B20  ----\n -- Options: %s (type) %s",
            self.options,
            type(self.options),
        )
        sensor_precision_entry: dict[str, str] | None = self.options.get(
            "sensor_precision"
        )
        _LOGGER.info(
            "\n---- STEP_DEFAULT_DS18B20  ----\n -- Precision entry type: %s",
            type(sensor_precision_entry),
        )

        if sensor_precision_entry and device in sensor_precision_entry:
            return sensor_precision_entry[device]
        return "Default"

    def _update_ds18b20_config_option(
        self, device: str, user_input: dict[str, Any]
    ) -> None:
        """Update the options precision entry with the new precision for the actual device."""
        sensor_precision_entry = self.options.get("sensor_precision")
        if sensor_precision_entry:
            sensor_precision_entry[device] = user_input["sensor_precision"]
        else:
            sensor_precision_entry = {device: user_input["sensor_precision"]}
        self.options.update({"sensor_precision": sensor_precision_entry})

    def _update_options_dict(self, user_input: dict[str, Any]) -> None:
        """Update the local options according to the user input."""
        if "ds18b20_device_selection" in user_input:
            name_list = user_input["ds18b20_device_selection"]
            for index, entry in enumerate(name_list):
                name_list[index] = self._get_device_id_from_long_name(entry)
        self.options.update(user_input)
