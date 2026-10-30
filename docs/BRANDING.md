# AI Video Studio — Brand and Repository Migration

## Current identity

**AI Video Studio** is the public-facing name for this project. The current software is **short-form first**. Its generic timeline, aspect-ratio options, and custom duration controls do not by themselves establish a complete or production-validated long-form workflow. Track that work in [#882–#885](https://github.com/yeongseon/short-form-studio/issues/882).

This branding change is intentionally **nonbreaking** at runtime. The following existing identifiers remain stable for compatibility:

- Python import module `shorts_api` and API route paths.
- Existing `shorts_default`, `ssul_v2`, recipes, workflow and persisted job identifiers.
- PostgreSQL database names, migrations, environment variables, Redis task/queue identifiers and object storage keys.
- Existing Docker Compose service names, images, and telemetry identities until a separate migration is reviewed.

The distribution/workspace name is updated to `ai-video-studio` in the root `pyproject.toml` and `uv.lock`. Packaged project consumers should check their installation references before switching; the import-level application namespaces remain unchanged.

## GitHub repository rename — separate administrative action

The original repository remains `yeongseon/short-form-studio` until the owner completes [the repository rename tracker (#886)](https://github.com/yeongseon/short-form-studio/issues/886). All existing clone commands, GitHub source links, and workflow references intentionally point to the current live slug until then.

When ready for the administrative cutover:

1. Confirm `yeongseon/ai-video-studio` is available and review existing GitHub Actions, image registries, badges, Pages, deployments, webhook subscriptions, and clone URLs.
2. Rename the repository through GitHub repository Settings; update its description and topics.
3. Change canonical repository URLs in root/package metadata, docs and examples. Validate that existing links redirect, while updating external consumers explicitly rather than relying indefinitely on redirects.
4. Verify `git remote` URLs, `uv lock --check`, web unit tests, Python tests, CI, image digest identity, registry references, and the protected deployment flow.
5. Preserve historical issue/PR references and do not rename production storage namespaces or deployment resources as a cosmetic change.

Do not enable public ingress or deploy a new production release solely as a consequence of a repository rename. Azure Container Apps staging deployment and its security prerequisites are tracked separately in [#893–#897](https://github.com/yeongseon/short-form-studio/issues/893).
