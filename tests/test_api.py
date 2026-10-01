"""VnishClient against a fake miner speaking real HTTP/TCP."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest
from aiohttp import web

from custom_components.vnish.api import (
    VnishApiError,
    VnishAuthError,
    VnishClient,
    VnishConnectionError,
)

from .fake_vnish import FakeVnish


@pytest.fixture
async def session(socket_enabled):
    async with aiohttp.ClientSession() as session:
        yield session


@pytest.fixture
async def fake(socket_enabled):
    fake = FakeVnish()
    runner = web.AppRunner(fake.app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    rpc = await asyncio.start_server(fake.rpc, "127.0.0.1", 0)
    fake.port = site._server.sockets[0].getsockname()[1]
    fake.rpc_port = rpc.sockets[0].getsockname()[1]
    yield fake
    rpc.close()
    await rpc.wait_closed()
    await runner.cleanup()


def make_client(session, fake: FakeVnish, password: str = "admin") -> VnishClient:
    return VnishClient(
        session, "127.0.0.1", password, port=fake.port, rpc_port=fake.rpc_port
    )


async def test_unlock_then_bare_token(session, fake):
    data = await make_client(session, fake).summary()

    assert data["miner"]["power_usage"] == 3250
    assert fake.calls == [
        ("POST", "unlock", None),
        ("GET", "summary", "tok-1"),
    ]


async def test_system_endpoints_use_bearer(session, fake):
    await make_client(session, fake).reboot()

    assert fake.calls[-1] == ("POST", "system/reboot", "Bearer tok-1")


async def test_token_is_reused(session, fake):
    client = make_client(session, fake)
    await client.summary()
    await client.settings()

    assert [c[1] for c in fake.calls].count("unlock") == 1


async def test_expired_token_is_renewed(session, fake):
    client = make_client(session, fake)
    await client.summary()
    fake.token = "tok-2"  # the miner rebooted and forgot our token

    await client.summary()

    assert fake.calls[-2:] == [("POST", "unlock", None), ("GET", "summary", "tok-2")]


async def test_wrong_password(session, fake):
    with pytest.raises(VnishAuthError):
        await make_client(session, fake, "nope").summary()


async def test_unreachable_miner(session, fake):
    fake.port = 1  # nothing listens there
    with pytest.raises(VnishConnectionError):
        await make_client(session, fake).summary()


@pytest.mark.parametrize("wrap", [False, True])
async def test_presets_accepts_list_or_dict(session, fake, wrap):
    if wrap:
        fake.presets = {"presets": fake.presets}

    presets = await make_client(session, fake).presets()

    assert [p["name"] for p in presets] == ["2000", "3250"]


async def test_mining_commands_hit_the_right_endpoints(session, fake):
    client = make_client(session, fake)
    await client.pause_mining()
    await client.resume_mining()
    await client.start_mining()
    await client.stop_mining()
    await client.restart_mining()

    paths = [c[1] for c in fake.calls if c[1] != "unlock"]
    assert paths == [
        "mining/pause",
        "mining/resume",
        "mining/start",
        "mining/stop",
        "mining/restart",
    ]


async def test_set_preset_keeps_other_overclock_settings(session, fake):
    await make_client(session, fake).set_preset("2000")

    sent = fake.bodies["settings"]["miner"]["overclock"]
    assert sent == {"preset": "2000", "globals": {"volt": 0, "freq": 0}}
    assert "mining/restart" not in [c[1] for c in fake.calls]


async def test_set_preset_restarts_when_asked(session, fake):
    fake.settings_reply = {"restart_required": True, "reboot_required": False}

    await make_client(session, fake).set_preset("2000")

    assert "mining/restart" in [c[1] for c in fake.calls]


async def test_set_preset_detects_silent_rejection(session, fake):
    fake.apply_settings = False

    with pytest.raises(VnishApiError, match="not applied"):
        await make_client(session, fake).set_preset("2000")


async def test_rpc_summary(session, fake):
    data = await make_client(session, fake).rpc_summary()

    assert data["GHS 5s"] == 110500.0


async def test_rpc_unreachable(session, fake):
    fake.rpc_port = 1
    with pytest.raises(VnishConnectionError):
        await make_client(session, fake).rpc_summary()


async def test_switch_pool_uses_rpc_only(session, fake):
    await make_client(session, fake).switch_pool("backup.example:3333", "wallet.worker")

    assert ("switchpool", "1") in fake.rpc_commands
    assert fake.rpc_pools[1]["Stratum Active"] is True
    # Pool table untouched, mining not restarted.
    assert "settings" not in fake.bodies
    assert not [c for c in fake.calls if c[0] == "POST" and c[1] != "unlock"]


async def test_switch_pool_to_the_first_pool_sends_index_zero(session, fake):
    await make_client(session, fake).switch_pool("pool.example:3333", "wallet.worker")

    assert ("switchpool", "0") in fake.rpc_commands


async def test_switch_pool_matches_url_when_user_differs(session, fake):
    await make_client(session, fake).switch_pool("backup.example:3333", "other-user")

    assert ("switchpool", "1") in fake.rpc_commands


async def test_switch_pool_unknown(session, fake):
    with pytest.raises(VnishApiError, match="not known"):
        await make_client(session, fake).switch_pool("nope:1", "x")


async def test_switch_pool_refused_by_readonly_rpc(session, fake):
    fake.rpc_write_allowed = False

    with pytest.raises(VnishApiError, match="Access denied"):
        await make_client(session, fake).switch_pool("backup.example:3333", "wallet.worker")


async def test_rpc_pools(session, fake):
    pools = await make_client(session, fake).rpc_pools()

    assert [p["POOL"] for p in pools] == [0, 1]
