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
from .const import CONF_POOL_ORDER, DOMAIN, SCAN_INTERVAL_SECONDS
from .models import VnishData, firmware_version, hostname, mac_address, model, pool_key

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

        data = VnishData(summary, settings, rpc_summary, self._presets)
        if settings is not None:
            data.pool_order = self._stable_pool_order(data)
        return data

    def _stable_pool_order(self, data: VnishData) -> list[tuple[str, str]]:
        """Pool numbers follow the order first seen, whatever the miner's priority.

        Switching pools reorders the miner's list; without this, "pool 2" would
        become "pool 1" after being selected. The order is kept in the entry.
        """
        present = [pool_key(p) for p in data.miner_pools]
        saved = [tuple(k) for k in self.config_entry.data.get(CONF_POOL_ORDER, [])]
        order = [k for k in saved if k in present] + [k for k in present if k not in saved]
        if order != saved:
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_POOL_ORDER: [list(k) for k in order]},
            )
        return order

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
