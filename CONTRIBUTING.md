# Contributing

Bug reports, documentation fixes, and pull requests are welcome under the MIT license.

## Development

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run python scripts/update_openapi.py --check
docker build .
```

Rules:

- Never use real trading credentials in tests or examples.
- Never add a CI path that submits a live order.
- Keep trading disabled by default.
- Add tests for changes to authentication, rate limiting, or trading safeguards.
- Use Conventional Commit messages.
- Update the OpenAPI manifest with `uv run python scripts/update_openapi.py --update` only after
  reviewing the official specification change.
