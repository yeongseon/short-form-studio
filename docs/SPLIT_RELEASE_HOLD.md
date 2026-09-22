# Source integration hold and eventual release

Merge the dedicated CD safety PR **before** the seven refactor groups. CD's
entry points now require the repository variable `DEPLOYMENT_ENABLED` to equal
`true`. An absent variable is closed by default: main CI still runs, but CD
does not build/publish images or execute migrations. Manual dispatch is held too,
including the `always()` deployment-tag path. No repository setting is changed
by merging this workflow. Confirm the variable is absent or false and inspect
any already-running CD jobs before merging: a new gate cannot stop older runs.

This is a source-integration safeguard, not production release authorization.
Keep it closed throughout all seven merges. Require exact-current-head CI and
fresh 100/100 security/production-hardening review for each applicable PR.
Early boundaries may expose the pre-existing fresh-clone smoke failure; inspect
it and bring forward its focused PR7 fix through review instead of bypassing CI.

## Operator resume procedure (separate release approval)

1. After the complete series lands, record the exact reviewed source SHA and
   successful `lint`, `test`, `docker`, and `first-short-runtime` checks for that
   SHA. The runtime check arrives in PR7; never substitute a moving main ref or
   a skipped runtime run. The CD wait inputs use `github.sha`.
2. Record the current database migration revision and take restorable backups
   of both the database and media bytes/object storage. Verify restoration in
   isolation. Reserve a maintenance window for migration 035's ordinary index
   creation if `api_keys` is large. Apply 034/035 before code needs media storage.
3. Record matched API, worker, and Studio image **digests** for the release and
   previous compatible version. Neither `latest` nor the current date-tag
   generator is a reliable rollback identity. Drain/isolate queued work before
   changing the API/worker approval contract; enable the new UI only with its
   matching API/worker. Preserve the explicitly supported legacy generation flow.
4. Implement and review real deployment commands and smoke targets first.
   Current deploy commands only echo placeholders; staging smoke targets
   `staging.example.com`. Migrations, in contrast, are real. Do not enable this
   workflow merely to try the placeholders. Environment names alone do not
   establish approval protection. Review publication-before-scan behavior too.
5. Only an explicitly authorized operator may set `DEPLOYMENT_ENABLED=true`
   for an approved release and deliberately trigger the reviewed release path.
   Reconfirm the exact source/check/image correspondence immediately beforehand.
   Leave it false/absent until that procedure exists. Setting it true permits
   subsequent main pushes to publish and migrate; restore the hold after the
   approved release window. This document/task does not perform either action.

## Data-preserving rollback

Prefer matched compatible application images while retaining additive schema
and data. Define how new-stage runs/approvals and queued jobs are handled before
rollback. Migration **034 downgrade drops `creator_media_assets` and its data**;
do not run automatic downgrades to roll back application code. Restore database
and media together only under a separately approved restore plan.

The existing manual `image_tag` input is not a validated rollback mechanism:
it skips build/scans, runs migrations from the dispatched checkout rather than
the image's source, and reaches placeholder deployment steps. Keep the hold
closed for this path as well; do not claim it restores running applications.
