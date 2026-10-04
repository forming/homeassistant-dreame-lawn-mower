"""MQTT push channel for live mower telemetry."""

from __future__ import annotations

import json
import logging
import random
import ssl
import string
from collections.abc import Callable, Mapping
from importlib.resources import files
from typing import Any

import paho.mqtt.client as mqtt

from .const import (
    MQTT_KEEPALIVE,
    MQTT_RECONNECT_DELAY_MAX,
    MQTT_RECONNECT_DELAY_MIN,
)

_LOGGER = logging.getLogger(__name__)

_ROOT_CA = ("certs", "vendor_root_ca.pem")


def build_ssl_context() -> ssl.SSLContext:
    """Return a TLS context that trusts the broker's private root CA.

    The broker serves a chain rooted at GlobalSign Root CA, which is not in most
    system bundles. ``VERIFY_X509_STRICT`` is cleared because the vendor leaf
    omits the Authority Key Identifier; chain and hostname checks stay on.
    """
    context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    root = files(__package__).joinpath(*_ROOT_CA).read_text(encoding="ascii")
    context.load_verify_locations(cadata=root)
    return context


class RealtimeClient:
    """Subscribes to the vendor's push topic and hands decoded payloads up.

    The channel is subscribe-only: commands always travel over HTTPS.
    """

    def __init__(
        self,
        host: str,
        did: str,
        uid: str,
        model: str,
        region: str,
        username: str,
        password: str,
        *,
        on_message: Callable[[Mapping[str, Any]], None],
        on_state: Callable[[bool], None] | None = None,
    ) -> None:
        self._host, _, port = host.partition(":")
        self._username = username
        self._password = password
        self._topic = f"/status/{did}/{uid}/{model}/{region}/"
        self._on_message = on_message
        self._on_state = on_state
        self._client = self._build(uid, self._host)

        self._client.username_pw_set(username, password)
        self._client.tls_set_context(build_ssl_context())
        self._client.tls_insecure_set(False)
        self._client.reconnect_delay_set(MQTT_RECONNECT_DELAY_MIN, MQTT_RECONNECT_DELAY_MAX)

    def _build(self, uid: str, host: str) -> mqtt.Client:
        agent = "".join(random.choice(string.ascii_uppercase) for _ in range(13))
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"p_{uid}_{agent}_{host.split('.')[0]}",
            clean_session=True,
        )
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message_raw
        return client

    def _on_connect(self, client, _userdata, _flags, reason_code, _props=None) -> None:
        if reason_code == 0:
            client.subscribe(self._topic)  # QoS 0, matches the mobile app
            if self._on_state:
                self._on_state(True)
        else:
            _LOGGER.warning("Dreame push connection refused: %s", reason_code)
            if self._on_state:
                self._on_state(False)

    def _on_disconnect(self, _client, _userdata, _flags, reason_code, _props=None) -> None:
        if self._on_state:
            self._on_state(False)
        if reason_code == 5:
            # Bad credentials: the access token changed, so drop it and let the
            # owning device re-login on the next poll.
            self._password = ""

    def _on_message_raw(self, _client, _userdata, message) -> None:
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            _LOGGER.debug("Ignoring undecodable push payload")
            return
        data = payload.get("data") if isinstance(payload, Mapping) else None
        if isinstance(data, Mapping) and data:
            self._on_message(data)

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Connect and begin the network loop in a background thread."""
        self._client.connect(self._host, int(self._port or 8883), MQTT_KEEPALIVE)
        self._client.loop_start()

    def set_password(self, password: str) -> None:
        """Apply a refreshed access token to the next connection attempt."""
        if password and password != self._password:
            self._password = password
            self._client.username_pw_set(self._username, password)

    def stop(self) -> None:
        """Disconnect and stop the network loop."""
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:  # noqa: BLE001 - shutdown must never raise
            _LOGGER.debug("Ignoring error while stopping push client", exc_info=True)

    @property
    def connected(self) -> bool:
        """Return whether the push channel is currently usable."""
        return self._client.is_connected()
