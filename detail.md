# Project Detail: local-llm-observability

## Overview

Real-time observability pipeline for Local LLMs (Ollama) using Docker, PostgreSQL, and Grafana.
The primary use case is **automated translation of a Korean tech blog** ("Algorithm Bot" series) into English and Japanese, with performance monitoring (latency, TPS, translation quality) logged to a PostgreSQL database and visualized via Grafana.

- **Author**: Nam Jeong Hun
- **License**: MIT (2026)
- **Python**: 3.13 (venv)
- **Key Libraries**: `ollama`, `psycopg2-binary`, `python-dotenv`, `python-frontmatter`, `rich`, `tqdm`

---

## Project Structure

```
local-llm-observability/
├── .env                          # Database connection credentials
├── .gitignore                    # Standard Python gitignore
├── LICENSE                       # MIT License
├── README.md                     # Project overview (brief)
├── requirements.txt              # Python dependencies
├── docker-compose.yml            # PostgreSQL + Grafana services
├── database/
│   └── init.sql                  # DB schema initialization
├── data/
│   └── glossary.json             # Static glossary (KO/EN/JP) reference
├── src/
│   ├── __init__.py               # Package init (empty)
│   ├── main.py                   # CLI entry point — orchestrates translation pipeline
│   ├── translation_agent.py      # Core translation agent (KO → EN/JP) with Ollama
│   ├── monitor_agent.py          # Glossary extraction agent (extracts terms from blog posts)
│   ├── glossary_refined.py       # Glossary refinement/migration via LLM filtering
│   ├── translate_heavy.py        # Advanced async translation agent (chunked, glossary-aware)
│   ├── translation_model_test.py # Simpler translation agent with glossary verification
│   ├── db/
│   │   ├── __init__.py           # Package init (empty)
│   │   └── db_manager.py         # PostgreSQL CRUD operations (glossary, audit logs)
│   ├── Algorithm_Bot_01.mdx      # Source blog post #1 (Korean) — Algorithm review bot
│   ├── Algorithm_Bot_01_jp.mdx   # Translated output #1 (Japanese)
│   ├── Algorithm_Bot_02.mdx      # Source blog post #2 (Korean) — RAG-based recommendation
│   ├── Algorithm_Bot_02_jp.mdx   # Translated output #2 (Japanese)
│   ├── Algorithm_Bot_03.mdx      # Source blog post #3 (Korean) — RAG model comparison
│   ├── Algorithm_Bot_03_jp.mdx   # Translated output #3 (Japanese)
│   ├── Algorithm_Bot_04.mdx      # Source blog post #4 (Korean) — RAG dev process & results
│   ├── Algorithm_Bot_05.mdx      # Source blog post #5 (Korean) — RAG revision (Numpy)
│   └── Algorithm_Bot_05_jp.mdx   # Translated output #5 (Japanese)
├── jp_Algorithm_Bot_02.mdx       # Translated output #2 (Japanese, root-level variant)
├── jp_Algorithm_Bot_03.md        # Translated output #3 (Japanese, root-level variant)
└── jp_Algorithm_Bot_04.mdx       # Translated output #4 (Japanese, root-level variant)
```

---

## Infrastructure (Docker)

### `docker-compose.yml`

Two services:

| Service    | Image                  | Container Name    | Port  | Purpose                            |
|------------|------------------------|-------------------|-------|------------------------------------|
| PostgreSQL | `postgres:15-alpine`   | `mlops-db`        | 5432  | Stores translation logs, glossary  |
| Grafana    | `grafana/grafana:latest` | `mlops-dashboard` | 3000  | Dashboard for observability metrics |

- PostgreSQL is initialized with `database/init.sql` on first startup.
- Both services share the `mlops-net` Docker network.
- Persistent volumes: `postgres_data`, `grafana_data`.

### `.env`

```
DB_HOST=localhost
DB_NAME=mlops_logs
DB_USER=admin
DB_PASS=password123
DB_PORT=5432
```

---

## Database Schema (`database/init.sql`)

### `translation_logs`
Main observability table. Logs every LLM inference call.

| Column           | Type         | Description                              |
|------------------|--------------|------------------------------------------|
| id               | SERIAL PK    | Auto-increment ID                        |
| timestamp        | TIMESTAMP    | When the inference occurred               |
| model_name       | VARCHAR(50)  | LLM model used (e.g., `gemma2:9b`)      |
| source_lang      | VARCHAR(10)  | Source language (`KO`)                   |
| target_lang      | VARCHAR(10)  | Target language (`EN` or `JP`)           |
| input_length     | INT          | Character count of input                 |
| output_length    | INT          | Character count of output                |
| latency_ms       | FLOAT        | Inference latency in milliseconds        |
| tokens_per_sec   | FLOAT        | Throughput (tokens/second)               |
| similarity_score | FLOAT        | Translation quality score                |
| input_text       | TEXT         | Raw input text                           |
| output_text      | TEXT         | Translated output text                   |

Indexes: `model_name`, `timestamp`

### `glossary_en`
English glossary table (Korean → English term mappings).

| Column     | Type         | Description                    |
|------------|--------------|--------------------------------|
| ko_term    | VARCHAR(255) | Korean term (UNIQUE)           |
| en_term    | VARCHAR(255) | English translation            |
| type       | VARCHAR(50)  | Category (tech, slang, concept)|
| updated_at | TIMESTAMP    | Last update time               |

### `glossary_jp`
Japanese glossary table (Korean → Japanese term mappings). Same structure as `glossary_en` with `jp_term`.

### `glossary_jp_refined`
Refined/filtered version of `glossary_jp`. Created by `glossary_refined.py` to remove noise from the raw glossary.

### `audit_logs`
Detailed translation audit trail with LLM reasoning stored as JSONB.

| Column          | Type         | Description                         |
|-----------------|--------------|-------------------------------------|
| target_lang     | VARCHAR(10)  | `en` or `jp`                        |
| filename        | VARCHAR(255) | Source file name                    |
| paragraph_index | INT          | Paragraph position in the document  |
| original_text   | TEXT         | Original Korean text                |
| llm_reasoning   | JSONB        | LLM's reasoning/explanation         |
| final_translation | TEXT       | Final translated output             |
| model_name      | VARCHAR(100) | Model used for this translation     |

---

## Python Source Files — Detailed Breakdown

### 1. `src/main.py` — CLI Entry Point

**Purpose**: Command-line orchestrator for the translation pipeline.

**Usage**:
```bash
python src/main.py [target] [--force] [--last]
```

**Arguments**:
- `target` (optional): A specific file path or directory. Defaults to `~/hun-bot-blog/src/content/blog/ko`.
- `--force`: Re-translate all files even if translations already exist.
- `--last`: Automatically select only the most recently modified `.mdx` file.

**Workflow**:
1. Initializes `MLOpsMonitor` (for DB logging) and `TranslationAgent`.
2. Resolves target files based on CLI arguments.
3. For directory mode, filters out already-translated files (checks `/en/` and `/jp/` paths).
4. Iterates through files with a `tqdm` progress bar.
5. Calls `translator.process_file()` for each file.

**Dependencies**: `monitor_agent.MLOpsMonitor`, `translation_agent.TranslationAgent`, `tqdm`, `argparse`

---

### 2. `src/translation_agent.py` — Core Translation Agent

**Purpose**: Translates Korean MDX blog posts into English and Japanese using local Ollama LLMs.

**Models**:
| Language | Model         |
|----------|---------------|
| English  | `gemma2:9b`   |
| Japanese | `qwen2.5:14b` |

**Key Features**:
- **Frontmatter-aware**: Parses MDX frontmatter (`---` delimited) and translates `title`, `description`, and `tags` separately with specialized prompts.
- **Tag format preservation**: Ensures `['tag1', 'tag2']` format is maintained after translation.
- **Memory management**: Calls `ollama.generate(model=..., keep_alive=0)` after each inference to free GPU memory.
- **Metrics logging**: Logs latency (ms), tokens-per-second (TPS), and a hardcoded quality score (0.95) to PostgreSQL via `MLOpsMonitor`.

**Translation Flow**:
1. Read `.mdx` file and split into frontmatter + body.
2. For each language (EN, JP):
   - Translate frontmatter fields (title, description, tags) individually.
   - Translate body as a single block.
   - Assemble final MDX and write to the target language directory.

**System Prompts**:
- **English**: Casual but professional DevLog style, first person "I", preserve Markdown.
- **Japanese**: Polite `です・ます` tone, Katakana for loanwords, preserve Markdown.

---

### 3. `src/monitor_agent.py` — Glossary Extraction Agent

**Purpose**: Scans all Korean blog posts and extracts technical terms into EN/JP glossary tables.

**NOTE**: Despite the filename `monitor_agent.py`, this file actually contains the glossary extraction logic (not the `MLOpsMonitor` class referenced in `main.py`). The `MLOpsMonitor` class appears to have been refactored/moved, and `main.py` still references it from this module.

**Models**:
| Task               | Model         |
|--------------------|---------------|
| EN term extraction | `gemma2:9b`   |
| JP term extraction | `qwen2.5:14b` |

**Functions**:
- `extract_en(text)`: Prompts Gemma to extract Korean→English technical terms as JSON. Uses regex to parse the JSON array from LLM output.
- `extract_jp(text)`: Prompts Qwen to extract Korean→Japanese technical terms. Handles `\`\`\`json` wrapper removal.
- `main()`: Scans all `.mdx` files in the blog directory, extracts terms for both languages, upserts into DB, and displays results using `rich` tables.

**Term Categories**: `tech`, `slang`, `concept`, `idiom`, `common`

---

### 4. `src/glossary_refined.py` — Glossary Refinement via LLM

**Purpose**: Migrates raw glossary data from `glossary_jp` to `glossary_jp_refined` by using an LLM to filter out noise (sentences, descriptions) and keep only proper technical terms.

**Model**: `qwen2.5:14b`

**Workflow**:
1. Fetches all raw KO→JP terms from `glossary_jp`.
2. Processes in batches of 25.
3. Prompts the LLM to filter out non-technical entries (e.g., full sentences, conversational noise).
4. Inserts refined terms into `glossary_jp_refined` with `ON CONFLICT` upsert.

---

### 5. `src/translate_heavy.py` — Advanced Async Translation Agent

**Purpose**: High-quality async translation agent designed for complex/long blog posts (e.g., posts with ASCII trees, LaTeX formulas, Markdown tables).

**Model**: `qwen2.5:14b` (Japanese only)

**Key Features**:
- **Async with concurrency control**: Uses `asyncio` + `ollama.AsyncClient()` with `Semaphore(2)` to limit parallel inference.
- **Chunk-based translation**: Splits content into ~1000-character chunks at paragraph boundaries to preserve structural elements.
- **Glossary-aware**: Loads refined glossary from `glossary_jp_refined` and injects it into every prompt.
- **Structure preservation rules**: Special instructions for ASCII trees (`├─`, `└─`), LaTeX formulas, Markdown tables, and image alt-text.
- **Rich progress UI**: Displays per-file and overall progress using `rich`.

**Translation Style**: Professional Japanese tech blog (Zenn/Qiita style), `です・ます` tone.

---

### 6. `src/translation_model_test.py` — Simple Translation Agent with Verification

**Purpose**: A simpler translation agent that translates entire files at once and verifies glossary term usage in the output.

**Model**: `qwen2.5:14b` (Japanese only)

**Key Features**:
- **Whole-file translation**: Sends the entire file content (frontmatter + body) to the LLM in a single prompt.
- **Glossary verification**: After translation, checks if Korean terms from the glossary appear in the source and their corresponding Japanese terms appear in the output.
- **Batch processing**: Can process multiple files sequentially via `run_batch()`.

---

### 7. `src/db/db_manager.py` — Database Manager

**Purpose**: PostgreSQL connection and CRUD operations.

**Methods**:
| Method       | Description                                    |
|--------------|------------------------------------------------|
| `upsert_en`  | Insert/update English glossary term            |
| `upsert_jp`  | Insert/update Japanese glossary term           |
| `get_glossary` | Retrieve glossary as dict by language (`en`/`jp`) |
| `log_audit`  | Insert audit log with LLM reasoning (JSONB)    |
| `close`      | Close DB connection                            |

**Configuration**: Reads from `.env` via `python-dotenv`.

---

## Data Files

### `data/glossary.json`
Static glossary reference with 3 sample entries:

| Korean         | English          | Japanese        | Type         |
|----------------|------------------|-----------------|--------------|
| 블로그 개발일지 | Blog Dev Log     | ブログ開発日誌   | series_title |
| 삽질           | trial and error  | 試行錯誤         | idiom        |
| 동적 라우팅     | Dynamic Routing  | 動的ルーティング  | tech_term    |

---

## Blog Content (MDX Files)

The `src/` directory contains 5 Korean source blog posts from the "Algorithm Bot" series and their Japanese translations:

| # | File                    | Title (Korean)                                | Topic                                    |
|---|-------------------------|-----------------------------------------------|------------------------------------------|
| 1 | Algorithm_Bot_01.mdx    | 알고리즘 복습 효율화                            | Ebbinghaus review bot with Slack webhook |
| 2 | Algorithm_Bot_02.mdx    | 알고리즘 학습 자동화 +⍺: RAG 기반 유사 문제 추천 | RAG-based similar problem recommendation |
| 3 | Algorithm_Bot_03.mdx    | 알고리즘 RAG 개발 과정 및 모델 성능 비교         | Embedding model performance comparison   |
| 4 | Algorithm_Bot_04.mdx    | 알고리즘 RAG 개발 과정 및 결과물                 | LangChain + FAISS final system           |
| 5 | Algorithm_Bot_05.mdx    | 알고리즘 RAG 수정                               | FAISS → Numpy migration                  |

Japanese translated versions exist as `*_jp.mdx` files in `src/` and also some variants in the project root (`jp_Algorithm_Bot_*.mdx`).

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────┐
│                    CLI (main.py)                 │
│            --target / --force / --last           │
└──────────┬──────────────────────────┬────────────┘
           │                          │
           ▼                          ▼
┌──────────────────┐     ┌──────────────────────┐
│ TranslationAgent │     │    MLOpsMonitor       │
│ (translation_    │     │ (metrics logging)     │
│  agent.py)       │     └──────────┬────────────┘
│                  │                │
│  gemma2:9b (EN)  │                ▼
│  qwen2.5:14b(JP) │     ┌──────────────────────┐
└──────────────────┘     │   PostgreSQL (Docker) │
                         │   - translation_logs  │
┌──────────────────┐     │   - glossary_en       │
│  monitor_agent   │────▶│   - glossary_jp       │
│  (term extract)  │     │   - glossary_jp_refined│
└──────────────────┘     │   - audit_logs        │
                         └──────────┬────────────┘
┌──────────────────┐                │
│ glossary_refined │                ▼
│ (LLM filtering)  │     ┌──────────────────────┐
└──────────────────┘     │   Grafana (Docker)    │
                         │   - Latency dashboard │
┌──────────────────┐     │   - TPS metrics       │
│ translate_heavy  │     │   - Quality tracking  │
│ (async chunked)  │     └──────────────────────┘
└──────────────────┘
```

---

## LLM Models Used (via Ollama)

| Model          | Size | Used For                           |
|----------------|------|------------------------------------|
| `gemma2:9b`    | 9B   | Korean → English translation       |
| `qwen2.5:14b`  | 14B  | Korean → Japanese translation      |

Both models run locally via [Ollama](https://ollama.ai).

---

## How to Run

```bash
# 1. Start infrastructure
docker-compose up -d

# 2. Activate virtual environment
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run translation pipeline
python src/main.py --last              # Translate most recent file
python src/main.py ~/path/to/file.mdx  # Translate specific file
python src/main.py ~/path/to/dir/      # Translate all untranslated files in directory
python src/main.py --force             # Re-translate all files

# 5. Run glossary extraction
python src/monitor_agent.py

# 6. Run glossary refinement
python src/glossary_refined.py

# 7. Run advanced async translation
python src/translate_heavy.py

# 8. View metrics at http://localhost:3000 (Grafana)
```
