"""Diagnostics download (secrets and identifiers redacted)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import VnishConfigEntry

TO_REDACT = {
    "host", "password", "pass", "pw", "token", "user", "User", "key",
    "mac", "serial", "psu_serial", "ip", "ipaddress", "gateway", "dns", "dnsservers",
    "hostname", "netmask",
}  # fmt: skip


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: VnishConfigEntry
) -> dict[str, Any]:
    data = entry.runtime_data.data
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "info": data.info,
            "summary": data.summary,
            "settings": data.settings,
            "presets": data.presets,
            "rpc_summary": data.rpc_summary,
            "rpc_pools": data.rpc_pools,
        },
        TO_REDACT,
    )
