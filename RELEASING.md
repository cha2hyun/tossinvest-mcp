# Releasing TossInvest MCP

The project uses Semantic Versioning and immutable annotated tags named `vX.Y.Z`.

## Choose the version

- Patch (`X.Y.Z+1`): compatible fixes, documentation, dependency, and OpenAPI maintenance.
- Minor (`X.Y+1.0`): compatible tools or capabilities.
- Major (`X+1.0.0`): breaking tool schemas, configuration, or behavior.

Update the version in both `pyproject.toml` and `src/tossinvest_mcp/__init__.py`. The contract test
requires these values to match.

## Publish a release

1. Run the verification commands documented in `README.md`.
2. Commit the version change to `main`, push it, and wait for CI to pass.
3. Create and push an annotated tag that exactly matches the package version:

   ```bash
   git tag -a vX.Y.Z -m "Release vX.Y.Z"
   git push origin vX.Y.Z
   ```

The `Release` GitHub Actions workflow validates the source again, builds the Python wheel and
source distribution, generates `SHA256SUMS.txt`, publishes amd64/arm64 container images to GHCR,
and creates a GitHub Release with generated notes and attached distributions.

Published tags must never be moved or reused. If a release needs a correction, publish the next
patch version.
