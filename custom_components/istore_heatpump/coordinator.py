from datetime import timedelta
import logging

import aiohttp
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import IStoreApiError, IStoreAuthError

_LOGGER = logging.getLogger(__name__)


class iStoreCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, api, config_entry):
        self.api = api
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="iStore Heat Pump",
            update_interval=timedelta(seconds=30),
        )

    async def _async_update_data(self):
        """Fetch latest data from iStore API.

        Bad credentials raise ConfigEntryAuthFailed so HA asks to re-authenticate.
        Network/API errors raise UpdateFailed: entities go unavailable and
        polling continues, so the integration recovers when the internet returns.
        """
        try:
            data = await self.api.get_measurements()
        except IStoreAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (IStoreApiError, aiohttp.ClientError, TimeoutError, OSError) as err:
            raise UpdateFailed(f"iStore update failed: {err}") from err
        return data["data"]
