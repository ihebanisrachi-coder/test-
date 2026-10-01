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
        key="pause_mining",
        translation_key="pause_mining",
        icon="mdi:pause",
        press_fn=lambda c: c.pause_mining(),
    ),
    VnishButtonDescription(
        key="resume_mining",
        translation_key="resume_mining",
        icon="mdi:play",
        press_fn=lambda c: c.resume_mining(),
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
    coordinator = entry.runtime_data
    async_add_entities(VnishButton(coordinator, d) for d in BUTTONS)

    # One "use this pool" button per pool configured on the miner.
    known: set[str] = set()

    def _add_new_pools() -> None:
        new = [p for p in coordinator.data.pool_labels if p not in known]
        known.update(new)
        async_add_entities(VnishPoolButton(coordinator, label) for label in new)

    _add_new_pools()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_pools))


class VnishButton(VnishEntity, ButtonEntity):
    entity_description: VnishButtonDescription

    def __init__(
        self, coordinator: VnishCoordinator, description: VnishButtonDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        await self._command(self.entity_description.press_fn(self.coordinator.client))


class VnishPoolButton(VnishEntity, ButtonEntity):
    """Make one configured pool the primary pool."""

    _attr_translation_key = "pool"
    _attr_icon = "mdi:server-network"

    def __init__(self, coordinator: VnishCoordinator, label: str) -> None:
        super().__init__(coordinator, f"pool_{label}")
        self._label = label
        self._attr_translation_placeholders = {"pool": label}

    @property
    def available(self) -> bool:
        return super().available and self._label in self.coordinator.data.pool_labels

    async def async_press(self) -> None:
        await self._switch_pool(self._label)
