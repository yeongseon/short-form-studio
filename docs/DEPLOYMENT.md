# Production Deployment Guide

This document outlines the production deployment workflow for Short Form Studio, with a focus on database migration safety and rollback strategies.

## Overview

The CD (Continuous Deployment) workflow automates production deployments with the following stages:

1. **CI Gate**: Wait for all CI checks (lint, test, docker) to pass
2. **Migration**: Run Alembic migrations against production database
3. **Verification**: Confirm migration success and schema consistency
4. **Deploy**: Deploy application services (API, Worker, Frontend)
5. **Health Check**: Verify deployment success

## Prerequisites

### Required Secrets

Configure these in GitHub repository settings (`Settings > Secrets and variables > Actions`):

| Secret | Description | Example |
|--------|-------------|---------|
| `DATABASE_URL` | Production PostgreSQL connection string | `postgresql://user:pass@prod-db.example.com:5432/dbname` |
| _(deployment-specific)_ | Cloud provider credentials, SSH keys, etc. | Varies by infrastructure |

### Environment Protection Rules

The `production` environment should be configured with the following protections:

1. **Required Reviewers**: At least 1 reviewer from the production deployment team
2. **Deployment Branches**: Only `main` branch can deploy
3. **Wait Timer**: Optional 5-minute wait timer for additional safety
4. **Environment Secrets**: All production credentials stored as environment secrets

Configure in GitHub: `Settings > Environments > production > Protection rules`

### Infrastructure Requirements

Production environment must have:

- PostgreSQL 14+ database (accessible from GitHub Actions runners)
- Target deployment infrastructure (Kubernetes cluster, VMs, cloud platform, etc.)
- Network connectivity from GitHub Actions to production systems
- Monitoring and alerting configured for health checks

## Migration Strategy

### Philosophy: Backward-Compatible Migrations

All database migrations MUST be backward-compatible to support zero-downtime deployments:

**Allowed (safe) migrations:**
- Add new tables
- Add new columns with default values or NULL allowed
- Add new indexes (use `CONCURRENTLY` in PostgreSQL)
- Create new constraints that existing data already satisfies
- Add new ENUM values (at end of list in PostgreSQL)

**Requires Multi-Step Deployment:**
- Remove columns (1: make nullable, 2: stop using in code, 3: drop column)
- Remove tables (1: stop using in code, 2: drop table)
- Rename columns (1: add new column, 2: dual-write, 3: migrate data, 4: drop old column)
- Change column types (1: add new column, 2: migrate data, 3: drop old column)
- Add NOT NULL constraints (1: add nullable, 2: migrate data, 3: add constraint)

### Migration Workflow

#### 1. Creating a New Migration

```bash
# Always start from latest
cd apps/api
alembic upgrade head

# Create migration with descriptive name
alembic revision --autogenerate -m "add_video_thumbnail_url_column"

# Review generated migration file in migrations/versions/
# Verify upgrade() and downgrade() are correct
```

#### 2. Testing Migration Locally

```bash
# Test upgrade
alembic upgrade head

# Test downgrade (ensure rollback works)
alembic downgrade -1

# Re-upgrade to test idempotency
alembic upgrade head
```

#### 3. CI Validation

The CI workflow automatically validates migrations:

- **Single head check**: Ensures no branched migration history
- **Migration syntax check**: Verifies migration files are valid Python

No manual action needed - CI will fail if migrations are malformed.

#### 4. Production Deployment

When you push to `main`:

1. CI runs and validates migrations
2. CD workflow waits for CI to pass
3. GitHub prompts for production environment approval (required reviewer)
4. After approval, migrations run against production database
5. Application deploys only if migrations succeed

**Manual override** (emergency only):

```bash
# SSH to production server or use cloud CLI
cd /path/to/app
source venv/bin/activate
export DATABASE_URL="postgresql://..."
cd apps/api
alembic upgrade head
```

### Migration Verification

After migrations run, the CD workflow verifies:

```bash
# Show current revision
alembic current

# Show latest head(s)
alembic heads

# Verify no pending migrations
alembic history | grep "(head)" | wc -l  # Should be 1
```

## Rollback Strategy

### Application Rollback

If deployment fails or issues arise:

1. **Immediate**: Revert to previous deployment (e.g., `kubectl rollout undo`, Docker image tag rollback)
2. **Database**: Database stays at migrated state (see below)

### Database Rollback

**WARNING**: Database rollbacks are risky and should be avoided by following backward-compatible migration practices.

#### When to Rollback Migrations

Only rollback if:
- Migration introduced a critical bug affecting data integrity
- Migration blocked application functionality
- Rollback can be done safely without data loss

#### How to Rollback

```bash
# 1. Stop application traffic to database (read-only mode or full shutdown)
# 2. Identify target revision
cd apps/api
alembic history

# 3. Downgrade to previous revision
alembic downgrade -1  # Go back one revision
# OR
alembic downgrade <revision_id>  # Go to specific revision

# 4. Verify
alembic current

# 5. Restart application on older version
```

#### After Rollback

If you rolled back a migration:

1. Fix the migration locally
2. Test thoroughly (upgrade + downgrade + upgrade)
3. Create new PR with corrected migration
4. Deploy new migration after approval

**DO NOT** reuse the same revision ID - Alembic tracks executed revisions in `alembic_version` table.

## Deployment Commands

The CD workflow includes placeholder deployment steps. Configure based on your infrastructure:

### Kubernetes

```bash
# Update deployment images
kubectl set image deployment/api api=your-registry/api:${GITHUB_SHA}
kubectl set image deployment/worker worker=your-registry/worker:${GITHUB_SHA}

# Wait for rollout
kubectl rollout status deployment/api
kubectl rollout status deployment/worker

# Health check
kubectl exec deploy/api -- curl -sf http://localhost:8000/healthz
```

### Docker Compose (Single Server)

```bash
# SSH to server
ssh production-server << 'EOF'
cd /opt/short-form-studio
git pull origin main
docker compose pull
docker compose up -d --remove-orphans
docker compose ps
EOF

# Health check
curl -sf https://api.example.com/healthz
```

### Cloud Platforms

- **AWS ECS**: Update task definitions, create new service deployment
- **GCP Cloud Run**: Deploy new revision with `gcloud run deploy`
- **Azure Container Instances**: Update container group with new image
- **Heroku**: `git push heroku main` (migrations run automatically via release phase)

## Health Checks

After deployment, verify all services are healthy:

### API Health Check

```bash
curl -sf https://api.example.com/healthz
# Expected: {"status": "healthy"}
```

### Worker Health Check

```bash
# Check Celery worker logs
docker logs short-form-studio-worker-1
# OR
kubectl logs -l app=worker --tail=50

# Check Flower dashboard (if enabled)
open https://flower.example.com
```

### Frontend Health Check

```bash
curl -sf https://app.example.com/
# Expected: 200 OK with HTML content
```

### Database Connection Check

```bash
# From API container
docker exec short-form-studio-api-1 python -c "
from sqlalchemy import create_engine
import os
engine = create_engine(os.environ['DATABASE_URL'])
with engine.connect() as conn:
    result = conn.execute('SELECT 1')
    print('Database connected:', result.fetchone())
"
```

## Monitoring and Alerts

### Recommended Monitoring

- **Migration duration**: Alert if migrations take longer than expected
- **Deployment success rate**: Track failed deployments
- **Health check failures**: Alert immediately on 5xx errors
- **Database connections**: Monitor connection pool saturation
- **Worker queue depth**: Alert on backlog growth

### Logging

Key logs to monitor during deployment:

- **Alembic migration logs**: Verify each migration step
- **Application startup logs**: Check for configuration errors
- **Database query logs**: Identify slow queries after schema changes

## Troubleshooting

### Migration Fails with "Target database is not up to date"

**Cause**: Production database is behind expected revision.

**Solution**:
```bash
# Check current revision
alembic current

# Check expected revision
alembic heads

# Run pending migrations manually
alembic upgrade head
```

### Migration Fails with "Can't locate revision identified by '<revision>'"

**Cause**: Migration file missing or revision ID mismatch.

**Solution**:
1. Verify all migration files are committed and pushed
2. Check `alembic_version` table in database
3. If corrupted, manually fix revision ID in database

### Multiple Heads Detected

**Cause**: Conflicting migrations created on separate branches.

**Solution**:
```bash
# Show all heads
alembic heads

# Merge heads into single history
alembic merge -m "merge_migration_branches" <rev1> <rev2>

# Test merged migration
alembic upgrade head
```

### Deployment Succeeds but Application Crashes

**Cause**: Migration and code are incompatible.

**Solution**:
1. Check application logs for errors
2. Verify migration was backward-compatible
3. If not, rollback application (NOT database) to previous version
4. Fix code to handle new schema
5. Redeploy

## Security Considerations

### Database Credentials

- Store `DATABASE_URL` as encrypted GitHub secret
- Use read-write database user for migrations (not superuser)
- Rotate credentials regularly
- Audit migration logs for suspicious activity

### Migration Review

All migrations MUST be reviewed by at least one other engineer before merge:

- **Review checklist**:
  - [ ] Migration is backward-compatible
  - [ ] Downgrade function is correct and tested
  - [ ] No hardcoded credentials or sensitive data
  - [ ] Indexes use `CONCURRENTLY` for large tables
  - [ ] Data migrations are idempotent
  - [ ] Performance impact is acceptable

### Deployment Approval

Production deployments require manual approval from designated reviewers:

- Platform/SRE team for infrastructure changes
- Security team for auth/permission changes
- Product lead for schema changes affecting user data

## Emergency Procedures

### Roll Forward (Preferred)

If a deployment introduces a bug:

1. Create hotfix branch from `main`
2. Fix the issue
3. Deploy hotfix through normal CD pipeline (with expedited review)

### Roll Back (Last Resort)

If roll forward is not possible:

1. Revert application deployment to previous version
2. **DO NOT** rollback migrations unless absolutely necessary
3. Monitor for data consistency issues
4. Plan roll forward fix immediately

### Database Corruption

If migration corrupts data:

1. **STOP ALL APPLICATION TRAFFIC IMMEDIATELY**
2. Assess damage scope (query affected tables)
3. Restore from backup if necessary
4. Replay transaction logs if available
5. Notify users of potential data loss
6. Post-mortem required

## Post-Deployment

After successful deployment:

1. Monitor error rates and performance metrics for 1 hour
2. Verify background jobs are processing normally
3. Check Sentry/error tracking for new exceptions
4. Update deployment log with timestamp and version
5. Notify team in Slack/Discord

## References

- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [PostgreSQL Concurrent Indexes](https://www.postgresql.org/docs/current/sql-createindex.html#SQL-CREATEINDEX-CONCURRENTLY)
- [GitHub Actions Environment Protection Rules](https://docs.github.com/en/actions/deployment/targeting-different-environments/using-environments-for-deployment#environment-protection-rules)
- [Usage Guide](USAGE.md)
- [Production Cutover Checklist](CUTOVER.md)
