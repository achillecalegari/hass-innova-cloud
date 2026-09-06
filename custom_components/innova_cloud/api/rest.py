"""REST client for the Innova app backend (``https://v2.api.innova.solutiontech.tech``).

Only the endpoints the integration needs are wrapped:

* ``POST /app/users/login`` ``{"email", "password"}`` -> JSON containing a JWT
* ``GET  /app/homes`` -> homes with rooms, devices and members (``Authorization: Bearer <jwt>``)

Error format: ``{"code": 1302, "message": "Authentication token is missing or invalid"}``.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import aiohttp

from .models import DeviceInfo, HomeInfo

DEFAULT_REST_BASE = "https://v2.api.innova.solutiontech.tech"
DEFAULT_GRPC_HOST = "v2.grpc.innova.solutiontech.tech"
DEFAULT_GRPC_PORT = 443

ERROR_CODE_AUTH = 1302
ERROR_CODE_INVALID_CREDENTIALS = 1304


class InnovaApiError(Exception):
    """Generic API failure."""

    def __init__(self, message: str, code: int | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class InnovaAuthError(InnovaApiError):
    """Token missing/expired or bad credentials."""


def decode_jwt_claims(token: str) -> dict[str, Any]:
    """Return the (unverified) claims of a JWT, or an empty dict."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:  # noqa: BLE001
        return {}


def _looks_like_jwt(value: Any) -> bool:
    return isinstance(value, str) and value.count(".") == 2 and value.startswith("eyJ")


def extract_token(payload: Any) -> str | None:
    """Find the JWT in a login response whatever the field is called."""
    if isinstance(payload, str):
        return payload if _looks_like_jwt(payload) else None
    if isinstance(payload, dict):
        for key in ("jwt", "accessToken", "access_token", "token", "idToken"):
            value = payload.get(key)
            if _looks_like_jwt(value):
                return value
        for value in payload.values():
            found = extract_token(value)
            if found:
                return found
    if isinstance(payload, list):
        for value in payload:
            found = extract_token(value)
            if found:
                return found
    return None


class InnovaRestClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: str | None = None,
        base_url: str = DEFAULT_REST_BASE,
    ) -> None:
        self._session = session
        self._base = base_url.rstrip("/")
        self.token = token

    # -- low level ---------------------------------------------------------------------

    async def _request(self, method: str, path: str, *, json_body: Any = None, auth: bool = True) -> Any:
        headers = {"Accept": "application/json; charset=utf-8"}
        if auth:
            if not self.token:
                raise InnovaAuthError("no token")
            headers["Authorization"] = f"Bearer {self.token}"
        url = f"{self._base}/app/{path.lstrip('/')}"
        try:
            async with self._session.request(
                method, url, json=json_body, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                text = await resp.text()
                data: Any = None
                if text:
                    try:
                        data = json.loads(text)
                    except ValueError:
                        data = text
                if resp.status == 401 or (isinstance(data, dict) and data.get("code") in (ERROR_CODE_AUTH, ERROR_CODE_INVALID_CREDENTIALS)):
                    message = data.get("message") if isinstance(data, dict) else "unauthorized"
                    raise InnovaAuthError(message or "unauthorized", code=data.get("code") if isinstance(data, dict) else None, status=resp.status)
                if resp.status >= 400:
                    message = data.get("message") if isinstance(data, dict) else str(data)
                    raise InnovaApiError(f"HTTP {resp.status}: {message}", code=data.get("code") if isinstance(data, dict) else None, status=resp.status)
                return data
        except aiohttp.ClientError as err:
            raise InnovaApiError(f"connection error: {err}") from err
        except TimeoutError as err:
            raise InnovaApiError(f"timeout calling {path}") from err

    # -- public ------------------------------------------------------------------------

    async def login(self, email: str, password: str) -> str:
        """Log in with email/password and store the returned JWT."""
        data = await self._request("POST", "users/login", json_body={"email": email, "password": password}, auth=False)
        token = extract_token(data)
        if not token:
            raise InnovaApiError(f"login succeeded but no token found in response: {data!r}")
        self.token = token
        return token

    async def get_homes_raw(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "homes")
        if not isinstance(data, list):
            raise InnovaApiError(f"unexpected /homes payload: {data!r}")
        return data

    async def get_homes(self) -> list[HomeInfo]:
        homes: list[HomeInfo] = []
        for raw in await self.get_homes_raw():
            rooms = {room.get("id"): room.get("name") for room in raw.get("rooms", []) or []}
            home = HomeInfo(id=str(raw.get("id")), name=raw.get("name") or "Home", timezone=raw.get("timezone"))
            for dev in raw.get("devices", []) or []:
                uid = dev.get("uid") or {}
                mac = str(dev.get("macAddress") or "").upper()
                if len(mac.replace(":", "").replace("-", "")) != 12:
                    continue  # not a controllable unit (or a malformed entry)
                home.devices.append(
                    DeviceInfo(
                        home_id=home.id,
                        mac=mac,
                        node_id=int(dev.get("nodeId") or 0),
                        name=dev.get("name") or dev.get("macAddress") or "Innova",
                        vendor_id=uid.get("vendorId"),
                        product_id=uid.get("productId"),
                        hw_revision=uid.get("hwRevision"),
                        serial_number=dev.get("serialNumber"),
                        room_id=dev.get("roomId"),
                        room_name=rooms.get(dev.get("roomId")),
                    )
                )
            homes.append(home)
        return homes
