from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest
import yaml

import tossinvest_mcp.service as service_module
from tossinvest_mcp import __version__
from tossinvest_mcp.rate_limit import RATE_LIMITS
from tossinvest_mcp.server import create_mcp
from tossinvest_mcp.settings import Settings

from .test_service import StubClient

ROOT = Path(__file__).resolve().parents[1]


def test_package_version_has_one_consistent_release_value() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["version"] == __version__


def test_rate_limiter_covers_every_service_api_group() -> None:
    service_source = Path(service_module.__file__).read_text(encoding="utf-8")
    used_groups = set(re.findall(r'group="([A-Z_]+)"', service_source))

    assert used_groups <= set(RATE_LIMITS)


@pytest.mark.asyncio
async def test_every_official_operation_maps_to_an_implementation(
    trading_settings: Settings,
) -> None:
    manifest = json.loads(
        (ROOT / "openapi" / "operation-manifest.json").read_text(encoding="utf-8")
    )
    tool_map = json.loads((ROOT / "openapi" / "tool-map.json").read_text(encoding="utf-8"))
    assert set(manifest["operation_ids"]) == set(tool_map)

    for mapping in tool_map.values():
        assert mapping["kind"] in {"internal", "tool", "unsupported"}
        if mapping["kind"] == "tool":
            assert mapping["tools"]
        elif mapping["kind"] == "internal":
            assert mapping["implementation"]
        else:
            assert mapping["reason"]

    mcp, _ = create_mcp(trading_settings, client=StubClient())
    registered = {tool.name for tool in await mcp.list_tools()}
    mapped_tools = {
        tool
        for mapping in tool_map.values()
        if mapping["kind"] == "tool"
        for tool in mapping["tools"]
    }
    assert mapped_tools == registered


@pytest.mark.parametrize(
    ("skill_name", "required_tools", "body_marker"),
    [
        (
            "tossinvest",
            ["mcp_tossinvest_get_prices"],
            "# TossInvest Read Workflows",
        ),
        (
            "tossinvest-trading",
            [
                "mcp_tossinvest_preview_order",
                "mcp_tossinvest_place_order",
            ],
            "# TossInvest Trading",
        ),
    ],
)
def test_hermes_skills_have_supported_metadata_and_installable_shape(
    skill_name: str,
    required_tools: list[str],
    body_marker: str,
) -> None:
    path = ROOT / "skills" / skill_name / "SKILL.md"
    content = path.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    _, frontmatter, body = content.split("---", 2)
    metadata = yaml.safe_load(frontmatter)

    assert set(metadata) <= {"name", "description", "license", "metadata"}
    assert metadata["name"] == skill_name
    assert metadata["description"].startswith("Use ")
    assert metadata["license"] == "MIT"
    hermes = metadata["metadata"]["hermes"]
    assert hermes["category"] == "finance"
    assert hermes["tags"]
    assert hermes["requires_tools"] == required_tools
    assert body_marker in body
    assert "TODO" not in body
