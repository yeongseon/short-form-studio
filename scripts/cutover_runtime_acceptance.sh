#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export COMPOSE_PROJECT_NAME="cutover-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
STATE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/cutover-acceptance.XXXXXX")"
ENV_BACKUP="$STATE_DIR/env.backup"
if [ -f .env ]; then cp .env "$ENV_BACKUP"; fi

fail() { printf 'ACCEPTANCE FAIL: %s\n' "$*" >&2; exit 1; }
code() { curl -sS -o /dev/null -w '%{http_code}' "$@"; }
cleanup() {
  docker compose down --volumes --remove-orphans || true
  if [ -f "$ENV_BACKUP" ]; then cp "$ENV_BACKUP" .env; else rm -f .env; fi
  rm -rf "$STATE_DIR"
}
trap cleanup EXIT

cp .env.example .env
docker compose up -d postgres redis
docker compose run --rm api alembic upgrade head

docker compose run --rm api python scripts/create_api_key.py \
  --email cutover@example.com --workspace cutover --name cutover-ci > "$STATE_DIR/cutover-key.txt"
API_KEY="$(grep -oE '  [A-Za-z0-9_-]+$' "$STATE_DIR/cutover-key.txt" | tr -d ' ')"
[ -n "$API_KEY" ] || fail "creator key bootstrap returned no key"
export API_KEY

docker compose run --rm api python scripts/create_api_key.py \
  --email foreign@example.com --workspace foreign --name foreign-ci > "$STATE_DIR/foreign-key.txt"
FOREIGN_WORKSPACE_ID="$(grep -oE 'Workspace: id=[0-9]+' "$STATE_DIR/foreign-key.txt" | cut -d= -f2)"
[ -n "$FOREIGN_WORKSPACE_ID" ] || fail "foreign workspace bootstrap returned no id"

python3 - "$API_KEY" <<'PY'
from pathlib import Path
import sys

path = Path(".env")
lines = path.read_text(encoding="utf-8").splitlines()
path.write_text(
    "\n".join(f"API_KEY={sys.argv[1]}" if line.startswith("API_KEY=") else line for line in lines) + "\n",
    encoding="utf-8",
)
PY

docker compose up -d api worker beat studio-web
timeout 90 bash -c 'until curl -sf http://127.0.0.1:8000/healthz >/dev/null; do sleep 2; done'
timeout 90 bash -c 'until curl -sf http://127.0.0.1:5174/ >/dev/null; do sleep 2; done'

[ "$(code http://127.0.0.1:8000/api/creator/users/me)" = 401 ] \
  || fail "creator endpoint did not return 401 without a key"
[ "$(code -H "X-API-Key: ${API_KEY}" http://127.0.0.1:8000/api/creator/users/me)" = 200 ] \
  || fail "creator endpoint did not return 200 with the exported key"

for task in reconcile_stale_dispatches retry_failed_artifact_deletions sweep_expired_artifacts; do
  timeout 60 bash -c "until docker compose exec -T worker celery -A celery_app.celery_app inspect registered 2>/dev/null | grep -q '$task'; do sleep 2; done"
  printf 'registered: %s\n' "$task"
done

PROJECT="$(curl -fsS -H "X-API-Key: ${API_KEY}" -H 'Content-Type: application/json' \
  -d '{"title":"Beat acceptance","source_type":"idea","idea_brief":"disposable"}' \
  http://127.0.0.1:8000/api/creator/projects)"
PROJECT_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$PROJECT")"
RUN="$(curl -fsS -H "X-API-Key: ${API_KEY}" -H 'Content-Type: application/json' \
  -d '{"style_preset":"default"}' \
  "http://127.0.0.1:8000/api/creator/projects/${PROJECT_ID}/runs")"
RUN_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$RUN")"

docker compose exec -T postgres psql -U short_form_user -d short_form_studio -v ON_ERROR_STOP=1 \
  -c "INSERT INTO creator_run_tasks (run_id,task_type,celery_task_id,status,attempt,created_at) VALUES (${RUN_ID},'generate_script','cutover-stale-${RUN_ID}','pending',1,NOW()-INTERVAL '5 minutes');"

timeout 150 bash -c "until [ \"\$(docker compose exec -T postgres psql -U short_form_user -d short_form_studio -Atc \"SELECT status FROM creator_run_tasks WHERE celery_task_id='cutover-stale-${RUN_ID}'\")\" = failed ]; do sleep 3; done"
RUN_STATE="$(docker compose exec -T postgres psql -U short_form_user -d short_form_studio -Atc "SELECT status||':'||current_stage FROM creator_runs WHERE id=${RUN_ID}")"
[ "$RUN_STATE" = "failed:FAILED" ] || fail "Beat housekeeping produced unexpected run state: $RUN_STATE"
docker compose logs beat | grep -q 'reconcile-stale-dispatches' \
  || fail "Beat log has no reconcile-stale-dispatches dispatch evidence"

ORIGIN='Origin: http://localhost:5174'
MUTATION_CODE="$(code -H "$ORIGIN" -H 'Content-Type: application/json' \
  -d '{"title":"nginx mutation","source_type":"idea","idea_brief":"same origin"}' \
  http://localhost:5174/api/creator/projects)"
[ "$MUTATION_CODE" = 201 ] || fail "same-origin nginx mutation returned $MUTATION_CODE"

FOREIGN_CODE="$(code "http://localhost:5174/api/creator/workspaces/${FOREIGN_WORKSPACE_ID}/assets")"
[ "$FOREIGN_CODE" = 404 ] || fail "foreign workspace returned $FOREIGN_CODE instead of 404"

PNG="$STATE_DIR/upload.png"
printf '%s' 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=' | base64 -d > "$PNG"
WORKSPACE_ID="$(grep -oE 'Workspace: id=[0-9]+' "$STATE_DIR/cutover-key.txt" | cut -d= -f2)"
UPLOAD_CODE="$(code -H "$ORIGIN" -H 'Accept: application/json' \
  -F "file=@${PNG};type=image/png" \
  "http://localhost:5174/api/creator/workspaces/${WORKSPACE_ID}/assets")"
[ "$UPLOAD_CODE" = 201 ] || fail "same-origin nginx upload returned $UPLOAD_CODE"

printf 'Cutover runtime acceptance passed: auth 401/200, workspace 404, mutation/upload, Beat DB transition.\n'
