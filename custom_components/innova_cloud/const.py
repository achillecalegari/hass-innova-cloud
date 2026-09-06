"""Constants for the Innova Cloud integration."""

from datetime import timedelta

DOMAIN = "innova_cloud"
MANUFACTURER = "Innova"

CONF_TOKEN = "token"
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_REST_BASE = "rest_base"
CONF_GRPC_HOST = "grpc_host"
CONF_BRAND = "brand"
CONF_POLL_MINUTES = "poll_minutes"

# White-label tenants of the same Solution Tech cloud: hosts are v2.api.<slug> / v2.grpc.<slug>.
# Slugs verified live (each answers 401 on /app/homes without a token).
BRANDS: dict[str, str] = {
    "innova": "Innova",
    "aquarea-home": "Panasonic Aquarea Home",
    "diffusapp": "DiffusApp (STG / Diffusalp)",
    "rhoss-tema": "Rhoss Tema",
    "etherma-fire-ice-2": "Etherma Fire+Ice 2",
    "custom": "Custom hosts",
}
DEFAULT_BRAND = "innova"


def brand_hosts(slug: str) -> tuple[str, str]:
    """(REST base URL, gRPC host) for a tenant slug."""
    return f"https://v2.api.{slug}.solutiontech.tech", f"v2.grpc.{slug}.solutiontech.tech"


DEFAULT_POLL_MINUTES = 10
MIN_POLL_MINUTES = 1
MAX_POLL_MINUTES = 60

PLATFORMS = ["climate", "sensor", "switch"]

# Re-read the home layout (new devices, renamed rooms) from the REST API.
HOMES_REFRESH_INTERVAL = timedelta(hours=6)
# Delay before re-reading the full state after a command (events normally arrive earlier).
POST_COMMAND_REFRESH_DELAY = 3.0

ATTR_OPERATION_MODE = "operation_mode"
ATTR_CALENDAR_PRESET = "calendar_preset"
ATTR_MANUAL_UNTIL = "manual_until"
ATTR_ALARMS = "alarms"
ATTR_HVAC_ACTUAL = "hvac_actual_mode"
ATTR_NODE_ID = "node_id"
ATTR_RAW = "raw_state"
