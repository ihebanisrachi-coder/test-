"""Autotune preset selector (the power-limit knob for automations)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
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
    async_add_entities(
        [VnishPresetSelect(entry.runtime_data), VnishPoolSelect(entry.runtime_data)]
    )


class VnishPresetSelect(VnishEntity, SelectEntity):
    _attr_translation_key = "preset"
    _attr_icon = "mdi:tune-vertical"

    def __init__(self, coordinator: VnishCoordinator) -> None:
        super().__init__(coordinator, "preset")

    @property
    def options(self) -> list[str]:
        return self.coordinator.data.preset_options

    @property
    def current_option(self) -> str | None:
        current = self.coordinator.data.preset
        return current if current in self.options else None

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Human readable label of each preset, e.g. '3250 watt ~ 110 TH'."""
        return {
            str(p["name"]): str(p["pretty"])
            for p in self.coordinator.data.presets
            if p.get("name") is not None and p.get("pretty")
        }

    async def async_select_option(self, option: str) -> None:
        await self._command(self.coordinator.client.set_preset(option))


class VnishPoolSelect(VnishEntity, SelectEntity):
    """Primary pool; the other configured pools remain failovers."""

    _attr_translation_key = "pool"
    _attr_icon = "mdi:server-network"

    def __init__(self, coordinator: VnishCoordinator) -> None:
        super().__init__(coordinator, "pool")

    @property
    def options(self) -> list[str]:
        return self.coordinator.data.pool_labels

    @property
    def current_option(self) -> str | None:
        return self.coordinator.data.active_pool

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Pool number -> URL (no credentials)."""
        data = self.coordinator.data
        return {
            label: str(pool["url"])
            for label, pool in zip(data.pool_labels, data.pools, strict=True)
        }

    async def async_select_option(self, option: str) -> None:
        await self._switch_pool(option)
