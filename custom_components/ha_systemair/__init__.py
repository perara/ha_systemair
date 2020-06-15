"""The savecair integration."""
import asyncio
import logging

import voluptuous as vol

from .const import (
    DOMAIN,
    SIGNAL_SYSTEMAIR_UPDATE_RECEIVED,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .systemair.save.api import SaveAPI

_LOGGER = logging.getLogger(__name__)
CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({})}, extra=vol.ALLOW_EXTRA)
PLATFORMS = ["climate"]


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the savecair component."""
    hass.data[DOMAIN] = {}

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up savecair from a config entry."""

    async def on_error(err):
        _LOGGER.error(err)

    async def on_update(data):
        async_dispatcher_send(hass, SIGNAL_SYSTEMAIR_UPDATE_RECEIVED, data)

    sa = SaveAPI(
        iam_id=entry.data["iam_id"], password=entry.data["password"], load_all=True
    )
    sa.add_listener_on_error(on_error)
    sa.add_listener_on_update(on_update)

    await sa.connect()
    state = await sa.login()

    if "machineID" not in state:
        return False

    hass.data[DOMAIN][entry.entry_id] = sa

    for component in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, component)
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, component)
                for component in PLATFORMS
            ]
        )
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
