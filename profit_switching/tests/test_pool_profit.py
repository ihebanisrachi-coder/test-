"""profit_switching/packages: the REST parsing runs on real API answers, the sensors and the
automation run in Home Assistant's own engines."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import load_yaml
from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

ROOT = Path(__file__).parent.parent
SENSORS_FILE = ROOT / "packages" / "pool_profit.yaml"
SWITCH_FILE = ROOT / "packages" / "pool_profit_switch.yaml"
SENSORS = load_yaml(str(SENSORS_FILE))
SWITCH = load_yaml(str(SWITCH_FILE))
DATA = Path(__file__).parent / "data"


def _merged(domain: str, *packages: dict):
    """What Home Assistant builds from several packages: dicts merge, lists concatenate."""
    parts = [p[domain] for p in (packages or (SENSORS, SWITCH)) if domain in p]
    if isinstance(parts[0], dict):
        return {k: v for part in parts for k, v in part.items()}
    return [item for part in parts for item in part]

P = "antminer_s19"
SELECT = f"select.{P}_active_pool"


def _sample(name: str) -> dict:
    return json.loads((DATA / name).read_text())


def _rest(resource_part: str) -> dict:
    (block,) = [r for r in SENSORS["rest"] if resource_part in r["resource"]]
    return block


# --- 1. The REST sensors turn real API answers into the numbers the sensors expect ------------


async def _render(hass: HomeAssistant, template: str, value_json: dict):
    return Template(template, hass).async_render({"value_json": value_json})


@pytest.mark.parametrize(
    ("resource", "sample", "expected"),
    [
        ("/btc/api", "kryptex_btc_pool_info.json", 49.3358),   # sat/TH/day, gross (fee removed)
        ("/bsv/api", "kryptex_bsv_pool_info.json", 205381.1),  # idem
        ("k1pool.com/api/stats", "k1pool_quai_stats.json", 2.2574),  # QUAI/TH/day, gross
    ],
)
async def test_gross_yield_from_real_pool_answers(hass, resource, sample, expected) -> None:
    (sensor,) = _rest(resource)["sensor"]

    value = await _render(hass, sensor["value_template"], _sample(sample))

    assert value == pytest.approx(expected, rel=1e-3)


async def test_attributes_needed_by_the_profit_sensors_are_exposed() -> None:
    assert _rest("/bsv/api")["sensor"][0]["json_attributes"] == ["fee"]
    assert _rest("k1pool.com")["sensor"][0]["json_attributes"] == ["coinPriceUsd", "coinPoolFee"]
    quai = _sample("k1pool_quai_stats.json")
    assert float(quai["coinPriceUsd"]) == pytest.approx(0.01026545)  # a string in the API: |float


async def test_a_null_estimate_does_not_crash_the_template(hass) -> None:
    """Kryptex answers `estimated_profit_day: null` for Quai (and could for any coin)."""
    (sensor,) = _rest("/btc/api")["sensor"]
    sample = {**_sample("kryptex_btc_pool_info.json"), "estimated_profit_day": None}

    with pytest.raises(Exception):  # noqa: B017,PT011 - the REST sensor then stays unknown
        await _render(hass, sensor["value_template"], sample)


async def test_price_templates_follow_the_coingecko_format(hass) -> None:
    prices = {"bitcoin": {"usd": 85123.0}, "bitcoin-cash-sv": {"usd": 21.5}}
    btc, bsv = _rest("coingecko")["sensor"]

    assert await _render(hass, btc["value_template"], prices) == 85123.0
    assert await _render(hass, bsv["value_template"], prices) == 21.5


# --- 2. Profit sensors and the automation, in Home Assistant ---------------------------------

# The automation runs every 10 minutes: the clock starts on a boundary and the tests move it
# by multiples of 10 minutes, so its real `time_pattern` trigger is what fires.
START = datetime(2026, 10, 2, 10, 0, 0, tzinfo=UTC)


async def _settle(hass: HomeAssistant, freezer) -> None:
    """Let the sensor cascade (source -> profit -> best pool) refresh: each hop has ~1 s of delay."""
    await hass.async_block_till_done()
    for _ in range(2):
        freezer.tick(timedelta(seconds=2))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()


async def _at(hass: HomeAssistant, freezer, minutes: int) -> None:
    """Move the clock to START + `minutes` and let the 10-minute trigger fire."""
    freezer.move_to(START + timedelta(minutes=minutes))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


async def _set(hass: HomeAssistant, domain: str, service: str, entity: str, **data) -> None:
    await hass.services.async_call(domain, service, {"entity_id": entity, **data}, blocking=True)


@pytest.fixture
async def setup(hass: HomeAssistant, freezer):
    """Sources set as the REST sensors would; the package's own helpers/sensors/automation."""
    freezer.move_to(START)
    hass.states.async_set("sensor.gain_brut_btc", "49.34")
    hass.states.async_set("sensor.prix_btc", "85000")
    hass.states.async_set("sensor.gain_brut_bsv", "205381.1", {"fee": 0.03})
    hass.states.async_set("sensor.prix_bsv", "20")
    hass.states.async_set(
        "sensor.gain_brut_quai", "2.2574", {"coinPriceUsd": "0.01026545", "coinPoolFee": 2}
    )
    hass.states.async_set(SELECT, "3")  # currently mining Quai, since START
    hass.states.async_set(f"switch.{P}_mining", "on")
    hass.states.async_set(f"binary_sensor.{P}_problem", "off")

    for domain in ("input_boolean", "input_number", "template", "automation"):
        assert await async_setup_component(hass, domain, {domain: _merged(domain)})
    await hass.async_block_till_done()
    await _settle(hass, freezer)

    calls = async_mock_service(hass, "select", "select_option")
    async_mock_service(hass, "logbook", "log")
    return calls


async def _enable(hass: HomeAssistant) -> None:
    await _set(hass, "input_boolean", "turn_on", "input_boolean.profit_switching_enabled")


async def test_profit_sensors_use_fees_and_prices(hass, setup) -> None:
    states = hass.states
    # BTC: 49.34 sat x 1e-8 x 85000 USD x (1 - 2.5 % f2pool fee)
    assert float(states.get("sensor.rentabilite_btc").state) == pytest.approx(0.040893, rel=1e-3)
    # BSV: 205381.1 sat x 1e-8 x 20 USD x (1 - 3 % Kryptex fee)
    assert float(states.get("sensor.rentabilite_bsv").state) == pytest.approx(0.039845, rel=1e-3)
    # Quai: 2.2574 QUAI x 0.01026545 USD x (1 - 2 % K1Pool fee) x correction 1.0
    assert float(states.get("sensor.rentabilite_quai").state) == pytest.approx(0.022711, rel=1e-3)
    best = states.get("sensor.meilleur_pool")
    assert best.state == "1"
    assert best.attributes["classement"][0].startswith("BTC = ")
    assert best.attributes["classement"][-1].startswith("Quai = ")


async def test_the_quai_correction_factor_can_change_the_winner(hass, setup, freezer) -> None:
    # The two pools disagree by x4.3 on Quai's block time: this knob is how to settle it.
    await _set(hass, "input_number", "set_value", "input_number.profit_quai_factor", value=4.3)
    await _settle(hass, freezer)

    assert hass.states.get("sensor.meilleur_pool").state == "3"


@pytest.mark.parametrize("missing", ["sensor.prix_bsv", "sensor.gain_brut_btc"])
async def test_no_comparison_on_partial_data(hass, setup, freezer, missing) -> None:
    hass.states.async_set(missing, "unavailable")
    await _settle(hass, freezer)

    assert hass.states.get("sensor.meilleur_pool").state == "unavailable"


async def test_switches_to_the_best_pool(hass, setup, freezer) -> None:
    await _enable(hass)
    await _at(hass, freezer, 40)

    # The select service accepts the number as text (cv.string): "1" == 1 once validated.
    assert [(c.data["entity_id"], str(c.data["option"])) for c in setup] == [([SELECT], "1")]


async def test_does_nothing_while_disabled(hass, setup, freezer) -> None:
    await _at(hass, freezer, 40)

    assert setup == []


async def test_waits_for_the_minimum_time_between_switches(hass, setup, freezer) -> None:
    await _enable(hass)
    await _at(hass, freezer, 20)  # 20 min on this pool: under the 30 min minimum
    assert setup == []

    await _at(hass, freezer, 40)
    assert len(setup) == 1


async def test_ignores_a_gain_below_the_threshold(hass, setup, freezer) -> None:
    """Quai only 3 % behind BTC: not worth reconnecting."""
    await _enable(hass)
    factor = 0.97 * 0.040893 / 0.022711
    await _set(
        hass, "input_number", "set_value", "input_number.profit_quai_factor", value=round(factor, 2)
    )
    await _settle(hass, freezer)

    await _at(hass, freezer, 40)

    assert setup == []


@pytest.mark.parametrize(
    ("entity", "state"),
    [
        (f"switch.{P}_mining", "off"),          # miner stopped
        (f"binary_sensor.{P}_problem", "on"),   # board or fan failure
        (SELECT, "unknown"),                    # active pool not known
        ("sensor.prix_btc", "unavailable"),     # partial data
    ],
)
async def test_safety_conditions(hass, setup, freezer, entity, state) -> None:
    await _enable(hass)
    hass.states.async_set(entity, state)
    await _settle(hass, freezer)

    await _at(hass, freezer, 40)

    assert setup == []


async def test_nothing_to_do_when_already_on_the_best_pool(hass, setup, freezer) -> None:
    await _enable(hass)
    hass.states.async_set(SELECT, "1")  # BTC is the best pool
    await _settle(hass, freezer)

    await _at(hass, freezer, 40)

    assert setup == []


# --- 3. The two packages and the Vnish module stay independent --------------------------------


async def test_sensors_package_works_alone(hass: HomeAssistant, freezer) -> None:
    """No miner, no integration, no automation: the profit comparison still runs."""
    hass.states.async_set("sensor.gain_brut_btc", "49.34")
    hass.states.async_set("sensor.prix_btc", "85000")
    hass.states.async_set("sensor.gain_brut_bsv", "205381.1", {"fee": 0.03})
    hass.states.async_set("sensor.prix_bsv", "20")
    hass.states.async_set(
        "sensor.gain_brut_quai", "2.2574", {"coinPriceUsd": "0.01026545", "coinPoolFee": 2}
    )
    for domain in ("input_number", "template"):
        assert await async_setup_component(hass, domain, {domain: SENSORS[domain]})
    await _settle(hass, freezer)

    assert hass.states.get("sensor.meilleur_pool").state == "1"
    assert not hass.states.async_entity_ids("automation")


def test_sensors_package_never_mentions_a_miner() -> None:
    """Checked on the parsed content: the comments may explain that there is no dependency."""
    content = json.dumps(SENSORS).lower()

    assert "automation" not in SENSORS
    for word in ("vnish", "antminer", "select.", "switch.", "binary_sensor."):
        assert word not in content, word


def test_the_vnish_module_knows_nothing_about_pool_profitability() -> None:
    module = ROOT.parent / "custom_components" / "vnish"
    words = ("kryptex", "k1pool", "coingecko", "profit", "rentab")

    for path in module.rglob("*"):
        if path.is_file() and path.suffix in {".py", ".json", ".yaml"}:
            text = path.read_text().lower()
            assert not [w for w in words if w in text], path.name
