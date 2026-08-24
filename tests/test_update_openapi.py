from __future__ import annotations

from copy import deepcopy
from typing import Any

from scripts.update_openapi import build_manifest, contract_changed


def sample_openapi() -> dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Example API",
            "version": "1.0.0",
            "description": "Original documentation.",
        },
        "externalDocs": {"url": "https://example.test/docs"},
        "tags": [{"name": "Quotes", "description": "Quote documentation."}],
        "paths": {
            "/quotes": {
                "get": {
                    "operationId": "getQuotes",
                    "summary": "Get quotes",
                    "tags": ["Quotes"],
                    "responses": {
                        "200": {
                            "description": "Success",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Quote"},
                                    "example": {"price": "100"},
                                }
                            },
                        }
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "Quote": {
                    "type": "object",
                    "title": "Quote",
                    "description": "A quote response.",
                    "properties": {
                        "price": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["price", "description"],
                }
            }
        },
    }


def test_documentation_changes_do_not_change_contract_fingerprint() -> None:
    original = sample_openapi()
    documented = deepcopy(original)
    documented["info"]["description"] = "Now with WebSocket documentation."
    documented["externalDocs"] = {"url": "https://example.test/asyncapi.json"}
    documented["tags"][0]["description"] = "Updated quote documentation."
    documented["paths"]["/quotes"]["get"]["summary"] = "Read current quotes"

    original_manifest = build_manifest(original)
    documented_manifest = build_manifest(documented)

    assert original_manifest["schema_sha256"] != documented_manifest["schema_sha256"]
    assert original_manifest["contract_sha256"] == documented_manifest["contract_sha256"]
    assert contract_changed(documented_manifest, original_manifest) is False


def test_schema_changes_change_contract_fingerprint() -> None:
    original = sample_openapi()
    changed = deepcopy(original)
    changed["components"]["schemas"]["Quote"]["properties"]["price"]["type"] = "number"

    original_manifest = build_manifest(original)
    changed_manifest = build_manifest(changed)

    assert original_manifest["contract_sha256"] != changed_manifest["contract_sha256"]
    assert contract_changed(changed_manifest, original_manifest) is True


def test_schema_properties_named_like_annotations_remain_in_contract() -> None:
    original = sample_openapi()
    changed = deepcopy(original)
    changed["components"]["schemas"]["Quote"]["properties"]["description"]["type"] = "number"

    original_manifest = build_manifest(original)
    changed_manifest = build_manifest(changed)

    assert original_manifest["contract_sha256"] != changed_manifest["contract_sha256"]


def test_old_manifest_without_contract_fingerprint_requires_review() -> None:
    current = build_manifest(sample_openapi())
    legacy = {key: value for key, value in current.items() if key != "contract_sha256"}

    assert contract_changed(current, legacy) is True
