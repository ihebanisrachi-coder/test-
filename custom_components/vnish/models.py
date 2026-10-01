"""Parsing of Vnish API payloads. Every accessor tolerates missing fields."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# miner_state values that mean "the hashboards are not working".
OFF_STATES = frozenset({"stopped", "shutting-down", "failure", "paused"})


def _get(data: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def mac_address(payload: dict[str, Any]) -> str | None:
    """MAC from a /summary or /info payload."""
    mac = _get(payload, "system", "network_status", "mac")
    return mac if isinstance(mac, str) and mac else None


def hostname(payload: dict[str, Any]) -> str | None:
    name = _get(payload, "system", "network_status", "hostname")
    return name if isinstance(name, str) and name else None


def _miner_type(summary: dict[str, Any]) -> str | None:
    value = _get(summary, "miner", "miner_type")
    return value if isinstance(value, str) and value else None


def model(summary: dict[str, Any]) -> str | None:
    """'Antminer S19 (Vnish 1.2.6)' -> 'Antminer S19'."""
    miner_type = _miner_type(summary)
    return miner_type.split("(Vnish")[0].strip() if miner_type else None


def firmware_version(summary: dict[str, Any]) -> str | None:
    """'Antminer S19 (Vnish 1.2.6)' -> '1.2.6'."""
    miner_type = _miner_type(summary)
    if miner_type and "(Vnish" in miner_type:
        return miner_type.split("(Vnish", 1)[1].strip(" )") or None
    return None


@dataclass
class VnishData:
    """One polling round."""

    summary: dict[str, Any]
    settings: dict[str, Any] | None = None
    rpc_summary: dict[str, Any] | None = None
    presets: list[dict[str, Any]] = field(default_factory=list)

    @property
    def state(self) -> str | None:
        state = _get(self.summary, "miner", "miner_status", "miner_state")
        return state if isinstance(state, str) else None

    @property
    def is_mining(self) -> bool | None:
        return None if self.state is None else self.state not in OFF_STATES

    @property
    def power(self) -> float | None:
        """Wall power in watts."""
        return _num(_get(self.summary, "miner", "power_usage"))

    @property
    def hashrate(self) -> float | None:
        """Hashrate in TH/s (the RPC API reports GH/s)."""
        ghs = _num(_get(self.rpc_summary, "GHS 5s"))
        return None if ghs is None else ghs / 1000

    @property
    def efficiency(self) -> float | None:
        """J/TH."""
        if self.power is None or not self.hashrate:
            return None
        return self.power / self.hashrate

    def _max_temp(self, kind: str) -> float | None:
        """Hottest 'chip_temp'/'pcb_temp', from the global value or per chain."""
        top = _num(_get(self.summary, "miner", kind, "max"))
        if top is not None:
            return top
        chains = _get(self.summary, "miner", "chains")
        if not isinstance(chains, list):
            return None
        temps = [_num(_get(chain, kind, "max")) for chain in chains]
        return max((t for t in temps if t is not None), default=None)

    @property
    def chip_temp(self) -> float | None:
        return self._max_temp("chip_temp")

    @property
    def pcb_temp(self) -> float | None:
        return self._max_temp("pcb_temp")

    @property
    def fans(self) -> list[float | None]:
        """Fan speeds in RPM, in the order reported by the miner."""
        fans = _get(self.summary, "miner", "cooling", "fans")
        if not isinstance(fans, list):
            return []
        return [_num(_get(fan, "rpm")) for fan in fans]

    @property
    def preset(self) -> str | None:
        value = _get(self.settings, "miner", "overclock", "preset")
        return str(value) if value is not None else None

    @property
    def preset_options(self) -> list[str]:
        return [str(p["name"]) for p in self.presets if p.get("name") is not None]

    @property
    def pools(self) -> list[dict[str, Any]]:
        """Configured pools, primary first (empty slots dropped)."""
        pools = _get(self.settings, "miner", "pools")
        if not isinstance(pools, list):
            return []
        return [p for p in pools if isinstance(p, dict) and p.get("url")]

    @property
    def pool_labels(self) -> list[str]:
        """Stable, credential-free names for `pools`: the URL (+ user if URLs clash)."""
        urls = [str(p["url"]) for p in self.pools]
        return [
            url if urls.count(url) == 1 else f"{url} ({p.get('user', '')})"
            for url, p in zip(urls, self.pools, strict=True)
        ]

    def pool_by_label(self, label: str) -> dict[str, Any] | None:
        labels = self.pool_labels
        return self.pools[labels.index(label)] if label in labels else None
