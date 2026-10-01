"""Parsing of Vnish API payloads. Every accessor tolerates missing fields."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Documented `miner_state` values (see the firmware's API reference).
MINER_STATES = (
    "mining",
    "initializing",
    "starting",
    "auto-tuning",
    "restarting",
    "shutting-down",
    "stopped",
    "failure",
)
# ... of which these mean "the hashboards are not working".
OFF_STATES = frozenset({"stopped", "shutting-down", "failure"})

BOARD_STATES = (
    "initializing",
    "mining",
    "stopped",
    "failure",
    "disconnected",
    "disabled",
    "unknown",
)


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


def model(summary: dict[str, Any], info: dict[str, Any] | None = None) -> str | None:
    """Display name from /info, else 'Antminer S19 (Vnish 1.2.6)' -> 'Antminer S19'."""
    if isinstance(name := _get(info, "miner"), str) and name:
        return name
    miner_type = _miner_type(summary)
    return miner_type.split("(Vnish")[0].strip() if miner_type else None


def firmware_version(
    summary: dict[str, Any], info: dict[str, Any] | None = None
) -> str | None:
    """Version from /info, else 'Antminer S19 (Vnish 1.2.6)' -> '1.2.6'."""
    if isinstance(version := _get(info, "fw_version"), str) and version:
        return version
    miner_type = _miner_type(summary)
    if miner_type and "(Vnish" in miner_type:
        return miner_type.split("(Vnish", 1)[1].strip(" )") or None
    return None


def _normalize_url(url: Any) -> str:
    """'stratum+tcp://Pool.example:3333/' -> 'pool.example:3333'."""
    return str(url or "").split("://", 1)[-1].rstrip("/").lower()


def find_live_pool(
    pool: dict[str, Any], live_pools: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """The running pool (see `VnishData.live_pools`) behind a settings-table pool.

    Same URL and user; if the user differs, accept the URL alone when it is unique.
    """
    same_url = [
        p for p in live_pools if _normalize_url(p["url"]) == _normalize_url(pool.get("url"))
    ]
    for live in same_url:
        if live["user"] == str(pool.get("user", "")):
            return live
    return same_url[0] if len(same_url) == 1 else None


@dataclass
class VnishData:
    """One polling round."""

    summary: dict[str, Any]
    settings: dict[str, Any] | None = None
    rpc_summary: dict[str, Any] | None = None
    presets: list[dict[str, Any]] = field(default_factory=list)
    rpc_pools: list[dict[str, Any]] = field(default_factory=list)
    info: dict[str, Any] = field(default_factory=dict)

    @property
    def state(self) -> str | None:
        state = _get(self.summary, "miner", "miner_status", "miner_state")
        return state if isinstance(state, str) else None

    @property
    def is_mining(self) -> bool | None:
        return None if self.state is None else self.state not in OFF_STATES

    @property
    def power(self) -> float | None:
        """Wall power in watts.

        `power_usage` is deprecated and, on recent firmware, equals the efficiency;
        it is only used when `power_consumption` is missing (older firmware).
        """
        miner = _get(self.summary, "miner")
        for key in ("power_consumption", "power_usage"):
            if (value := _num(_get(miner, key))) is not None:
                return value
        return None

    @property
    def hashrate_unit(self) -> str:
        """Unit of `hashrate`: the miner reports GH/s (SHA-256) or MH/s (Scrypt)."""
        return "GH/s" if _get(self.info, "hr_measure") == "MH/s" else "TH/s"

    def _scaled(self, value: Any) -> float | None:
        """Miner hashrate (GH/s or MH/s) -> `hashrate_unit` (TH/s or GH/s)."""
        number = _num(value)
        return None if number is None else number / 1000

    @property
    def hashrate(self) -> float | None:
        """Real-time hashrate in `hashrate_unit`.

        From /summary (`hr_realtime`, in the firmware's `hr_measure` unit), else from
        the RPC `GHS 5s` (SHA-256 only: its unit is not documented for Scrypt).
        """
        if (value := self._scaled(_get(self.summary, "miner", "hr_realtime"))) is not None:
            return value
        if self.hashrate_unit == "TH/s":
            return self._scaled(_get(self.rpc_summary, "GHS 5s"))
        return None

    @property
    def expected_hashrate(self) -> float | None:
        """Nominal hashrate of the current preset, in `hashrate_unit`."""
        return self._scaled(_get(self.summary, "miner", "hr_nominal"))

    @property
    def efficiency(self) -> float | None:
        """J/TH (J/GH for Scrypt miners)."""
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
    def fan_duty(self) -> float | None:
        """Overall fan speed in %."""
        return _num(_get(self.summary, "miner", "cooling", "fan_duty"))

    @property
    def hw_error_percent(self) -> float | None:
        return _num(_get(self.summary, "miner", "hw_errors_percent"))

    @property
    def throttle(self) -> float | None:
        """Current throttling level in % (100 = not throttled)."""
        return _num(_get(self.summary, "miner", "miner_status", "throttled"))

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
        """Pools of the miner's settings table, in table order (empty slots dropped)."""
        pools = _get(self.settings, "miner", "pools")
        if not isinstance(pools, list):
            return []
        return [p for p in pools if isinstance(p, dict) and p.get("url")]

    @property
    def pool_labels(self) -> list[str]:
        """'1', '2', ... : the position of each pool in the table."""
        return [str(i) for i in range(1, len(self.pools) + 1)]

    @property
    def live_pools(self) -> list[dict[str, Any]]:
        """Pools as the miner runs them: [{id, url, user, active}].

        From /summary (`pools[].id/status`), or from the RPC `pools` command on
        firmware whose summary has no pool list.
        """
        pools = _get(self.summary, "miner", "pools")
        if isinstance(pools, list):
            live = [
                {
                    "id": p["id"],
                    "url": str(p.get("url", "")),
                    "user": str(p.get("user", "")),
                    "active": p.get("status") == "active",
                }
                for p in pools
                if isinstance(p, dict) and isinstance(p.get("id"), int)
            ]
            if live:
                return live
        return [
            {
                "id": p["POOL"],
                "url": str(p.get("URL", "")),
                "user": str(p.get("User", "")),
                "active": p.get("Stratum Active") is True,
            }
            for p in self.rpc_pools
            if isinstance(p.get("POOL"), int)
        ]

    @property
    def active_pool(self) -> str | None:
        """Label of the pool the miner is currently connected to."""
        live_pools = self.live_pools
        for label, pool in zip(self.pool_labels, self.pools, strict=True):
            live = find_live_pool(pool, live_pools)
            if live is not None and live["active"]:
                return label
        return None

    def pool_by_label(self, label: str) -> dict[str, Any] | None:
        labels = self.pool_labels
        return self.pools[labels.index(label)] if label in labels else None

    def pool_id(self, label: str) -> int | None:
        """The miner's `pool_id` for a pool label, if the pool is running."""
        pool = self.pool_by_label(label)
        live = find_live_pool(pool, self.live_pools) if pool else None
        return live["id"] if live else None

    @property
    def boards(self) -> list[dict[str, Any]]:
        """Hashboards: [{hashrate, temperature, state}] in the miner's order."""
        chains = _get(self.summary, "miner", "chains")
        if not isinstance(chains, list):
            return []
        boards = []
        for chain in chains:
            state = _get(chain, "status", "state")
            boards.append(
                {
                    "hashrate": self._scaled(_get(chain, "hashrate_rt")),
                    "temperature": _num(_get(chain, "chip_temp", "max")),
                    "state": state if isinstance(state, str) else None,
                }
            )
        return boards

    @property
    def problems(self) -> list[str]:
        """What is wrong right now (empty when everything is fine)."""
        problems = []
        if self.state == "failure":
            problems.append("miner failure")
        problems += [
            f"board {i} failure" for i, b in enumerate(self.boards, 1) if b["state"] == "failure"
        ]
        fans = _get(self.summary, "miner", "cooling", "fans")
        if isinstance(fans, list):
            problems += [
                f"fan {i} lost"
                for i, fan in enumerate(fans, 1)
                if _get(fan, "status") == "lost"
            ]
        return problems

    @property
    def problem(self) -> bool | None:
        return None if self.state is None else bool(self.problems)
