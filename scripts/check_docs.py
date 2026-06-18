#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

from tossinvest_mcp.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", ".venv", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist"}
LINK_PATTERN = re.compile(r"!?\[[^\]]*]\(([^)]+)\)")
HEADING_PATTERN = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
RAW_APPROVAL_ASSIGNMENT = re.compile(
    r"^\s*TOSSINVEST_APPROVAL_TOKEN\s*=",
    re.MULTILINE,
)


def markdown_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*.md")
        if not any(part in SKIP_PARTS for part in path.relative_to(ROOT).parts)
    )


def github_slug(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value).strip().lower()
    value = re.sub(r"[^\w\- ]", "", value, flags=re.UNICODE)
    return re.sub(r"\s+", "-", value)


def anchors(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    counts: dict[str, int] = {}
    values: set[str] = set()
    for heading in HEADING_PATTERN.findall(text):
        base = github_slug(heading)
        count = counts.get(base, 0)
        counts[base] = count + 1
        values.add(base if count == 0 else f"{base}-{count}")
    return values


def check_markdown(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    if text.count("```") % 2:
        errors.append(f"{path.relative_to(ROOT)}: unbalanced fenced code block")

    for raw_link in LINK_PATTERN.findall(text):
        link = raw_link.strip().strip("<>")
        if not link or "://" in link or link.startswith(("mailto:", "file:")):
            continue
        target_text, _, anchor = link.partition("#")
        target = path if not target_text else (path.parent / target_text).resolve()
        if not target.exists():
            errors.append(f"{path.relative_to(ROOT)}: missing local link target {raw_link!r}")
            continue
        if anchor and target.suffix.lower() == ".md" and anchor not in anchors(target):
            errors.append(
                f"{path.relative_to(ROOT)}: missing anchor #{anchor} in {target.relative_to(ROOT)}"
            )
    return errors


def dotenv_keys() -> set[str]:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    return {match.group(1) for match in re.finditer(r"^([A-Z][A-Z0-9_]*)=", text, re.MULTILINE)}


def expected_dotenv_keys() -> set[str]:
    keys = {
        field.upper() for field in Settings.model_fields if field != "tossinvest_enable_trading"
    }
    keys.add("MCP_PUBLISHED_PORT")
    return keys


def main() -> int:
    errors: list[str] = []
    files = markdown_files()
    for path in files:
        errors.extend(check_markdown(path))
        if RAW_APPROVAL_ASSIGNMENT.search(path.read_text(encoding="utf-8")):
            errors.append(f"{path.relative_to(ROOT)}: must not assign the raw approval token")

    actual = dotenv_keys()
    expected = expected_dotenv_keys()
    if actual != expected:
        errors.append(
            ".env.example keys differ from Settings/Compose: "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )

    canonical_readme = (ROOT / "README.md").read_text(encoding="utf-8")
    undocumented = sorted(key for key in actual if f"`{key}`" not in canonical_readme)
    if undocumented:
        errors.append(f"README.md does not document environment keys: {undocumented}")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(
        f"Documentation checks passed ({len(files)} Markdown files, {len(actual)} environment keys)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
