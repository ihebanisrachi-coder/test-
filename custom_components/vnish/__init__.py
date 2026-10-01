"""Control a Vnish-firmware miner from Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import VnishClient
from .coordinator import VnishCoordinator

PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.BUTTON, Platform.SELECT]

type VnishConfigEntry = ConfigEntry[VnishCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: VnishConfigEntry) -> bool:
    client = VnishClient(
        async_get_clientsession(hass), entry.data[CONF_HOST], entry.data[CONF_PASSWORD]
    )
    coordinator = VnishCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: VnishConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
