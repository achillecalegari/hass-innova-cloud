"""Config flow: sign in with the Innova app account (email/password) or paste a session token."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import InnovaApiError, InnovaAuthError, InnovaRestClient
from .api.rest import decode_jwt_claims
from .const import CONF_EMAIL, CONF_PASSWORD, CONF_TOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_CREDENTIALS_SCHEMA = vol.Schema({vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str})
STEP_TOKEN_SCHEMA = vol.Schema({vol.Required(CONF_TOKEN): str})


class InnovaConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["credentials", "token"])

    async def async_step_credentials(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client = InnovaRestClient(async_get_clientsession(self.hass))
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
            client = InnovaRestClient(async_get_clientsession(self.hass), token=token)
            try:
                await client.get_homes_raw()
            except InnovaAuthError:
                errors["base"] = "invalid_auth"
            except InnovaApiError as err:
                _LOGGER.debug("Token check failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                return await self._async_finish(token)
        return self.async_show_form(step_id="token", data_schema=STEP_TOKEN_SCHEMA, errors=errors)

    async def _async_finish(self, token: str, email: str | None = None, password: str | None = None) -> ConfigFlowResult:
        claims = decode_jwt_claims(token)
        unique_id = claims.get("sub") or email or "innova"
        data: dict[str, Any] = {CONF_TOKEN: token}
        if email and password:
            data[CONF_EMAIL] = email
            data[CONF_PASSWORD] = password

        if self._reauth_entry is not None:
            return self.async_update_reload_and_abort(self._reauth_entry, data_updates=data)

        await self.async_set_unique_id(str(unique_id))
        self._abort_if_unique_id_configured(updates=data)
        title = email or f"Innova ({str(unique_id)[:8]})"
        return self.async_create_entry(title=title, data=data)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        self._reauth_entry = self._get_reauth_entry()
        return await self.async_step_user()
