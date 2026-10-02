"""kryptex_best_sha256.yaml: Kryptex's own answers in, the most profitable SHA-256 coin out.

Only each coin's own gain counts: merged mining (BTC + FB) is deliberately not added.
"""

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
POOL_PROFIT = load_yaml(str(ROOT / "packages" / "pool_profit.yaml"))  # the other package
sys.path.insert(0, str(ROOT / "tools"))
import gen_kryptex_package as generator  # noqa: E402

# estimated_profit_day / fee as Kryptex answered (pool/info), one entry per coin. The BTC pool also
# announces `mergemining: FB`; the package ignores it.
POOL_INFO = {
    "btc": {"fee": 0.03, "estimated_profit_day": 4.785094177685909e-19, "mergemining": "FB"},
    "bch": {"fee": 0.03, "estimated_profit_day": 1.205828677180498e-16, "mergemining": ""},
    "fb": {"fee": 0.02, "estimated_profit_day": 5.733284778820599e-14, "mergemining": ""},
    "xec": {"fee": 0.02, "estimated_profit_day": 1.0443064353738855e-09, "mergemining": ""},
    "dgb": {"fee": 0.02, "estimated_profit_day": 7.1817657750556024e-12, "mergemining": ""},
    "bsv": {"fee": 0.03, "estimated_profit_day": 2.0015463119184003e-15, "mergemining": ""},
}
# Kryptex answers `estimated_profit_day: null` for Quai; it is ranked from K1Pool instead.
QUAI_NULL_ESTIMATE = {"fee": 0.01, "estimated_profit_day": None, "mergemining": ""}
# Quai from K1Pool (real answer in data/k1pool_quai_stats.json): 2.2574 QUAI/TH x 0.01026545 USD x (1 - 2 %).
QUAI_K1POOL_PROFIT = 0.02271
K1POOL_STATS = json.loads((Path(__file__).parent / "data" / "k1pool_quai_stats.json").read_text())
QUAI = "sensor.k1pool_rentabilite_quai"
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


@pytest.mark.parametrize(("slug", "info"), list(POOL_INFO.items()))
async def test_gain_is_coin_per_th_per_day(hass, slug, info) -> None:
    block = _rest(f"/{slug}/api/v1/pool/info")
    (sensor,) = block["sensor"]

    value = await _render(hass, sensor["value_template"], info)

    # Tiny numbers come out as text in scientific notation ("4.78e-07"): a valid sensor state.
    assert float(value) == pytest.approx(info["estimated_profit_day"] * 1e12)


async def test_a_null_estimate_gives_an_unknown_sensor_not_an_error(hass) -> None:
    block = _rest("/btc/api/v1/pool/info")

    value = await _render(hass, block["sensor"][0]["value_template"], QUAI_NULL_ESTIMATE)

    assert value == "unknown"


async def test_price_is_the_latest_point_of_the_chart_not_the_first(hass) -> None:
    (sensor,) = _rest("/coin/btc/price/chart")["sensor"]

    assert await _render(hass, sensor["value_template"], _chart(85000.0)) == 85000.0
    assert await _render(hass, sensor["value_template"], []) == "unknown"


def test_every_coin_reads_kryptex_and_exposes_what_the_ranking_needs() -> None:
    resources = [r["resource"] for r in PACKAGE["rest"]]
    kryptex = [r for r in resources if r.startswith("https://pool.kryptex.com/")]

    for slug in POOL_INFO:
        assert f"https://pool.kryptex.com/{slug}/api/v1/pool/info" in resources
        assert f"https://pool.kryptex.com/api/v1/coin/{slug}/price/chart" in resources
    # Kryptex answers null for Quai: it is read from K1Pool, and only from there
    assert not [r for r in kryptex if "quai" in r]
    assert [r for r in resources if r not in kryptex] == ["https://k1pool.com/api/stats/quaisha256"]
    assert _rest("/btc/api/v1/pool/info")["sensor"][0]["json_attributes"] == ["fee"]


async def test_quai_gain_from_the_real_k1pool_answer(hass) -> None:
    (sensor,) = _rest("k1pool.com/api/stats/quaisha256")["sensor"]

    gain = await _render(hass, sensor["value_template"], K1POOL_STATS)

    # reward x blocks per day x 1 TH/s / network hashrate
    assert float(gain) == pytest.approx(2.2574, rel=1e-3)
    assert sensor["json_attributes"] == ["coinPriceUsd", "coinPoolFee"]
    assert float(K1POOL_STATS["coinPriceUsd"]) == pytest.approx(0.01026545)  # text in the API


@pytest.mark.parametrize("broken", [{}, {"coinBlocktime": 0}, {"networkSpeed": None}])
async def test_a_broken_k1pool_answer_gives_an_unknown_sensor_not_an_error(hass, broken) -> None:
    (sensor,) = _rest("k1pool.com/api/stats/quaisha256")["sensor"]
    answer = {**K1POOL_STATS, **broken} if broken else {}

    assert await _render(hass, sensor["value_template"], answer) == "unknown"


# --- 2. Ranking, in Home Assistant -----------------------------------------------------------

BEST = "sensor.meilleur_coin_sha256_kryptex"


async def _settle(hass: HomeAssistant, freezer) -> None:
    """Sensors that depend on other template sensors refresh with ~1 s of delay per hop."""
    await hass.async_block_till_done()
    for _ in range(3):
        freezer.tick(timedelta(seconds=2))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()


def _expected(coin: str) -> float:
    """USD per TH/s per day: the coin's own gain x its price, nothing else."""
    return POOL_INFO[coin]["estimated_profit_day"] * 1e12 * PRICES[coin]


@pytest.fixture
async def setup(hass: HomeAssistant, freezer):
    hass.states.async_set(
        "sensor.k1pool_gain_quai",
        "2.2574",
        {"coinPriceUsd": K1POOL_STATS["coinPriceUsd"], "coinPoolFee": K1POOL_STATS["coinPoolFee"]},
    )
    for slug, cid, _label in generator.COINS:
        info = POOL_INFO[slug]
        gain = info["estimated_profit_day"]
        hass.states.async_set(
            f"sensor.kryptex_gain_{cid}",
            "unknown" if gain is None else str(gain * 1e12),
            {"fee": info["fee"]},
        )
        hass.states.async_set(f"sensor.kryptex_prix_{cid}", str(PRICES[cid]))
    # Only this package: nothing else is installed.
    for domain in ("input_number", "template"):
        assert await async_setup_component(hass, domain, {domain: PACKAGE[domain]})
    await _settle(hass, freezer)


async def test_bsv_wins_with_each_coins_own_gain_only(hass, setup) -> None:
    best = hass.states.get(BEST)

    assert best.state == "BSV"
    assert best.attributes["usd_th_jour"] == pytest.approx(_expected("bsv"), rel=1e-4)
    assert float(hass.states.get("sensor.gain_du_meilleur_coin_sha256").state) == pytest.approx(
        _expected("bsv"), rel=1e-4
    )


async def test_merged_mining_is_not_counted(hass, setup) -> None:
    """The BTC pool announces `mergemining: FB`: its FB must not be added to the BTC figure."""
    btc = hass.states.get("sensor.kryptex_rentabilite_btc")

    assert float(btc.state) == pytest.approx(_expected("btc"), rel=1e-4)
    assert "minage_fusionne" not in btc.attributes


async def test_ranking_is_sorted_and_includes_quai_from_k1pool(hass, setup) -> None:
    attrs = hass.states.get(BEST).attributes

    names = [line.split(" = ")[0] for line in attrs["classement"]]
    assert names == ["BSV", "BTC", "DGB", "BCH", "QUAI", "FB", "XEC"]
    assert float(hass.states.get(QUAI).state) == pytest.approx(QUAI_K1POOL_PROFIT, abs=1e-5)
    assert attrs["indisponibles"] == []


async def test_quai_is_listed_as_unavailable_when_k1pool_has_no_data(hass, setup, freezer) -> None:
    hass.states.async_set("sensor.k1pool_gain_quai", "unknown")
    await _settle(hass, freezer)

    attrs = hass.states.get(BEST).attributes
    assert hass.states.get(BEST).state == "BSV"
    assert attrs["indisponibles"] == ["QUAI"]
    assert [line.split(" = ")[0] for line in attrs["classement"]] == ["BSV", "BTC", "DGB", "BCH", "FB", "XEC"]


async def test_the_quai_correction_knob_moves_quai_in_the_ranking(hass, setup, freezer) -> None:
    """The two pools disagree by x4.3 on Quai's block time: this knob is how to settle it."""
    await hass.services.async_call(
        "input_number", "set_value",
        {"entity_id": "input_number.k1pool_quai_factor", "value": 4.3}, blocking=True,
    )
    await _settle(hass, freezer)

    assert hass.states.get(BEST).state == "QUAI"
    assert hass.states.get(BEST).attributes["usd_th_jour"] == pytest.approx(4.3 * QUAI_K1POOL_PROFIT, abs=1e-4)


async def test_the_leader_without_price_drops_out_and_the_next_one_takes_over(
    hass, setup, freezer
) -> None:
    hass.states.async_set("sensor.kryptex_prix_bsv", "unavailable")
    await _settle(hass, freezer)

    best = hass.states.get(BEST)
    assert best.state == "BTC"
    assert "BSV" in best.attributes["indisponibles"]
    assert best.attributes["usd_th_jour"] == pytest.approx(_expected("btc"), rel=1e-4)


async def test_nothing_to_show_when_no_data_at_all(hass, setup, freezer) -> None:
    for _slug, cid, _label in generator.COINS:
        hass.states.async_set(f"sensor.kryptex_prix_{cid}", "unavailable")
    hass.states.async_set("sensor.k1pool_gain_quai", "unavailable")
    await _settle(hass, freezer)

    assert hass.states.get(BEST).state == "unavailable"
    assert hass.states.get("sensor.gain_du_meilleur_coin_sha256").state == "unavailable"


# --- 3. The dashboard card ------------------------------------------------------------------


async def test_the_dashboard_card_shows_the_winner_and_the_ranking(hass, setup) -> None:
    card = load_yaml(str(ROOT / "dashboard" / "kryptex_best_sha256_card.yaml"))
    markdown = card["content"]

    text = Template(markdown, hass).async_render()

    assert "## BSV" in text
    assert "USD** par jour pour 1 TH/s" in text
    assert [line for line in text.splitlines() if line.startswith("- ")][:2] == [
        f"- BSV = {round(_expected('bsv'), 5)}",
        f"- BTC = {round(_expected('btc'), 5)}",
    ]
    assert "- QUAI = " in text
    assert "Sans estimation" not in text


async def test_the_dashboard_card_flags_a_coin_without_estimate(hass, setup) -> None:
    markdown = load_yaml(str(ROOT / "dashboard" / "kryptex_best_sha256_card.yaml"))["content"]

    # the best-coin sensor refreshes with a short delay: render from its last attributes
    hass.states.async_set(BEST, "BSV", {**hass.states.get(BEST).attributes, "indisponibles": ["QUAI"]})
    assert "Sans estimation : QUAI" in Template(markdown, hass).async_render()


async def test_the_dashboard_card_degrades_gracefully_without_data(hass) -> None:
    markdown = load_yaml(str(ROOT / "dashboard" / "kryptex_best_sha256_card.yaml"))["content"]

    assert "Aucune donnée Kryptex" in Template(markdown, hass).async_render()


# --- 4. The generated file and independence ---------------------------------------------------


def test_the_committed_package_is_the_generators_output() -> None:
    assert PACKAGE_FILE.read_text() == generator.render()


def test_the_package_never_mentions_a_miner() -> None:
    content = json.dumps(PACKAGE).lower()

    assert "automation" not in PACKAGE
    for word in ("vnish", "antminer", "select.", "switch.", "binary_sensor."):
        assert word not in content, word
    # and nothing about merged mining is left in the data or the templates
    assert "mergemining" not in content and "include_merged" not in content


def test_the_package_does_not_depend_on_pool_profit_and_does_not_clash_with_it() -> None:
    """Install either one, or both: no entity of the other is read, and no id is shared."""
    content = json.dumps(PACKAGE)
    for foreign in ("sensor.rentabilite_quai", "profit_quai_factor", "sensor.gain_brut_quai", "sensor.meilleur_pool"):
        assert foreign not in content, foreign

    def unique_ids(package: dict) -> set[str]:
        ids = {s["unique_id"] for block in package["rest"] for s in block["sensor"]}
        ids |= {s["unique_id"] for block in package["template"] for s in block["sensor"]}
        return ids

    assert not unique_ids(PACKAGE) & unique_ids(POOL_PROFIT)
    assert not set(PACKAGE["input_number"]) & set(POOL_PROFIT["input_number"])
