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


def test_spec_candidates_prefer_what_the_docs_page_references() -> None:
    page = """<script>SwaggerUIBundle({ url: "doc.json" })</script>
              <link href="/static/other.yaml">"""

    urls = probe.spec_candidates("http://m:80", page)

    assert urls[0] == "http://m:80/docs/doc.json"
    assert "http://m:80/static/other.yaml" in urls
    assert "http://m:80/api/v1/openapi.json" in urls
    assert len(urls) == len(set(urls))
