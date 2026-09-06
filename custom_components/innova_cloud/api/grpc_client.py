"""Async gRPC client for ``services.app.AppService`` (grpcio ``grpc.aio``)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable

import grpc
import grpc.aio

from . import messages
from .rest import DEFAULT_GRPC_HOST, DEFAULT_GRPC_PORT, InnovaApiError, InnovaAuthError

_LOGGER = logging.getLogger(__name__)

_IDENTITY: Callable[[bytes], bytes] = lambda payload: payload  # noqa: E731


class InnovaGrpcClient:
    def __init__(
        self,
        token_getter: Callable[[], str | None],
        host: str = DEFAULT_GRPC_HOST,
        port: int = DEFAULT_GRPC_PORT,
    ) -> None:
        self._token_getter = token_getter
        self._target = f"{host}:{port}"
        self._channel: grpc.aio.Channel | None = None
        self._lock = asyncio.Lock()

    async def _get_channel(self) -> grpc.aio.Channel:
        async with self._lock:
            if self._channel is None:
                self._channel = grpc.aio.secure_channel(
                    self._target,
                    grpc.ssl_channel_credentials(),
                    options=[
                        ("grpc.keepalive_time_ms", 30_000),
                        ("grpc.keepalive_timeout_ms", 10_000),
                        ("grpc.keepalive_permit_without_calls", 1),
                        ("grpc.http2.max_pings_without_data", 0),
                        ("grpc.enable_retries", 0),
                    ],
                )
            return self._channel

    def _metadata(self) -> tuple[tuple[str, str], ...]:
        token = self._token_getter()
        if not token:
            raise InnovaAuthError("no token")
        return (("authorization", f"Bearer {token}"),)

    async def close(self) -> None:
        async with self._lock:
            if self._channel is not None:
                await self._channel.close()
                self._channel = None

    @staticmethod
    def _translate(err: grpc.aio.AioRpcError) -> InnovaApiError:
        code = err.code()
        if code == grpc.StatusCode.UNAUTHENTICATED:
            return InnovaAuthError(err.details() or "unauthenticated")
        return InnovaApiError(f"gRPC {code.name}: {err.details()}")

    async def send_device(self, mac: bytes, node_id: int, request: bytes, timeout: float = 20.0) -> bytes:
        """Unary ``SendDevice``; returns the raw response payload."""
        channel = await self._get_channel()
        call = channel.unary_unary(messages.METHOD_SEND_DEVICE, request_serializer=_IDENTITY, response_deserializer=_IDENTITY)
        payload = messages.send_device_request(mac, node_id, request)
        try:
            return await call(payload, metadata=self._metadata(), timeout=timeout)
        except grpc.aio.AioRpcError as err:
            raise self._translate(err) from err

    async def get_state(self, mac: bytes, node_id: int = 0) -> messages.StateResponse:
        raw = await self.send_device(mac, node_id, messages.request_get_state())
        return messages.parse_state_response(raw)

    async def subscribe_events(self, home_id: bytes) -> AsyncIterator[messages.DeviceEvent]:
        """Server-streaming ``SubscribeEvents``; yields decoded events until the stream ends."""
        channel = await self._get_channel()
        call = channel.unary_stream(messages.METHOD_SUBSCRIBE_EVENTS, request_serializer=_IDENTITY, response_deserializer=_IDENTITY)
        stream = call(messages.subscribe_events_request(home_id), metadata=self._metadata())
        try:
            async for raw in stream:
                try:
                    event = messages.parse_event(raw)
                except ValueError as err:
                    _LOGGER.debug("Undecodable event %s: %s", raw.hex(), err)
                    continue
                if event is not None:
                    yield event
        except grpc.aio.AioRpcError as err:
            raise self._translate(err) from err
        finally:
            stream.cancel()
