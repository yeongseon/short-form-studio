install:
	python3 -m pip install -r apps/api/requirements.txt -r apps/worker-orchestrator/requirements.txt
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
	@echo "No tests scaffolded yet."

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
