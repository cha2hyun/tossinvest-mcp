#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

OPENAPI_URL = "https://openapi.tossinvest.com/openapi-docs/latest/openapi.json"
MANIFEST_PATH = Path(__file__).resolve().parents[1] / "openapi" / "operation-manifest.json"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def fetch_openapi() -> dict[str, Any]:
    request = urllib.request.Request(  # noqa: S310 - fixed HTTPS source
        OPENAPI_URL,
        headers={"User-Agent": "tossinvest-mcp-openapi-check/0.1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError("The OpenAPI document is not a JSON object")
    return payload


def build_manifest(document: dict[str, Any]) -> dict[str, Any]:
    operations = []
    for path, path_item in document["paths"].items():
        for method in path_item:
            if method.lower() in HTTP_METHODS:
                operations.append(f"{method.upper()} {path}")
    return {
        "version": str(document["info"]["version"]),
        "operations": sorted(operations),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--update", action="store_true")
    args = parser.parse_args()

    current = build_manifest(fetch_openapi())
    if args.update:
        MANIFEST_PATH.write_text(
            json.dumps(current, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Updated {MANIFEST_PATH}")
        return 0

    expected = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if current != expected:
        print("Official Toss Securities OpenAPI changed.", file=sys.stderr)
        print("Review it, then run this script with --update.", file=sys.stderr)
        return 1
    version = current["version"]
    operation_count = len(current["operations"])
    print(f"OpenAPI contract matches version {version} ({operation_count} ops)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
