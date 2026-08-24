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
DOCUMENTATION_KEYS = {
    "description",
    "example",
    "examples",
    "externalDocs",
    "summary",
    "tags",
    "title",
}
CONTRACT_TOP_LEVEL_KEYS = {
    "components",
    "jsonSchemaDialect",
    "openapi",
    "paths",
    "security",
    "servers",
    "webhooks",
}
NAMED_SCHEMA_MAP_KEYS = {
    "$defs",
    "definitions",
    "dependentSchemas",
    "patternProperties",
    "properties",
    "schemas",
}


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


def canonical_sha256(document: dict[str, Any]) -> str:
    canonical = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def contract_document(document: dict[str, Any]) -> dict[str, Any]:
    """Return the REST contract without documentation-only OpenAPI annotations."""

    def strip_documentation(value: Any, *, preserve_names: bool = False) -> Any:
        if isinstance(value, dict):
            return {
                key: strip_documentation(
                    item,
                    preserve_names=key in NAMED_SCHEMA_MAP_KEYS,
                )
                for key, item in value.items()
                if preserve_names or key not in DOCUMENTATION_KEYS
            }
        if isinstance(value, list):
            return [strip_documentation(item) for item in value]
        return value

    contract = {key: value for key, value in document.items() if key in CONTRACT_TOP_LEVEL_KEYS}
    return strip_documentation(contract)


def build_manifest(document: dict[str, Any]) -> dict[str, Any]:
    operations = []
    operation_ids = []
    for path, path_item in document["paths"].items():
        for method, operation in path_item.items():
            if method.lower() in HTTP_METHODS:
                operations.append(f"{method.upper()} {path}")
                operation_ids.append(str(operation["operationId"]))
    return {
        "version": str(document["info"]["version"]),
        "schema_sha256": canonical_sha256(document),
        "contract_sha256": canonical_sha256(contract_document(document)),
        "operations": sorted(operations),
        "operation_ids": sorted(operation_ids),
    }


def contract_changed(current: dict[str, Any], expected: dict[str, Any]) -> bool:
    contract_fields = ("version", "contract_sha256", "operations", "operation_ids")
    return any(current.get(field) != expected.get(field) for field in contract_fields)


def report_contract_changes(current: dict[str, Any], expected: dict[str, Any]) -> None:
    if current.get("version") != expected.get("version"):
        print(
            f"Version changed: {expected.get('version')} -> {current.get('version')}",
            file=sys.stderr,
        )

    for field, label in (("operations", "operations"), ("operation_ids", "operation IDs")):
        old_values = set(expected.get(field, []))
        new_values = set(current.get(field, []))
        added = sorted(new_values - old_values)
        removed = sorted(old_values - new_values)
        if added:
            print(f"Added {label}: {added}", file=sys.stderr)
        if removed:
            print(f"Removed {label}: {removed}", file=sys.stderr)

    if current.get("contract_sha256") != expected.get("contract_sha256"):
        print("REST request/response schemas or security requirements changed.", file=sys.stderr)


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
    if contract_changed(current, expected):
        print("Official Toss Securities OpenAPI changed.", file=sys.stderr)
        report_contract_changes(current, expected)
        print("Review it, then run this script with --update.", file=sys.stderr)
        return 1
    if current["schema_sha256"] != expected.get("schema_sha256"):
        print("OpenAPI documentation changed; the REST contract is unchanged.")
    version = current["version"]
    operation_count = len(current["operations"])
    print(
        f"OpenAPI contract matches version {version} ({operation_count} ops, contract fingerprint)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
