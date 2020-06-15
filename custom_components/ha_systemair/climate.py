"""Support for the SystemAIR HVAC."""
import logging

from .const import (
    ATTR_TARGET_TEMPERATURE,
    PRESET_AUTO,
    PRESET_CROWDED,
    PRESET_FIREPLACE,
    PRESET_HOLIDAY,
    PRESET_IDLE,
    PRESET_MANUAL,
    PRESET_REFRESH,
    SIGNAL_SYSTEMAIR_UPDATE_RECEIVED,
)

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ATTR_CURRENT_HUMIDITY,
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_OFF,
    HVAC_MODE_AUTO,
    HVAC_MODE_OFF,
    SUPPORT_FAN_MODE,
    SUPPORT_PRESET_MODE,
    SUPPORT_TARGET_TEMPERATURE,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, TEMP_CELSIUS
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN
from .systemair.save.const import (
    SENSOR_MODE_CHANGE_REQUEST,
    SENSOR_CURRENT_FAN_MODE,
    SENSOR_TARGET_TEMPERATURE,
    SENSOR_CUSTOM_OPERATION,
    SENSOR_TEMPERATURE_EXTRACT,
    SENSOR_CURRENT_OPERATION,
    SENSOR_CUSTOM_FAN_MODE,
    SENSOR_CURRENT_HUMIDITY,
    SA_OPERATION_MODE_AUTO,
    SA_OPERATION_MODE_MANUAL,
    SA_OPERATION_MODE_CROWDED,
    SA_OPERATION_MODE_REFRESH,
    SA_OPERATION_MODE_FIREPLACE,
    SA_OPERATION_MODE_HOLIDAY,
    SA_OPERATION_MODE_IDLE,
    SA_OPERATION_MODE_OFF
)

_LOGGER = logging.getLogger(__name__)

HA_STATE_TO_SA = {
    HVAC_MODE_AUTO: SA_OPERATION_MODE_AUTO,
    HVAC_MODE_OFF: SA_OPERATION_MODE_OFF,
}

HA_PRESET_TO_SA = {
    PRESET_AUTO: SA_OPERATION_MODE_AUTO,
    PRESET_MANUAL:SA_OPERATION_MODE_MANUAL,
    PRESET_CROWDED: SA_OPERATION_MODE_CROWDED,
    PRESET_REFRESH: SA_OPERATION_MODE_REFRESH,
    PRESET_FIREPLACE: SA_OPERATION_MODE_FIREPLACE,
    PRESET_HOLIDAY: SA_OPERATION_MODE_HOLIDAY,
    PRESET_IDLE: SA_OPERATION_MODE_IDLE,
}

FAN_MAXIMUM = "maximum"

HA_SET_ATTR_TO_SA = {
    ATTR_HVAC_MODE: SENSOR_CUSTOM_OPERATION,
    ATTR_TEMPERATURE: SENSOR_TARGET_TEMPERATURE,
    ATTR_FAN_MODE: SENSOR_CURRENT_FAN_MODE,
    ATTR_PRESET_MODE: SENSOR_MODE_CHANGE_REQUEST,
}

HA_ATTR_TO_SA = {
    ATTR_TEMPERATURE: SENSOR_TEMPERATURE_EXTRACT,
    ATTR_TARGET_TEMPERATURE: SENSOR_TARGET_TEMPERATURE,
    ATTR_PRESET_MODE: SENSOR_CURRENT_OPERATION,
    ATTR_FAN_MODE: SENSOR_CUSTOM_FAN_MODE,
    ATTR_HVAC_MODE: SENSOR_CUSTOM_OPERATION,
    ATTR_CURRENT_HUMIDITY: SENSOR_CURRENT_HUMIDITY,
}


async def async_setup_entry(hass, config_entry: ConfigEntry, async_add_entities):
    """Set up Systemair climate based on config_entry."""
    api = hass.data[DOMAIN][config_entry.entry_id]

    async_add_entities([SystemAIRClimate(hass, api)])


class SystemAIRClimate(ClimateEntity):
    """Representation of a SystemAIR HVAC."""

    def __init__(self, hass, sab):
        """Initialize the climate device."""
        self._name = DOMAIN
        self._sab = sab
        self._list = {
            ATTR_HVAC_MODE: list(HA_STATE_TO_SA),
            ATTR_FAN_MODE: [FAN_OFF, FAN_LOW, FAN_MEDIUM, FAN_HIGH, FAN_MAXIMUM],
        }

        self._supported_features = SUPPORT_TARGET_TEMPERATURE
        self._supported_features |= SUPPORT_PRESET_MODE
        self._supported_features |= SUPPORT_FAN_MODE

        async def _handle_update(var):
            self.async_schedule_update_ha_state()

        # Register for dispatcher updates
        async_dispatcher_connect(hass, SIGNAL_SYSTEMAIR_UPDATE_RECEIVED, _handle_update)

    def get(self, key):
        """Retrieve device settings from API library cache."""
        sa_key = HA_ATTR_TO_SA.get(key)
        if sa_key not in self._sab.state:
            _LOGGER.warning("Missing attribute %s", sa_key)
            return None

        sa_value = self._sab.state[sa_key]
        _LOGGER.debug("sa_key=%s, key=%s, value=%s", sa_key, key, sa_value)
        return sa_value

    async def _set(self, settings):
        """Set device settings using API."""
        for ha_key in HA_SET_ATTR_TO_SA:
            value = settings.get(ha_key)
            if value is None:
                continue

            sa_key = HA_SET_ATTR_TO_SA.get(ha_key)
            _LOGGER.debug("sa_key=%s, ha_key=%s, value=%s", sa_key, ha_key, value)
            await self._sab.set(sa_key, value)

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._supported_features

    @property
    def name(self):
        """Return the name of the thermostat, if any."""
        return self._name

    @property
    def temperature_unit(self):
        """Return the unit of measurement which this thermostat uses."""
        return TEMP_CELSIUS

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self.get(ATTR_TEMPERATURE)

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self.get(ATTR_TARGET_TEMPERATURE)

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        return 1

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        await self._set(kwargs)

    @property
    def hvac_mode(self):
        """Return current operation ie. heat, cool, idle."""
        return self.get(ATTR_HVAC_MODE)

    @property
    def hvac_modes(self):
        """Return the list of available operation modes."""
        return self._list.get(ATTR_HVAC_MODE)

    async def async_set_hvac_mode(self, hvac_mode):
        """Set HVAC mode."""
        await self._set({ATTR_HVAC_MODE: hvac_mode})

    @property
    def fan_mode(self):
        """Return the fan setting."""
        return self.get(ATTR_FAN_MODE)

    async def async_set_fan_mode(self, fan_mode):
        """Set fan mode."""
        await self._set({ATTR_FAN_MODE: fan_mode})

    @property
    def fan_modes(self):
        """List of available fan modes."""
        return self._list.get(ATTR_FAN_MODE)

    @property
    def preset_mode(self):
        """Return the fan setting."""
        return self.get(ATTR_PRESET_MODE)

    async def async_set_preset_mode(self, preset_mode):
        """Set new target temperature."""
        await self._set({ATTR_PRESET_MODE: preset_mode})

    @property
    def current_humidity(self):
        """Return the humidity value."""
        return self.get(ATTR_CURRENT_HUMIDITY)

    @property
    def preset_modes(self):
        """List of available swing modes."""
        return list(HA_PRESET_TO_SA)

    async def async_update(self):
        """Retrieve latest state."""
        await self._sab.poll_now()
