from __future__ import annotations

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "pool_probe", Path(__file__).parent.parent / "tools" / "pool_probe.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_shorten_keeps_structure_and_cuts_lists_and_strings() -> None:
    out = probe.shorten({"a": list(range(10)), "b": "x" * 500, "c": {"d": 1.5}})

    assert out["a"] == [0, 1, 2, "... 7 more"]
    assert out["b"] == "x" * 120 + "..."
    assert out["c"] == {"d": 1.5}


def test_shorten_stops_at_a_maximum_depth() -> None:
    deep: dict = {}
    node = deep
    for _ in range(20):
        node["n"] = {}
        node = node["n"]

    assert "..." in str(probe.shorten(deep))


def test_urls_cover_the_three_coins_on_kryptex_and_quai_on_k1pool() -> None:
    urls = probe.urls()

    assert urls["kryptex btc pool info"] == "https://pool.kryptex.com/btc/api/v1/pool/info"
    assert urls["kryptex bsv network stats"] == "https://pool.kryptex.com/api/v1/net/stats/bsv"
    assert urls["kryptex quai-sha256 coin info"].endswith("/api/v1/coin/quai-sha256/info")
    assert urls["k1pool quaisha256 stats"] == "https://k1pool.com/api/stats/quaisha256"
    assert urls["k1pool quaisha256 dashboard"] == "https://k1pool.com/api/dashboard/quaisha256"
    # Price sources the profitability package relies on.
    assert urls["kryptex bsv price chart"].endswith("/api/v1/coin/bsv/price/chart")
    assert urls["k1pool btc stats"] == "https://k1pool.com/api/stats/btc"
    assert "ids=bitcoin,bitcoin-cash-sv" in urls["coingecko prices"]
