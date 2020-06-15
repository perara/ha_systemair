import asyncio
import json
import logging
import os
import socket

import websockets
from websockets.protocol import State
from systemair.savecair import const
from systemair.savecair.command import read, login, write
from systemair.savecair.const import SA_FAN_MODE_MEDIUM, SA_FAN_MODE_LOW, SA_FAN_MODE_OFF, SA_FAN_MODE_HIGH, \
    SA_OPERATION_MODE_REFRESH, SA_OPERATION_MODE_FIREPLACE, SA_OPERATION_MODE_CROWDED, SA_OPERATION_MODE_HOLIDAY, \
    SA_OPERATION_MODE_IDLE, SA_OPERATION_MODE_AUTO, SA_OPERATION_MODE_MANUAL, SENSOR_CURRENT_OPERATION, \
    SENSOR_CUSTOM_FAN_MODE, SENSOR_CUSTOM_OPERATION, SA_OPERATION_MODE_OFF, POSTPROCESS_MAP, SENSOR_TARGET_TEMPERATURE, \
    SENSOR_MODE_CHANGE_REQUEST, SENSOR_CURRENT_FAN_MODE, USER_MODE

from custom_components.ha_systemair.systemair.save.exceptions import (
    InvalidDeviceError,
    InvalidIAMError,
    InvalidPasswordError,
    UnknownError
)


logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(__name__)
DIR_PATH = os.path.dirname(os.path.realpath(__file__))
RETRY_TIMER = 15


class SystemAIRSocket:

    def __init__(self,
                 url="wss://homesolutions.systemair.com/ws/",
                 reconnect=True,
                 reconnect_interval=60
                 ):
        self._url = url
        self._reconnect = reconnect
        self._reconnect_interval = reconnect_interval
        self.ctx = None

        self._listener_on_message = [
            self.on_message
        ]
        self._listener_on_open = [
            self.on_open
        ]
        self._listener_on_close = [
            self.on_close
        ]

        self._listener_on_error = [
            self.on_error
        ]

        self._e_auth_ok = asyncio.Event()
        self._e_wait_message = asyncio.Event()

    def add_listener_on_error(self, coro):
        self._listener_on_error.append(coro)

    def add_listener_on_close(self, coro):
        self._listener_on_close.append(coro)

    def add_listener_on_open(self, coro):
        self._listener_on_open.append(coro)

    def add_listener_on_update(self, coro):
        self._listener_on_message.append(coro)

    async def connect(self):
        try:
            self.ctx = await websockets.connect(self._url)
            await self._on_open()
            asyncio.get_event_loop().create_task(self._handler())
            asyncio.get_event_loop().create_task(self._poll())
        except socket.gaierror as e:
            await self._on_error(e)
            await self._on_close()

    async def on_open(self):
        pass

    async def on_close(self):
        if self._reconnect:
            _LOGGER.warning("Attempting to reconnect to the savecair device")
            await asyncio.sleep(self._reconnect_interval)
            await self.connect()

    async def on_error(self, err):
        pass

    async def on_message(self, data):
        pass

    async def _on_open(self):
        for coro in self._listener_on_open:
            await coro()

    async def _on_close(self):
        self.ctx = None
        for coro in self._listener_on_close:
            await coro()

    async def _on_error(self, err):
        for coro in self._listener_on_error:
            await coro(err)

    async def _on_message(self, msg):
        for coro in self._listener_on_message:
            await coro(msg)

    async def _handler(self):
        while True:

            while self.ctx is None or self.ctx.state != State.OPEN:
                await asyncio.sleep(.5)

            if self.ctx.state == State.CLOSING:
                await self.ctx.wait_closed()
                return

            while self.ctx.state == State.OPEN:
                try:
                    data = await self.ctx.recv()
                    data = json.loads(data)

                    await self._on_message(data)
                except websockets.ConnectionClosedError as e:
                    await self._on_error(e)
                except websockets.ConnectionClosedOK as e:
                    await self._on_close()
                except ValueError as e:
                    _LOGGER.error("Message from server is not JSON: %s", e)
                finally:
                    self._e_wait_message.set()

            await asyncio.sleep(.1)

    async def send(self, data):
        """Send a message through the websocket channel."""
        if self.ctx is None or not self.ctx.open:
            _LOGGER.warning("Tried to send query when connection does not exists!")
            return False

        await self.ctx.send(str(data))


class SaveAPI(SystemAIRSocket):
    class OpmodeDoesNotExistsError(Exception):
        pass

    class FanmodeDoesNotExistsError(Exception):
        pass

    @staticmethod
    def _load_sensors():
        for sensor in [x for x in dir(const) if "SENSOR_" in x]:
            yield getattr(const, sensor)

    def __init__(self, iam_id=None, password=None, poll_interval=60, load_all=False):
        super().__init__()
        self._iam_id = iam_id
        self._password = password

        """Load parameters from file or arguments."""
        self.available_sensors = set(SaveAPI._load_sensors())
        self.subscribed_sensors = set(self.available_sensors) if load_all else set()

        self._poll_interval = poll_interval

        self.state = {}

        self._fan_mode = {
            SA_FAN_MODE_OFF: self.set_fan_off,
            SA_FAN_MODE_LOW: self.set_fan_low,
            SA_FAN_MODE_MEDIUM: self.set_fan_normal,
            SA_FAN_MODE_HIGH: self.set_fan_high
        }

        self._custom_fan_map = {
            SA_OPERATION_MODE_REFRESH: "user_mode_refresh_supply",
            SA_OPERATION_MODE_FIREPLACE: "user_mode_fireplace_supply",
            SA_OPERATION_MODE_CROWDED: "user_mode_crowded_supply",
            SA_OPERATION_MODE_HOLIDAY: "user_mode_holiday_supply",
            SA_OPERATION_MODE_IDLE: "user_mode_away_supply",
            SA_OPERATION_MODE_AUTO: "user_mode_auto_supply",
            SA_OPERATION_MODE_MANUAL: "main_airflow"
        }

        self._opmode = {
            SA_OPERATION_MODE_AUTO: self.set_auto_mode,
            SA_OPERATION_MODE_MANUAL: self.set_manual_mode,
            SA_OPERATION_MODE_CROWDED: self.set_crowded_mode,
            SA_OPERATION_MODE_REFRESH: self.set_refresh_mode,
            SA_OPERATION_MODE_FIREPLACE: self.set_fireplace_mode,
            SA_OPERATION_MODE_HOLIDAY: self.set_holiday_mode,
            SA_OPERATION_MODE_IDLE: self.set_away_mode
        }

    async def _poll(self):

        while True:

            if not self.ctx or not self.ctx.state == State.OPEN:
                break
            await self._e_auth_ok.wait()
            _LOGGER.warning("Updating sensors: %s" % self.subscribed_sensors)
            await self.poll_now()
            await asyncio.sleep(self._poll_interval)

    async def poll_now(self):
        await self.send(read(list(self.subscribed_sensors)))

    async def _ha_postprocess(self):
        op_key = SENSOR_CURRENT_OPERATION

        if op_key not in self.state:
            return

        op_val = self.state[op_key]
        if op_val in self._custom_fan_map:
            self.state[SENSOR_CUSTOM_FAN_MODE] = self.state[self._custom_fan_map[op_val]]
            self.state[SENSOR_CUSTOM_OPERATION] = SA_OPERATION_MODE_AUTO
        elif SA_OPERATION_MODE_OFF:
            self.state[SENSOR_CUSTOM_FAN_MODE] = SA_FAN_MODE_OFF
            self.state[SENSOR_CUSTOM_OPERATION] = SA_OPERATION_MODE_OFF

    async def _postprocess_and_update(self, data):
        for k, v in data.items():
            if k in POSTPROCESS_MAP:
                v = POSTPROCESS_MAP[k](v)
            self.state[k] = v

        await self._ha_postprocess()

    async def on_message(self, data):
        try:
            self.state["type"] = data["type"]
        except Exception:
            pass

        if data["type"] == "LOGGED_IN":
            _LOGGER.debug("Client connected and authenticated")
            await self._postprocess_and_update({
                "machineID": data["loggedinToMachineId"]
            })

            return

        elif data["type"] == "READ" and "readValues" in data:
            _LOGGER.debug("readValues: %s", data)
            values = data["readValues"]
            await self._postprocess_and_update(values)

        elif data["type"] == "VALUE_CHANGED" and "changedValues" in data:
            _LOGGER.debug("changedValues: %s", data)
            values = data["changedValues"]
            await self._postprocess_and_update(values)

        elif data["type"] == "ERROR":
            _LOGGER.error(data)
            await self.on_error(data)
        else:
            _LOGGER.warning("The read commend is not implemented correctly: %s", data)

    async def on_error(self, err):
        _LOGGER.error(err)
        self.state["type"] = "ERROR"
        self.state["errorTypeId"] = err["errorTypeId"]

    async def on_close(self):
        self._e_auth_ok.clear()

    async def on_open(self):
        pass

    async def login(self, iam_id=None, password=None):
        """Send login string."""
        iam_id = iam_id if iam_id else self._iam_id
        password = password if password else self._password

        self._e_wait_message.clear()
        await self.send(login(iam_id, password))

        await self._e_wait_message.wait()

        # Error occured during authentication
        if self.state["type"] == "ERROR":

            if self.state["errorTypeId"] == "WRONG_PASSWORD":
                raise InvalidPasswordError("Incorrect password")
            elif self.state["errorTypeId"] == "ACCESS_DENIED_SEVERE":
                raise InvalidIAMError("Incorrect IAM")
            elif self.state["errorTypeId"] == "UNIT_NOT_CONNECTED":
                raise InvalidDeviceError("Incorrect device")
            raise UnknownError("An error occured during login.")

        self._e_auth_ok.set()
        return self.state  # {"title": data["loggedinToMachineId"]} if is_logged_in else False

    async def set_temperature(self, value):
        """Set the temperature of the ventilation unit."""
        await self.send(write(main_temperature_offset=int(value * 10)))

    async def set_manual_mode(self):
        """Set the ventilation unit in manual mode."""
        await self.send(write(mode_change_request="1"))

    async def set_crowded_mode(self):
        """Set the ventilation unit in crowded mode."""
        await self.send(write(
            user_mode_crowded_duration=8,
            mode_change_request="2"
        ))

    async def set_refresh_mode(self):
        """Set the ventilation unit in refresh mode."""
        await self.send(write(
            user_mode_refresh_duration=240,
            mode_change_request="3"
        ))

    async def set_fireplace_mode(self):
        """Set the ventilation unit in fireplace mode."""
        await self.send(write(
            user_mode_fireplace_duration=60,
            mode_change_request="4"
        ))

    async def set_holiday_mode(self):
        """Set the ventilation unit in holiday mode."""
        await self.send(write(
            user_mode_holiday_duration=365,
            mode_change_request="6"
        ))

    async def set_auto_mode(self):
        """Set the ventilation unit in auto mode."""
        await self.send(write(mode_change_request="0"))

    async def set_away_mode(self):
        """Set the ventilation unit in away mode."""
        await self.send(write(
            user_mode_away_duration=72,
            mode_change_request="5"
        ))

    async def set_fan_off(self):
        """Set the fan speed to off."""
        await self.send(write(main_airflow="1"))

    async def set_fan_low(self):
        """Set the fan speed to low."""
        await self.send(write(main_airflow="2"))

    async def set_fan_normal(self):
        """Set the fan speed to normal."""
        await self.send(write(main_airflow="3"))

    async def set_fan_high(self):
        """Set the fan speed to high."""
        await self.send(write(main_airflow="4"))

    async def set_operation_mode(self, opmode):
        if opmode not in self._opmode:
            raise SaveAPI.OpmodeDoesNotExistsError("The opmode %s does not exists" % opmode)

        await self._opmode[opmode]()

    async def set_fan_mode(self, fan_mode):
        if fan_mode not in self._fan_mode:
            raise SaveAPI.FanmodeDoesNotExistsError("The fanmode %s does not exists" % fan_mode)

        await self._fan_mode[fan_mode]()

    async def set(self, k, value):
        if k == SENSOR_TARGET_TEMPERATURE:
            await self.set_temperature(value)
        elif k == SENSOR_MODE_CHANGE_REQUEST:
            await self.set_operation_mode(value)
        elif k == SENSOR_CURRENT_FAN_MODE:
            await self.set_fan_mode(value)
        elif k == SENSOR_CUSTOM_OPERATION:

            if value == SA_OPERATION_MODE_OFF:
                await self.set_manual_mode()
                await self.set_fan_off()
            elif value == SA_OPERATION_MODE_AUTO:
                await self.set_auto_mode()

    def get_current_operation(self):
        if SENSOR_CURRENT_OPERATION not in self.state:
            return None

        if self.state[SENSOR_CURRENT_OPERATION] is None:
            return None

        opcode = int(self.state[SENSOR_CURRENT_OPERATION])

        try:
            return USER_MODE[opcode]
        except KeyError:
            return None
