"""Dreame cloud REST client: authentication, device discovery and commands."""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from collections.abc import Mapping
from typing import Any

import requests

from .const import (
    API_CODE_DEVICE_OFFLINE,
    API_CODE_OK,
    AUTH_PATH,
    BATCH_DATA_PATH,
    CLIENT_BASIC_AUTH,
    CLOUD_HOSTS,
    CLOUD_PORT,
    CN_RLC_HEADER,
    DEFAULT_TIMEOUT,
    DEVICE_INFO_PATH,
    DEVICE_LIST_PATH,
    DEVICE_PERMIT_PATH,
    OTA_STATUS_PATH,
    OTA_UPDATE_PATH,
    PASSWORD_SALT,
    PROPS_PATH,
    READ_RETRY_DELAYS,
    REGIONS,
    TENANT_IDS,
    USER_AGENTS,
)
from .exceptions import (
    DreameApiError,
    DreameAuthError,
    DreameCommandRejectedError,
    DreameConnectionError,
)
from .models import DeviceDescriptor

_LOGGER = logging.getLogger(__name__)


class DreameCloud:
    """Blocking HTTP client for the Dreame vendor cloud.

    Every call is synchronous; Home Assistant runs it in an executor.
    """

    def __init__(
        self,
        username: str,
        password: str,
        region: str = "eu",
        account_type: str = "dreame",
    ) -> None:
        if region not in REGIONS:
            raise ValueError(f"Unsupported region: {region}")
        if account_type not in CLOUD_HOSTS:
            raise ValueError(f"Unsupported account type: {account_type}")
        self.username = username
        self.password = password
        self.region = region
        self.account_type = account_type
        self.base_url = f"https://{region}.{CLOUD_HOSTS[account_type]}:{CLOUD_PORT}"

        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.user_id: str = ""
        self.tenant_id: str = TENANT_IDS[account_type]
        self._expires_at: float = 0.0

        # Device identity, filled in by attach_device().
        self.did: str = ""
        self.model: str = ""
        self.host: str = ""
        self.uid: str = ""
        self._command_id = random.randint(1, 100)
        self._session = requests.Session()

    # -- auth ---------------------------------------------------------------

    def _headers(self, *, authenticated: bool) -> dict[str, str]:
        headers = {
            "Accept": "*/*",
            "Content-Type": "application/json",
            "Accept-Language": "en-US;q=0.8",
            "User-Agent": USER_AGENTS[self.account_type],
            "Authorization": CLIENT_BASIC_AUTH,
            "Tenant-Id": self.tenant_id or TENANT_IDS[self.account_type],
        }
        if self.region == "cn":
            headers["Dreame-Rlc"] = CN_RLC_HEADER
        if authenticated and self.access_token:
            headers["Dreame-Auth"] = self.access_token
        return headers

    @staticmethod
    def hash_password(password: str) -> str:
        """Return the vendor's salted MD5 digest of an account password."""
        return hashlib.md5(  # noqa: S324 - vendor protocol requires MD5
            (password + PASSWORD_SALT).encode()
        ).hexdigest()

    @property
    def logged_in(self) -> bool:
        """Return whether a non-expired access token is held."""
        return bool(self.access_token) and time.time() < self._expires_at

    def login(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        """Obtain an access token, refreshing it when possible."""
        if self.refresh_token:
            body = (
                "platform=IOS&scope=all&grant_type=refresh_token&refresh_token="
                f"{self.refresh_token}"
            )
        else:
            body = (
                "platform=IOS&scope=all&grant_type=password"
                f"&username={self.username}"
                f"&password={self.hash_password(self.password)}&type=account"
            )

        data = self._post_form(AUTH_PATH, body, timeout=timeout)
        if "error_description" in data:
            message = str(data["error_description"])
            if "refresh token" in message:
                # The stored refresh token died; start over with the password.
                self.refresh_token = None
                return self.login(timeout=timeout)
            raise DreameAuthError(message)
        if not data.get("access_token"):
            raise DreameAuthError("Cloud login returned no access token")

        self.access_token = data["access_token"]
        self.refresh_token = data.get("refresh_token")
        self.user_id = str(data.get("uid") or "")
        self.tenant_id = str(data.get("tenant_id") or self.tenant_id)
        self._expires_at = time.time() + float(data.get("expires_in") or 3600) - 120

    def _ensure_login(self) -> None:
        if not self.logged_in:
            self.login()

    def _post_form(self, path: str, body: str, timeout: float) -> dict[str, Any]:
        try:
            response = self._session.post(
                f"{self.base_url}{path}",
                data=body,
                headers={
                    **self._headers(authenticated=False),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=timeout,
            )
        except requests.RequestException as err:
            raise DreameConnectionError(f"Cloud request to {path} failed: {err}") from err
        if response.status_code == 401:
            raise DreameAuthError("Cloud rejected the stored session")
        return _json_or_raise(response, path)

    def _post(
        self,
        path: str,
        payload: Mapping[str, Any],
        timeout: float = DEFAULT_TIMEOUT,
        *,
        retries: int = 0,
    ) -> Any:
        self._ensure_login()
        body = json.dumps(payload, separators=(",", ":"))
        last: Exception | None = None
        # A 401 proves the cloud rejected the request before it reached the
        # device, so re-authenticating and sending it once more is always safe --
        # including for mutations, which otherwise never retry.
        reauthenticated = False
        attempts = retries + 2
        for attempt in range(attempts):
            try:
                response = self._session.post(
                    f"{self.base_url}{path}",
                    data=body.encode(),
                    headers=self._headers(authenticated=True),
                    timeout=timeout,
                )
            except requests.RequestException as err:
                last = DreameConnectionError(f"Cloud request to {path} failed: {err}")
            else:
                if response.status_code == 401 and not reauthenticated:
                    self.access_token = None
                    self.login(timeout=timeout)
                    reauthenticated = True
                    last = DreameAuthError("Cloud session expired during request")
                    continue
                return _json_or_raise(response, path, raise_on_error=False)
            if attempt < retries:
                time.sleep(READ_RETRY_DELAYS[min(attempt, len(READ_RETRY_DELAYS) - 1)])
        raise last or DreameConnectionError(f"Cloud request to {path} failed")

    # -- discovery ----------------------------------------------------------

    def list_devices(self, timeout: float = DEFAULT_TIMEOUT) -> list[DeviceDescriptor]:
        """Return every robotic mower bound to the account."""
        self._ensure_login()
        raw = self._post(DEVICE_LIST_PATH, {"current": 1, "size": 50}, timeout)
        records = raw
        if isinstance(raw, Mapping):
            page = raw.get("page")
            if isinstance(page, Mapping) and isinstance(page.get("records"), list):
                records = page["records"]
        if not isinstance(records, list):
            raise DreameConnectionError("Device list response had no records")

        devices: list[DeviceDescriptor] = []
        for record in records:
            if not isinstance(record, Mapping):
                continue
            model = str(record.get("model") or "")
            if ".mower." not in model:
                continue  # vacuums, air purifiers, fans share this cloud
            devices.append(
                DeviceDescriptor(
                    did=str(record.get("did") or ""),
                    model=model,
                    mac=str(record.get("mac") or ""),
                    name=str(record.get("customName") or "").strip(),
                    host=str(record.get("bindDomain") or record.get("localip") or ""),
                    uid=str(record.get("masterUid") or ""),
                    account_type=self.account_type,
                    region=self.region,
                    firmware=str(record.get("ver") or ""),
                )
            )
        return sorted(devices, key=lambda d: d.name.lower())

    def attach(self, descriptor: DeviceDescriptor) -> None:
        """Bind this client to one device and learn its MQTT broker."""
        self.did = descriptor.did
        self.model = descriptor.model
        self.uid = descriptor.uid
        self.host = descriptor.host
        if self.uid and self.host:
            return
        data = self._post(DEVICE_INFO_PATH, {"did": self.did})
        info = data.get("data") if isinstance(data, Mapping) else None
        info = info if isinstance(info, Mapping) else {}
        self.uid = str(info.get("masterUid") or self.uid)
        self.host = str(info.get("bindDomain") or self.host)
        self.model = str(info.get("model") or self.model)
        if not self.uid or not self.host:
            raise DreameConnectionError("Device is missing an MQTT broker in its cloud record")

    # -- reads --------------------------------------------------------------

    def get_properties(
        self, keys: list[str], timeout: float = DEFAULT_TIMEOUT
    ) -> dict[str, Any]:
        """Read cloud property values, keyed by ``"siid.piid"``."""
        raw = self._post(PROPS_PATH, {"did": self.did, "keys": keys}, timeout, retries=2)
        items = raw.get("data") if isinstance(raw, Mapping) else None
        if not isinstance(items, list):
            return {}
        result: dict[str, Any] = {}
        for item in items:
            if isinstance(item, Mapping) and "key" in item:
                result[str(item["key"])] = item.get("value")
        return result

    def get_batch_data(
        self, prefixes: list[str] | None = None, timeout: float = DEFAULT_TIMEOUT
    ) -> dict[str, str]:
        """Read the device's batch text payload, keyed by raw batch key."""
        raw = self._post(
            BATCH_DATA_PATH,
            {"did": self.did, "model": prefixes or []},
            timeout,
            retries=2,
        )
        data = raw.get("data") if isinstance(raw, Mapping) else None
        if not isinstance(data, Mapping):
            return {}
        return {
            str(key): value
            for key, value in data.items()
            if isinstance(value, (str, int, float))
        }

    def get_permissions(self, timeout: float = DEFAULT_TIMEOUT) -> Any:
        """Return the device's permission record, when the cloud exposes one."""
        raw = self._post(DEVICE_PERMIT_PATH, {"did": self.did}, timeout)
        return raw.get("data") if isinstance(raw, Mapping) else None

    def get_ota_status(self, timeout: float = DEFAULT_TIMEOUT) -> Any:
        """Return the OTA record used to drive the update entity."""
        raw = self._post(OTA_STATUS_PATH, {"did": self.did}, timeout)
        return raw.get("data") if isinstance(raw, Mapping) else None

    def install_firmware(self, timeout: float = DEFAULT_TIMEOUT) -> Any:
        """Ask the device to apply an available firmware update."""
        raw = self._post(OTA_UPDATE_PATH, {"did": self.did, "retry_count": 0}, timeout)
        return raw.get("data") if isinstance(raw, Mapping) else None

    # -- writes -------------------------------------------------------------

    def _send(self, method: str, params: Mapping[str, Any], retries: int = 0) -> Any:
        if not self.host:
            raise DreameConnectionError("No MQTT broker known for this device")
        self._command_id += 1
        command_id = self._command_id
        label = self.host.split(".")[0].split(":")[0]
        payload = {
            "did": self.did,
            "id": command_id,
            "data": {
                "did": self.did,
                "id": command_id,
                "method": method,
                "params": dict(params),
            },
        }
        raw = self._post(
            f"/dreame-iot-com-{label}/device/sendCommand",
            payload,
            retries=retries,
        )
        return _unwrap_result(raw)

    def set_property(self, siid: int, piid: int, value: Any) -> Any:
        """Write one legacy MIoT property."""
        return self._send(
            "set_properties",
            {"did": self.did, "siid": siid, "piid": piid, "value": value},
        )

    def action(self, siid: int, aiid: int, params: list[Any] | None = None) -> Any:
        """Invoke one legacy MIoT action."""
        return self._send(
            "action",
            {"did": self.did, "siid": siid, "aiid": aiid, "in": params or []},
        )

    def app_action(self, payload: Mapping[str, Any]) -> Any:
        """Send one app-bridge command.

        Reads (``m == "g"``) retry; mutations never do, because a duplicated
        write can change device state twice.
        """
        from .const import APP_ACTION_AIID, APP_ACTION_SIID

        return self._send(
            "action",
            {
                "did": self.did,
                "siid": APP_ACTION_SIID,
                "aiid": APP_ACTION_AIID,
                "in": [dict(payload)],
            },
            retries=2 if payload.get("m") == "g" else 0,
        )


def _json_or_raise(
    response: requests.Response, path: str, *, raise_on_error: bool = True
) -> Any:
    try:
        data = response.json()
    except ValueError as err:
        raise DreameConnectionError(
            f"Cloud returned non-JSON from {path}: {response.status_code}"
        ) from err
    if not isinstance(data, dict):
        raise DreameConnectionError(f"Cloud returned an unexpected body from {path}")
    if raise_on_error and data.get("code") not in (API_CODE_OK, None):
        raise DreameApiError(
            int(data["code"]),
            str(data.get("msg") or data.get("message") or ""),
        )
    return data


def _unwrap_result(raw: Any) -> Any:
    """Return the device answer inside a sendCommand envelope."""
    if not isinstance(raw, Mapping):
        return None
    code = raw.get("code")
    if code == API_CODE_DEVICE_OFFLINE:
        raise DreameCommandRejectedError("Device did not answer in time")
    if code not in (API_CODE_OK, None):
        raise DreameApiError(int(code), str(raw.get("msg") or raw.get("message") or ""))
    data = raw.get("data")
    if not isinstance(data, Mapping):
        return None
    return data.get("result")
