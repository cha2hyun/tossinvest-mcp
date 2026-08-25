# Releasing TossInvest MCP

The project uses Semantic Versioning and immutable annotated tags named `vX.Y.Z`.

## Choose the version

- Patch (`0.1.0` → `0.1.1`): compatible fixes, documentation, dependency, and OpenAPI maintenance.
- Minor (`0.1.1` → `0.2.0`): compatible tools or capabilities.
- Major (`0.2.0` → `1.0.0`): breaking tool schemas, configuration, or behavior.

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

The full `X.Y.Z` container tag is immutable. The `X.Y` and `latest` tags are convenience aliases
and move when a compatible or any new release is published, respectively. Production deployments
should pin the full version tag or image digest.

If the workflow fails before the GitHub Release is complete, fix the workflow or transient cause
and rerun the same GitHub Actions run. The workflow can upload rebuilt artifacts to an existing
release. Do not delete, recreate, or move the release tag.

Published tags must never be moved or reused. If a release needs a correction, publish the next
patch version.
