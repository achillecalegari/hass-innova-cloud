"""Coordinator: keeps device state in sync via gRPC events, with polling as a fallback.

Resilience strategy (see docs/ROBUSTNESS.md):

* live updates come from one ``SubscribeEvents`` stream per home; the stream is restarted with
  exponential backoff that resets as soon as a connection is accepted, and a full state refresh
  is requested after every reconnect so nothing missed during the gap is lost;
* a full ``get_state`` poll every ``POLL_INTERVAL`` covers anything the stream did not deliver;
  gateways are polled concurrently and a failure on one never affects the others;
* the home layout is re-read periodically: new homes get a stream, removed homes lose it,
  removed devices are dropped from the state and from the device registry;
* authentication errors go through a single choke point: re-login with stored credentials when
  possible, otherwise Home Assistant's reauth flow is started exactly once;
* every timer and task is owned by the config entry so reloads and shutdowns are clean.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_call_later
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

STREAM_BACKOFF_MIN = 5.0
STREAM_BACKOFF_MAX = 300.0
# Consecutive UNAUTHENTICATED stream failures (after a successful re-login) before giving up
# and asking the user to re-authenticate.
STREAM_AUTH_FAILURES_MAX = 3
# Do not re-login more often than this, whatever the trigger.
RELOGIN_MIN_INTERVAL = 60.0


class InnovaCoordinator(DataUpdateCoordinator[dict[str, DeviceState]]):
    """One coordinator per config entry (= one Innova account)."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, rest: InnovaRestClient, grpc_client: InnovaGrpcClient) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=POLL_INTERVAL, config_entry=entry)
        self.rest = rest
        self.grpc = grpc_client
        self.homes: dict[str, HomeInfo] = {}
        self.devices: dict[str, DeviceInfo] = {}
        self.stream_connected: bool = False
        self._homes_loaded_at: datetime | None = None
        self._stream_tasks: dict[str, asyncio.Task] = {}
        self._refresh_cancels: dict[str, CALLBACK_TYPE] = {}
        self._relogin_lock = asyncio.Lock()
        self._last_relogin: float = 0.0
        self._reauth_started = False
        self._stream_ever_connected = False
        self._stopped = False

    # ------------------------------------------------------------------ setup / teardown

    async def async_initialize(self) -> None:
        """Validate the token (re-login with stored credentials if needed) and load homes."""
        await self._with_auth_retry(self._load_homes)

    async def async_shutdown(self) -> None:
        self._stopped = True
        for cancel in self._refresh_cancels.values():
            cancel()
        self._refresh_cancels.clear()
        for task in self._stream_tasks.values():
            task.cancel()
        self._stream_tasks.clear()
        await self.grpc.close()
        await super().async_shutdown()

    # ------------------------------------------------------------------ auth

    async def _try_relogin(self) -> bool:
        """Renew the token with the stored credentials. Rate limited; False if impossible."""
        email = self.config_entry.data.get(CONF_EMAIL)
        password = self.config_entry.data.get(CONF_PASSWORD)
        if not email or not password:
            return False
        async with self._relogin_lock:
            now = self.hass.loop.time()
            if now - self._last_relogin < RELOGIN_MIN_INTERVAL:
                # Somebody else just renewed the token (or it just failed): reuse the outcome.
                return bool(self.rest.token) and self._last_relogin_ok
            self._last_relogin = now
            try:
                token = await self.rest.login(email, password)
            except InnovaApiError as err:
                self._last_relogin_ok = False
                _LOGGER.warning("Re-login failed: %s", err)
                return False
            self._last_relogin_ok = True
            # Persist the new token. There is no update listener, so this does not reload the entry.
            self.hass.config_entries.async_update_entry(self.config_entry, data={**self.config_entry.data, CONF_TOKEN: token})
            _LOGGER.info("Innova session token renewed")
            return True

    _last_relogin_ok: bool = False

    def _start_reauth_once(self) -> None:
        if not self._reauth_started:
            self._reauth_started = True
            self.config_entry.async_start_reauth(self.hass)

    async def _with_auth_retry(self, func: Callable[..., Awaitable[Any]], *args: Any) -> Any:
        """Run ``func``; on an auth error try one re-login and retry, else raise ConfigEntryAuthFailed."""
        try:
            return await func(*args)
        except InnovaAuthError as err:
            if await self._try_relogin():
                try:
                    return await func(*args)
                except InnovaAuthError as err2:
                    self._start_reauth_once()
                    raise ConfigEntryAuthFailed(str(err2)) from err2
            self._start_reauth_once()
            raise ConfigEntryAuthFailed(str(err)) from err

    # ------------------------------------------------------------------ homes / devices

    async def _load_homes(self) -> None:
        homes = await self.rest.get_homes()
        self.homes = {home.id: home for home in homes}
        self.devices = {dev.key: dev for home in homes for dev in home.devices}
        self._homes_loaded_at = dt_util.utcnow()
        _LOGGER.debug("Loaded %d home(s), %d device(s)", len(self.homes), len(self.devices))
        self._sync_streams()
        self._prune_removed_devices()

    def _prune_removed_devices(self) -> None:
        """Forget state and registry entries of devices that disappeared from the account."""
        if self.data:
            for key in [k for k in self.data if k not in self.devices]:
                _LOGGER.info("Device %s is no longer in the Innova account, removing it", key)
                self.data.pop(key, None)
        registry = dr.async_get(self.hass)
        for device in dr.async_entries_for_config_entry(registry, self.config_entry.entry_id):
            keys = {identifier[1] for identifier in device.identifiers if identifier[0] == DOMAIN}
            if keys and not keys & self.devices.keys():
                registry.async_update_device(device.id, remove_config_entry_id=self.config_entry.entry_id)

    # ------------------------------------------------------------------ polling

    async def _async_update_data(self) -> dict[str, DeviceState]:
        if self._homes_loaded_at is None or dt_util.utcnow() - self._homes_loaded_at > HOMES_REFRESH_INTERVAL:
            try:
                await self._with_auth_retry(self._load_homes)
            except ConfigEntryAuthFailed:
                raise
            except InnovaApiError as err:
                _LOGGER.debug("Could not refresh homes: %s", err)

        data: dict[str, DeviceState] = dict(self.data or {})
        macs = sorted({dev.mac for dev in self.devices.values()})
        results = await asyncio.gather(*(self._with_auth_retry(self._refresh_gateway, mac, data) for mac in macs), return_exceptions=True)
        errors: list[str] = []
        for mac, result in zip(macs, results):
            if isinstance(result, ConfigEntryAuthFailed):
                raise result
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, Exception):
                errors.append(f"{mac}: {result}")
        if errors and not data:
            raise UpdateFailed("; ".join(errors))
        if errors:
            _LOGGER.debug("Partial state refresh: %s", "; ".join(errors))
        return data

    async def _refresh_gateway(self, mac: str, data: dict[str, DeviceState]) -> None:
        """Read the full state of one gateway (MAC) and merge every node into ``data``."""
        try:
            response = await self.grpc.get_state(mac_to_bytes(mac), 0)
        except ValueError as err:
            # Undecodable reply or malformed MAC: report for this gateway only.
            raise InnovaApiError(f"undecodable state for {mac}: {err}") from err
        keys_for_mac = [key for key, dev in self.devices.items() if dev.mac == mac]

        if response.error_code is not None:
            # RESPONSE_TIMEOUT / CACHE_NOT_READY: the unit is unreachable for the cloud (offline,
            # rebooting, Wi-Fi dropped). Keep the last known values but mark the node offline.
            _LOGGER.debug("get_state %s error: %s %s", mac, response.error_code.name, response.error_message)
            for key in keys_for_mac:
                state = data.setdefault(key, DeviceState())
                state.online = response.error_code == ResponseErrorCode.UNSPECIFIED and state.online
            return

        for node_id, node_state in response.nodes.items():
            key = f"{mac}/{node_id}"
            existing = data.get(key)
            if existing is not None and node_state.kind == DEVICE_KIND_UNKNOWN and node_state.node_error is not None:
                existing.node_error = node_state.node_error
                existing.online = node_state.node_error != NodeError.OFFLINE
                continue
            if existing is not None:
                node_state.carry_over(existing)
            node_state.node_error = node_state.node_error
            node_state.online = node_state.node_error != NodeError.OFFLINE
            if response.gateway is not None:
                node_state.gateway = response.gateway
            data[key] = node_state
            if key not in self.devices:
                _LOGGER.debug("State for node %s not listed in /homes", key)

    # ------------------------------------------------------------------ event stream

    @callback
    def _sync_streams(self) -> None:
        """Start a stream for every known home and stop the ones for homes that disappeared."""
        if self._stopped:
            return
        for home_id in list(self._stream_tasks):
            if home_id not in self.homes:
                _LOGGER.info("Home %s removed, stopping its event stream", home_id)
                self._stream_tasks.pop(home_id).cancel()
        for home_id in self.homes:
            task = self._stream_tasks.get(home_id)
            if task is None or task.done():
                self._stream_tasks[home_id] = self.config_entry.async_create_background_task(
                    self.hass, self._run_stream(home_id), name=f"innova_cloud events {home_id}"
                )

    def start_event_stream(self) -> None:
        self._sync_streams()

    async def _run_stream(self, home_id: str) -> None:
        backoff = STREAM_BACKOFF_MIN
        auth_failures = 0
        while not self._stopped:
            connected = False

            def _on_connected() -> None:
                nonlocal connected, backoff, auth_failures
                connected = True
                backoff = STREAM_BACKOFF_MIN
                auth_failures = 0
                self._on_stream_connected()

            try:
                _LOGGER.debug("Subscribing to events for home %s", home_id)
                async for event in self.grpc.subscribe_events(uuid_to_bytes(home_id), _on_connected):
                    self._handle_event(event)
                _LOGGER.debug("Event stream for %s ended", home_id)
            except asyncio.CancelledError:
                raise
            except InnovaAuthError as err:
                self.stream_connected = False
                auth_failures += 1
                _LOGGER.debug("Event stream authentication error (%d): %s", auth_failures, err)
                relogged = auth_failures <= STREAM_AUTH_FAILURES_MAX and await self._try_relogin()
                if not relogged:
                    _LOGGER.warning("Event stream authentication failed, re-authentication required: %s", err)
                    self._start_reauth_once()
                    return
            except InnovaApiError as err:
                self.stream_connected = False
                _LOGGER.debug("Event stream error: %s", err)
            except Exception:  # noqa: BLE001
                self.stream_connected = False
                _LOGGER.exception("Unexpected error in event stream")
            if self._stopped:
                return
            if not connected:
                backoff = min(backoff * 2, STREAM_BACKOFF_MAX)
            await asyncio.sleep(backoff + random.uniform(0, 2))

    @callback
    def _on_stream_connected(self) -> None:
        self.stream_connected = True
        if self._stream_ever_connected:
            # Reconnected after a gap: events emitted meanwhile are lost, read everything again.
            _LOGGER.debug("Event stream reconnected, refreshing all states")
            self.hass.async_create_task(self.async_request_refresh())
        else:
            _LOGGER.debug("Event stream connected")
        self._stream_ever_connected = True

    @callback
    def _handle_event(self, event: DeviceEvent) -> None:
        mac = mac_to_str(event.mac) if event.mac else None
        if not mac:
            return
        node_id = event.node_id if event.node_id is not None else 0
        key = f"{mac}/{node_id}"
        data = dict(self.data or {})
        state = data.get(key)
        if state is None:
            if not any(dev.mac == mac for dev in self.devices.values()):
                _LOGGER.debug("Event for unknown device %s ignored", key)
                return
            state = DeviceState()
            data[key] = state
        if event.connection is not None:
            for k, s in data.items():
                if k.startswith(f"{mac}/"):
                    s.online = event.connection
            if event.connection:
                self._schedule_gateway_refresh(mac)
        if event.patch is not None:
            state.apply_event(event.patch)
            state.online = True
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Event %s: %s", key, event.raw)
        self.async_set_updated_data(data)

    # ------------------------------------------------------------------ commands

    async def async_send_request(self, device_key: str, request: bytes) -> None:
        dev = self.devices.get(device_key)
        if dev is None:
            raise InnovaApiError(f"device {device_key} is no longer in the Innova account")
        raw = await self._with_auth_retry(self.grpc.send_device, mac_to_bytes(dev.mac), dev.node_id, request)
        _LOGGER.debug("SendDevice %s -> %s", device_key, raw.hex() if raw else "<empty>")
        self._schedule_gateway_refresh(dev.mac)

    @callback
    def _schedule_gateway_refresh(self, mac: str) -> None:
        """Re-read one gateway shortly after a command or a reconnection (debounced per MAC)."""
        if self._stopped:
            return
        cancel = self._refresh_cancels.pop(mac, None)
        if cancel:
            cancel()

        @callback
        def _fire(_now: datetime) -> None:
            self._refresh_cancels.pop(mac, None)
            if not self._stopped:
                self.config_entry.async_create_background_task(self.hass, self._refresh_one(mac), name=f"innova_cloud refresh {mac}")

        self._refresh_cancels[mac] = async_call_later(self.hass, POST_COMMAND_REFRESH_DELAY, _fire)

    async def _refresh_one(self, mac: str) -> None:
        data = dict(self.data or {})
        try:
            await self._with_auth_retry(self._refresh_gateway, mac, data)
        except (InnovaApiError, ConfigEntryAuthFailed) as err:
            _LOGGER.debug("Post-command refresh failed for %s: %s", mac, err)
            return
        if not self._stopped:
            self.async_set_updated_data(data)

    # ------------------------------------------------------------------ helpers

    def get_state(self, device_key: str) -> DeviceState | None:
        return (self.data or {}).get(device_key)

    @callback
    def notify_optimistic_update(self) -> None:
        """Push an in-place optimistic change to every entity of the coordinator."""
        if not self._stopped:
            self.async_set_updated_data(dict(self.data or {}))
