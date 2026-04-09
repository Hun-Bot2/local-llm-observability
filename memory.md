# Project Memory

Last updated: 2026-04-09

## Current Goal

Build a translation platform for Korean MDX blog posts that:

- uses `RunPod` for GPU inference
- stores metrics and cache in `PostgreSQL`
- exposes a web dashboard through `Firebase Hosting`
- evolves into a strong portfolio project with observability and quality tracking

## Architecture Decisions

- Frontend hosting: `Firebase Hosting`
- Frontend style for V1: static `HTML/CSS/JS`, not React/Next.js
- Backend/orchestrator target: `Cloud Run` + Python API later
- Database target for V1 design: `Neon Postgres + pgvector`
- GPU inference: `RunPod`
- Dashboard/observability target: `Grafana Cloud`

## RunPod Status

- Custom image created and pushed:
  - `hunbot/blog-translator-worker:latest`
- Worker file exists:
  - `runpod/worker.py`
- Container setup exists:
  - `runpod/Dockerfile`
  - `runpod/entrypoint.sh`
- RunPod worker endpoints verified:
  - `/health`
  - `/translate`
  - `/embed`
- Important RunPod configuration learned:
  - expose `8000/http`
  - mount network volume at `/root/.ollama`
  - use enough container disk

## Translation Pipeline Status

- Main CLI exists:
  - `translate.py`
- Separate local-only test script exists:
  - `testing/local_translate.py`
- Local tester is intended for quick model comparison without DB/cache/RunPod dependencies

## Model Notes

- Local Ollama confirmed working
- Confirmed local models:
  - `gemma4:latest`
  - `qwen3:14b`
- Current preference:
  - KR -> EN candidate: `gemma4:latest`
  - KR -> JP candidate: `qwen3:14b`

## Known Translation Issues

Observed in `Algorithm_Bot_01_en.mdx`:

- frontmatter description expanded incorrectly
- some Korean code comments were not translated
- some generated English content was hallucinated/over-expanded

Mitigations already added:

- stronger frontmatter rules:
  - do not change frontmatter structure
  - translate only the value
  - one-line output for title/description
- code block prompt:
  - preserve code exactly
  - translate only comments/docstrings

## Frontend Status

Firebase Hosting frontend files now exist:

- `frontend/index.html`
- `frontend/style.css`
- `frontend/app.js`
- `frontend/404.html`

Current frontend state:

- real static UI exists
- currently uses mock data
- prepared for future API integration via `CONFIG.apiBaseUrl` in `frontend/app.js`

## Docs Status

- V1 written architecture:
  - `v1.md`
- New clean draw.io architecture:
  - `docs/v1-architecture.drawio`

## Important Repo Files

- RunPod worker:
  - `runpod/worker.py`
- Main CLI:
  - `translate.py`
- Local tester:
  - `testing/local_translate.py`
- DB manager:
  - `src/db/db_manager.py`
- Parser:
  - `src/mdx_parser.py`
- Cache manager:
  - `src/cache_manager.py`
- Frontend:
  - `frontend/index.html`
  - `frontend/style.css`
  - `frontend/app.js`

## Immediate Next Steps

1. Build a real post-scanning/checking script
   - count source Korean posts
   - count translated EN/JP posts
   - detect missing/stale translations

2. Add backend API endpoints for the frontend
   - dashboard summary
   - recent runs
   - translation status per document
   - trigger endpoint

3. Replace mock frontend data with real API data

4. Revisit translation quality after comparing:
   - `gemma4:latest`
   - `qwen3:14b`

## Reminder

- Do not introduce extra frameworks without clear need
- Ruby-based web app was judged overengineering for V1
- Keep the frontend simple and the backend/API authoritative
