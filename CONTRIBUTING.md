# Contributing

Bug reports, documentation fixes, and pull requests are welcome under the MIT license.

## Development

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src scripts tests
uv run python scripts/check_docs.py
uv run python scripts/validate_skills.py
uv run python scripts/update_openapi.py --check
uv run pip-audit --strict .
uv build
docker build .
./scripts/run_e2e.sh
```

Rules:

- Never use real trading credentials in tests or examples.
- Never add a CI path that submits a live order.
- Keep E2E tests hermetic; they must use the local fake upstream and never contact a live API.
- Keep trading disabled by default.
- Add tests for changes to authentication, rate limiting, or trading safeguards.
- Keep `.env.example`, README variable names, MCP annotations, and Skill tool dependencies aligned.
- Do not add the raw human approval token to server or Hermes configuration examples.
- Use Conventional Commit messages.
- Update the OpenAPI manifest with `uv run python scripts/update_openapi.py --update` only after
  reviewing the official specification change.

## Releases

See [RELEASING.md](RELEASING.md) for the versioning, validation, tagging, and automated GitHub
Release process. Release tags are immutable and must match the package version exactly.
