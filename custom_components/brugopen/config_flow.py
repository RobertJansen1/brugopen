"""Config flow for the Brugopeningen integration.

The integration requires no user-supplied credentials or settings to start –
it simply connects to the public NDW open data API.  The config flow is
therefore a single "confirm" step.

After setup the user can open the options flow (⚙️ on the integration card)
to select which specific bridges to follow.  All newly discovered bridges are
shown as a searchable multi-select list.  An empty selection means "follow all
bridges".
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import CONF_SCAN_INTERVAL, CONF_WATCHED_BRIDGES, DEFAULT_SCAN_INTERVAL, DOMAIN


class BrugOpenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup of the Brugopeningen integration."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Show a single confirmation form and create the config entry."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="Brugopeningen", data={})

        return self.async_show_form(step_id="user")

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return BrugOpenOptionsFlow(config_entry)


class BrugOpenOptionsFlow(config_entries.OptionsFlow):
    """Options flow – two steps:
      1. init   : general settings (refresh interval)
      2. bridges: bridge selection
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._options: dict = dict(config_entry.options)

    # ------------------------------------------------------------------
    # Step 1 – general settings
    # ------------------------------------------------------------------

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            self._options[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
            return await self.async_step_bridges()

        current_interval: int = self._options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=current_interval,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=5,
                            max=300,
                            step=5,
                            unit_of_measurement="s",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )

    # ------------------------------------------------------------------
    # Step 2 – bridge selection
    # ------------------------------------------------------------------

    async def async_step_bridges(self, user_input: dict | None = None) -> FlowResult:
        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id]
        bridges = coordinator.data

        if user_input is not None:
            self._options[CONF_WATCHED_BRIDGES] = user_input.get(CONF_WATCHED_BRIDGES, [])
            return self.async_create_entry(title="", data=self._options)

        currently_watched: list[str] = self._options.get(CONF_WATCHED_BRIDGES, [])

        bridge_options = [
            selector.SelectOptionDict(value=bid, label=b.name)
            for bid, b in sorted(bridges.items(), key=lambda x: x[1].name.lower())
        ]

        return self.async_show_form(
            step_id="bridges",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_WATCHED_BRIDGES,
                        default=currently_watched,
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=bridge_options,
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )
