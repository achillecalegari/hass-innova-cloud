"""Config flow: pick the brand (cloud tenant), then sign in with email/password or paste a session token.
Options flow: polling interval."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import InnovaApiError, InnovaAuthError, InnovaRestClient
from .api.rest import DEFAULT_REST_BASE, decode_jwt_claims
from .const import (
    BRANDS,
    CONF_BRAND,
    CONF_EMAIL,
    CONF_GRPC_HOST,
    CONF_PASSWORD,
    CONF_POLL_MINUTES,
    CONF_REST_BASE,
    CONF_TOKEN,
    DEFAULT_BRAND,
    DEFAULT_POLL_MINUTES,
    DOMAIN,
    MAX_POLL_MINUTES,
    MIN_POLL_MINUTES,
    brand_hosts,
)

_LOGGER = logging.getLogger(__name__)

STEP_BRAND_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BRAND, default=DEFAULT_BRAND): SelectSelector(
            SelectSelectorConfig(
                options=[SelectOptionDict(value=slug, label=label) for slug, label in BRANDS.items()],
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
    }
)
STEP_CUSTOM_HOSTS_SCHEMA = vol.Schema({vol.Required(CONF_REST_BASE): str, vol.Required(CONF_GRPC_HOST): str})
STEP_CREDENTIALS_SCHEMA = vol.Schema({vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str})
STEP_TOKEN_SCHEMA = vol.Schema({vol.Required(CONF_TOKEN): str})


class InnovaConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._hosts: dict[str, str] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return InnovaOptionsFlow()

    # -- brand / hosts -----------------------------------------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            brand = user_input[CONF_BRAND]
            if brand == "custom":
                return await self.async_step_custom_hosts()
            rest_base, grpc_host = brand_hosts(brand)
            self._hosts = {CONF_BRAND: brand, CONF_REST_BASE: rest_base, CONF_GRPC_HOST: grpc_host}
            return await self.async_step_auth()
        return self.async_show_form(step_id="user", data_schema=STEP_BRAND_SCHEMA)

    async def async_step_custom_hosts(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._hosts = {
                CONF_BRAND: "custom",
                CONF_REST_BASE: user_input[CONF_REST_BASE].strip().rstrip("/"),
                CONF_GRPC_HOST: user_input[CONF_GRPC_HOST].strip(),
            }
            return await self.async_step_auth()
        return self.async_show_form(step_id="custom_hosts", data_schema=STEP_CUSTOM_HOSTS_SCHEMA)

    async def async_step_auth(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="auth", menu_options=["credentials", "token"])

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        self._hosts = {
            CONF_BRAND: entry_data.get(CONF_BRAND, DEFAULT_BRAND),
            CONF_REST_BASE: entry_data.get(CONF_REST_BASE, DEFAULT_REST_BASE),
            CONF_GRPC_HOST: entry_data.get(CONF_GRPC_HOST, brand_hosts(DEFAULT_BRAND)[1]),
        }
        return await self.async_step_auth()

    # -- authentication ----------------------------------------------------------------

    def _client(self, token: str | None = None) -> InnovaRestClient:
        return InnovaRestClient(async_get_clientsession(self.hass), token=token, base_url=self._hosts.get(CONF_REST_BASE, DEFAULT_REST_BASE))

    async def async_step_credentials(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client = self._client()
            try:
                token = await client.login(user_input[CONF_EMAIL], user_input[CONF_PASSWORD])
                await client.get_homes_raw()
            except InnovaAuthError:
                errors["base"] = "invalid_auth"
            except InnovaApiError as err:
                _LOGGER.debug("Login failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                return await self._async_finish(token, email=user_input[CONF_EMAIL], password=user_input[CONF_PASSWORD])
        return self.async_show_form(step_id="credentials", data_schema=STEP_CREDENTIALS_SCHEMA, errors=errors)

    async def async_step_token(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_TOKEN].strip().removeprefix("Bearer ").strip()
            client = self._client(token)
            try:
                await client.get_homes_raw()
                me = await client.get_me()
            except InnovaAuthError:
                errors["base"] = "invalid_auth"
            except InnovaApiError as err:
                _LOGGER.debug("Token check failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                return await self._async_finish(token, email=me.get("email"))
        return self.async_show_form(step_id="token", data_schema=STEP_TOKEN_SCHEMA, errors=errors)

    async def _async_finish(self, token: str, email: str | None = None, password: str | None = None) -> ConfigFlowResult:
        claims = decode_jwt_claims(token)
        unique_id = str(claims.get("sub") or email or "innova")
        data: dict[str, Any] = {**self._hosts, CONF_TOKEN: token}
        if email and password:
            data[CONF_EMAIL] = email
            data[CONF_PASSWORD] = password

        await self.async_set_unique_id(unique_id)
        if self.source == SOURCE_REAUTH:
            # Refuse credentials of a different account: the entry's devices belong to this one.
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=data)

        self._abort_if_unique_id_configured(updates=data)
        brand = BRANDS.get(self._hosts.get(CONF_BRAND, DEFAULT_BRAND), "Innova")
        title = f"{brand} ({email})" if email else f"{brand} ({unique_id[:8]})"
        return self.async_create_entry(title=title, data=data)


class InnovaOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_POLL_MINUTES, DEFAULT_POLL_MINUTES)
        schema = vol.Schema(
            {
                vol.Required(CONF_POLL_MINUTES, default=current): NumberSelector(
                    NumberSelectorConfig(min=MIN_POLL_MINUTES, max=MAX_POLL_MINUTES, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement="min")
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
