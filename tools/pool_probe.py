#!/usr/bin/env python3
"""Show what the Kryptex, K1Pool and CoinGecko public APIs answer (profitability comparison).

Read-only: public GET requests, no account, no credentials. Standard library only.

    python3 pool_probe.py > pools.json

Long lists are cut to a few items and long strings are shortened, so the output stays small.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

KRYPTEX = "https://pool.kryptex.com"
K1POOL = "https://k1pool.com"
KRYPTEX_COINS = ("btc", "bsv", "quai-sha256")
K1POOL_POOLS = ("quaisha256", "btc")
COINGECKO = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,bitcoin-cash-sv,quai-network&vs_currencies=usd"

MAX_ITEMS = 3
MAX_STRING = 120
MAX_DEPTH = 8


def shorten(value, depth: int = 0):
    """Keep the structure and a few examples of a JSON document."""
    if depth >= MAX_DEPTH:
        return "..."
    if isinstance(value, dict):
        return {k: shorten(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        items = [shorten(v, depth + 1) for v in value[:MAX_ITEMS]]
        if len(value) > MAX_ITEMS:
            items.append(f"... {len(value) - MAX_ITEMS} more")
        return items
    if isinstance(value, str) and len(value) > MAX_STRING:
        return value[:MAX_STRING] + "..."
    return value


def urls() -> dict[str, str]:
    found = {"kryptex index": f"{KRYPTEX}/api/v1/index"}
    for coin in KRYPTEX_COINS:
        found[f"kryptex {coin} pool info"] = f"{KRYPTEX}/{coin}/api/v1/pool/info"
        found[f"kryptex {coin} coin info"] = f"{KRYPTEX}/api/v1/coin/{coin}/info"
        found[f"kryptex {coin} network stats"] = f"{KRYPTEX}/api/v1/net/stats/{coin}"
        found[f"kryptex {coin} price chart"] = f"{KRYPTEX}/api/v1/coin/{coin}/price/chart"
    for pool in K1POOL_POOLS:
        found[f"k1pool {pool} stats"] = f"{K1POOL}/api/stats/{pool}"
        found[f"k1pool {pool} dashboard"] = f"{K1POOL}/api/dashboard/{pool}"
    found["coingecko prices"] = COINGECKO
    return found


def fetch(url: str):
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (vnish-ha pool probe)", "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def main() -> int:
    report = {}
    for label, url in urls().items():
        try:
            report[label] = {"url": url, "data": shorten(fetch(url))}
        except (urllib.error.URLError, OSError, ValueError) as err:
            report[label] = {"url": url, "error": str(err)}
    json.dump(report, sys.stdout, indent=1, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
