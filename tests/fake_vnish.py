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
        "miner_status": {"miner_state": "mining", "miner_state_time": 3600},
        "power_usage": 3250,
        "chip_temp": {"min": 60, "max": 78},
        "pcb_temp": {"min": 50, "max": 65},
        "cooling": {
            "fan_num": 4,
            "fans": [
                {"id": 0, "rpm": 5400, "status": "ok", "max_rpm": 6000},
                {"id": 1, "rpm": 5390, "status": "ok", "max_rpm": 6000},
                {"id": 2, "rpm": 5410, "status": "ok", "max_rpm": 6000},
                {"id": 3, "rpm": 5420, "status": "ok", "max_rpm": 6000},
            ],
        },
        "chains": [],
    },
    "system": {
        "network_status": {"mac": "AA:BB:CC:DD:EE:FF", "hostname": "antminer-s19"}
    },
}

SETTINGS: dict[str, Any] = {
    "miner": {
        "overclock": {"preset": "3250", "globals": {"volt": 0, "freq": 0}},
        "cooling": {"mode": {"name": "auto", "param": 65}},
        "pools": [{"url": "pool.example:3333", "user": "wallet.worker", "pass": "x"}],
    }
}

PRESETS: list[dict[str, Any]] = [
    {"name": "2000", "pretty": "2000 watt ~ 70 TH", "status": "tuned", "modded_psu_required": False},
    {"name": "3250", "pretty": "3250 watt ~ 110 TH", "status": "tuned", "modded_psu_required": False},
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
        self.settings_reply: dict[str, Any] = {"restart_required": False, "reboot_required": False}
        self.apply_settings = True
        self.rpc_ghs = 110500.0
        self.app = web.Application()
        self.app.add_routes(
            [
                web.post("/api/v1/unlock", self.unlock),
                web.get("/api/v1/summary", self.get_summary),
                web.get("/api/v1/settings", self.get_settings),
                web.post("/api/v1/settings", self.post_settings),
                web.get("/api/v1/autotune/presets", self.get_presets),
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
            self.settings["miner"]["overclock"] = body["miner"]["overclock"]
        return web.json_response(self.settings_reply)

    async def get_presets(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.Response(status=401)
        return web.json_response(self.presets)

    async def command(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.Response(status=401)
        return web.json_response({"success": True})

    async def rpc(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read(1024)
        payload = {"STATUS": [{"STATUS": "S"}], "SUMMARY": [{"GHS 5s": self.rpc_ghs}], "id": 1}
        writer.write(json.dumps(payload).encode() + b"\x00")
        await writer.drain()
        writer.close()
