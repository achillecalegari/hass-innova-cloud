"""Standalone client for the Innova (Solution Tech) cloud used by the new-generation Innova app.

This package has no Home Assistant dependency so it can be reused by scripts and tests.
"""

from .rest import InnovaRestClient, InnovaAuthError, InnovaApiError
from .grpc_client import InnovaGrpcClient
from .models import DeviceState, DeviceInfo, HomeInfo
from . import messages

__all__ = [
    "InnovaRestClient",
    "InnovaAuthError",
    "InnovaApiError",
    "InnovaGrpcClient",
    "DeviceState",
    "DeviceInfo",
    "HomeInfo",
    "messages",
]
