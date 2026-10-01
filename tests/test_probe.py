"""The probe must never leak credentials."""

from __future__ import annotations

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "vnish_probe", Path(__file__).parent.parent / "tools" / "vnish_probe.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_redact_removes_secrets_and_truncates_macs() -> None:
    out = probe.redact(
        {
            "miner": {"pools": [{"url": "pool:3333", "user": "wallet.w1", "pass": "x"}]},
            "system": {"network_status": {"mac": "AA:BB:CC:DD:EE:FF"}},
            "token": "abc",
        }
    )

    pool = out["miner"]["pools"][0]
    assert pool == {"url": "pool:3333", "user": "<redacted>", "pass": "<redacted>"}
    assert out["system"]["network_status"]["mac"] == "AA:BB:CC:xx:xx:xx"
    assert out["token"] == "<redacted>"


def test_api_paths_lists_methods_only() -> None:
    spec = {
        "paths": {
            "/mining/pause": {"post": {"summary": "x"}, "parameters": []},
            "/summary": {"get": {}},
        }
    }

    assert probe.api_paths(spec) == {"/mining/pause": ["POST"], "/summary": ["GET"]}
    assert probe.api_paths("not a spec") == {}
