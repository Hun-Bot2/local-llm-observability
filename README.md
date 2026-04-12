# local-llm-observability

Translation pipeline and observability project for Korean MDX blog posts.

This repo is focused on:

- translating Korean blog posts to English and Japanese
- running translation on local Ollama or RunPod GPU
- checking translation quality against the original Korean source
- storing pipeline/cache/quality data in PostgreSQL
- preparing a Firebase-hosted operations dashboard

## What It Does

The project reads Korean `.mdx` blog posts, splits them into sections, translates them, scores quality, and writes translated files back to disk.

Current workflow:

1. Read Korean source posts from a local folder or repo
2. Parse frontmatter and body sections
3. Translate sections with local Ollama or RunPod
4. Score quality
5. Save translated output
6. Track cache, runs, and metrics in PostgreSQL
7. Surface status in a web dashboard later

## Current Architecture

- Translation backend: Python
- Local inference: Ollama
- Cloud inference: RunPod worker
- Storage: PostgreSQL + pgvector
- Controller API: FastAPI with Server-Sent Events for run progress
- Ops frontend: SvelteKit dashboard, deployable as static output to Firebase Hosting
- Observability target: Grafana Cloud

Architecture docs:

- [v1.md](/Users/jeonghun/local-llm-observability/v1.md)
- [v1+v2.md](/Users/jeonghun/local-llm-observability/v1+v2.md)
- [v1-architecture.drawio](/Users/jeonghun/local-llm-observability/docs/v1-architecture.drawio)

## Main Files

- [scripts/scan_posts.py](/Users/jeonghun/local-llm-observability/scripts/scan_posts.py)
  V2 scanner for missing/stale translated MDX files.

- [scripts/translate_changed.py](/Users/jeonghun/local-llm-observability/scripts/translate_changed.py)
  V2 incremental runner. It scans first and only translates files that need work.

- [local_llm_observability/translator.py](/Users/jeonghun/local-llm-observability/local_llm_observability/translator.py)
  Main translation pipeline with DB/cache/trace integration.

- [tests/local_translate.py](/Users/jeonghun/local-llm-observability/tests/local_translate.py)
  Local-only model comparison script without DB/RunPod dependencies.

- [runpod/worker.py](/Users/jeonghun/local-llm-observability/runpod/worker.py)
  RunPod worker API exposing `/health`, `/translate`, and `/embed`.

- [local_llm_observability/mdx_parser.py](/Users/jeonghun/local-llm-observability/local_llm_observability/mdx_parser.py)
  MDX parser and section splitter.

- [local_llm_observability/cache_manager.py](/Users/jeonghun/local-llm-observability/local_llm_observability/cache_manager.py)
  Cache diffing and cache write-back.

- [local_llm_observability/quality_scorer.py](/Users/jeonghun/local-llm-observability/local_llm_observability/quality_scorer.py)
  Structure / glossary / length / hallucination scoring.

- [local_llm_observability/db/db_manager.py](/Users/jeonghun/local-llm-observability/local_llm_observability/db/db_manager.py)
  PostgreSQL access layer.

- [local_llm_observability/api/main.py](/Users/jeonghun/local-llm-observability/local_llm_observability/api/main.py)
  Local FastAPI controller for posts, file details, translation runs, and event streaming.

- [frontend/src/routes/+page.svelte](/Users/jeonghun/local-llm-observability/frontend/src/routes/+page.svelte)
  Real-time SvelteKit operations dashboard.

## Repo Layout

```text
local-llm-observability/
├── local_llm_observability/ # Python application package
│   ├── api/          # FastAPI controller API
│   └── db/           # PostgreSQL access layer
├── scripts/          # CLI entrypoints for scanning and incremental runs
├── tests/            # Unit tests and local-only model comparison script
├── samples/          # Local MDX fixtures and generated sample outputs
├── frontend/         # SvelteKit real-time dashboard
├── runpod/           # Docker image + worker for GPU inference
├── database/         # PostgreSQL schema
├── docs/             # Architecture diagrams
├── scan_posts.py     # Compatibility wrapper for scripts/scan_posts.py
├── translate_changed.py # Compatibility wrapper for scripts/translate_changed.py
├── translate.py      # Compatibility wrapper for local_llm_observability.translator
├── v1.md             # V1 architecture
├── v1+v2.md          # V1/V2 roadmap
├── new-arch.md       # Research-driven architecture and development order
└── memory.md         # Project state memory
```

## Useful Commands

Start local controller:

```bash
./venv/bin/uvicorn controller.main:app --reload --port 8000
```

Start frontend dashboard:

```bash
npm --prefix frontend install
npm --prefix frontend run dev
```

Run deterministic tests:

```bash
./venv/bin/python tests/run_tests.py
```

Scan local source posts without translating:

```bash
./venv/bin/python scripts/scan_posts.py --source-dir samples/mdx
```

Run V2 in dry-run mode for English only:

```bash
./venv/bin/python scripts/translate_changed.py --source-dir samples/mdx --langs en
```

Run V2 for real with local Ollama:

```bash
./venv/bin/python scripts/translate_changed.py --langs en --local --only After_interview --limit 1 --execute
```

Run V2 for real with RunPod:

```bash
./venv/bin/python scripts/translate_changed.py --source-dir samples/mdx --langs en jp --runpod-url https://YOUR-POD-8000.proxy.runpod.net --execute
```

For production use, replace `samples/mdx` with the real Korean blog source path.

Model testing command:

```bash
./venv/bin/python scripts/translate_changed.py --langs en --local --en-model gemma4:latest --only After_interview --limit 1 --execute
```

## Roadmap

### V1

- translate all existing local Korean blog posts
- score translation quality
- write outputs into local folder
- notify started / running / completed / failed / low-quality
- manual review and manual commit

### V2

- detect newly committed or changed Korean blog posts
- run translation automatically
- score quality automatically
- notify results automatically

Current V2 foundation:

- deterministic scanner exists
- incremental dry-run exists
- real execution is available behind `--execute`
- local FastAPI controller exists
- real-time SvelteKit dashboard exists
- progress events are recorded in PostgreSQL `run_events`
