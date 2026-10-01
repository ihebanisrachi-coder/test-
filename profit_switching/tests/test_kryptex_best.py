"""kryptex_best_sha256.yaml: Kryptex's own answers in, the most profitable SHA-256 coin out."""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import load_yaml
from pytest_homeassistant_custom_component.common import async_fire_time_changed

ROOT = Path(__file__).parent.parent
PACKAGE_FILE = ROOT / "packages" / "kryptex_best_sha256.yaml"
PACKAGE = load_yaml(str(PACKAGE_FILE))
sys.path.insert(0, str(ROOT / "tools"))
import gen_kryptex_package as generator  # noqa: E402

# estimated_profit_day / fee / mergemining as Kryptex answered (pool/info), one entry per coin.
POOL_INFO = {
    "btc": {"fee": 0.03, "estimated_profit_day": 4.785094177685909e-19, "mergemining": "FB"},
    "bch": {"fee": 0.03, "estimated_profit_day": 1.205828677180498e-16, "mergemining": ""},
    "fb": {"fee": 0.02, "estimated_profit_day": 5.733284778820599e-14, "mergemining": ""},
    "xec": {"fee": 0.02, "estimated_profit_day": 1.0443064353738855e-09, "mergemining": ""},
    "dgb": {"fee": 0.02, "estimated_profit_day": 7.1817657750556024e-12, "mergemining": ""},
    "bsv": {"fee": 0.03, "estimated_profit_day": 2.0015463119184003e-15, "mergemining": ""},
    "quai-sha256": {"fee": 0.01, "estimated_profit_day": None, "mergemining": ""},
}
# Latest USD price per coin. The real answer is a list of {timestamp, price} points, one per hour;
# these are made-up "now" values in the same order of magnitude as the real ones.
PRICES = {"btc": 85000.0, "bch": 245.0, "fb": 0.33, "xec": 6.8e-06, "dgb": 0.0043, "bsv": 22.0}


def _chart(last: float) -> list[dict]:
    """First points as Kryptex returned them (old prices), then the current one last."""
    return [
        {"timestamp": 1788300000000.0, "price": 77225.0},
        {"timestamp": 1788303600000.0, "price": 77375.08166666667},
        {"timestamp": 1790896000000.0, "price": last},
    ]


def _rest(resource_end: str) -> dict:
    (block,) = [r for r in PACKAGE["rest"] if r["resource"].endswith(resource_end)]
    return block


# --- 1. REST parsing -------------------------------------------------------------------------


async def _render(hass: HomeAssistant, template: str, value_json):
    return Template(template, hass).async_render({"value_json": value_json})


@pytest.mark.parametrize(("slug", "info"), [(s, i) for s, i in POOL_INFO.items() if s != "quai-sha256"])
async def test_gain_is_coin_per_th_per_day(hass, slug, info) -> None:
    block = _rest(f"/{slug}/api/v1/pool/info")
    (sensor,) = block["sensor"]

    value = await _render(hass, sensor["value_template"], info)

    # Tiny numbers come out as text in scientific notation ("4.78e-07"): a valid sensor state.
    assert float(value) == pytest.approx(info["estimated_profit_day"] * 1e12)


async def test_a_null_estimate_gives_an_unknown_sensor_not_an_error(hass) -> None:
    block = _rest("/quai-sha256/api/v1/pool/info")

    value = await _render(hass, block["sensor"][0]["value_template"], POOL_INFO["quai-sha256"])

    assert value == "unknown"


async def test_price_is_the_latest_point_of_the_chart_not_the_first(hass) -> None:
    (sensor,) = _rest("/coin/btc/price/chart")["sensor"]

    assert await _render(hass, sensor["value_template"], _chart(85000.0)) == 85000.0
    assert await _render(hass, sensor["value_template"], []) == "unknown"


def test_every_coin_reads_kryptex_and_exposes_what_the_ranking_needs() -> None:
    resources = [r["resource"] for r in PACKAGE["rest"]]

    assert all(r.startswith("https://pool.kryptex.com/") for r in resources)
    for slug in POOL_INFO:
        assert f"https://pool.kryptex.com/{slug}/api/v1/pool/info" in resources
        assert f"https://pool.kryptex.com/api/v1/coin/{slug}/price/chart" in resources
    pool_info = _rest("/btc/api/v1/pool/info")
    assert pool_info["sensor"][0]["json_attributes"] == ["fee", "mergemining"]


# --- 2. Ranking, in Home Assistant -----------------------------------------------------------

BEST = "sensor.meilleur_coin_sha256_kryptex"


async def _settle(hass: HomeAssistant, freezer) -> None:
    """Sensors that depend on other template sensors refresh with ~1 s of delay per hop."""
    await hass.async_block_till_done()
    for _ in range(3):
        freezer.tick(timedelta(seconds=2))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()


def _expected(coin: str, merged: bool = False) -> float:
    info = POOL_INFO[{"quai": "quai-sha256"}.get(coin, coin)]
    own = info["estimated_profit_day"] * 1e12 * PRICES[coin]
    if merged and coin == "btc":
        own += POOL_INFO["fb"]["estimated_profit_day"] * 1e12 * PRICES["fb"]
    return own


@pytest.fixture
async def setup(hass: HomeAssistant, freezer):
    for slug, cid, _label in generator.COINS:
        info = POOL_INFO[slug]
        gain = info["estimated_profit_day"]
        hass.states.async_set(
            f"sensor.kryptex_gain_{cid}",
            "unknown" if gain is None else str(gain * 1e12),
            {"fee": info["fee"], "mergemining": info["mergemining"]},
        )
        hass.states.async_set(
            f"sensor.kryptex_prix_{cid}", str(PRICES[cid]) if cid in PRICES else "unknown"
        )
    for domain in ("input_boolean", "template"):
        assert await async_setup_component(hass, domain, {domain: PACKAGE[domain]})
    await _settle(hass, freezer)


async def test_btc_wins_when_the_merged_fb_is_counted(hass, setup) -> None:
    best = hass.states.get(BEST)

    assert best.state == "BTC"
    btc = _expected("btc", merged=True)
    assert best.attributes["usd_th_jour"] == pytest.approx(btc, rel=1e-4)
    assert float(hass.states.get("sensor.kryptex_rentabilite_btc").state) == pytest.approx(btc, rel=1e-4)
    # own revenue and what comes from the merged coin are both visible
    attrs = hass.states.get("sensor.kryptex_rentabilite_btc").attributes
    assert attrs["gain_propre"] == pytest.approx(_expected("btc"), rel=1e-3)
    assert attrs["minage_fusionne"] == "FB"
    assert float(hass.states.get("sensor.gain_du_meilleur_coin_sha256").state) == pytest.approx(btc, rel=1e-4)


async def test_without_the_merged_coin_bsv_wins(hass, setup, freezer) -> None:
    await hass.services.async_call(
        "input_boolean", "turn_off", {"entity_id": "input_boolean.kryptex_include_merged"}, blocking=True
    )
    await _settle(hass, freezer)

    assert hass.states.get(BEST).state == "BSV"  # 22 USD x 2.0e-3 beats BTC alone


async def test_ranking_is_sorted_and_lists_what_is_unavailable(hass, setup) -> None:
    attrs = hass.states.get(BEST).attributes

    names = [line.split(" = ")[0] for line in attrs["classement"]]
    assert names == ["BTC", "BSV", "DGB", "BCH", "FB", "XEC"]
    assert attrs["indisponibles"] == ["QUAI"]  # Kryptex publishes no estimate for it


async def test_a_coin_without_price_drops_out_but_the_others_still_rank(hass, setup, freezer) -> None:
    hass.states.async_set("sensor.kryptex_prix_btc", "unavailable")
    await _settle(hass, freezer)

    best = hass.states.get(BEST)
    assert best.state == "BSV"
    assert "BTC" in best.attributes["indisponibles"]


async def test_nothing_to_show_when_no_data_at_all(hass, setup, freezer) -> None:
    for _slug, cid, _label in generator.COINS:
        hass.states.async_set(f"sensor.kryptex_prix_{cid}", "unavailable")
    await _settle(hass, freezer)

    assert hass.states.get(BEST).state == "unavailable"
    assert hass.states.get("sensor.gain_du_meilleur_coin_sha256").state == "unavailable"


# --- 3. The dashboard card ------------------------------------------------------------------


async def test_the_dashboard_card_shows_the_winner_and_the_ranking(hass, setup) -> None:
    card = load_yaml(str(ROOT / "dashboard" / "kryptex_best_sha256_card.yaml"))
    markdown = card["cards"][0]["content"]

    text = Template(markdown, hass).async_render()

    assert "## BTC" in text
    assert "USD** par jour pour 1 TH/s" in text
    assert [line for line in text.splitlines() if line.startswith("- ")][:2] == [
        f"- BTC = {round(_expected('btc', merged=True), 5)}",
        f"- BSV = {round(_expected('bsv'), 5)}",
    ]
    assert "Sans estimation : QUAI" in text


async def test_the_dashboard_card_degrades_gracefully_without_data(hass) -> None:
    markdown = load_yaml(str(ROOT / "dashboard" / "kryptex_best_sha256_card.yaml"))["cards"][0]["content"]

    assert "Aucune donnée Kryptex" in Template(markdown, hass).async_render()


# --- 4. The generated file and independence ---------------------------------------------------


def test_the_committed_package_is_the_generators_output() -> None:
    assert PACKAGE_FILE.read_text() == generator.render()


def test_the_package_never_mentions_a_miner() -> None:
    content = json.dumps(PACKAGE).lower()

    assert "automation" not in PACKAGE
    for word in ("vnish", "antminer", "select.", "switch.", "binary_sensor."):
        assert word not in content, word
