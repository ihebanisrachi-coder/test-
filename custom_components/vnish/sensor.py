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
    PERCENTAGE,
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
from .models import BOARD_STATES, MINER_STATES, VnishData


def _enum(value: str | None, options: tuple[str, ...]) -> str | None:
    """An enum sensor must never be handed a value outside its options."""
    return value if value in options else None


@dataclass(frozen=True, kw_only=True)
class VnishSensorDescription(SensorEntityDescription):
    value_fn: Callable[[VnishData], StateType]
    unit_fn: Callable[[VnishData], str] | None = None


SENSORS: tuple[VnishSensorDescription, ...] = (
    VnishSensorDescription(
        key="state",
        translation_key="state",
        icon="mdi:pickaxe",
        device_class=SensorDeviceClass.ENUM,
        options=list(MINER_STATES),
        value_fn=lambda d: _enum(d.state, MINER_STATES),
    ),
    VnishSensorDescription(
        key="hashrate",
        translation_key="hashrate",
        icon="mdi:speedometer",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.hashrate,
        unit_fn=lambda d: d.hashrate_unit,
    ),
    VnishSensorDescription(
        key="expected_hashrate",
        translation_key="expected_hashrate",
        icon="mdi:speedometer-medium",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.expected_hashrate,
        unit_fn=lambda d: d.hashrate_unit,
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
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.efficiency,
        unit_fn=lambda d: "J/GH" if d.hashrate_unit == "GH/s" else "J/TH",
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
    VnishSensorDescription(
        key="fan_duty",
        translation_key="fan_duty",
        icon="mdi:fan",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.fan_duty,
    ),
    VnishSensorDescription(
        key="hw_errors",
        translation_key="hw_errors",
        icon="mdi:alert-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.hw_error_percent,
    ),
)

BOARD_SENSORS: tuple[VnishSensorDescription, ...] = (
    VnishSensorDescription(
        key="hashrate",
        translation_key="board_hashrate",
        icon="mdi:speedometer",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: None,  # replaced per board, see VnishBoardSensor
        unit_fn=lambda d: d.hashrate_unit,
    ),
    VnishSensorDescription(
        key="temperature",
        translation_key="board_temperature",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: None,
    ),
    VnishSensorDescription(
        key="state",
        translation_key="board_state",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=list(BOARD_STATES),
        value_fn=lambda d: None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VnishConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(VnishSensor(coordinator, desc) for desc in SENSORS)

    # Fans and boards are only known once the miner reports them.
    known_fans: set[int] = set()
    known_boards: set[int] = set()

    def _add_new() -> None:
        data = coordinator.data
        new_fans = set(range(len(data.fans))) - known_fans
        known_fans.update(new_fans)
        new_boards = set(range(len(data.boards))) - known_boards
        known_boards.update(new_boards)
        async_add_entities(
            [VnishFanSensor(coordinator, i) for i in sorted(new_fans)]
            + [
                VnishBoardSensor(coordinator, i, desc)
                for i in sorted(new_boards)
                for desc in BOARD_SENSORS
            ]
        )

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


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

    @property
    def native_unit_of_measurement(self) -> str | None:
        if unit_fn := self.entity_description.unit_fn:
            return unit_fn(self.coordinator.data)
        return self.entity_description.native_unit_of_measurement


class VnishBoardSensor(VnishSensor):
    """One value of one hashboard (hashrate, temperature or state)."""

    def __init__(
        self,
        coordinator: VnishCoordinator,
        index: int,
        description: VnishSensorDescription,
    ) -> None:
        super().__init__(coordinator, description)
        self._index = index
        self._attr_unique_id = f"{coordinator.unique_id}_board_{index + 1}_{description.key}"
        self._attr_translation_placeholders = {"board": str(index + 1)}

    @property
    def native_value(self) -> StateType:
        boards = self.coordinator.data.boards
        if self._index >= len(boards):
            return None
        value = boards[self._index][self.entity_description.key]
        if self.entity_description.key == "state":
            return _enum(value, BOARD_STATES)
        return value


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
