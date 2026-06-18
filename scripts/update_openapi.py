#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

OPENAPI_URL = "https://openapi.tossinvest.com/openapi-docs/latest/openapi.json"
MANIFEST_PATH = Path(__file__).resolve().parents[1] / "openapi" / "operation-manifest.json"
TOOL_MAP_PATH = Path(__file__).resolve().parents[1] / "openapi" / "tool-map.json"
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
    operation_ids = []
    for path, path_item in document["paths"].items():
        for method, operation in path_item.items():
            if method.lower() in HTTP_METHODS:
                operations.append(f"{method.upper()} {path}")
                operation_ids.append(str(operation["operationId"]))
    canonical = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return {
        "version": str(document["info"]["version"]),
        "schema_sha256": hashlib.sha256(canonical).hexdigest(),
        "operations": sorted(operations),
        "operation_ids": sorted(operation_ids),
    }


def validate_tool_map(manifest: dict[str, Any]) -> bool:
    tool_map = json.loads(TOOL_MAP_PATH.read_text(encoding="utf-8"))
    expected = set(manifest["operation_ids"])
    mapped = set(tool_map)
    missing = sorted(expected - mapped)
    extra = sorted(mapped - expected)
    if missing or extra:
        print(f"Missing operation mappings: {missing}", file=sys.stderr)
        print(f"Unknown operation mappings: {extra}", file=sys.stderr)
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--update", action="store_true")
    args = parser.parse_args()

    current = build_manifest(fetch_openapi())
    if not validate_tool_map(current):
        return 1
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
    print(
        f"OpenAPI contract matches version {version} "
        f"({operation_count} ops, full schema fingerprint)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
