"""Reboot / restart buttons."""

from __future__ import annotations

from collections.abc import Callable, Awaitable
from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VnishConfigEntry
from .api import VnishClient
from .coordinator import VnishCoordinator
from .entity import VnishEntity


@dataclass(frozen=True, kw_only=True)
class VnishButtonDescription(ButtonEntityDescription):
    press_fn: Callable[[VnishClient], Awaitable[None]]


BUTTONS: tuple[VnishButtonDescription, ...] = (
    VnishButtonDescription(
        key="reboot",
        translation_key="reboot",
        device_class=ButtonDeviceClass.RESTART,
        press_fn=lambda c: c.reboot(),
    ),
    VnishButtonDescription(
        key="restart_mining",
        translation_key="restart_mining",
        device_class=ButtonDeviceClass.RESTART,
        press_fn=lambda c: c.restart_mining(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VnishConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(VnishButton(entry.runtime_data, d) for d in BUTTONS)


class VnishButton(VnishEntity, ButtonEntity):
    entity_description: VnishButtonDescription

    def __init__(
        self, coordinator: VnishCoordinator, description: VnishButtonDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        await self._command(self.entity_description.press_fn(self.coordinator.client))
