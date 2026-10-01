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
        summary={"miner": {"power_consumption": 3000}},
        rpc_summary={"GHS 5s": "100000.0"},  # cgminer sometimes sends strings
    )

    assert data.hashrate == 100.0
    assert data.efficiency == 30.0


def test_efficiency_needs_a_running_miner() -> None:
    data = VnishData(summary={"miner": {"power_consumption": 50}}, rpc_summary={"GHS 5s": 0})

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


def _pool_data(active_url: str, *, source: str = "summary") -> VnishData:
    data = VnishData(
        summary={},
        settings={
            "miner": {
                "pools": [
                    {"url": "a:1", "user": "u"},
                    {"url": "", "user": ""},
                    {"url": "b:1", "user": "u"},
                ]
            }
        },
    )
    if source == "summary":
        data.summary = {
            "miner": {
                "pools": [
                    {"id": 0, "url": "stratum+tcp://A:1/", "user": "u", "status": "active" if active_url == "a:1" else "working"},
                    {"id": 1, "url": "b:1", "user": "u", "status": "active" if active_url == "b:1" else "working"},
                    {"id": 2, "url": "DevFee", "user": "dev", "status": "working"},
                ]
            }
        }
    else:
        data.rpc_pools = [
            {"POOL": 0, "URL": "a:1", "User": "u", "Stratum Active": active_url == "a:1"},
            {"POOL": 1, "URL": "b:1", "User": "u", "Stratum Active": active_url == "b:1"},
        ]
    return data


def test_pool_numbers_follow_the_settings_table() -> None:
    data = _pool_data("a:1")

    assert [p["url"] for p in data.pools] == ["a:1", "b:1"]
    assert data.pool_labels == ["1", "2"]
    assert data.pool_by_label("2")["url"] == "b:1"
    assert data.pool_by_label("9") is None


@pytest.mark.parametrize("source", ["summary", "rpc"])
@pytest.mark.parametrize(("active", "label"), [("a:1", "1"), ("b:1", "2"), ("", None)])
def test_active_pool(source: str, active: str, label: str | None) -> None:
    assert _pool_data(active, source=source).active_pool == label


@pytest.mark.parametrize("source", ["summary", "rpc"])
def test_pool_id_is_the_miners_id_not_the_label(source: str) -> None:
    data = _pool_data("a:1", source=source)

    assert data.pool_id("1") == 0
    assert data.pool_id("2") == 1
    assert data.pool_id("9") is None


def test_pool_id_unknown_when_the_pool_is_not_running() -> None:
    data = _pool_data("a:1")
    data.summary["miner"]["pools"].pop(1)

    assert data.pool_id("2") is None


def test_power_prefers_power_consumption_over_deprecated_power_usage() -> None:
    both = VnishData(summary={"miner": {"power_consumption": 3250, "power_usage": 29.5}})
    old_firmware = VnishData(summary={"miner": {"power_usage": 3100}})

    assert both.power == 3250
    assert old_firmware.power == 3100


def test_summary_hashrate_wins_over_rpc() -> None:
    data = VnishData(
        summary={"miner": {"hr_realtime": 100000}}, rpc_summary={"GHS 5s": 1.0}
    )

    assert data.hashrate == 100.0
    assert data.hashrate_unit == "TH/s"


def test_scrypt_miners_use_mhs_and_ignore_the_rpc_unit() -> None:
    scrypt = {"hr_measure": "MH/s"}

    assert VnishData(summary={"miner": {"hr_realtime": 9500}}, info=scrypt).hashrate == 9.5
    assert VnishData(summary={"miner": {"hr_realtime": 9500}}, info=scrypt).hashrate_unit == "GH/s"
    # The RPC unit is only known for SHA-256: no guessing for Scrypt.
    assert VnishData(summary={}, rpc_summary={"GHS 5s": 9500}, info=scrypt).hashrate is None


def test_boards_and_problems() -> None:
    data = VnishData(
        summary={
            "miner": {
                "miner_status": {"miner_state": "mining"},
                "chains": [
                    {"hashrate_rt": 50000, "chip_temp": {"max": 70}, "status": {"state": "mining"}},
                    {"hashrate_rt": 0, "status": {"state": "failure"}},
                ],
                "cooling": {"fans": [{"rpm": 5000, "status": "ok"}, {"rpm": 0, "status": "lost"}]},
            }
        }
    )

    assert data.boards == [
        {"hashrate": 50.0, "temperature": 70.0, "state": "mining"},
        {"hashrate": 0.0, "temperature": None, "state": "failure"},
    ]
    assert data.problems == ["board 2 failure", "fan 2 lost"]
    assert data.problem is True


def test_problem_unknown_without_state_and_false_when_healthy() -> None:
    assert VnishData(summary={}).problem is None
    healthy = VnishData(summary={"miner": {"miner_status": {"miner_state": "mining"}}})
    assert healthy.problem is False
    assert VnishData(summary={"miner": {"miner_status": {"miner_state": "failure"}}}).problems == [
        "miner failure"
    ]


def test_throttle_fan_duty_and_error_rate() -> None:
    data = VnishData(
        summary={
            "miner": {
                "miner_status": {"throttled": 60},
                "cooling": {"fan_duty": 55},
                "hw_errors_percent": 0.5,
                "hr_nominal": 112000,
            }
        }
    )

    assert (data.throttle, data.fan_duty, data.hw_error_percent) == (60, 55, 0.5)
    assert data.expected_hashrate == 112.0


def test_identity_prefers_info() -> None:
    info = {"miner": "Antminer S19j Pro", "fw_version": "1.3.0"}
    summary = {"miner": {"miner_type": "Antminer S19 (Vnish 1.2.6)"}}

    assert model(summary, info) == "Antminer S19j Pro"
    assert firmware_version(summary, info) == "1.3.0"
    assert model(summary) == "Antminer S19"
