#!/usr/bin/env python3
"""Dump what a Vnish miner answers, to check the field names the integration uses.

Read-only: it logs in (POST /api/v1/unlock) and then only issues GET requests plus
the CGMiner "summary" RPC. Standard library only, run it from any machine that can
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
    try:
        report["rpc summary"] = rpc(args.host, args.rpc_port, "summary")
    except (OSError, ValueError) as err:
        report["rpc summary"] = {"error": str(err)}

    json.dump(redact(report), sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
