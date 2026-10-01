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
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .models import VnishData, firmware_version, hostname, mac_address, model

_LOGGER = logging.getLogger(__name__)


class VnishCoordinator(DataUpdateCoordinator[VnishData]):
    """Fetch summary (required) plus settings, info and RPC data (best effort)."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: VnishClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {client.host}",
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client
        self._presets: list[dict] = []
        self._info: dict = {}

    async def _async_update_data(self) -> VnishData:
        try:
            summary = await self.client.summary()
        except VnishAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except VnishError as err:
            raise UpdateFailed(str(err)) from err

        settings = await self._optional(self.client.settings(), "settings")
        perf_summary = await self._optional(self.client.perf_summary(), "perf-summary")
        rpc_summary = await self._optional(self.client.rpc_summary(), "RPC summary")
        if not self._presets:
            self._presets = await self._optional(self.client.presets(), "presets") or []

        rpc_pools = await self._optional(self.client.rpc_pools(), "RPC pools") or []
        if not self._info:  # static: model, firmware, serial, hashrate unit
            self._info = await self._optional(self.client.info(), "info") or {}

        return VnishData(
            summary,
            settings,
            rpc_summary,
            self._presets,
            rpc_pools,
            self._info,
            perf_summary,
        )

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
        summary, info = self.data.summary, self.data.info
        mac = mac_address(info) or mac_address(summary)
        serial = info.get("serial")
        return DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            connections={(CONNECTION_NETWORK_MAC, mac)} if mac else set(),
            name=hostname(info) or hostname(summary) or self.config_entry.title,
            manufacturer="Vnish",
            model=model(summary, info),
            serial_number=serial if isinstance(serial, str) and serial else None,
            sw_version=firmware_version(summary, info),
            configuration_url=f"http://{self.client.host}",
        )
