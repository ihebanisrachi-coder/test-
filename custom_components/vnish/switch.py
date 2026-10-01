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
from .models import OFF_STATES


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
        """`start` after a full stop, `resume` after a pause; fall back to the other."""
        client = self.coordinator.client
        stopped = self.coordinator.data.state in OFF_STATES
        first, second = (
            (client.start_mining, client.resume_mining)
            if stopped
            else (client.resume_mining, client.start_mining)
        )
        try:
            await first()
        except VnishApiError:
            await second()
