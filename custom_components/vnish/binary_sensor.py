"""Problem sensor: miner/board failure or a lost fan."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    async_add_entities([VnishProblemSensor(entry.runtime_data)])


class VnishProblemSensor(VnishEntity, BinarySensorEntity):
    _attr_translation_key = "problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: VnishCoordinator) -> None:
        super().__init__(coordinator, "problem")

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.problem

    @property
    def extra_state_attributes(self) -> dict[str, list[str]]:
        return {"problems": self.coordinator.data.problems}
