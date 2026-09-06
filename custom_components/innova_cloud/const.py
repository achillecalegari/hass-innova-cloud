"""Constants for the Innova Cloud integration."""

from datetime import timedelta

DOMAIN = "innova_cloud"
MANUFACTURER = "Innova"

CONF_TOKEN = "token"
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_REST_BASE = "rest_base"
CONF_GRPC_HOST = "grpc_host"

PLATFORMS = ["climate", "sensor", "switch"]

# Full state refresh (polling fallback; live updates arrive via the gRPC event stream).
POLL_INTERVAL = timedelta(minutes=10)
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
