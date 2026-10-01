"""Payload parsing: the miner's JSON may be incomplete, never crash on it."""

from __future__ import annotations

import pytest

from custom_components.vnish.models import (
    VnishData,
    firmware_version,
    mac_address,
    model,
)


def test_empty_payload_gives_no_values() -> None:
    data = VnishData(summary={})

    assert data.state is None
    assert data.is_mining is None
    assert data.power is None
    assert data.hashrate is None
    assert data.efficiency is None
    assert data.chip_temp is None
    assert data.fans == []
    assert data.preset is None
    assert data.preset_options == []


@pytest.mark.parametrize(
    ("state", "mining"),
    [
        ("mining", True),
        ("initializing", True),
        ("auto-tuning", True),
        ("stopped", False),
        ("shutting-down", False),
        ("failure", False),
    ],
)
def test_is_mining(state: str, mining: bool) -> None:
    data = VnishData(summary={"miner": {"miner_status": {"miner_state": state}}})

    assert data.is_mining is mining


def test_hashrate_converted_from_ghs_to_ths_and_efficiency() -> None:
    data = VnishData(
        summary={"miner": {"power_usage": 3000}},
        rpc_summary={"GHS 5s": "100000.0"},  # cgminer sometimes sends strings
    )

    assert data.hashrate == 100.0
    assert data.efficiency == 30.0


def test_efficiency_needs_a_running_miner() -> None:
    data = VnishData(summary={"miner": {"power_usage": 50}}, rpc_summary={"GHS 5s": 0})

    assert data.efficiency is None


def test_temperature_falls_back_to_hottest_chain() -> None:
    data = VnishData(
        summary={
            "miner": {
                "chains": [
                    {"chip_temp": {"max": 70}, "pcb_temp": {"max": 55}},
                    {"chip_temp": {"max": 82}},
                    {"chip_temp": None},
                ]
            }
        }
    )

    assert data.chip_temp == 82
    assert data.pcb_temp == 55


def test_garbage_values_are_ignored() -> None:
    data = VnishData(
        summary={"miner": {"power_usage": "n/a", "cooling": {"fans": [{"rpm": None}, "x"]}}}
    )

    assert data.power is None
    assert data.fans == [None, None]


def test_preset_options_and_current() -> None:
    data = VnishData(
        summary={},
        settings={"miner": {"overclock": {"preset": 3250}}},
        presets=[{"name": "2000"}, {"name": 3250}, {"pretty": "no name"}],
    )

    assert data.preset == "3250"
    assert data.preset_options == ["2000", "3250"]


def test_identity_helpers() -> None:
    summary = {
        "miner": {"miner_type": "Antminer S19 XP (Vnish 1.2.6)"},
        "system": {"network_status": {"mac": "AA:BB"}},
    }

    assert model(summary) == "Antminer S19 XP"
    assert firmware_version(summary) == "1.2.6"
    assert mac_address(summary) == "AA:BB"
    assert model({}) is None
    assert firmware_version({"miner": {"miner_type": "Antminer S19"}}) is None


def test_pool_labels_hide_user_unless_urls_clash() -> None:
    data = VnishData(
        summary={},
        settings={
            "miner": {
                "pools": [
                    {"url": "a:1", "user": "u1"},
                    {"url": "", "user": ""},
                    {"url": "b:1", "user": "u1"},
                    {"url": "b:1", "user": "u2"},
                ]
            }
        },
    )

    assert data.pool_labels == ["a:1", "b:1 (u1)", "b:1 (u2)"]
