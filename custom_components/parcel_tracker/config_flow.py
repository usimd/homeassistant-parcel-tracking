"""Config flow for Parcel Tracker integration."""

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .api import Ship24Api
from .const import (
    CONF_API_KEY,
    CONF_CLEANUP_DAYS,
    CONF_DROP_OFF_LOCATION,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_CLEANUP_DAYS,
    DEFAULT_DROP_OFF_LOCATION,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class ParcelTrackerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Parcel Tracker."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - Ship24 API key entry."""
        errors = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY]

            # Validate the API key
            api = Ship24Api(self.hass, api_key)
            if await api.test_connection():
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="Parcel Tracker",
                    data={CONF_API_KEY: api_key},
                )
            else:
                errors["base"] = "cannot_connect"

        data_schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "ParcelTrackerOptionsFlow":
        """Get the options flow handler."""
        return ParcelTrackerOptionsFlow(config_entry)


class ParcelTrackerOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Parcel Tracker."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle options step."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_CLEANUP_DAYS,
                    default=self._config_entry.options.get(
                        CONF_CLEANUP_DAYS, DEFAULT_CLEANUP_DAYS
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=30,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_SCAN_INTERVAL_HOURS,
                    default=self._config_entry.options.get(
                        CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=12,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_DROP_OFF_LOCATION,
                    default=self._config_entry.options.get(
                        CONF_DROP_OFF_LOCATION, DEFAULT_DROP_OFF_LOCATION
                    ),
                ): str,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
        )
