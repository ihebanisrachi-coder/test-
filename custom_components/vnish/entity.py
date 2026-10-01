"""Base entity shared by every platform."""

from __future__ import annotations

from collections.abc import Awaitable

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import VnishError
from .coordinator import VnishCoordinator


class VnishEntity(CoordinatorEntity[VnishCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: VnishCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.unique_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.device_info

    async def _command(self, call: Awaitable[None]) -> None:
        """Run a miner command, surface failures in the UI, then refresh."""
        try:
            await call
        except VnishError as err:
            raise HomeAssistantError(f"Vnish command failed: {err}") from err
        await self.coordinator.async_request_refresh()

    async def _switch_pool(self, label: str) -> None:
        pool_id = self.coordinator.data.pool_id(label)
        if pool_id is None:
            raise HomeAssistantError(f"Pool {label} is not known to the miner")
        await self._command(self.coordinator.client.switch_pool(pool_id))
