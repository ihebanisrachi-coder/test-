#!/usr/bin/env python3
"""Dump what a Vnish miner answers, to check the field names the integration uses.

Read-only: it logs in (POST /api/v1/unlock) and then only issues GET requests plus
the CGMiner "summary" and "pools" RPC commands. Standard library only, run it from any machine that can
reach the miner:

    python3 vnish_probe.py 192.168.1.50 --password admin > probe.json

Passwords, tokens and pool credentials are replaced by "<redacted>" and MAC
addresses are truncated, but read the output before sharing it.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

ENDPOINTS = ("info", "summary", "settings", "autotune/presets", "perf-summary")
SECRET_KEYS = {"pass", "pw", "password", "token", "user", "key", "secret"}
MAC = re.compile(r"\b([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){2})(?::[0-9A-Fa-f]{2}){3}\b")


def redact(value):
    if isinstance(value, dict):
        return {
            k: "<redacted>" if k.lower() in SECRET_KEYS else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return MAC.sub(r"\1:xx:xx:xx", value)
    return value


def http(method: str, url: str, token: str | None = None, body: dict | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = token
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read() or b"{}")


# Spec files referenced by the /docs page: Swagger UI's `url: "..."` or any *.json/*.yaml.
SPEC_REF = re.compile(r"""url\s*[:=]\s*["']([^"']+)["']|["'(]([^"'()\s]+\.(?:json|ya?ml))""", re.I)
SPEC_NAMES = ("openapi.json", "swagger.json", "doc.json")
SPEC_DIRS = ("/docs/", "/", "/api/v1/", "/api/", "/swagger/", "/docs/swagger/")


def http_text(url: str, token: str | None = None) -> str:
    req = urllib.request.Request(url, headers={"Authorization": token} if token else {})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode(errors="replace")


def api_paths(spec: dict) -> dict[str, list[str]]:
    """OpenAPI document -> {path: [methods]} (no schemas, no examples)."""
    paths = spec.get("paths", {}) if isinstance(spec, dict) else {}
    return {
        path: sorted(m.upper() for m in ops if m.lower() in {"get", "post", "put", "delete", "patch"})
        for path, ops in paths.items()
        if isinstance(ops, dict)
    }


def spec_candidates(root: str, page: str) -> list[str]:
    """URLs worth trying for the OpenAPI document: referenced by /docs, then usual names."""
    found = [a or b for a, b in SPEC_REF.findall(page)]
    guesses = [f"{d}{n}" for d in SPEC_DIRS for n in SPEC_NAMES]
    urls = [urllib.parse.urljoin(f"{root}/docs/", ref) for ref in found]
    urls += [f"{root}{g}" for g in guesses]
    return list(dict.fromkeys(urls))


def find_api_spec(host: str, port: int, token: str) -> dict:
    """List the endpoints the miner documents at /docs (read-only GETs)."""
    root = f"http://{host}:{port}"
    try:
        page = http_text(f"{root}/docs", token)
    except (urllib.error.URLError, OSError) as err:
        page, error = "", str(err)
    else:
        error = ""
    for url in spec_candidates(root, page):
        try:
            paths = api_paths(json.loads(http_text(url, token)))
        except (urllib.error.URLError, OSError, ValueError):
            continue
        if paths:
            return {"spec": url, "paths": paths}
    return {
        "error": f"no OpenAPI spec found; open {root}/docs in a browser",
        "docs page error": error,
        "docs page start": page[:1500],
    }


def rpc(host: str, port: int, command: str):
    with socket.create_connection((host, port), timeout=5) as sock:
        sock.sendall(json.dumps({"command": command}).encode())
        chunks = []
        while chunk := sock.recv(4096):
            chunks.append(chunk)
    return json.loads(b"".join(chunks).rstrip(b"\x00"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("host")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--port", type=int, default=80)
    parser.add_argument("--rpc-port", type=int, default=4028)
    args = parser.parse_args()

    base = f"http://{args.host}:{args.port}/api/v1"
    report: dict = {}
    try:
        token = http("POST", f"{base}/unlock", body={"pw": args.password})["token"]
    except (urllib.error.URLError, KeyError, OSError, ValueError) as err:
        print(f"unlock failed: {err}", file=sys.stderr)
        return 1

    for endpoint in ENDPOINTS:
        try:
            report[endpoint] = http("GET", f"{base}/{endpoint}", token)
        except (urllib.error.URLError, OSError, ValueError) as err:
            report[endpoint] = {"error": str(err)}
    for command in ("summary", "pools"):
        try:
            report[f"rpc {command}"] = rpc(args.host, args.rpc_port, command)
        except (OSError, ValueError) as err:
            report[f"rpc {command}"] = {"error": str(err)}

    report["documented endpoints"] = find_api_spec(args.host, args.port, token)

    json.dump(redact(report), sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
