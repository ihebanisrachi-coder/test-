from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

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


async def test_rpc_failure_only_loses_hashrate(hass: HomeAssistant, client, entry) -> None:
    client.rpc_summary.side_effect = VnishConnectionError("closed")

    await _setup(hass, entry)

    assert hass.states.get(f"sensor.{P}_hashrate").state == STATE_UNKNOWN
    assert hass.states.get(f"sensor.{P}_power").state == "3250.0"


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
    client.resume_mining.assert_awaited_once()
    client.start_mining.assert_not_awaited()


async def test_turn_on_falls_back_to_start(hass: HomeAssistant, client, entry) -> None:
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
    [("reboot", "reboot"), ("restart_mining", "restart_mining")],
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
    assert state.state == "pool.example:3333"
    assert state.attributes["options"] == ["pool.example:3333", "backup.example:3333"]
    assert "wallet" not in str(state.attributes)  # no credentials exposed

    await hass.services.async_call(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: select, "option": "backup.example:3333"},
        blocking=True,
    )

    client.set_active_pool.assert_awaited_once_with("backup.example:3333", "wallet.worker")


async def test_pool_buttons(hass: HomeAssistant, client, entry) -> None:
    await _setup(hass, entry)
    primary = f"button.{P}_use_pool_pool_example_3333"
    backup = f"button.{P}_use_pool_backup_example_3333"
    assert hass.states.get(primary) is not None
    assert hass.states.get(f"button.{P}_use_pool_") is None  # empty slot: no button

    await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: backup}, blocking=True)

    client.set_active_pool.assert_awaited_once_with("backup.example:3333", "wallet.worker")


async def test_pool_button_unavailable_when_pool_removed(hass: HomeAssistant, client, entry) -> None:
    await _setup(hass, entry)
    client.settings.return_value["miner"]["pools"].pop(1)
    await entry.runtime_data.async_refresh()

    assert hass.states.get(f"button.{P}_use_pool_backup_example_3333").state == "unavailable"
