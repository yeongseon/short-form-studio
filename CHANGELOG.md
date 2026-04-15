# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Mermaid architecture diagrams in README (system topology, pipeline flow, package dependencies)
- CI pipeline with lint, test (coverage), Docker build, and smoke test
- Community files: CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md
- GitHub issue templates (bug report, feature request) and PR template
- Documentation: Usage Guide (`docs/USAGE.md`), Deployment Guide (`docs/CUTOVER.md`)
- API contract tests for response shapes and CORS policy
- Python constraints file (`constraints.txt`) for reproducible installs
- Provider abstraction layer with pluggable LLM, Image, TTS, and STT adapters
- Support for remote providers: OpenAI, Anthropic, Google Gemini, Stability AI, ElevenLabs
- Support for local GPU providers: Ollama, Stable Diffusion, Qwen TTS, Whisper STT
- Redis-based GPU lock for local model execution
- Docker Compose profiles: `gpu` for AI services, `monitoring` for Flower
- Authenticated artifact route replacing static file mounts
- Paragraph-level generation with per-section skip/retry logic
- Human-in-the-loop review gates at every pipeline stage

### Changed

- Raised basedpyright type checking to `standard` mode (0 errors)
- Bound all Docker services to `127.0.0.1` for security
- Switched Gemini API key transport from URL query string to `x-goog-api-key` header
- Split Docker Compose into base (`docker-compose.yml`) and dev (`docker-compose.dev.yml`)
- Consolidated stage policy into central location (`types/api.ts`)
- Extended Vite dev proxy for same-origin API workflows

### Fixed

- Paragraph-level generation status detection and completed section skipping
- Worker `active_task_id` cleanup on paragraph task completion
- Paragraph-level artifact filtering from run-level audio/subtitle queries
- Duplicate task dispatch blocked when generation already in progress
- Late-finishing worker prevented from advancing cancelled runs
- Hard-coded Alembic password fallback removed
- Run stage conflict returns 409 instead of silent failure
- Model-default validation before task dispatch (audio, subtitle, render profiles)
- Stage guard enforcement on script and visual-plan mutation endpoints
- Optimistic UI state rollback on model-default update failure
- Subtitle format restricted to `srt|vtt` enum
- Nginx proxy health/docs routing for same-origin OpsPage
