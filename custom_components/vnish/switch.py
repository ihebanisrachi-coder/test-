"""Mining on/off switch."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VnishConfigEntry
from .api import VnishApiError
from .coordinator import VnishCoordinator
from .entity import VnishEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VnishConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([VnishMiningSwitch(entry.runtime_data)])


class VnishMiningSwitch(VnishEntity, SwitchEntity):
    _attr_translation_key = "mining"
    _attr_icon = "mdi:pickaxe"

    def __init__(self, coordinator: VnishCoordinator) -> None:
        super().__init__(coordinator, "mining")

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.is_mining

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._command(self._resume())

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._command(self.coordinator.client.stop_mining())

    async def _resume(self) -> None:
        client = self.coordinator.client
        try:
            await client.resume_mining()
        except VnishApiError:
            # Some firmware versions only accept "start" after a full stop.
            await client.start_mining()
