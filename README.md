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
- Ops frontend: Firebase Hosting static web app
- Observability target: Grafana Cloud

Architecture docs:

- [v1.md](/Users/jeonghun/local-llm-observability/v1.md)
- [v1+v2.md](/Users/jeonghun/local-llm-observability/v1+v2.md)
- [v1-architecture.drawio](/Users/jeonghun/local-llm-observability/docs/v1-architecture.drawio)

## Main Files

- [translate.py](/Users/jeonghun/local-llm-observability/translate.py)
  Main CLI pipeline for translation with DB/cache integration.

- [testing/local_translate.py](/Users/jeonghun/local-llm-observability/testing/local_translate.py)
  Local-only model comparison script without DB/RunPod dependencies.

- [runpod/worker.py](/Users/jeonghun/local-llm-observability/runpod/worker.py)
  RunPod worker API exposing `/health`, `/translate`, and `/embed`.

- [src/mdx_parser.py](/Users/jeonghun/local-llm-observability/src/mdx_parser.py)
  MDX parser and section splitter.

- [src/cache_manager.py](/Users/jeonghun/local-llm-observability/src/cache_manager.py)
  Cache diffing and cache write-back.

- [src/quality_scorer.py](/Users/jeonghun/local-llm-observability/src/quality_scorer.py)
  Structure / glossary / length / hallucination scoring.

- [src/db/db_manager.py](/Users/jeonghun/local-llm-observability/src/db/db_manager.py)
  PostgreSQL access layer.

- [frontend/index.html](/Users/jeonghun/local-llm-observability/frontend/index.html)
  Static Firebase-hosted operations dashboard shell.

## Repo Layout

```text
local-llm-observability/
├── frontend/         # Firebase Hosting static dashboard
├── runpod/           # Docker image + worker for GPU inference
├── src/              # Parser, cache, DB, quality, sample MDX files
├── testing/          # Local-only translation test scripts
├── database/         # PostgreSQL schema
├── docs/             # Architecture diagrams
├── translate.py      # Main translation CLI
├── v1.md             # V1 architecture
├── v1+v2.md          # V1/V2 roadmap
└── memory.md         # Project state memory
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
