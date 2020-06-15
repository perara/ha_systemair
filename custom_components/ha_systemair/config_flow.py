"""Config flow for savecair integration."""
import logging

import voluptuous as vol

from homeassistant import config_entries, exceptions

from .const import DOMAIN  # pylint:disable=unused-import
from .systemair.save.api import SaveAPI
from .systemair.save.exceptions import InvalidDeviceError, InvalidIAMError, InvalidPasswordError

_LOGGER = logging.getLogger(__name__)


DATA_SCHEMA = vol.Schema({"iam_id": str, "password": str})


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for savecair."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    def __init__(self):
        self._session = SaveAPI()

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:

                # Connect to the savecair endpoint
                await self._session.connect()

                # Attempt to login into the savecair portal
                info = await self._session.login(
                    user_input["iam_id"], user_input["password"]
                )

                return self.async_create_entry(title=info["machineID"], data=user_input)
            except ConnectionError:
                errors["base"] = "cannot_connect"
            except InvalidDeviceError:
                errors["base"] = "invalid_device"
            except InvalidIAMError:
                errors["base"] = "invalid_auth"
            except InvalidPasswordError:
                errors["base"] = "invalid_password"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )
