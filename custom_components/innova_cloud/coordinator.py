"""Coordinator: keeps device state in sync via gRPC events, with polling as a fallback."""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import InnovaApiError, InnovaAuthError, InnovaGrpcClient, InnovaRestClient
from .api.messages import DeviceEvent
from .api.models import (
    DEVICE_KIND_UNKNOWN,
    DeviceInfo,
    DeviceState,
    HomeInfo,
    NodeError,
    ResponseErrorCode,
    mac_to_bytes,
    mac_to_str,
    uuid_to_bytes,
)
from .const import (
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_TOKEN,
    DOMAIN,
    HOMES_REFRESH_INTERVAL,
    POLL_INTERVAL,
    POST_COMMAND_REFRESH_DELAY,
)

_LOGGER = logging.getLogger(__name__)


class InnovaCoordinator(DataUpdateCoordinator[dict[str, DeviceState]]):
    """One coordinator per config entry (= one Innova account)."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, rest: InnovaRestClient, grpc_client: InnovaGrpcClient) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=POLL_INTERVAL, config_entry=entry)
        self.rest = rest
        self.grpc = grpc_client
        self.homes: dict[str, HomeInfo] = {}
        self.devices: dict[str, DeviceInfo] = {}
        self._homes_loaded_at: datetime | None = None
        self._stream_tasks: dict[str, asyncio.Task] = {}
        self._refresh_handles: dict[str, asyncio.TimerHandle] = {}
        self._relogin_lock = asyncio.Lock()
        self.stream_connected: bool = False

    # ------------------------------------------------------------------ setup / auth

    async def async_initialize(self) -> None:
        """Validate the token (re-login with stored credentials if needed) and load homes."""
        await self._with_auth_retry(self._load_homes)

    async def _try_relogin(self) -> bool:
        email = self.config_entry.data.get(CONF_EMAIL)
        password = self.config_entry.data.get(CONF_PASSWORD)
        if not email or not password:
            return False
        async with self._relogin_lock:
            try:
                token = await self.rest.login(email, password)
            except InnovaApiError as err:
                _LOGGER.warning("Re-login failed: %s", err)
                return False
            self.hass.config_entries.async_update_entry(self.config_entry, data={**self.config_entry.data, CONF_TOKEN: token})
            _LOGGER.info("Innova session token renewed")
            return True

    async def _with_auth_retry(self, func, *args):
        try:
            return await func(*args)
        except InnovaAuthError:
            if await self._try_relogin():
                return await func(*args)
            raise

    async def _load_homes(self) -> None:
        homes = await self.rest.get_homes()
        self.homes = {home.id: home for home in homes}
        self.devices = {dev.key: dev for home in homes for dev in home.devices}
        self._homes_loaded_at = dt_util.utcnow()
        _LOGGER.debug("Loaded %d home(s), %d device(s)", len(self.homes), len(self.devices))

    async def async_shutdown(self) -> None:
        for task in self._stream_tasks.values():
            task.cancel()
        for handle in self._refresh_handles.values():
            handle.cancel()
        self._stream_tasks.clear()
        self._refresh_handles.clear()
        await self.grpc.close()
        await super().async_shutdown()

    # ------------------------------------------------------------------ polling

    async def _async_update_data(self) -> dict[str, DeviceState]:
        if self._homes_loaded_at is None or dt_util.utcnow() - self._homes_loaded_at > HOMES_REFRESH_INTERVAL:
            try:
                await self._with_auth_retry(self._load_homes)
            except InnovaAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except InnovaApiError as err:
                _LOGGER.debug("Could not refresh homes: %s", err)

        data: dict[str, DeviceState] = dict(self.data or {})
        errors: list[str] = []
        # One get_state per gateway (MAC); the reply carries every node behind it.
        for mac in {dev.mac for dev in self.devices.values()}:
            try:
                await self._with_auth_retry(self._refresh_gateway, mac, data)
            except InnovaAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except InnovaApiError as err:
                errors.append(f"{mac}: {err}")
        if errors and not data:
            raise UpdateFailed("; ".join(errors))
        if errors:
            _LOGGER.debug("Partial state refresh: %s", "; ".join(errors))
        return data

    async def _refresh_gateway(self, mac: str, data: dict[str, DeviceState]) -> None:
        response = await self.grpc.get_state(mac_to_bytes(mac), 0)
        if response.error_code is not None:
            # CACHE_NOT_READY / RESPONSE_TIMEOUT: the unit is offline or just booted.
            _LOGGER.debug("get_state %s error: %s %s", mac, response.error_code.name, response.error_message)
            for key, dev in self.devices.items():
                if dev.mac == mac:
                    state = data.setdefault(key, DeviceState())
                    state.online = response.error_code != ResponseErrorCode.RESPONSE_TIMEOUT and state.kind != DEVICE_KIND_UNKNOWN
            return
        for node_id, node_state in response.nodes.items():
            key = f"{mac}/{node_id}"
            existing = data.get(key)
            if existing is not None and node_state.kind == DEVICE_KIND_UNKNOWN and node_state.node_error is not None:
                existing.node_error = node_state.node_error
                existing.online = node_state.node_error != NodeError.OFFLINE
                continue
            if existing is not None and node_state.kind != DEVICE_KIND_UNKNOWN:
                node_state.gateway = existing.gateway
            node_state.online = node_state.node_error != NodeError.OFFLINE
            if response.gateway is not None:
                node_state.gateway = response.gateway
            data[key] = node_state
            if key not in self.devices:
                _LOGGER.debug("State for unknown node %s (not in /homes)", key)

    # ------------------------------------------------------------------ event stream

    def start_event_stream(self) -> None:
        for home_id in self.homes:
            if home_id not in self._stream_tasks:
                self._stream_tasks[home_id] = self.config_entry.async_create_background_task(
                    self.hass, self._run_stream(home_id), name=f"innova_cloud events {home_id}"
                )

    async def _run_stream(self, home_id: str) -> None:
        backoff = 5.0
        while True:
            try:
                _LOGGER.debug("Subscribing to events for home %s", home_id)
                async for event in self.grpc.subscribe_events(uuid_to_bytes(home_id)):
                    if not self.stream_connected:
                        self.stream_connected = True
                        backoff = 5.0
                    self._handle_event(event)
                _LOGGER.debug("Event stream for %s ended", home_id)
            except asyncio.CancelledError:
                raise
            except InnovaAuthError as err:
                self.stream_connected = False
                if await self._try_relogin():
                    continue
                _LOGGER.warning("Event stream authentication failed: %s", err)
                self.config_entry.async_start_reauth(self.hass)
                return
            except InnovaApiError as err:
                self.stream_connected = False
                _LOGGER.debug("Event stream error: %s", err)
            except Exception:  # noqa: BLE001
                self.stream_connected = False
                _LOGGER.exception("Unexpected error in event stream")
            await asyncio.sleep(backoff + random.uniform(0, 2))
            backoff = min(backoff * 2, 300.0)

    def _handle_event(self, event: DeviceEvent) -> None:
        mac = mac_to_str(event.mac) if event.mac else None
        if not mac:
            return
        node_id = event.node_id if event.node_id is not None else 0
        key = f"{mac}/{node_id}"
        data = dict(self.data or {})
        state = data.get(key)
        if state is None:
            state = DeviceState()
            data[key] = state
        if event.connection is not None:
            for k, s in data.items():
                if k.startswith(f"{mac}/"):
                    s.online = event.connection
            if event.connection:
                self._schedule_refresh(mac)
        if event.patch is not None:
            state.apply_event(event.patch)
            state.online = True
        _LOGGER.debug("Event %s: %s", key, event.raw)
        self.async_set_updated_data(data)

    # ------------------------------------------------------------------ commands

    async def async_send_request(self, device_key: str, request: bytes) -> None:
        dev = self.devices[device_key]
        try:
            raw = await self._with_auth_retry(self.grpc.send_device, mac_to_bytes(dev.mac), dev.node_id, request)
        except InnovaAuthError:
            self.config_entry.async_start_reauth(self.hass)
            raise
        _LOGGER.debug("SendDevice %s -> %s", device_key, raw.hex() if raw else "<empty>")
        self._schedule_refresh(dev.mac)

    def _schedule_refresh(self, mac: str) -> None:
        handle = self._refresh_handles.pop(mac, None)
        if handle:
            handle.cancel()
        self._refresh_handles[mac] = self.hass.loop.call_later(
            POST_COMMAND_REFRESH_DELAY, lambda: self.hass.async_create_task(self._refresh_one(mac))
        )

    async def _refresh_one(self, mac: str) -> None:
        self._refresh_handles.pop(mac, None)
        data = dict(self.data or {})
        try:
            await self._with_auth_retry(self._refresh_gateway, mac, data)
        except InnovaApiError as err:
            _LOGGER.debug("Post-command refresh failed for %s: %s", mac, err)
            return
        self.async_set_updated_data(data)

    # ------------------------------------------------------------------ helpers

    def get_state(self, device_key: str) -> DeviceState | None:
        return (self.data or {}).get(device_key)
