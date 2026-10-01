"""Autotune preset selector (the power-limit knob for automations)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
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
        labels = self.coordinator.data.pool_labels
        return labels[0] if labels else None

    async def async_select_option(self, option: str) -> None:
        data = self.coordinator.data
        try:
            pool = data.pools[data.pool_labels.index(option)]
        except ValueError as err:
            raise HomeAssistantError(f"Unknown pool {option!r}") from err
        await self._command(
            self.coordinator.client.set_active_pool(pool["url"], pool.get("user", ""))
        )
