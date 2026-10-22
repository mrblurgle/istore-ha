import logging

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, CONF_USERNAME, CONF_PASSWORD, CONF_ACCESS_TOKEN, CONF_PARENT_ID, CONF_MDM_ID
from .api import authenticate, IStoreAuthError, IStoreApiError

_LOGGER = logging.getLogger(__name__)


class CannotConnect(HomeAssistantError):
    """Error raised when API connection fails."""


class InvalidAuth(HomeAssistantError):
    """Error for invalid authentication."""


def _credentials_schema(username=None):
    """Username/password form, pre-filling the username when known."""
    if username:
        user_field = vol.Required(CONF_USERNAME, default=username)
    else:
        user_field = vol.Required(CONF_USERNAME)
    return vol.Schema(
        {
            user_field: str,
            vol.Required(CONF_PASSWORD): str,
        }
    )


async def _try_login(user_input, errors):
    """Log in with the submitted credentials. Returns creds, or None with errors set."""
    try:
        return await authenticate(
            user_input[CONF_USERNAME],
            user_input[CONF_PASSWORD],
        )
    except IStoreAuthError:
        errors["base"] = "invalid_auth"
    except (IStoreApiError, aiohttp.ClientError, TimeoutError, OSError):
        errors["base"] = "cannot_connect"
    except Exception:
        _LOGGER.exception("Unexpected error during iStore login")
        errors["base"] = "cannot_connect"
    return None


def _entry_data(user_input, creds):
    return {
        CONF_USERNAME: user_input[CONF_USERNAME],
        CONF_PASSWORD: user_input[CONF_PASSWORD],
        CONF_ACCESS_TOKEN: creds["access_token"],
        CONF_PARENT_ID: creds["parent_id"],
        CONF_MDM_ID: creds["mdm_id"],
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    @staticmethod
    def async_get_options_flow(config_entry):
        from .options_flow import OptionsFlowHandler
        return OptionsFlowHandler()

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            creds = await _try_login(user_input, errors)

            if not errors:
                for existing_entry in self._async_current_entries():
                    if existing_entry.data.get(CONF_MDM_ID) == creds["mdm_id"]:
                        return self.async_abort(reason="already_configured")

                return self.async_create_entry(
                    title="iStore Heat Pump",
                    data=_entry_data(user_input, creds),
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_credentials_schema(),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data):
        """Start reauth when the stored credentials stop working or are missing."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        entry = self._get_reauth_entry()
        return await self._async_update_credentials(
            entry, "reauth_confirm", user_input
        )

    async def async_step_reconfigure(self, user_input=None):
        """Change the iStore username/password without removing the integration."""
        entry = self._get_reconfigure_entry()
        return await self._async_update_credentials(
            entry, "reconfigure", user_input
        )

    async def _async_update_credentials(self, entry, step_id, user_input):
        """Shared reauth/reconfigure step: log in, check it's the same device, save."""
        errors = {}

        if user_input is not None:
            creds = await _try_login(user_input, errors)

            if not errors:
                if entry.data.get(CONF_MDM_ID) not in (None, creds["mdm_id"]):
                    return self.async_abort(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=_entry_data(user_input, creds),
                )

        return self.async_show_form(
            step_id=step_id,
            data_schema=_credentials_schema(entry.data.get(CONF_USERNAME)),
            errors=errors,
        )
