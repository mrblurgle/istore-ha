import voluptuous as vol
from homeassistant import config_entries


class OptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """Handle options flow for iStore Heat Pump (entry reloads on save)."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options

        data_schema = vol.Schema(
            {
                vol.Optional(
                    "cold_water_temp",
                    default=options.get("cold_water_temp", 15),
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=30)),
                vol.Optional(
                    "shower_flow_rate",
                    default=options.get("shower_flow_rate", 9.0),
                ): vol.All(vol.Coerce(float), vol.Range(min=1, max=30)),
                vol.Optional(
                    "shower_temp",
                    default=options.get("shower_temp", 40),
                ): vol.All(vol.Coerce(float), vol.Range(min=20, max=60)),
                vol.Optional(
                    "tempering_temp",
                    default=options.get("tempering_temp", 50),
                ): vol.All(vol.Coerce(float), vol.Range(min=20, max=70)),
                vol.Optional(
                    "tank_volume",
                    default=options.get("tank_volume", 0),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=500)),
            }
        )

        return self.async_show_form(step_id="init", data_schema=data_schema)
