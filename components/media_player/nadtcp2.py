"""
Support for NAD digital amplifiers which can be remote controlled via tcp/ip.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/media_player.nadtcp/
"""
import logging
import voluptuous as vol
from homeassistant.components.media_player import (
    SUPPORT_VOLUME_SET,
    SUPPORT_VOLUME_MUTE, SUPPORT_TURN_ON, SUPPORT_TURN_OFF,
    SUPPORT_VOLUME_STEP, SUPPORT_SELECT_SOURCE, MediaPlayerDevice,
    PLATFORM_SCHEMA)
from homeassistant.const import (
    CONF_NAME, STATE_OFF, STATE_ON, EVENT_HOMEASSISTANT_STOP)
from homeassistant.core import CoreState, callback
import homeassistant.helpers.config_validation as cv
import async_timeout
import asyncio

REQUIREMENTS = ['nadtcp']

_LOGGER = logging.getLogger(__name__)

DEFAULT_RECONNECT_INTERVAL = 10
CONNECTION_TIMEOUT = 10
DEFAULT_NAME = 'NAD amplifier'
DEFAULT_MIN_VOLUME = -60
DEFAULT_MAX_VOLUME = -10
DEFAULT_VOLUME_STEP = 4

SUPPORT_NAD = SUPPORT_VOLUME_SET | SUPPORT_VOLUME_MUTE | SUPPORT_TURN_ON | \
              SUPPORT_TURN_OFF | SUPPORT_VOLUME_STEP | SUPPORT_SELECT_SOURCE

CONF_MIN_VOLUME = 'min_volume'
CONF_MAX_VOLUME = 'max_volume'
CONF_VOLUME_STEP = 'volume_step'
CONF_RECONNECT_INTERVAL = 'reconnect_interval'
CONF_HOST = 'host'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_RECONNECT_INTERVAL, default=DEFAULT_RECONNECT_INTERVAL): int,
    vol.Optional(CONF_MIN_VOLUME, default=DEFAULT_MIN_VOLUME): int,
    vol.Optional(CONF_MAX_VOLUME, default=DEFAULT_MAX_VOLUME): int,
    vol.Optional(CONF_VOLUME_STEP, default=DEFAULT_VOLUME_STEP): int,
})


@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    """Setup the NAD platform."""
    from nadtcp import NADC338Protocol

    async_add_devices([NADDevice(
        NADC338Protocol,
        config.get(CONF_NAME),
        config.get(CONF_HOST),
        config.get(CONF_RECONNECT_INTERVAL),
        config.get(CONF_MIN_VOLUME),
        config.get(CONF_MAX_VOLUME),
        config.get(CONF_VOLUME_STEP),
    )])

    return True


class NADDevice(MediaPlayerDevice):
    """Device handler for the NAD protocol"""

    def __init__(self, protocol_class, name, host, reconnect_interval, min_volume, max_volume, volume_step):
        """Initialize the device properties"""
        self._protocol_class = protocol_class
        self._protocol = None
        self._name = name
        self._host = host
        self._reconnect_interval = reconnect_interval
        self._min_vol = min_volume
        self._max_vol = max_volume
        self._volume_step = volume_step
        self._power = None
        self._muted = None
        self._volume = None
        self._source = None

    def nad_vol_to_internal_vol(self, nad_volume):
        """Convert the configured volume range to internal volume range.
        Takes into account configured min and max volume.
        """
        if nad_volume is None:
            volume_internal = 0.0
        elif nad_volume < self._min_vol:
            volume_internal = 0.0
        elif nad_volume > self._max_vol:
            volume_internal = 1.0
        else:
            volume_internal = (nad_volume - self._min_vol) / \
                              (self._max_vol - self._min_vol)
        return volume_internal

    def set_protocol(self, protocol):
        """Sets the associated NAD protocol for the device"""
        self._protocol = protocol

    def is_connected(self):
        """Return whether the protocol is connected"""
        return self._protocol is not None

    def message_received(self, key, value):
        """Handle the received messages"""
        if key == 'Main.Volume':
            self._volume = value
        elif key == 'Main.Power':
            self._power = value
        elif key == 'Main.Mute':
            self._muted = value
        elif key == 'Main.Source':
            self._source = value

        self.hass.async_run_job(self.async_update_ha_state())

    @property
    def should_poll(self):
        """No polling needed."""
        return False

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def state(self):
        """Return the state of the device."""
        if self.is_connected():
            return STATE_ON if self._power == self._protocol.MSG_ON else STATE_OFF
        else:
            return STATE_OFF

    @property
    def source(self):
        """Name of the current input source."""
        return self._source

    @property
    def source_list(self):
        """List of available input sources."""
        if self.is_connected():
            return self._protocol.get_available_sources()
        else:
            return []

    @property
    def volume_level(self):
        """Volume level of the media player (0..1)."""
        return self.nad_vol_to_internal_vol(self._volume)

    @property
    def is_volume_muted(self):
        """Boolean if volume is currently muted."""
        if self.is_connected():
            return self._muted == self._protocol.MSG_ON
        else:
            return False

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        return SUPPORT_NAD

    @asyncio.coroutine
    def async_turn_off(self):
        """Turn the media player off."""
        if self.is_connected():
            self._protocol.set_value(self._protocol.MSG_POWER, self._protocol.MSG_OFF)

    @asyncio.coroutine
    def async_turn_on(self):
        """Turn the media player on."""
        if self.is_connected():
            self._protocol.set_value(self._protocol.MSG_POWER, self._protocol.MSG_ON)

    @asyncio.coroutine
    def async_volume_up(self):
        """Step volume up in the configured increments."""
        if self.is_connected():
            self._protocol.cycle_up(self._protocol.MSG_VOLUME)

    @asyncio.coroutine
    def async_volume_down(self):
        """Step volume down in the configured increments."""
        if self.is_connected():
            self._protocol.cycle_down(self._protocol.MSG_VOLUME)

    @asyncio.coroutine
    def async_set_volume_level(self, volume):
        """Set volume level, range 0..1."""
        if self.is_connected():
            nad_volume_to_set = \
                int(round(volume * (self._max_vol - self._min_vol) +
                          self._min_vol))
            self._protocol.set_value(self._protocol.MSG_VOLUME, nad_volume_to_set)

    @asyncio.coroutine
    def async_mute_volume(self, mute):
        """Mute (true) or unmute (false) media player."""
        if self.is_connected():
            if mute:
                self._protocol.set_value(self._protocol.MSG_MUTE, self._protocol.MSG_ON)
            else:
                self._protocol.set_value(self._protocol.MSG_MUTE, self._protocol.MSG_OFF)

    @asyncio.coroutine
    def async_select_source(self, source):
        """Select input source."""
        if self.is_connected():
            self._protocol.set_value(self._protocol.MSG_SOURCE, source)

    @asyncio.coroutine
    def async_update(self):
        """Get the latest details from the device."""
        if self.is_connected():
            self._protocol.get_value(self._protocol.MSG_MAIN)

    @asyncio.coroutine
    def async_added_to_hass(self):
        def reconnect(exc=None):
            self.set_protocol(None)

            if self.hass.state != CoreState.stopping:
                _LOGGER.warning('Disconnected from %s, reconnecting', self._host)
                self.hass.async_add_job(connect)

        @callback
        def message_received(key, value):
            _LOGGER.debug('Got event from %s, key %s, value %s', self._host, key, value)
            self.message_received(key, value)

        @asyncio.coroutine
        def connect():
            _LOGGER.info('Initiating connection to %s', self._host)

            connection = self._protocol_class.create_nad_connection(loop=self.hass.loop,
                                                                    target_ip=self._host,
                                                                    disconnect_callback=reconnect,
                                                                    message_received_callback=message_received)

            try:
                with async_timeout.timeout(CONNECTION_TIMEOUT,
                                           loop=self.hass.loop):
                    transport, protocol = yield from connection
            except (ConnectionRefusedError,
                    TimeoutError, OSError, asyncio.TimeoutError) as exc:
                _LOGGER.exception(
                    "Error connecting to %s, reconnecting in %s", self._host,
                    self._reconnect_interval)
                self.hass.loop.call_later(self._reconnect_interval, reconnect, exc)
                return

            self.set_protocol(protocol)

            self.hass.async_add_job(self.async_update)

            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP,
                                            lambda x: transport.close())

            return True

        self.hass.async_add_job(connect)
