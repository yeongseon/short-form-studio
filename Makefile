install:
	python3 -m pip install -c constraints.txt -r apps/api/requirements.txt -r apps/worker-orchestrator/requirements.txt
	npm --prefix apps/studio-web install

dev:
	@echo "Run services in separate terminals:"
	@echo "- API: uvicorn shorts_api.main:app --app-dir apps/api/src --reload"
	@echo "- Worker: celery -A celery_app.celery_app worker --workdir apps/worker-orchestrator --loglevel=info"
	@echo "- Web: npm --prefix apps/studio-web run dev"

lint:
	ruff check apps packages
	python3 -m compileall apps packages
	@if [ -d apps/studio-web/node_modules ]; then npm --prefix apps/studio-web run lint; else echo "Skipping studio-web lint (run make install first)"; fi

format:
	ruff format apps packages
	@if [ -d apps/studio-web/node_modules ]; then npm --prefix apps/studio-web run format; else echo "Skipping studio-web format (run make install first)"; fi

test:
	cd apps/api && python3 -m pytest tests/ -v
	cd apps/worker-orchestrator && python3 -m pytest tests/ -v
	@if [ -d apps/studio-web/node_modules ]; then npm --prefix apps/studio-web run test; else echo "Skipping studio-web tests (run make install first)"; fi

build:
	python3 -m compileall apps packages
	@if [ -d apps/studio-web/node_modules ]; then npm --prefix apps/studio-web run build; else echo "Skipping studio-web build (run make install first)"; fi

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-up-all:
	docker compose --profile monitoring up -d

docker-logs:
	docker compose logs -f

# --- Local Server (LAN-accessible) ---

docker-local-up:
	docker compose -f docker-compose.yml -f docker-compose.local-server.yml up -d postgres redis api worker studio-web

docker-local-build:
	docker compose -f docker-compose.yml -f docker-compose.local-server.yml up -d --build postgres redis api worker studio-web

docker-local-migrate:
	docker compose run --rm api alembic upgrade head

docker-local-bootstrap:
	docker compose run --rm api python scripts/create_api_key.py --email local@example.com --workspace local --name local-server
	@echo ""
	@echo "Copy the generated API key into .env as API_KEY, then run:"
	@echo "  make docker-local-up"

docker-local-logs:
	docker compose -f docker-compose.yml -f docker-compose.local-server.yml logs -f api worker studio-web

docker-local-down:
	docker compose -f docker-compose.yml -f docker-compose.local-server.yml down

docker-local-status:
	docker compose -f docker-compose.yml -f docker-compose.local-server.yml ps

# --- Dependency locking ---
# Regenerate constraints.txt from the uv lockfile (deterministic, no environment pollution).
lock:
	uv export --no-hashes -o constraints.txt
	@echo "constraints.txt regenerated from uv.lock"

# Bump version in pyproject.toml. Usage: make release VERSION=0.5.0
release:
	@test -n "$(VERSION)" || { echo "Usage: make release VERSION=0.5.0"; exit 1; }
	python3 -c "import re; s=open('pyproject.toml').read(); s=re.sub(r'^version = \".*\"', 'version = \"$(VERSION)\"', s, flags=re.M); open('pyproject.toml','w').write(s)"
	@echo "Bumped pyproject.toml to $(VERSION). Review, commit, then: git tag v$(VERSION) && git push --tags"
