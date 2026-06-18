#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "skills"
ALLOWED_FRONTMATTER = {"name", "description", "license", "metadata"}
NAME_PATTERN = re.compile(r"^[a-z0-9-]{1,64}$")


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def validate_skill(path: Path) -> list[str]:
    errors: list[str] = []
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        return [f"{path.relative_to(ROOT)}: missing YAML frontmatter"]
    try:
        _, frontmatter, body = content.split("---", 2)
    except ValueError:
        return [f"{path.relative_to(ROOT)}: malformed YAML frontmatter"]

    metadata = yaml.safe_load(frontmatter)
    if not isinstance(metadata, dict):
        return [f"{path.relative_to(ROOT)}: frontmatter must be an object"]
    unexpected = set(metadata) - ALLOWED_FRONTMATTER
    if unexpected:
        errors.append(
            f"{path.relative_to(ROOT)}: unsupported frontmatter keys {sorted(unexpected)}"
        )

    name = metadata.get("name")
    if not isinstance(name, str) or NAME_PATTERN.fullmatch(name) is None:
        errors.append(f"{path.relative_to(ROOT)}: invalid skill name")
    elif path.parent.name != name:
        errors.append(f"{path.relative_to(ROOT)}: directory must match skill name {name!r}")

    description = metadata.get("description")
    if not isinstance(description, str) or not 40 <= len(description) <= 1024:
        errors.append(f"{path.relative_to(ROOT)}: description must contain 40 to 1024 characters")
    if len(frontmatter) > 2000:
        errors.append(f"{path.relative_to(ROOT)}: frontmatter exceeds 2000 characters")
    if "TODO" in body:
        errors.append(f"{path.relative_to(ROOT)}: unresolved TODO in skill body")

    hermes = metadata.get("metadata", {}).get("hermes", {})
    required_tools = hermes.get("requires_tools")
    if not isinstance(required_tools, list) or not required_tools:
        errors.append(f"{path.relative_to(ROOT)}: Hermes requires_tools must be non-empty")

    openai_path = path.parent / "agents" / "openai.yaml"
    if not openai_path.exists():
        errors.append(f"{path.relative_to(ROOT)}: missing agents/openai.yaml")
    else:
        openai = load_yaml(openai_path)
        interface = openai.get("interface", {}) if isinstance(openai, dict) else {}
        prompt = interface.get("default_prompt")
        if isinstance(name, str) and (not isinstance(prompt, str) or f"${name}" not in prompt):
            errors.append(f"{openai_path.relative_to(ROOT)}: default_prompt must mention ${name}")
    return errors


def main() -> int:
    skill_files = sorted(SKILLS_ROOT.glob("*/SKILL.md"))
    errors = [error for path in skill_files for error in validate_skill(path)]
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Skill validation passed ({len(skill_files)} skills)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
