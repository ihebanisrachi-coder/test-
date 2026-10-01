"""Async client for the Vnish firmware (REST API + CGMiner-style RPC)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)
RPC_TIMEOUT = 5


class VnishError(Exception):
    """Base error for the Vnish client."""


class VnishConnectionError(VnishError):
    """The miner could not be reached."""


class VnishAuthError(VnishError):
    """The miner rejected the web password or the token."""


class VnishApiError(VnishError):
    """The miner answered with something unexpected."""


class VnishClient:
    """Talk to a Vnish miner.

    Authentication: ``POST /api/v1/unlock {"pw": "<password>"}`` returns a token
    that is sent back in the ``Authorization`` header. Endpoints below ``system/``
    expect ``Bearer <token>``, all the others the bare token. The token is
    renewed transparently when the miner rejects it.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        password: str,
        *,
        port: int = 80,
        rpc_port: int = 4028,
    ) -> None:
        self._session = session
        self._host = host
        self._password = password
        self._base = f"http://{host}:{port}/api/v1"
        self._rpc_port = rpc_port
        self._token: str | None = None
        self._auth_lock = asyncio.Lock()

    @property
    def host(self) -> str:
        return self._host

    async def authenticate(self) -> None:
        """Unlock the web API and store the token."""
        async with self._auth_lock:
            try:
                async with self._session.post(
                    f"{self._base}/unlock",
                    json={"pw": self._password},
                    timeout=REQUEST_TIMEOUT,
                ) as resp:
                    if 400 <= resp.status < 500:
                        raise VnishAuthError(f"Unlock refused (HTTP {resp.status})")
                    if resp.status != 200:
                        raise VnishApiError(f"Unlock failed (HTTP {resp.status})")
                    data = await resp.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError) as err:
                raise VnishConnectionError(f"Cannot reach {self._host}: {err}") from err
            except ValueError as err:
                raise VnishApiError("Unlock returned invalid JSON") from err

            token = data.get("token") if isinstance(data, dict) else None
            if not token:
                raise VnishApiError("Unlock did not return a token")
            self._token = token

    def _auth_header(self, path: str) -> str:
        assert self._token is not None
        return f"Bearer {self._token}" if path.startswith("system") else self._token

    async def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> Any:
        for attempt in (1, 2):
            if self._token is None:
                await self.authenticate()
            try:
                async with self._session.request(
                    method,
                    f"{self._base}/{path}",
                    headers={"Authorization": self._auth_header(path)},
                    json=body,
                    timeout=REQUEST_TIMEOUT,
                ) as resp:
                    status = resp.status
                    text = await resp.text()
            except (aiohttp.ClientError, TimeoutError) as err:
                raise VnishConnectionError(f"Cannot reach {self._host}: {err}") from err

            if status in (401, 403):
                self._token = None  # expired token: unlock again, retry once
                if attempt == 2:
                    raise VnishAuthError(f"{method} {path} refused (HTTP {status})")
                continue
            if status != 200:
                raise VnishApiError(f"{method} {path} returned HTTP {status}")
            if not text.strip():
                return {}
            try:
                return json.loads(text)
            except ValueError as err:
                raise VnishApiError(f"{method} {path} returned invalid JSON") from err
        raise VnishApiError(f"{method} {path} failed")  # pragma: no cover

    # --- read ---------------------------------------------------------------

    async def info(self) -> dict[str, Any]:
        return await self._request("GET", "info")

    async def summary(self) -> dict[str, Any]:
        return await self._request("GET", "summary")

    async def settings(self) -> dict[str, Any]:
        return await self._request("GET", "settings")

    async def presets(self) -> list[dict[str, Any]]:
        """Autotune presets; the miner answers with a list or {"presets": [...]}."""
        data = await self._request("GET", "autotune/presets")
        if isinstance(data, dict):
            data = data.get("presets", [])
        return [p for p in data if isinstance(p, dict)] if isinstance(data, list) else []

    async def _rpc(self, command: str, parameter: Any = None) -> dict[str, Any]:
        """One CGMiner API call (port 4028); the miner closes the socket after replying."""
        payload: dict[str, Any] = {"command": command}
        if parameter is not None:
            payload["parameter"] = str(parameter)
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._rpc_port), RPC_TIMEOUT
            )
            try:
                writer.write(json.dumps(payload).encode())
                await writer.drain()
                raw = await asyncio.wait_for(reader.read(-1), RPC_TIMEOUT)
            finally:
                writer.close()
                with contextlib.suppress(OSError):
                    await writer.wait_closed()
        except (OSError, TimeoutError) as err:
            raise VnishConnectionError(f"RPC {self._host}: {err}") from err
        try:
            return json.loads(raw.rstrip(b"\x00").decode())
        except ValueError as err:
            raise VnishApiError(f"Unexpected RPC {command} answer") from err

    async def rpc_summary(self) -> dict[str, Any]:
        """CGMiner ``summary`` command; its hashrate is in GH/s."""
        try:
            return (await self._rpc("summary"))["SUMMARY"][0]
        except (KeyError, IndexError, TypeError) as err:
            raise VnishApiError("Unexpected RPC summary answer") from err

    async def rpc_pools(self) -> list[dict[str, Any]]:
        """CGMiner ``pools`` command: URL, User, Status, ``Stratum Active``."""
        try:
            pools = (await self._rpc("pools"))["POOLS"]
        except (KeyError, TypeError) as err:
            raise VnishApiError("Unexpected RPC pools answer") from err
        return [p for p in pools if isinstance(p, dict)]

    # --- commands -----------------------------------------------------------

    async def _command(self, path: str) -> None:
        await self._request("POST", path, {})

    async def pause_mining(self) -> None:
        await self._command("mining/pause")

    async def resume_mining(self) -> None:
        await self._command("mining/resume")

    async def start_mining(self) -> None:
        await self._command("mining/start")

    async def stop_mining(self) -> None:
        await self._command("mining/stop")

    async def restart_mining(self) -> None:
        await self._command("mining/restart")

    async def reboot(self) -> None:
        await self._command("system/reboot")

    async def _apply_miner_settings(self, miner: dict[str, Any], what: str) -> None:
        """POST a partial ``miner`` settings block, honouring restart requests."""
        result = await self._request("POST", "settings", {"miner": miner})
        if isinstance(result, dict):
            if result.get("restart_required"):
                await self.restart_mining()
            if result.get("reboot_required"):
                _LOGGER.warning("%s needs a reboot to apply %s", self._host, what)

    async def _miner_settings(self, key: str) -> Any:
        try:
            return (await self.settings())["miner"][key]
        except (KeyError, TypeError) as err:
            raise VnishApiError("Unexpected settings layout") from err

    async def set_preset(self, preset: str) -> None:
        """Select an autotune preset (e.g. a power level) and make sure it stuck."""
        overclock = await self._miner_settings("overclock")
        await self._apply_miner_settings(
            {"overclock": {**overclock, "preset": preset}}, f"preset {preset}"
        )
        # The answer does not say whether the change was accepted: read it back.
        applied = (await self._miner_settings("overclock")).get("preset")
        if applied != preset:
            raise VnishApiError(f"Preset {preset!r} was not applied (still {applied!r})")

    async def switch_pool(self, pool_id: int) -> None:
        """Connect to another configured pool right now.

        Only the active pool changes: the pool table is not rewritten and mining
        is not restarted. `pool_id` is the pool's `id` in /summary.
        """
        await self._request("POST", "mining/switch-pool", {"pool_id": pool_id})
