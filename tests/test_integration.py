from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.vnish.api import (
    VnishApiError,
    VnishAuthError,
    VnishConnectionError,
)

# Device name is the miner hostname -> "antminer-s19" -> "antminer_s19".
P = "antminer_s19"


async def _setup(hass: HomeAssistant, entry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_sensors(hass: HomeAssistant, client, entry) -> None:
    await _setup(hass, entry)

    assert hass.states.get(f"sensor.{P}_state").state == "mining"
    assert hass.states.get(f"sensor.{P}_hashrate").state == "110.5"
    assert hass.states.get(f"sensor.{P}_power").state == "3250.0"
    assert float(hass.states.get(f"sensor.{P}_efficiency").state) == pytest.approx(29.41, abs=0.01)
    assert hass.states.get(f"sensor.{P}_chip_temperature").state == "78.0"
    assert hass.states.get(f"sensor.{P}_pcb_temperature").state == "65.0"
    for fan in range(1, 5):
        assert hass.states.get(f"sensor.{P}_fan_{fan}") is not None
    assert hass.states.get(f"sensor.{P}_fan_1").state == "5400.0"
    assert hass.states.get(f"sensor.{P}_fan_5") is None


async def test_rpc_failure_does_not_lose_the_hashrate(hass: HomeAssistant, client, entry) -> None:
    client.rpc_summary.side_effect = VnishConnectionError("closed")

    await _setup(hass, entry)

    assert hass.states.get(f"sensor.{P}_hashrate").state == "110.5"  # from /summary
    assert hass.states.get(f"sensor.{P}_power").state == "3250.0"


async def test_hashrate_unknown_without_summary_value_and_rpc(hass: HomeAssistant, client, entry) -> None:
    del client.summary.return_value["miner"]["hr_realtime"]
    client.rpc_summary.side_effect = VnishConnectionError("closed")

    await _setup(hass, entry)

    assert hass.states.get(f"sensor.{P}_hashrate").state == STATE_UNKNOWN


async def test_hashrate_falls_back_to_rpc(hass: HomeAssistant, client, entry) -> None:
    del client.summary.return_value["miner"]["hr_realtime"]

    await _setup(hass, entry)

    assert hass.states.get(f"sensor.{P}_hashrate").state == "110.5"


async def test_mining_switch(hass: HomeAssistant, client, entry) -> None:
    await _setup(hass, entry)
    switch = f"switch.{P}_mining"
    assert hass.states.get(switch).state == STATE_ON

    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: switch}, blocking=True
    )
    client.stop_mining.assert_awaited_once()

    client.summary.return_value["miner"]["miner_status"]["miner_state"] = "stopped"
    await entry.runtime_data.async_refresh()
    assert hass.states.get(switch).state == STATE_OFF

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: switch}, blocking=True
    )
    # Mining was fully stopped: it must be started again, not resumed.
    client.start_mining.assert_awaited_once()
    client.resume_mining.assert_not_awaited()


async def test_turn_on_after_pause_resumes_and_falls_back_to_start(
    hass: HomeAssistant, client, entry
) -> None:
    client.resume_mining.side_effect = VnishApiError("HTTP 409")
    await _setup(hass, entry)

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: f"switch.{P}_mining"}, blocking=True
    )

    client.start_mining.assert_awaited_once()


async def test_command_failure_is_reported(hass: HomeAssistant, client, entry) -> None:
    client.stop_mining.side_effect = VnishConnectionError("down")
    await _setup(hass, entry)

    with pytest.raises(HomeAssistantError, match="Vnish command failed"):
        await hass.services.async_call(
            "switch", "turn_off", {ATTR_ENTITY_ID: f"switch.{P}_mining"}, blocking=True
        )


@pytest.mark.parametrize(
    ("button", "method"),
    [
        ("reboot", "reboot"),
        ("restart_mining", "restart_mining"),
        ("pause_mining", "pause_mining"),
        ("resume_mining", "resume_mining"),
    ],
)
async def test_buttons(hass: HomeAssistant, client, entry, button, method) -> None:
    await _setup(hass, entry)

    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: f"button.{P}_{button}"}, blocking=True
    )

    getattr(client, method).assert_awaited_once()


async def test_preset_select(hass: HomeAssistant, client, entry) -> None:
    await _setup(hass, entry)
    select = f"select.{P}_preset"
    state = hass.states.get(select)
    assert state.state == "3250"
    # The untuned preset is not offered: selecting it would start an autotune.
    assert state.attributes["options"] == ["2000", "3250"]
    assert state.attributes["2000"] == "2000 watt ~ 70 TH"

    await hass.services.async_call(
        "select", "select_option", {ATTR_ENTITY_ID: select, "option": "2000"}, blocking=True
    )

    client.set_preset.assert_awaited_once_with("2000")


async def test_preset_unknown_when_manual_overclock(hass: HomeAssistant, client, entry) -> None:
    client.settings.return_value["miner"]["overclock"]["preset"] = "disabled"

    await _setup(hass, entry)

    assert hass.states.get(f"select.{P}_preset").state == STATE_UNKNOWN


async def test_miner_offline_makes_entities_unavailable(hass: HomeAssistant, client, entry) -> None:
    await _setup(hass, entry)
    client.summary.side_effect = VnishConnectionError("down")

    await entry.runtime_data.async_refresh()

    assert hass.states.get(f"sensor.{P}_power").state == "unavailable"


async def test_bad_password_starts_reauth(hass: HomeAssistant, client, entry) -> None:
    client.summary.side_effect = VnishAuthError("refused")

    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(hass.config_entries.flow.async_progress_by_handler("vnish"))


async def test_unload(hass: HomeAssistant, client, entry) -> None:
    await _setup(hass, entry)

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_fan_sensors_appear_when_the_miner_reports_them(
    hass: HomeAssistant, client, entry
) -> None:
    client.summary.return_value["miner"]["cooling"]["fans"] = []
    await _setup(hass, entry)
    assert hass.states.get(f"sensor.{P}_fan_1") is None

    client.summary.return_value["miner"]["cooling"]["fans"] = [{"rpm": 4800}]
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(f"sensor.{P}_fan_1").state == "4800.0"


async def test_pool_select(hass: HomeAssistant, client, entry) -> None:
    await _setup(hass, entry)
    select = f"select.{P}_active_pool"
    state = hass.states.get(select)
    assert state.state == "1"
    assert state.attributes["options"] == ["1", "2"]
    assert state.attributes["2"] == "backup.example:3333"
    assert "wallet" not in str(state.attributes)  # no credentials exposed

    await hass.services.async_call(
        "select", "select_option", {ATTR_ENTITY_ID: select, "option": "2"}, blocking=True
    )

    client.switch_pool.assert_awaited_once_with(1)  # the miner's pool_id
    client.set_preset.assert_not_awaited()  # nothing else is touched


async def test_active_pool_follows_the_miner(hass: HomeAssistant, client, entry) -> None:
    await _setup(hass, entry)
    pools = client.summary.return_value["miner"]["pools"]
    pools[0]["status"], pools[1]["status"] = "working", "active"

    await entry.runtime_data.async_refresh()

    assert hass.states.get(f"select.{P}_active_pool").state == "2"


async def test_active_pool_falls_back_to_rpc_when_summary_has_no_pools(
    hass: HomeAssistant, client, entry
) -> None:
    del client.summary.return_value["miner"]["pools"]
    rpc = client.rpc_pools.return_value
    rpc[0]["Stratum Active"], rpc[1]["Stratum Active"] = False, True

    await _setup(hass, entry)

    assert hass.states.get(f"select.{P}_active_pool").state == "2"


async def test_active_pool_unknown_without_pool_data(hass: HomeAssistant, client, entry) -> None:
    del client.summary.return_value["miner"]["pools"]
    client.rpc_pools.side_effect = VnishConnectionError("closed")

    await _setup(hass, entry)

    assert hass.states.get(f"select.{P}_active_pool").state == STATE_UNKNOWN


async def test_pool_buttons(hass: HomeAssistant, client, entry) -> None:
    await _setup(hass, entry)
    assert hass.states.get(f"button.{P}_use_pool_1") is not None
    assert hass.states.get(f"button.{P}_use_pool_3") is None  # empty slot: no button

    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: f"button.{P}_use_pool_2"}, blocking=True
    )

    client.switch_pool.assert_awaited_once_with(1)


async def test_pool_button_unavailable_when_pool_removed(hass: HomeAssistant, client, entry) -> None:
    await _setup(hass, entry)
    client.settings.return_value["miner"]["pools"].pop(1)
    await entry.runtime_data.async_refresh()

    assert hass.states.get(f"button.{P}_use_pool_2").state == "unavailable"


async def test_pool_switch_failure_is_reported(hass: HomeAssistant, client, entry) -> None:
    client.switch_pool.side_effect = VnishApiError("POST mining/switch-pool returned HTTP 404")
    await _setup(hass, entry)

    with pytest.raises(HomeAssistantError, match="switch-pool returned HTTP 404"):
        await hass.services.async_call(
            "button", "press", {ATTR_ENTITY_ID: f"button.{P}_use_pool_2"}, blocking=True
        )


async def test_extra_sensors(hass: HomeAssistant, client, entry) -> None:
    await _setup(hass, entry)

    assert hass.states.get(f"sensor.{P}_expected_hashrate").state == "112.0"
    assert hass.states.get(f"sensor.{P}_fan_speed").state == "72.0"
    assert hass.states.get(f"sensor.{P}_hardware_errors").state == "0.02"
    assert hass.states.get(f"sensor.{P}_hashrate").attributes["unit_of_measurement"] == "TH/s"
    assert hass.states.get(f"sensor.{P}_state").attributes["options"][0] == "mining"


async def test_board_sensors(hass: HomeAssistant, client, entry) -> None:
    await _setup(hass, entry)

    assert hass.states.get(f"sensor.{P}_board_1_hashrate").state == "55.0"
    assert hass.states.get(f"sensor.{P}_board_2_temperature").state == "78.0"
    assert hass.states.get(f"sensor.{P}_board_2_state").state == "mining"
    assert hass.states.get(f"sensor.{P}_board_3_hashrate") is None


async def test_unknown_miner_state_does_not_break_the_enum_sensor(
    hass: HomeAssistant, client, entry
) -> None:
    client.summary.return_value["miner"]["miner_status"]["miner_state"] = "brand-new-state"

    await _setup(hass, entry)

    assert hass.states.get(f"sensor.{P}_state").state == STATE_UNKNOWN


async def test_scrypt_miner_reports_ghs(hass: HomeAssistant, client, entry) -> None:
    client.info.return_value["hr_measure"] = "MH/s"
    client.summary.return_value["miner"]["hr_realtime"] = 9500.0  # MH/s

    await _setup(hass, entry)

    state = hass.states.get(f"sensor.{P}_hashrate")
    assert (state.state, state.attributes["unit_of_measurement"]) == ("9.5", "GH/s")


async def test_problem_sensor(hass: HomeAssistant, client, entry) -> None:
    await _setup(hass, entry)
    problem = f"binary_sensor.{P}_problem"
    assert hass.states.get(problem).state == STATE_OFF

    client.summary.return_value["miner"]["cooling"]["fans"][2]["status"] = "lost"
    client.summary.return_value["miner"]["chains"][0]["status"]["state"] = "failure"
    await entry.runtime_data.async_refresh()

    state = hass.states.get(problem)
    assert state.state == STATE_ON
    assert state.attributes["problems"] == ["board 1 failure", "fan 3 lost"]


async def test_throttle_number(hass: HomeAssistant, client, entry) -> None:
    await _setup(hass, entry)
    number = f"number.{P}_throttle"
    assert hass.states.get(number).state == "100.0"

    await hass.services.async_call(
        "number", "set_value", {ATTR_ENTITY_ID: number, "value": 60}, blocking=True
    )

    client.set_throttle.assert_awaited_once_with(60)


async def test_device_info_uses_info_endpoint(hass: HomeAssistant, client, entry) -> None:
    from homeassistant.helpers import device_registry as dr

    await _setup(hass, entry)

    device = dr.async_get(hass).async_get_device(identifiers={("vnish", "AA:BB:CC:DD:EE:FF")})
    assert device.model == "Antminer S19j Pro"
    assert device.sw_version == "1.2.6"
    assert device.serial_number == "SN123456"
    assert device.name == "antminer-s19"


async def test_diagnostics_hide_secrets(hass: HomeAssistant, client, entry) -> None:
    from custom_components.vnish.diagnostics import async_get_config_entry_diagnostics

    await _setup(hass, entry)

    text = str(await async_get_config_entry_diagnostics(hass, entry))

    for secret in ("wallet.worker", "AA:BB:CC:DD:EE:FF", "SN123456", "192.168.1.50", "'admin'"):
        assert secret not in text
    assert "pool.example:3333" in text  # useful, not secret


async def test_current_preset_comes_from_perf_summary(hass: HomeAssistant, client, entry) -> None:
    """With the automatic preset switcher the saved name can be stale."""
    client.perf_summary.return_value["current_preset"]["name"] = "2000"

    await _setup(hass, entry)

    assert hass.states.get(f"select.{P}_preset").state == "2000"


async def test_preset_falls_back_to_settings_without_perf_summary(
    hass: HomeAssistant, client, entry
) -> None:
    client.perf_summary.side_effect = VnishConnectionError("down")

    await _setup(hass, entry)

    assert hass.states.get(f"select.{P}_preset").state == "3250"


async def test_untuned_preset_cannot_be_selected(hass: HomeAssistant, client, entry) -> None:
    await _setup(hass, entry)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "select",
            "select_option",
            {ATTR_ENTITY_ID: f"select.{P}_preset", "option": "1500"},
            blocking=True,
        )

    client.set_preset.assert_not_awaited()
