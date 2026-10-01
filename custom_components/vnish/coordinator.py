"""Polling coordinator for a Vnish miner."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import VnishAuthError, VnishClient, VnishError
from .const import DOMAIN, SCAN_INTERVAL_SECONDS
from .models import VnishData, firmware_version, hostname, mac_address, model

_LOGGER = logging.getLogger(__name__)


class VnishCoordinator(DataUpdateCoordinator[VnishData]):
    """Fetch summary (required) plus settings and RPC hashrate (best effort)."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: VnishClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {client.host}",
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.client = client
        self._presets: list[dict] = []

    async def _async_update_data(self) -> VnishData:
        try:
            summary = await self.client.summary()
        except VnishAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except VnishError as err:
            raise UpdateFailed(str(err)) from err

        settings = await self._optional(self.client.settings(), "settings")
        rpc_summary = await self._optional(self.client.rpc_summary(), "RPC summary")
        if not self._presets:
            self._presets = await self._optional(self.client.presets(), "presets") or []

        return VnishData(summary, settings, rpc_summary, self._presets)

    async def _optional(self, awaitable, what: str):
        """Missing optional data must not make the whole miner unavailable."""
        try:
            return await awaitable
        except VnishError as err:
            _LOGGER.debug("Could not fetch %s from %s: %s", what, self.client.host, err)
            return None

    @property
    def unique_id(self) -> str:
        return self.config_entry.unique_id or self.client.host

    @property
    def device_info(self) -> DeviceInfo:
        summary = self.data.summary
        mac = mac_address(summary)
        return DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            connections={(CONNECTION_NETWORK_MAC, mac)} if mac else set(),
            name=hostname(summary) or self.config_entry.title,
            manufacturer="Vnish",
            model=model(summary),
            sw_version=firmware_version(summary),
            configuration_url=f"http://{self.client.host}",
        )
