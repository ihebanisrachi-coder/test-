"""A tiny stand-in for a Vnish miner (REST API + CGMiner RPC)."""

from __future__ import annotations

import asyncio
import copy
import json
from typing import Any

from aiohttp import web

SUMMARY: dict[str, Any] = {
    "miner": {
        "miner_type": "Antminer S19 (Vnish 1.2.6)",
        "miner_status": {"miner_state": "mining", "miner_state_time": 3600, "throttled": 100},
        "hr_realtime": 110500.0,
        "hr_nominal": 112000.0,
        "hw_errors_percent": 0.02,
        "power_usage": 29.5,  # deprecated: efficiency, not watts
        "power_consumption": 3250,
        "chip_temp": {"min": 60, "max": 78},
        "pcb_temp": {"min": 50, "max": 65},
        "cooling": {
            "fan_num": 4,
            "fan_duty": 72,
            "fans": [
                {"id": 0, "rpm": 5400, "status": "ok", "max_rpm": 6000},
                {"id": 1, "rpm": 5390, "status": "ok", "max_rpm": 6000},
                {"id": 2, "rpm": 5410, "status": "ok", "max_rpm": 6000},
                {"id": 3, "rpm": 5420, "status": "ok", "max_rpm": 6000},
            ],
        },
        "chains": [
            {"id": 0, "hashrate_rt": 55000.0, "chip_temp": {"min": 60, "max": 76}, "status": {"state": "mining"}},
            {"id": 1, "hashrate_rt": 55500.0, "chip_temp": {"min": 62, "max": 78}, "status": {"state": "mining"}},
        ],
        "pools": [
            {"id": 0, "url": "pool.example:3333", "user": "wallet.worker", "pool_type": "UserPool", "status": "active"},
            {"id": 1, "url": "backup.example:3333", "user": "wallet.worker", "pool_type": "UserPool", "status": "working"},
            {"id": 2, "url": "DevFee", "user": "dev", "pool_type": "DevFee", "status": "working"},
        ],
    },
    "system": {
        "network_status": {"mac": "AA:BB:CC:DD:EE:FF", "hostname": "antminer-s19"}
    },
}

SETTINGS: dict[str, Any] = {
    "miner": {
        "overclock": {"preset": "3250", "globals": {"volt": 0, "freq": 0}},
        "cooling": {"mode": {"name": "auto", "param": 65}},
        "pools": [
            {"url": "pool.example:3333", "user": "wallet.worker", "pass": "x"},
            {"url": "backup.example:3333", "user": "wallet.worker", "pass": "y"},
            {"url": "", "user": "", "pass": ""},
        ],
    }
}

PERF_SUMMARY: dict[str, Any] = {
    "preset_switcher": {"enabled": False},
    "current_preset": {"name": "3250", "pretty": "3250 watt ~ 110 TH", "status": "tuned"},
}

PRESETS: list[dict[str, Any]] = [
    {"name": "2000", "pretty": "2000 watt ~ 70 TH", "status": "tuned", "modded_psu_required": False},
    {"name": "3250", "pretty": "3250 watt ~ 110 TH", "status": "tuned", "modded_psu_required": False},
    {"name": "1500", "pretty": "1500 watt ~ 50 TH", "status": "untuned", "modded_psu_required": False},
]


INFO: dict[str, Any] = {
    "fw_name": "Vnish",
    "fw_version": "1.2.6",
    "miner": "Antminer S19j Pro",
    "model": "s19jpro",
    "algorithm": "sha256d",
    "hr_measure": "GH/s",
    "serial": "SN123456",
    "system": {
        "network_status": {"mac": "AA:BB:CC:DD:EE:FF", "hostname": "antminer-s19", "ip": "192.168.1.50"}
    },
}

RPC_POOLS: list[dict[str, Any]] = [
    {"POOL": 0, "URL": "stratum+tcp://pool.example:3333", "User": "wallet.worker",
     "Status": "Alive", "Stratum Active": True},
    {"POOL": 1, "URL": "stratum+tcp://backup.example:3333", "User": "wallet.worker",
     "Status": "Alive", "Stratum Active": False},
]


class FakeVnish:
    def __init__(self, password: str = "admin") -> None:
        self.password = password
        self.token = "tok-1"
        self.calls: list[tuple[str, str, str | None]] = []  # method, path, auth header
        self.bodies: dict[str, Any] = {}
        self.summary = copy.deepcopy(SUMMARY)
        self.settings = copy.deepcopy(SETTINGS)
        self.presets: Any = copy.deepcopy(PRESETS)
        self.perf_summary = copy.deepcopy(PERF_SUMMARY)
        self.settings_reply: dict[str, Any] = {"restart_required": False, "reboot_required": False}
        self.apply_settings = True
        self.has_switch_pool = True
        self.rpc_ghs = 110500.0
        self.rpc_pools = copy.deepcopy(RPC_POOLS)
        self.rpc_commands: list[tuple[str, str | None]] = []
        self.app = web.Application()
        self.app.add_routes(
            [
                web.post("/api/v1/unlock", self.unlock),
                web.get("/api/v1/summary", self.get_summary),
                web.get("/api/v1/settings", self.get_settings),
                web.post("/api/v1/settings", self.post_settings),
                web.get("/api/v1/autotune/presets", self.get_presets),
                web.get("/api/v1/info", self.get_info),
                web.get("/api/v1/perf-summary", self.get_perf_summary),
                web.post("/api/v1/mining/throttle", self.throttle),
                web.post("/api/v1/mining/switch-pool", self.switch_pool),
                web.post("/api/v1/{tail:.*}", self.command),
            ]
        )

    # -- helpers -----------------------------------------------------------
    def _record(self, request: web.Request) -> str | None:
        auth = request.headers.get("Authorization")
        self.calls.append((request.method, request.path.removeprefix("/api/v1/"), auth))
        return auth

    def _authorized(self, request: web.Request) -> bool:
        auth = self._record(request)
        expected = self.token
        if request.path.startswith("/api/v1/system"):
            expected = f"Bearer {self.token}"
        return auth == expected

    # -- handlers ----------------------------------------------------------
    async def unlock(self, request: web.Request) -> web.Response:
        self._record(request)
        body = await request.json()
        if body.get("pw") != self.password:
            return web.json_response({"error": "bad password"}, status=403)
        return web.json_response({"token": self.token})

    async def get_summary(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.Response(status=401)
        return web.json_response(self.summary)

    async def get_settings(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.Response(status=401)
        return web.json_response(self.settings)

    async def post_settings(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.Response(status=401)
        body = await request.json()
        self.bodies["settings"] = body
        if self.apply_settings:
            miner = dict(body["miner"])
            if "overclock" in miner:  # merge: fields that are not sent are kept
                miner["overclock"] = {**self.settings["miner"]["overclock"], **miner["overclock"]}
            self.settings["miner"].update(miner)
        return web.json_response(self.settings_reply)

    async def get_presets(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.Response(status=401)
        return web.json_response(self.presets)

    async def get_perf_summary(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.Response(status=401)
        return web.json_response(self.perf_summary)

    async def get_info(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.Response(status=401)
        return web.json_response(INFO)

    async def throttle(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.Response(status=401)
        self.bodies["throttle"] = await request.json()
        return web.json_response(self.settings_reply)

    async def switch_pool(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.Response(status=401)
        if not self.has_switch_pool:
            return web.Response(status=404)
        body = await request.json()
        self.bodies["switch-pool"] = body
        for pool in self.summary["miner"]["pools"]:
            pool["status"] = "active" if pool["id"] == body["pool_id"] else "working"
        return web.json_response({})

    async def command(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.Response(status=401)
        return web.json_response({"success": True})

    async def rpc(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request = json.loads((await reader.read(1024)).decode())
        command, parameter = request["command"], request.get("parameter")
        self.rpc_commands.append((command, parameter))
        if command == "summary":
            reply: dict[str, Any] = {"STATUS": [{"STATUS": "S"}], "SUMMARY": [{"GHS 5s": self.rpc_ghs}]}
        elif command == "pools":
            reply = {"STATUS": [{"STATUS": "S"}], "POOLS": self.rpc_pools}
        else:
            reply = {"STATUS": [{"STATUS": "E", "Msg": f"Access denied to '{command}' command"}]}
        writer.write(json.dumps(reply).encode() + b"\x00")
        await writer.drain()
        writer.close()
