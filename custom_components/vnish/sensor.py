"""Vnish sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    REVOLUTIONS_PER_MINUTE,
    EntityCategory,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import VnishConfigEntry
from .coordinator import VnishCoordinator
from .entity import VnishEntity
from .models import VnishData


@dataclass(frozen=True, kw_only=True)
class VnishSensorDescription(SensorEntityDescription):
    value_fn: Callable[[VnishData], StateType]


SENSORS: tuple[VnishSensorDescription, ...] = (
    VnishSensorDescription(
        key="state",
        translation_key="state",
        icon="mdi:pickaxe",
        value_fn=lambda d: d.state,
    ),
    VnishSensorDescription(
        key="hashrate",
        translation_key="hashrate",
        icon="mdi:speedometer",
        native_unit_of_measurement="TH/s",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.hashrate,
    ),
    VnishSensorDescription(
        key="power",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.power,
    ),
    VnishSensorDescription(
        key="efficiency",
        translation_key="efficiency",
        icon="mdi:flash",
        native_unit_of_measurement="J/TH",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.efficiency,
    ),
    VnishSensorDescription(
        key="chip_temp",
        translation_key="chip_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.chip_temp,
    ),
    VnishSensorDescription(
        key="pcb_temp",
        translation_key="pcb_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.pcb_temp,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VnishConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(VnishSensor(coordinator, desc) for desc in SENSORS)

    # The number of fans is only known once the miner reports them.
    known_fans: set[int] = set()

    def _add_new_fans() -> None:
        new = set(range(len(coordinator.data.fans))) - known_fans
        known_fans.update(new)
        async_add_entities(VnishFanSensor(coordinator, i) for i in sorted(new))

    _add_new_fans()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_fans))


class VnishSensor(VnishEntity, SensorEntity):
    entity_description: VnishSensorDescription

    def __init__(
        self, coordinator: VnishCoordinator, description: VnishSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        return self.entity_description.value_fn(self.coordinator.data)


class VnishFanSensor(VnishEntity, SensorEntity):
    _attr_translation_key = "fan"
    _attr_native_unit_of_measurement = REVOLUTIONS_PER_MINUTE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:fan"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: VnishCoordinator, index: int) -> None:
        super().__init__(coordinator, f"fan_{index + 1}")
        self._index = index
        self._attr_translation_placeholders = {"fan": str(index + 1)}

    @property
    def native_value(self) -> float | None:
        fans = self.coordinator.data.fans
        return fans[self._index] if self._index < len(fans) else None
