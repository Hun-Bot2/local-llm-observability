# Project Memory

Last updated: 2026-04-13

## Current Goal

Build a translation platform for Korean MDX blog posts that:

- scans the real local blog repository
- translates Korean MDX posts to English and Japanese
- uses `RunPod` for GPU inference
- stores metrics and cache in `PostgreSQL`
- exposes a real-time SvelteKit dashboard
- evolves into a strong portfolio project with observability and quality tracking

## Architecture Decisions

- Frontend hosting: `Firebase Hosting`
- Frontend app: `SvelteKit` for real-time dashboard, built as static output for Firebase Hosting later
- Backend/orchestrator: `FastAPI` local controller first, Cloud Run later
- Database target for V1 design: `Neon Postgres + pgvector`
- Development database: local PostgreSQL first, migrate to Neon later
- GPU inference: `RunPod`
- Local inference: `Ollama`
- Dashboard/observability target: `Grafana Cloud`
- WebAssembly: not for core pipeline now; possible later for browser-side MDX/token/structure analysis
- Translation quality architecture now follows `new-arch.md`:
  - human-owned quality rubric first
  - full LLM call tracing
  - hard validator gates
  - human review queue
  - correction dataset for future SFT/DPO
  - future COMETKiwi/xCOMET-style QE gating
- Target definition is service accuracy, not raw model accuracy:
  - `SPR@MQM >= 99%`
  - `SVPR >= 99.9%`
  - 0 critical errors allowed
  - validator failures must not ship

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

- Main translator package exists:
  - `local_llm_observability/translator.py`
- Main CLI wrapper exists:
  - `translate.py`
- Separate local-only test script exists:
  - `tests/local_translate.py`
- Local tester is intended for quick model comparison without DB/cache/RunPod dependencies
- V2 incremental runner exists:
  - `scripts/translate_changed.py`
- V2 source scanner exists:
  - `scripts/scan_posts.py`
  - `local_llm_observability/blog_scanner.py`
- Real blog source path is configured:
  - `/Users/jeonghun/hun-bot-blog/src/content/blog`
- Real blog layout:
  - Korean source: `/Users/jeonghun/hun-bot-blog/src/content/blog/ko/...`
  - English output: `/Users/jeonghun/hun-bot-blog/src/content/blog/en/...`
  - Japanese output: `/Users/jeonghun/hun-bot-blog/src/content/blog/jp/...`
- Scanner verified against real blog repo:
  - detected `43` Korean source posts
- Translation output path is mirror-based:
  - `ko/devlog/ALGO_BOT/Algorithm_Bot_01.mdx`
  - becomes `en/devlog/ALGO_BOT/Algorithm_Bot_01.mdx`
  - or `jp/devlog/ALGO_BOT/Algorithm_Bot_01.mdx`

## Model Notes

- Local Ollama confirmed working
- Confirmed local models:
  - `gemma4:latest`
  - `qwen3:14b`
- Current preference:
  - KR -> EN candidate: `gemma4:latest`
  - KR -> JP candidate: `qwen3:14b`
- Do not use `translategemma:12b` locally unless it is explicitly pulled.

## Known Translation Issues

Observed in `Algorithm_Bot_01_en.mdx`:

- frontmatter description expanded incorrectly
- some Korean code comments were not translated
- some generated English content was hallucinated/over-expanded

Observed in bad Japanese `Algorithm_Bot_02` output:

- generated whole unrelated article sections
- added headings not present in source
- added fake/example links such as `example.com`
- left Korean text inside Japanese output
- expanded sections far beyond source size

Mitigations already added:

- stronger frontmatter rules:
  - do not change frontmatter structure
  - translate only the value
  - one-line output for title/description
- code block prompt:
  - preserve code exactly
  - translate only comments/docstrings
- code fence issue fixed:
  - previous logic globally removed triple backticks
  - removed global backtick stripping
  - added deterministic code-fence restoration for code sections
  - cached code translations without required fences are rejected and retranslated
- hard translation validator added:
  - rejects added headings
  - rejects added URLs
  - rejects `example.com`
  - rejects translator/meta commentary
  - rejects too much leftover Korean in Japanese output
  - rejects excessive expansion
  - rejects broken/changed code fences
- invalid generated output is now recorded to `llm_calls` and queued in `human_review_queue`

## Current Translation Rules

- Do not change frontmatter structure.
- Translate only selected frontmatter values.
- Keep `title`, `description`, and `series` as one-line values.
- Preserve Markdown structure.
- Preserve fenced code blocks.
- Preserve opening code fence language marker exactly, for example:
  - triple backticks plus `yml`
  - triple backticks plus `python`
- Translate only human-language comments/docstrings inside code blocks.
- Do not translate identifiers, commands, URLs, secrets placeholders, or code syntax.

## Frontend Status

SvelteKit dashboard files now exist:

- `frontend/package.json`
- `frontend/src/routes/+page.svelte`
- `frontend/src/app.css`
- `frontend/404.html`

Current frontend state:

- real SvelteKit UI exists
- calls local FastAPI controller at `http://localhost:8000`
- supports file selector, local MDX file inspection, language/model/backend controls
- receives real-time progress through Server-Sent Events
- shows file stats, timeline, cost/time/token metrics, and run history
- has Apple-style glass UI direction
- has loading/progress motion:
  - spinning status pill
  - spinning translation button
  - pulsing live indicator
  - animated timeline updates
- has browser-local run history:
  - stored in `localStorage`
  - separate from Postgres run history
- has Postgres-backed run history:
  - loaded from `/api/runs`
- old static frontend files were replaced:
  - removed `frontend/index.html`
  - removed `frontend/style.css`
  - removed `frontend/app.js`

## Controller Status

- Local FastAPI controller exists:
  - `local_llm_observability/api/main.py`
  - `controller/main.py` remains a compatibility wrapper
- Current endpoints:
  - `GET /api/health`
  - `GET /api/posts`
  - `GET /api/file-detail?path=...`
  - `GET /api/runs`
  - `GET /api/runs/{run_id}`
  - `GET /api/runs/{run_id}/events`
  - `GET /api/quality/rubric/{lang}`
  - `GET /api/llm-calls`
  - `GET /api/review-queue`
  - `POST /api/translate`
- Progress is persisted in PostgreSQL:
  - `run_events`
- Controller starts translation in a background thread.
- Controller streams run events through SSE.
- Controller can inspect file details:
  - characters
  - bytes
  - lines
  - sections
  - paragraph sections
  - code sections
  - frontmatter

## Database Status

- Local PostgreSQL is the development database.
- Existing core tables:
  - `blog_posts`
  - `translation_cache`
  - `translation_sections`
  - `translation_quality`
  - `pipeline_runs`
  - `weekly_reports`
  - `glossary_en`
  - `glossary_jp`
- Added runtime event table:
  - `run_events`
- Added quality/tracing tables:
  - `llm_calls`
  - `translation_rubrics`
  - `translation_corrections`
  - `human_review_queue`
- `run_events` stores:
  - run id
  - event type
  - message
  - JSON details
  - created timestamp
- `llm_calls` stores:
  - run/file/section/lang/backend/model
  - endpoint
  - system prompt
  - user prompt
  - glossary text
  - raw response JSON
  - raw model output
  - normalized output
  - validation pass/fail
  - validation errors
  - tokens and latency/duration fields
- `translation_rubrics` stores:
  - human-owned active quality rules
  - target language
  - weights
  - thresholds
- `human_review_queue` stores rejected/low-confidence sections for review.
- `translation_corrections` stores human corrected outputs for cache updates and future training data.

## Docs Status

- V1 written architecture:
  - `v1.md`
- New clean draw.io architecture:
  - `docs/v1-architecture.drawio`
- New research-driven architecture/development order:
  - `new-arch.md`

## Important Repo Files

- RunPod worker:
  - `runpod/worker.py`
- Main translator package:
  - `local_llm_observability/translator.py`
- CLI wrappers:
  - `translate.py`
  - `scan_posts.py`
  - `translate_changed.py`
- CLI implementations:
  - `scripts/scan_posts.py`
  - `scripts/translate_changed.py`
- Local tester:
  - `tests/local_translate.py`
- DB manager:
  - `local_llm_observability/db/db_manager.py`
- Parser:
  - `local_llm_observability/mdx_parser.py`
- Cache manager:
  - `local_llm_observability/cache_manager.py`
- Validator:
  - `local_llm_observability/translation_validator.py`
- Human quality policy defaults:
  - `local_llm_observability/quality_policy.py`
- Human feedback ingestion:
  - `local_llm_observability/feedback.py`
- Sample MDX fixtures:
  - `samples/mdx/...`
- Frontend:
  - `frontend/package.json`
  - `frontend/src/routes/+page.svelte`
  - `frontend/src/app.css`
- Controller:
  - `local_llm_observability/api/main.py`
  - `controller/main.py` compatibility wrapper
- Tests:
  - `tests/run_tests.py`
  - `tests/test_blog_scanner.py`
  - `tests/test_cache_manager.py`
  - `tests/test_translation_normalizer.py`
  - `tests/test_translator_paths.py`

## Immediate Next Steps

1. Finalize the human-owned quality contract
   - define Major/Critical translation errors
   - add good/bad examples
   - tune rubric weights and thresholds in `translation_rubrics`

2. Run the local dashboard end-to-end
   - `docker compose up -d postgres`
   - `./venv/bin/uvicorn controller.main:app --reload --port 8000`
   - `npm --prefix frontend run dev`

3. Test one simple post in the dashboard
   - recommended: `After_interview`

4. Test one technical/code-heavy post in the dashboard
   - recommended: `Algorithm_Bot_01`

5. Compare translation quality between:
   - `gemma4:latest`
   - `qwen3:14b`

6. Add dashboard panels for:
   - active quality rubric
   - failed `llm_calls`
   - open `human_review_queue`

7. Add QE scorer abstraction before integrating COMETKiwi/xCOMET

8. After local quality is stable, decide cloud move:
   - Cloud Run controller
   - Neon Postgres
   - RunPod worker
   - GitHub push trigger / PR workflow

## V2 Implementation Status

- Added deterministic source scanner:
  - `scripts/scan_posts.py`
  - `local_llm_observability/blog_scanner.py`
- Added incremental translation runner:
  - `scripts/translate_changed.py`
- Added local dashboard controller:
  - `local_llm_observability/api/main.py`
- Added real-time SvelteKit frontend:
  - `frontend/src/routes/+page.svelte`
- Default real blog source path:
  - `/Users/jeonghun/hun-bot-blog/src/content/blog`
- Default output layout:
  - source: `/ko/...`
  - English: `/en/...`
  - Japanese: `/jp/...`
- Scanner currently detects:
  - Korean source MDX files
  - missing EN/JP translations
  - stale translations when source file is newer
  - changed files after a git commit with `--changed-only --since-ref`
- Runner defaults to dry-run and requires `--execute` before translation runs.
- Runner supports controlled testing:
  - `--only After_interview`
  - `--limit 1`
  - `--en-model gemma4:latest`
- Runner can translate both languages:
  - `--langs en jp`
  - local runs are usually sequential, not true parallel GPU execution
- Translator emits progress events:
  - started
  - parsing
  - cache_checked
  - language_started
  - model_started
  - model_completed
  - tokens_recorded
  - quality_scored
  - saved
  - completed
  - failed

## Test Status

- Test runner exists:
  - `./venv/bin/python tests/run_tests.py`
- Current deterministic test coverage:
  - scanner ignores translated language folders
  - scanner detects stale translations
  - translator maps `/ko/...` output to `/en/...` and `/jp/...`
  - code block normalizer restores missing fences
  - code block normalizer preserves existing fences
  - paragraph normalizer does not strip normal markdown fences
  - cache rejects broken fenced code translations
  - cache rejects cached Japanese translations with added placeholder links
  - validator rejects added headings
  - validator rejects added placeholder links
  - validator rejects leftover Korean in Japanese output
  - validator rejects excessive expansion
  - validator accepts reasonable Japanese heading translation
- Last known result:
  - `Ran 16 tests`
  - `OK`

## Verified Commands

- Python tests:
  - `./venv/bin/python tests/run_tests.py`
- Python compile checks:
  - `./venv/bin/python -m py_compile ...`
- Frontend build:
  - `npm --prefix frontend run build`
- Controller import:
  - `./venv/bin/python -c "import controller.main; print('controller import ok')"`
- Direct script checks:
  - `./venv/bin/python scripts/scan_posts.py --source-dir samples/mdx --langs jp`
  - `./venv/bin/python scripts/translate_changed.py --source-dir samples/mdx --langs jp --limit 1`
  - `./venv/bin/python translate.py --help`
  - `./venv/bin/python -c "import controller.main; import local_llm_observability.api.main; print('controller imports ok')"`

## Useful Runtime Commands

- Start local PostgreSQL:
  - `docker compose up -d postgres`
- Start controller:
  - `./venv/bin/uvicorn controller.main:app --reload --port 8000`
- Start dashboard:
  - `npm --prefix frontend run dev`
- Scan real blog posts:
  - `./venv/bin/python scripts/scan_posts.py`
- Translate one file EN:
  - `./venv/bin/python scripts/translate_changed.py --langs en --local --only Algorithm_Bot_01 --limit 1 --execute`
- Translate one file JP:
  - `./venv/bin/python scripts/translate_changed.py --langs jp --local --only Algorithm_Bot_01 --limit 1 --execute`
- Translate one file EN + JP:
  - `./venv/bin/python scripts/translate_changed.py --langs en jp --local --only Algorithm_Bot_01 --limit 1 --execute`

## Reminder

- Do not introduce extra frameworks without clear need
- Ruby-based web app was judged overengineering for V1
- Keep the frontend simple and the backend/API authoritative
