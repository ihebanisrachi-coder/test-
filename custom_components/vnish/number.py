"""Throttle slider: cap the miner at a percentage of its hashrate and power."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VnishConfigEntry
from .coordinator import VnishCoordinator
from .entity import VnishEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VnishConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([VnishThrottleNumber(entry.runtime_data)])


class VnishThrottleNumber(VnishEntity, NumberEntity):
    _attr_translation_key = "throttle"
    _attr_icon = "mdi:speedometer-slow"
    _attr_native_min_value = 20
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: VnishCoordinator) -> None:
        super().__init__(coordinator, "throttle")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.throttle

    async def async_set_native_value(self, value: float) -> None:
        await self._command(self.coordinator.client.set_throttle(round(value)))
