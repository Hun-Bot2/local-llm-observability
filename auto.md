# Automation: Blog Translation Pipeline — Implementation Plan

## Goal

When you push a new or edited Korean `.mdx` post to your blog repo (`hun-bot-blog`), the system automatically:
1. Detects new/changed Korean content (paragraph-level diff)
2. Spins up a cloud GPU (RunPod) — your MacBook stays untouched
3. Translates **only the changed paragraphs** to EN/JP (diff-aware cache)
4. Reassembles full translated files from cache + new translations
5. Scores translation quality and applies a quality gate
6. Commits and pushes — Vercel auto-deploys
7. Cloud GPU shuts down — $0 when idle

**Cost**: ~$0.01-0.05 per post. $0 when sleeping. MacBook never slowed down.

---

## Tech Stack

### By Layer

| Layer | Technology | Role | Runs On |
|-------|-----------|------|---------|
| **Trigger** | GitHub Webhooks | Detects push events on `main` branch | GitHub (cloud, free) |
| **Tunnel** | Cloudflare Tunnel (or ngrok) | Exposes local controller to internet for webhook delivery | Mac (free) |
| **Controller** | FastAPI + Uvicorn | Webhook receiver, pipeline orchestrator, status API | Mac (Docker, ~50MB) |
| **Cache** | PostgreSQL 15 + pgvector | Paragraph-level translation cache, glossary, quality scores, pipeline run logs, **vector similarity search** | Mac (Docker) |
| **Translation Memory** | pgvector (RAG pattern) | Retrieves similar past translations as few-shot examples for consistent style | Mac (Docker, in PostgreSQL) |
| **Hashing** | SHA-256 (hashlib) | Detects changed paragraphs by content hash | Mac (Docker) |
| **MDX Parser** | Python regex + custom splitter | Splits MDX into frontmatter fields + body paragraphs, preserves code blocks | Mac (Docker) |
| **GPU Compute** | RunPod On-Demand Pod (A40 48GB) | Runs Ollama + LLM inference. Starts on demand, shuts down after. $0 when idle | RunPod cloud |
| **LLM Server** | Ollama | Serves LLM models via REST API on the GPU pod | RunPod pod |
| **EN Translation** | Gemma 2 9B (`gemma2:9b`) | Korean → English translation | RunPod GPU |
| **JP Translation** | Qwen 2.5 14B (`qwen2.5:14b`) | Korean → Japanese translation | RunPod GPU |
| **Embedding** | nomic-embed-text | Multilingual embedding for semantic similarity scoring | RunPod GPU |
| **Quality: Structural** | Python regex | Checks Markdown structure preservation (code blocks, headings, URLs, images) | Mac (Docker) |
| **Quality: Semantic** | Cosine similarity + numpy | Compares embedding vectors of source vs. translation | Mac (Docker) |
| **Quality: Length** | Python arithmetic | Detects hallucination/omission via character ratio | Mac (Docker) |
| **Quality: Glossary** | String matching | Verifies glossary terms are correctly translated | Mac (Docker) |
| **Dashboard** | Grafana | Visualizes quality scores, cache hit rate, cost, pipeline runs | Mac (Docker) |
| **Containerization** | Docker Compose | Orchestrates controller + PostgreSQL + Grafana | Mac |
| **Model Storage** | RunPod Network Volume (30GB) | Persists Ollama models across pod restarts (no re-download) | RunPod cloud |
| **Blog Hosting** | Vercel | Auto-deploys on git push. Serves KO + EN + JP | Vercel (free tier) |
| **Blog Repo** | GitHub | Source of truth. Webhook source. Git-based content management | GitHub (free) |
| **Blog Format** | MDX (Markdown + JSX) | Blog post format with frontmatter metadata | — |

### By Component (What Depends on What)

```
┌─────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL SERVICES                            │
│                                                                     │
│  GitHub ──webhook──→ Cloudflare Tunnel ──→ Controller               │
│  RunPod API ←────── Controller (start/stop pod)                     │
│  Vercel ←─────────── GitHub (auto-deploy on push)                   │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  YOUR MAC (Docker Compose)                                          │
│                                                                     │
│  Controller (FastAPI)                                               │
│    ├── depends on: PostgreSQL (cache, glossary, scores)             │
│    ├── depends on: RunPod API (start/stop GPU pod)                  │
│    ├── uses: hashlib (SHA-256 paragraph hashing)                    │
│    ├── uses: regex (MDX parsing, structural scoring)                │
│    ├── uses: numpy (cosine similarity for embedding scores)         │
│    └── uses: requests (HTTP calls to RunPod worker + API)           │
│                                                                     │
│  PostgreSQL 15-alpine                                               │
│    ├── translation_cache (paragraph-level cache)                    │
│    ├── translation_quality (quality scores)                         │
│    ├── pipeline_runs (cost + performance logs)                      │
│    ├── glossary_en / glossary_jp (term dictionaries)                │
│    └── translation_logs (legacy inference logs)                     │
│                                                                     │
│  Grafana                                                            │
│    └── depends on: PostgreSQL (data source)                         │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  RUNPOD GPU POD (on-demand, ephemeral)                              │
│                                                                     │
│  Worker API (FastAPI)                                               │
│    ├── depends on: Ollama (LLM serving)                             │
│    ├── /translate endpoint → gemma2:9b (EN) / qwen2.5:14b (JP)     │
│    ├── /embed endpoint → nomic-embed-text                           │
│    └── /health endpoint → readiness check                           │
│                                                                     │
│  Ollama                                                             │
│    ├── gemma2:9b (5.4GB) ── English translation                    │
│    ├── qwen2.5:14b (8.9GB) ── Japanese translation                 │
│    └── nomic-embed-text (274MB) ── Semantic similarity scoring      │
│                                                                     │
│  Network Volume (30GB, persistent)                                  │
│    └── Stores model weights across pod restarts                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Python Dependencies

| Package | Where | Purpose |
|---------|-------|---------|
| `fastapi` | Controller + Worker | HTTP API framework |
| `uvicorn` | Controller + Worker | ASGI server for FastAPI |
| `psycopg2-binary` | Controller | PostgreSQL driver |
| `python-dotenv` | Controller | Load `.env` config |
| `requests` | Controller | HTTP client (RunPod API + worker calls) |
| `numpy` | Controller | Cosine similarity for quality scoring |
| `ollama` | Worker | Ollama Python client (chat + embed) |
| `tqdm` | Controller (optional) | Progress bars for batch operations |

### Cost Breakdown by Component

| Component | Monthly Cost | Notes |
|-----------|-------------|-------|
| GitHub | $0 | Free for public/private repos |
| Vercel | $0 | Free tier (hobby) |
| Cloudflare Tunnel | $0 | Free tier |
| Docker Compose (Mac) | $0 | Already running, negligible resources |
| PostgreSQL (Mac) | $0 | Docker container, ~100MB RAM |
| Grafana (Mac) | $0 | Docker container, ~100MB RAM |
| Controller (Mac) | $0 | Docker container, ~50MB RAM |
| RunPod Network Volume | ~$1.50 | 30GB persistent storage |
| RunPod GPU (A40) | ~$0.10-0.50 | Pay per second, only during translation |
| **Total** | **~$2/month** | |

---

## Vector DB vs pgvector — and RAG Translation Memory

### Do You Need a Vector Database?

**No.** Your data is too small for a dedicated vector DB.

| Solution | Designed For | Your Data | Verdict |
|----------|-------------|-----------|---------|
| Pinecone / Weaviate / Qdrant | Millions of vectors, multi-tenant SaaS | ~1,000 paragraphs | Massive overkill |
| ChromaDB | 10K-100K vectors, local prototyping | ~1,000 paragraphs | Still overkill, adds another service |
| FAISS | 100K+ vectors, in-memory ANN search | ~1,000 paragraphs | You already ditched this in Algorithm_Bot_05 |
| **pgvector (PostgreSQL extension)** | **1K-1M vectors, SQL-native** | **~1,000 paragraphs** | **Perfect fit — zero new infrastructure** |
| numpy brute-force | <10K vectors | ~1,000 paragraphs | Also works, but pgvector is cleaner |

pgvector adds vector search to your **existing PostgreSQL**. One image swap in docker-compose, no new containers.

### RAG for Translation: Translation Memory

The RAG pattern IS valuable here — not as a vector DB product, but as **Translation Memory (TM)**. When translating a new paragraph, retrieve similar past translations as few-shot examples.

**Current approach** (glossary only):
```
Prompt: "Translate this paragraph"
Context: glossary terms only (삽질 → 試行錯誤)
Problem: LLM has no idea how YOU write/translate
```

**With Translation Memory** (RAG pattern):
```
Prompt: "Translate this paragraph"
Context:
  1. Glossary terms (삽질 → 試行錯誤)
  2. Top 3 similar paragraphs YOU already translated:

     [Similarity: 0.91]
     KO: "Slack Webhook을 이용해서 매일 아침에 복습할 문제들을 알려주도록 했습니다."
     JP: "Slack Webhookを利用して毎朝復習すべき問題を通知するように設定しています。"

     [Similarity: 0.87]
     KO: "해당 코드는 제 파일 기준이기 때문에, 필요에 맞게 경로를 수정해서 사용하면 됩니다."
     JP: "このコードは私のファイル基準になっていますので、必要に応じてパスを修正して利用してください。"

Result: LLM sees YOUR actual translation style, tone, and patterns
```

#### What Translation Memory solves

| Problem | Glossary Only | With Translation Memory |
|---------|--------------|------------------------|
| Term consistency | Individual words only | Full phrases in context |
| Your personal style | LLM guesses from system prompt | LLM sees real examples of YOUR past translations |
| Tone ("です・ます") | Vague instruction | Concrete sentences showing exactly your tone |
| Code-mixed Korean | Often mistranslated | Past examples show `commit & push하면` → `commit & pushすると` |
| Series consistency | Each post translated in isolation | Post #5 sees how you translated similar content in #1-4 |

#### Implementation: pgvector in Existing PostgreSQL

**docker-compose change** (one line):

```yaml
  postgres:
    image: pgvector/pgvector:pg15    # was: postgres:15-alpine
```

**Schema addition**:

```sql
-- Add pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Add embedding column to existing cache table
ALTER TABLE translation_cache
    ADD COLUMN IF NOT EXISTS ko_embedding vector(768);

-- Index for fast similarity search
CREATE INDEX IF NOT EXISTS idx_cache_embedding
    ON translation_cache USING ivfflat (ko_embedding vector_cosine_ops)
    WITH (lists = 10);
```

**Similarity search query** (find top 3 similar past translations):

```sql
-- Given a new paragraph's embedding, find similar cached translations
SELECT
    ko_text,
    en_text,
    jp_text,
    1 - (ko_embedding <=> $1::vector) AS similarity  -- cosine similarity
FROM translation_cache
WHERE en_text IS NOT NULL
  AND jp_text IS NOT NULL
  AND filename != $2          -- exclude same file (avoid self-matching)
ORDER BY ko_embedding <=> $1::vector
LIMIT 3;
```

**Updated worker prompt** (RunPod side):

```python
# runpod/worker.py — updated translate endpoint

def build_prompt_with_memory(section, target_lang, glossary, similar_translations):
    """Build translation prompt with RAG-style translation memory."""
    system_prompt = SYSTEM_PROMPTS[target_lang]

    # Add glossary
    if glossary:
        system_prompt += f"\n\n[Glossary]\n{glossary}"

    # Add translation memory (few-shot examples from past translations)
    if similar_translations:
        lang_key = "en_text" if target_lang == "EN" else "jp_text"
        lang_name = "English" if target_lang == "EN" else "Japanese"

        memory_block = f"\n\n[Translation Memory — examples of past {lang_name} translations in this blog]\n"
        for i, tm in enumerate(similar_translations, 1):
            sim = round(tm['similarity'], 2)
            memory_block += f"\nExample {i} (similarity: {sim}):\n"
            memory_block += f"Korean: {tm['ko_text'][:300]}\n"
            memory_block += f"{lang_name}: {tm[lang_key][:300]}\n"

        system_prompt += memory_block
        system_prompt += "\nMaintain consistent style and terminology with these examples."

    return system_prompt
```

**Updated pipeline flow** (controller sends embeddings + retrieves memory):

```python
# In controller/pipeline.py — before sending to RunPod

def enrich_sections_with_memory(sections, db, pod_url):
    """For each section, find similar past translations from cache."""
    # Get embeddings for all new sections
    ko_texts = [s['ko_text'] for s in sections]
    embeddings = get_embeddings(pod_url, ko_texts)

    for section, embedding in zip(sections, embeddings):
        # Store embedding for future similarity searches
        section['ko_embedding'] = embedding

        # Retrieve similar past translations via pgvector
        with db.conn.cursor() as cur:
            cur.execute("""
                SELECT ko_text, en_text, jp_text,
                       1 - (ko_embedding <=> %s::vector) AS similarity
                FROM translation_cache
                WHERE en_text IS NOT NULL AND jp_text IS NOT NULL
                  AND filename != %s
                  AND 1 - (ko_embedding <=> %s::vector) > 0.5
                ORDER BY ko_embedding <=> %s::vector
                LIMIT 3
            """, (embedding, section['filename'], embedding, embedding))
            similar = [
                {"ko_text": r[0], "en_text": r[1], "jp_text": r[2], "similarity": r[3]}
                for r in cur.fetchall()
            ]
        section['similar_translations'] = similar

    return sections
```

#### Updated Architecture with Translation Memory

```
[New paragraph to translate]
       │
       ▼
[Embed paragraph]  ← nomic-embed-text on RunPod
       │
       ├──→ [pgvector search in PostgreSQL]
       │         │
       │         ▼
       │    Top 3 similar past translations (from cache table)
       │         │
       ▼         ▼
[Build prompt]
  = System prompt
  + Glossary terms
  + Translation Memory (3 similar examples)   ← RAG pattern
  + Current paragraph
       │
       ▼
[LLM translates]  ← gemma2:9b / qwen2.5:14b
       │
       ▼
[Store in cache + embedding]  ← becomes future Translation Memory for other paragraphs
```

The cache grows smarter over time: every translation you approve becomes a reference example for future translations. After 50 posts, the LLM has hundreds of real examples of YOUR translation style.

#### Cost Impact

| Component | Additional Cost |
|-----------|----------------|
| pgvector (PostgreSQL extension) | $0 — same container, just different image |
| Embedding storage (~768 floats × 1000 rows) | ~3MB — negligible |
| Extra embedding calls on RunPod | ~5 seconds per batch — included in existing GPU time |
| pgvector similarity search | <1ms per query — runs on Mac, not GPU |
| **Total additional cost** | **$0** |

---

## Why Not Local?

| Problem                         | Impact                                          |
|---------------------------------|-------------------------------------------------|
| gemma2:9b + qwen2.5:14b = ~24GB| Eats all MacBook unified memory                 |
| GPU inference blocks everything | Can't code, browse, or even switch apps smoothly|
| Translation takes 5-15 min     | Mac is a brick for that entire duration          |
| Models stay loaded in VRAM      | Even after translation, memory isn't fully freed |

**Solution**: Offload all inference to on-demand cloud GPU. Mac only runs a lightweight controller (FastAPI, ~50MB RAM).

---

## Final Architecture

```
You write/edit KO post
       │
       ▼
  git push → GitHub (main branch)
       │
       ▼ (webhook)
┌──────────────────────────────────────────────────────────────┐
│  Your Mac (Docker Compose) — lightweight, always sleeping    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Controller (FastAPI container, ~50MB RAM)            │   │
│  │                                                      │   │
│  │  1. Receive GitHub webhook                           │   │
│  │  2. git pull blog repo                               │   │
│  │  3. Parse MDX → split into paragraphs                │   │
│  │  4. Hash each paragraph                              │   │
│  │  5. Compare with cache in PostgreSQL                 │   │
│  │  6. Collect ONLY changed paragraphs                  │   │
│  │  7. Start RunPod GPU instance via API                │   │
│  │  8. Send changed paragraphs to RunPod                │   │
│  │  9. Receive translations back                        │   │
│  │  10. Update cache in PostgreSQL                      │   │
│  │  11. Reassemble full EN/JP files from cache          │   │
│  │  12. Score quality (structural + semantic)           │   │
│  │  13. Quality gate: block if score < 0.6             │   │
│  │  14. git commit & push                              │   │
│  │  15. Stop RunPod instance                           │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────┐    ┌───────────┐                          │
│  │  PostgreSQL   │    │  Grafana  │                          │
│  │  - cache      │    │  :3000    │                          │
│  │  - scores     │    │           │                          │
│  │  - glossary   │    │           │                          │
│  └──────────────┘    └───────────┘                          │
└──────────────────────────────────────────────────────────────┘
       │                          │
       │                          ▼
       │               ┌─────────────────────┐
       │               │  RunPod GPU (A40)    │
       │               │  (on-demand, ~$0.39/h│
       │               │   active ~5-10 min)  │
       │               │                     │
       │               │  Ollama API server   │
       │               │  - gemma2:9b (EN)    │
       │               │  - qwen2.5:14b (JP)  │
       │               │                     │
       │               │  Sleeps when done    │
       │               │  ($0 when off)       │
       │               └─────────────────────┘
       │
       ▼ (pushed commit triggers Vercel)
   Vercel auto-deploys (KO + EN + JP)
```

---

## Core Concept: Diff-Aware Paragraph Cache

Since you often edit published posts, re-translating the entire file is wasteful. Instead:

```
Original post (20 paragraphs) → First push → translate all 20 → cache all 20
       │
You edit paragraph 3 and 7 → Second push
       │
       ▼
Parse MDX → hash each paragraph → compare with cached hashes
       │
       ├── Paragraph 1:  hash matches cache → use cached EN/JP ✓
       ├── Paragraph 2:  hash matches cache → use cached EN/JP ✓
       ├── Paragraph 3:  HASH CHANGED → send to RunPod for translation
       ├── Paragraph 4:  hash matches cache → use cached EN/JP ✓
       ├── ...
       ├── Paragraph 7:  HASH CHANGED → send to RunPod for translation
       ├── ...
       └── Paragraph 20: hash matches cache → use cached EN/JP ✓
       │
       ▼
Only 2 paragraphs sent to GPU (instead of 20)
Cloud GPU time: ~30 seconds instead of ~10 minutes
Cost: ~$0.003 instead of ~$0.05
```

### Cache Schema

```sql
-- Paragraph-level translation cache
CREATE TABLE IF NOT EXISTS translation_cache (
    id SERIAL PRIMARY KEY,

    -- Identity
    filename VARCHAR(255) NOT NULL,
    section_type VARCHAR(20) NOT NULL,     -- 'frontmatter_title', 'frontmatter_desc',
                                           -- 'frontmatter_tags', 'body'
    section_index INT NOT NULL,            -- paragraph order within the file

    -- Content hash (SHA-256 of the Korean source text)
    content_hash VARCHAR(64) NOT NULL,

    -- Source and translations
    ko_text TEXT NOT NULL,
    en_text TEXT,                           -- NULL if not yet translated
    jp_text TEXT,                           -- NULL if not yet translated

    -- Metadata
    model_en VARCHAR(100),
    model_jp VARCHAR(100),
    translated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Unique constraint: one cached translation per file+section+hash
    UNIQUE(filename, section_type, section_index, content_hash)
);

CREATE INDEX idx_cache_filename ON translation_cache(filename);
CREATE INDEX idx_cache_hash ON translation_cache(content_hash);
```

### How MDX is Split

```python
import hashlib
import re

def parse_mdx_sections(content: str, filename: str) -> list[dict]:
    """
    Split MDX file into cacheable sections.
    Each section gets a hash so we can detect changes.
    """
    sections = []

    # 1. Split frontmatter from body
    parts = content.split('---', 2)
    if len(parts) >= 3:
        frontmatter = parts[1]
        body = parts[2]
    else:
        frontmatter = ""
        body = content

    # 2. Parse frontmatter fields individually
    if frontmatter:
        title_match = re.search(r"title:\s*['\"](.*?)['\"]", frontmatter)
        if title_match:
            text = title_match.group(1)
            sections.append({
                "filename": filename,
                "section_type": "frontmatter_title",
                "section_index": 0,
                "ko_text": text,
                "content_hash": hashlib.sha256(text.encode()).hexdigest(),
            })

        desc_match = re.search(r"description:\s*['\"](.*?)['\"]", frontmatter)
        if desc_match:
            text = desc_match.group(1)
            sections.append({
                "filename": filename,
                "section_type": "frontmatter_desc",
                "section_index": 0,
                "ko_text": text,
                "content_hash": hashlib.sha256(text.encode()).hexdigest(),
            })

        tags_match = re.search(r"tags:\s*(\[.*?\])", frontmatter)
        if tags_match:
            text = tags_match.group(1)
            sections.append({
                "filename": filename,
                "section_type": "frontmatter_tags",
                "section_index": 0,
                "ko_text": text,
                "content_hash": hashlib.sha256(text.encode()).hexdigest(),
            })

    # 3. Split body into paragraphs (separated by double newline)
    #    But keep code blocks as single units (don't split inside ```)
    chunks = split_preserving_code_blocks(body.strip())

    for i, chunk in enumerate(chunks):
        text = chunk.strip()
        if not text:
            continue
        sections.append({
            "filename": filename,
            "section_type": "body",
            "section_index": i,
            "ko_text": text,
            "content_hash": hashlib.sha256(text.encode()).hexdigest(),
        })

    return sections


def split_preserving_code_blocks(text: str) -> list[str]:
    """
    Split by double newline, but never split inside ``` code blocks.
    Code blocks + surrounding text stay as one chunk.
    """
    chunks = []
    current = []
    in_code_block = False

    for line in text.split('\n'):
        if line.strip().startswith('```'):
            in_code_block = not in_code_block

        if line == '' and not in_code_block and current:
            # Double newline outside code block → new chunk
            chunks.append('\n'.join(current))
            current = []
        else:
            current.append(line)

    if current:
        chunks.append('\n'.join(current))

    return chunks
```

### Diff Detection

```python
def get_changed_sections(
    sections: list[dict],
    db_manager
) -> tuple[list[dict], list[dict]]:
    """
    Compare parsed sections against cache.
    Returns: (changed_sections, cached_sections)
    """
    changed = []
    cached = []

    for section in sections:
        with db_manager.conn.cursor() as cur:
            cur.execute("""
                SELECT en_text, jp_text FROM translation_cache
                WHERE filename = %s
                  AND section_type = %s
                  AND section_index = %s
                  AND content_hash = %s
                  AND en_text IS NOT NULL
                  AND jp_text IS NOT NULL
            """, (
                section['filename'],
                section['section_type'],
                section['section_index'],
                section['content_hash'],
            ))
            row = cur.fetchone()

        if row:
            # Cache hit — hash matches, translations exist
            section['en_text'] = row[0]
            section['jp_text'] = row[1]
            cached.append(section)
        else:
            # Cache miss — new or changed paragraph
            changed.append(section)

    return changed, cached
```

---

## Cloud GPU: RunPod Setup

### Why RunPod

| Feature             | RunPod               | Vast.ai            | Lambda              |
|---------------------|----------------------|--------------------|--------------------|
| On-demand GPU Pods  | Yes                  | Yes                | Yes                |
| API to start/stop   | Yes (REST API)       | Yes                | Limited            |
| Cheapest A40 (48GB) | ~$0.39/hr            | ~$0.30/hr          | ~$0.50/hr          |
| Persistent disk     | Yes (network volume) | Yes                | No                 |
| Docker support      | Native               | Native             | Limited            |
| Ollama pre-built    | Template available   | Manual             | Manual             |

**5 minutes of A40 time = ~$0.03**. For a typical blog post with 20 paragraphs, translating to 2 languages.

### RunPod Worker Setup

#### 1. Create a Network Volume (persistent model storage)

Models (gemma2:9b + qwen2.5:14b = ~14GB) are stored on a persistent volume so they don't re-download every time.

```bash
# Via RunPod dashboard or API:
# Create a 30GB network volume in your preferred region
```

#### 2. Pod Template (Dockerfile)

```dockerfile
# runpod/Dockerfile
FROM ollama/ollama:latest

# Install Python + dependencies
RUN apt-get update && apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir fastapi uvicorn ollama

COPY worker.py /app/worker.py

# Start Ollama server + worker API
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

CMD ["/entrypoint.sh"]
```

```bash
# runpod/entrypoint.sh
#!/bin/bash

# Start Ollama in background
ollama serve &

# Wait for Ollama to be ready
sleep 5

# Pull models (skips if already on network volume)
ollama pull gemma2:9b
ollama pull qwen2.5:14b
# Pull embedding model for quality scoring
ollama pull nomic-embed-text

# Start the worker API
python3 /app/worker.py
```

#### 3. Worker API (runs on RunPod pod)

```python
# runpod/worker.py
"""
Lightweight translation worker that runs on RunPod GPU.
Receives paragraphs, translates them, returns results.
"""
import json
import ollama
from fastapi import FastAPI
import uvicorn

app = FastAPI()

SYSTEM_PROMPTS = {
    "EN": """You are a skilled Tech Blog Translator.
Translate the Korean text into natural, professional English for a developer audience.
Tone: Casual but professional (DevLog style). Use "I" for first person.
Technical Terms: Keep terms like 'Local LLM', 'vscode', 'commit & push' in English.
Preserve all Markdown formatting. Do NOT translate code blocks or URLs.""",

    "JP": """あなたはプロの技術ブロガーです。韓国語の技術ブログを日本のエンジニア向けに自然な日本語へ翻訳してください。
Tone: 「です・ます」調。Technical Terms: カタカナまたは英語で表記。
Markdownの形式を崩さないでください。コードブロックやURLは翻訳しないでください。"""
}

MODELS = {"EN": "gemma2:9b", "JP": "qwen2.5:14b"}

@app.post("/translate")
async def translate(request: dict):
    """
    Translate a batch of paragraphs.
    Input:  {"sections": [{"ko_text": "...", "section_type": "body", ...}], "target_lang": "EN"}
    Output: {"translations": [{"ko_text": "...", "translated": "...", ...}]}
    """
    sections = request["sections"]
    target_lang = request["target_lang"]
    model = MODELS[target_lang]
    system_prompt = SYSTEM_PROMPTS[target_lang]

    # Add glossary to prompt if provided
    glossary = request.get("glossary_text", "")
    if glossary:
        system_prompt += f"\n\n[Glossary Reference]\n{glossary}"

    results = []
    for section in sections:
        # Adjust prompt based on section type
        if section["section_type"] == "frontmatter_tags":
            extra = "\nIMPORTANT: Input is a tag list. Translate terms but keep ['...'] format. Output ONLY the list."
        elif section["section_type"].startswith("frontmatter"):
            extra = "\nTranslate this short metadata text. Keep it concise. Output ONLY the translation."
        else:
            extra = ""

        response = ollama.chat(model=model, messages=[
            {'role': 'system', 'content': system_prompt + extra},
            {'role': 'user', 'content': section["ko_text"]},
        ])

        translated = response['message']['content'].strip()

        # Clean up tags format
        if section["section_type"] == "frontmatter_tags":
            translated = translated.replace("```json", "").replace("```", "").strip()

        results.append({
            **section,
            "translated": translated,
            "model": model,
            "eval_count": response.get("eval_count", 0),
            "eval_duration": response.get("eval_duration", 0),
        })

    # Free GPU memory
    ollama.generate(model=model, keep_alive=0)

    return {"translations": results}


@app.post("/embed")
async def embed(request: dict):
    """Get embeddings for quality scoring."""
    texts = request["texts"]
    results = []
    for text in texts:
        response = ollama.embed(model="nomic-embed-text", input=text)
        results.append(response['embeddings'][0])
    return {"embeddings": results}


@app.get("/health")
async def health():
    return {"status": "ready"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

### RunPod Pod Management (from Controller)

```python
# controller/runpod_manager.py
import os
import time
import requests

RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY")
RUNPOD_API_URL = "https://api.runpod.io/v2"
POD_TEMPLATE_ID = os.getenv("RUNPOD_TEMPLATE_ID")  # Pre-configured template
NETWORK_VOLUME_ID = os.getenv("RUNPOD_VOLUME_ID")   # Persistent model storage

headers = {"Authorization": f"Bearer {RUNPOD_API_KEY}"}


def start_pod() -> dict:
    """Start an on-demand GPU pod. Returns pod info with IP."""
    response = requests.post(
        f"{RUNPOD_API_URL}/pods",
        headers=headers,
        json={
            "name": "blog-translator",
            "imageName": "your-dockerhub/blog-translator-worker:latest",
            "gpuTypeId": "NVIDIA A40",       # 48GB VRAM, ~$0.39/hr
            "volumeInGb": 0,
            "containerDiskInGb": 10,
            "networkVolumeId": NETWORK_VOLUME_ID,  # Models persist here
            "ports": "8000/http",
            "env": {
                "OLLAMA_MODELS": "/runpod-volume/ollama-models",
            },
        },
    )
    pod = response.json()
    pod_id = pod["id"]

    # Wait for pod to be ready
    for _ in range(60):  # Max 5 min wait
        status = requests.get(f"{RUNPOD_API_URL}/pods/{pod_id}", headers=headers).json()
        if status.get("desiredStatus") == "RUNNING" and status.get("runtime"):
            pod_ip = status["runtime"].get("ports", {}).get("8000/http", [{}])[0].get("ip")
            if pod_ip:
                return {"id": pod_id, "url": f"https://{pod_id}-8000.proxy.runpod.net"}
        time.sleep(5)

    raise TimeoutError("Pod failed to start within 5 minutes")


def wait_for_worker(pod_url: str, timeout=120):
    """Wait until the worker API is ready (models loaded)."""
    for _ in range(timeout // 5):
        try:
            resp = requests.get(f"{pod_url}/health", timeout=5)
            if resp.status_code == 200:
                return True
        except requests.ConnectionError:
            pass
        time.sleep(5)
    raise TimeoutError("Worker API not ready")


def stop_pod(pod_id: str):
    """Stop and remove the pod. $0 after this."""
    requests.delete(f"{RUNPOD_API_URL}/pods/{pod_id}", headers=headers)


def translate_sections(pod_url: str, sections: list[dict], target_lang: str, glossary_text: str = "") -> list[dict]:
    """Send sections to RunPod worker for translation."""
    response = requests.post(
        f"{pod_url}/translate",
        json={
            "sections": sections,
            "target_lang": target_lang,
            "glossary_text": glossary_text,
        },
        timeout=600,  # 10 min max for large files
    )
    return response.json()["translations"]


def get_embeddings(pod_url: str, texts: list[str]) -> list[list[float]]:
    """Get embeddings from RunPod for quality scoring."""
    response = requests.post(
        f"{pod_url}/embed",
        json={"texts": texts},
        timeout=60,
    )
    return response.json()["embeddings"]
```

---

## Controller: Full Pipeline Orchestration

```python
# controller/pipeline.py
"""
Main pipeline: webhook → diff → translate (cloud) → score → push
"""
import os
import json
import subprocess
from pathlib import Path

from mdx_parser import parse_mdx_sections, reassemble_mdx
from cache_manager import get_changed_sections, update_cache, get_cached_file
from runpod_manager import start_pod, wait_for_worker, stop_pod, translate_sections, get_embeddings
from quality_scorer import score_quality_fast, score_quality_with_embedding
from db.db_manager import DBManager

WORK_DIR = "/workspace/blog"
KO_DIR = f"{WORK_DIR}/src/content/blog/ko"


def run_pipeline(changed_files: list[str] = None):
    """
    Full translation pipeline.
    If changed_files is None, auto-detect untranslated/changed files.
    """
    db = DBManager()
    pod = None

    try:
        # ── Step 1: Git pull ──
        clone_or_pull()

        # ── Step 2: Detect files to process ──
        if changed_files:
            files = [Path(KO_DIR) / f for f in changed_files]
        else:
            files = detect_files_needing_translation()

        if not files:
            return {"status": "no_work", "message": "No files need translation"}

        # ── Step 3: Parse and diff all files ──
        all_changed = []    # Sections that need translation
        all_cached = []     # Sections with valid cache
        file_section_map = {}

        for file_path in files:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            filename = file_path.name
            sections = parse_mdx_sections(content, filename)
            changed, cached = get_changed_sections(sections, db)

            all_changed.extend(changed)
            all_cached.extend(cached)
            file_section_map[filename] = {"changed": changed, "cached": cached}

        # ── Step 4: If nothing changed (all cached), just reassemble ──
        if not all_changed:
            for filename, data in file_section_map.items():
                for lang in ["EN", "JP"]:
                    reassemble_and_write(filename, data["cached"], lang)
            commit_and_push(files)
            return {"status": "cache_hit", "message": "All from cache, no GPU needed"}

        # ── Step 5: Start cloud GPU ──
        pod = start_pod()
        wait_for_worker(pod["url"])

        # ── Step 6: Load glossary ──
        glossary_text = load_glossary(db)

        # ── Step 7: Translate changed sections (EN and JP) ──
        for lang in ["EN", "JP"]:
            translated = translate_sections(
                pod["url"], all_changed, lang, glossary_text
            )

            # Update cache with new translations
            for t in translated:
                update_cache(db, t, lang)

        # ── Step 8: Reassemble full files from cache ──
        for filename, data in file_section_map.items():
            # Reload all sections from cache (now includes new translations)
            all_sections = get_cached_file(db, filename)

            for lang in ["EN", "JP"]:
                full_content = reassemble_mdx(all_sections, lang)

                # ── Step 9: Quality scoring (standard mode) ──
                source_content = get_source_content(filename)
                embeddings = get_embeddings(pod["url"], [source_content, full_content])
                score = score_quality_with_embedding(
                    source_content, full_content, lang, embeddings
                )

                # Log score to DB
                log_quality_score(db, filename, lang, score)

                # ── Step 10: Quality gate ──
                if score["composite_score"] >= 0.6:
                    write_translated_file(filename, full_content, lang)
                else:
                    print(f"BLOCKED: {filename} ({lang}) score={score['composite_score']}")
                    # Still logged in Grafana for review

        # ── Step 11: Commit and push ──
        commit_and_push(files)

        return {
            "status": "success",
            "translated": len(all_changed),
            "cached": len(all_cached),
            "files": [f.name for f in files],
        }

    finally:
        # ── Step 12: Always stop GPU pod ──
        if pod:
            stop_pod(pod["id"])
        db.close()
```

---

## File Reassembly

```python
# controller/mdx_parser.py (continued)

def reassemble_mdx(sections: list[dict], target_lang: str) -> str:
    """
    Reassemble a full translated MDX file from cached sections.
    """
    lang_key = "en_text" if target_lang == "EN" else "jp_text"

    # Separate frontmatter and body sections
    fm_title = ""
    fm_desc = ""
    fm_tags = ""
    fm_raw = ""    # Non-translated frontmatter fields (pubDate, heroImage, etc.)
    body_parts = []

    for section in sorted(sections, key=lambda s: (s['section_type'], s['section_index'])):
        translated = section.get(lang_key, section['ko_text'])

        if section['section_type'] == 'frontmatter_title':
            fm_title = translated
        elif section['section_type'] == 'frontmatter_desc':
            fm_desc = translated
        elif section['section_type'] == 'frontmatter_tags':
            fm_tags = translated
        elif section['section_type'] == 'frontmatter_raw':
            fm_raw = section['ko_text']  # Keep as-is (pubDate, heroImage, etc.)
        elif section['section_type'] == 'body':
            body_parts.append(translated)

    # Rebuild frontmatter
    frontmatter_lines = []
    if fm_title:
        frontmatter_lines.append(f"title: '{fm_title}'")
    if fm_desc:
        frontmatter_lines.append(f"description: '{fm_desc}'")
    if fm_raw:
        frontmatter_lines.append(fm_raw)
    if fm_tags:
        frontmatter_lines.append(f"tags: {fm_tags}")

    frontmatter = '\n'.join(frontmatter_lines)
    body = '\n\n'.join(body_parts)

    return f"---\n{frontmatter}\n---\n\n{body}\n"
```

---

## Quality Scoring (Runs on Cloud GPU Too)

Since the cloud GPU is already running, use it for embedding-based scoring before shutting down. No extra cost — you're already paying for the time.

```python
# controller/quality_scorer.py
import re
import numpy as np

def cosine_similarity(a, b):
    a, b = np.array(a), np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def score_quality_fast(source: str, translated: str, target_lang: str) -> dict:
    """Fast scoring: structural + length. No GPU needed (~0ms)."""
    structural = score_structural_integrity(source, translated)
    length = score_length_ratio(source, translated, target_lang)

    composite = 0.65 * structural + 0.35 * length

    return {
        "composite_score": round(composite, 4),
        "structural_integrity": round(structural, 4),
        "length_ratio": round(length, 4),
    }


def score_quality_with_embedding(
    source: str, translated: str, target_lang: str, embeddings: list
) -> dict:
    """Standard scoring: structural + length + semantic. Uses pre-fetched embeddings."""
    structural = score_structural_integrity(source, translated)
    length = score_length_ratio(source, translated, target_lang)
    semantic = cosine_similarity(embeddings[0], embeddings[1])

    composite = 0.45 * semantic + 0.30 * structural + 0.15 * length + 0.10 * 1.0
    # last 0.10 reserved for glossary compliance (if glossary is loaded)

    return {
        "composite_score": round(composite, 4),
        "semantic_similarity": round(semantic, 4),
        "structural_integrity": round(structural, 4),
        "length_ratio": round(length, 4),
    }


def score_structural_integrity(source: str, translated: str) -> float:
    checks = []

    # Code blocks count
    src_code = len(re.findall(r"```", source))
    tgt_code = len(re.findall(r"```", translated))
    checks.append(src_code == tgt_code)

    # Heading count
    src_h = len(re.findall(r"^#{1,6}\s", source, re.MULTILINE))
    tgt_h = len(re.findall(r"^#{1,6}\s", translated, re.MULTILINE))
    checks.append(src_h == tgt_h)

    # URLs preserved
    src_urls = set(re.findall(r"\]\((https?://[^\)]+)\)", source))
    tgt_urls = set(re.findall(r"\]\((https?://[^\)]+)\)", translated))
    checks.append(src_urls == tgt_urls)

    # Image paths preserved
    src_imgs = set(re.findall(r"\]\((/images/[^\)]+)\)", source))
    tgt_imgs = set(re.findall(r"\]\((/images/[^\)]+)\)", translated))
    checks.append(src_imgs == tgt_imgs)

    # Inline code preserved (>80%)
    src_inline = set(re.findall(r"`([^`]+)`", source))
    tgt_inline = set(re.findall(r"`([^`]+)`", translated))
    if src_inline:
        checks.append(len(src_inline & tgt_inline) / len(src_inline) >= 0.8)

    return sum(checks) / len(checks) if checks else 1.0


EXPECTED_RATIOS = {
    "EN": {"min": 0.8, "max": 2.0},
    "JP": {"min": 0.6, "max": 1.5},
}

def score_length_ratio(source: str, translated: str, target_lang: str) -> float:
    if len(source) == 0:
        return 0.0
    ratio = len(translated) / len(source)
    bounds = EXPECTED_RATIOS.get(target_lang, {"min": 0.5, "max": 2.5})
    if bounds["min"] <= ratio <= bounds["max"]:
        return 1.0
    if ratio < bounds["min"]:
        return max(0.0, ratio / bounds["min"])
    return max(0.0, bounds["max"] / ratio)
```

---

## Database Schema (Full)

```sql
-- Add to database/init.sql

-- ── Existing tables (keep as-is) ──
-- translation_logs, glossary_en, glossary_jp, glossary_jp_refined, audit_logs

-- ── NEW: Paragraph-level translation cache ──
CREATE TABLE IF NOT EXISTS translation_cache (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    section_type VARCHAR(20) NOT NULL,
    section_index INT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    ko_text TEXT NOT NULL,
    en_text TEXT,
    jp_text TEXT,
    model_en VARCHAR(100),
    model_jp VARCHAR(100),
    translated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(filename, section_type, section_index, content_hash)
);

CREATE INDEX idx_cache_filename ON translation_cache(filename);
CREATE INDEX idx_cache_hash ON translation_cache(content_hash);

-- ── NEW: Translation quality scores ──
CREATE TABLE IF NOT EXISTS translation_quality (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    filename VARCHAR(255) NOT NULL,
    target_lang VARCHAR(10) NOT NULL,
    model_name VARCHAR(100),
    scoring_mode VARCHAR(20),
    composite_score FLOAT,
    semantic_similarity FLOAT,
    structural_integrity FLOAT,
    glossary_compliance FLOAT,
    length_ratio_score FLOAT,
    llm_judge_issues JSONB,
    input_char_count INT,
    output_char_count INT,
    paragraphs_total INT,
    paragraphs_cached INT,
    paragraphs_translated INT,
    UNIQUE(filename, target_lang, created_at)
);

CREATE INDEX idx_quality_score ON translation_quality(composite_score);
CREATE INDEX idx_quality_time ON translation_quality(created_at);

-- ── NEW: Pipeline run logs ──
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id SERIAL PRIMARY KEY,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    status VARCHAR(20),           -- 'success', 'failed', 'blocked'
    trigger_type VARCHAR(20),     -- 'webhook', 'manual', 'cron'
    files_processed INT,
    paragraphs_total INT,
    paragraphs_cached INT,        -- From cache (free)
    paragraphs_translated INT,    -- Sent to GPU (paid)
    gpu_time_seconds FLOAT,
    estimated_cost_usd FLOAT,     -- GPU time * hourly rate / 3600
    runpod_pod_id VARCHAR(100),
    error_message TEXT
);
```

---

## Grafana Dashboards

### Pipeline Health Panel

```sql
-- Last 10 pipeline runs
SELECT
    started_at AS time,
    status,
    files_processed,
    paragraphs_cached || '/' || paragraphs_total AS "Cache Hit",
    ROUND(gpu_time_seconds::numeric, 1) AS "GPU Seconds",
    '$' || ROUND(estimated_cost_usd::numeric, 4) AS "Cost"
FROM pipeline_runs
ORDER BY started_at DESC LIMIT 10;
```

### Cost Tracking (Time Series)

```sql
-- Monthly cost trend
SELECT
    DATE_TRUNC('month', started_at) AS time,
    SUM(estimated_cost_usd) AS monthly_cost,
    SUM(paragraphs_translated) AS paragraphs_paid,
    SUM(paragraphs_cached) AS paragraphs_free
FROM pipeline_runs
WHERE status = 'success'
GROUP BY DATE_TRUNC('month', started_at)
ORDER BY time;
```

### Cache Efficiency (Stat Panel)

```sql
-- Overall cache hit rate
SELECT
    ROUND(
        SUM(paragraphs_cached)::numeric /
        NULLIF(SUM(paragraphs_total), 0)::numeric * 100, 1
    ) AS "Cache Hit Rate %"
FROM pipeline_runs
WHERE status = 'success' AND started_at > NOW() - INTERVAL '30 days';
```

### Quality Score Over Time

```sql
SELECT
    created_at AS time,
    composite_score,
    target_lang,
    filename
FROM translation_quality
WHERE created_at > NOW() - INTERVAL '30 days'
ORDER BY created_at;
```

### Low Quality Alerts

```sql
SELECT filename, target_lang, composite_score, created_at
FROM translation_quality
WHERE composite_score < 0.6
ORDER BY created_at DESC;
```

### Dashboard Layout

```
┌────────────────────────────────────────────────────────────────┐
│  Translation Pipeline Dashboard                                 │
├───────────┬───────────┬────────────┬────────────┬──────────────┤
│ Pipeline  │ Cache Hit │ This Month │ Avg Quality│ Blocked      │
│ Runs: 23  │ Rate: 74% │ Cost: $0.41│ Score: 0.83│ Posts: 2     │
│ (stat)    │ (stat)    │ (stat)     │ (stat)     │ (stat)       │
├───────────┴───────────┴────────────┴────────────┴──────────────┤
│  Quality Score Over Time (time series — EN vs JP)               │
├────────────────────────────────┬───────────────────────────────┤
│  Cost Per Month (bar chart)    │  Cache Hit Rate (time series) │
│  Jan: $0.12                    │  ──────────╮                  │
│  Feb: $0.28                    │  60% → → → 82% ─────         │
│  Mar: $0.41                    │                               │
├────────────────────────────────┴───────────────────────────────┤
│  Recent Pipeline Runs (table)                                   │
│  Time       │ Status  │ Files │ Cache │ GPU(s) │ Cost          │
│  Mar 10 9pm │ success │  1    │ 18/20 │  32s   │ $0.003       │
│  Mar 8 3pm  │ blocked │  1    │  0/15 │ 180s   │ $0.020       │
│  Mar 5 8pm  │ success │  3    │ 41/52 │  95s   │ $0.010       │
├────────────────────────────────────────────────────────────────┤
│  Low Quality Alerts                                             │
│  ⚠ Bot_03.mdx │ JP │ 0.52 │ "ASCII tree broken"              │
└────────────────────────────────────────────────────────────────┘
```

---

## Updated docker-compose.yml

```yaml
version: '3.8'

services:
  postgres:
    image: pgvector/pgvector:pg15    # was: postgres:15-alpine (adds vector search)
    container_name: mlops-db
    environment:
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASS}
      POSTGRES_DB: ${DB_NAME}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./database/init.sql:/docker-entrypoint-initdb.d/init.sql
    networks:
      - mlops-net
    restart: always

  grafana:
    image: grafana/grafana:latest
    container_name: mlops-dashboard
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    depends_on:
      - postgres
    networks:
      - mlops-net
    volumes:
      - grafana_data:/var/lib/grafana
    restart: always

  controller:
    build:
      context: .
      dockerfile: controller/Dockerfile
    container_name: translation-controller
    ports:
      - "8000:8000"
    environment:
      - RUNPOD_API_KEY=${RUNPOD_API_KEY}
      - RUNPOD_TEMPLATE_ID=${RUNPOD_TEMPLATE_ID}
      - RUNPOD_VOLUME_ID=${RUNPOD_VOLUME_ID}
      - GITHUB_TOKEN=${GITHUB_TOKEN}
      - WEBHOOK_SECRET=${WEBHOOK_SECRET}
      - BLOG_REPO_URL=${BLOG_REPO_URL}
      - DB_HOST=postgres
      - DB_PORT=5432
      - DB_NAME=${DB_NAME}
      - DB_USER=${DB_USER}
      - DB_PASS=${DB_PASS}
    volumes:
      - blog_workspace:/workspace
    depends_on:
      - postgres
    networks:
      - mlops-net
    restart: always

volumes:
  postgres_data:
  grafana_data:
  blog_workspace:

networks:
  mlops-net:
```

### Updated .env

```bash
# Database
DB_HOST=localhost
DB_NAME=mlops_logs
DB_USER=admin
DB_PASS=password123
DB_PORT=5432

# GitHub
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
BLOG_REPO_URL=https://github.com/<your-username>/hun-bot-blog.git
WEBHOOK_SECRET=your-webhook-secret-here

# RunPod
RUNPOD_API_KEY=your-runpod-api-key
RUNPOD_TEMPLATE_ID=your-template-id
RUNPOD_VOLUME_ID=your-volume-id
```

---

## Implementation Steps (Ordered)

### Phase 1: Foundation (cache + parser)

| Step | Task | Files to Create/Modify |
|------|------|------------------------|
| 1.1 | Add new tables to init.sql | `database/init.sql` |
| 1.2 | Build MDX paragraph parser + hasher | `src/mdx_parser.py` |
| 1.3 | Build cache manager (read/write/diff) | `src/cache_manager.py` |
| 1.4 | Add cache methods to DBManager | `src/db/db_manager.py` |
| 1.5 | Switch PostgreSQL image to `pgvector/pgvector:pg15` | `docker-compose.yml` |
| 1.6 | Add pgvector extension + embedding column + similarity search query | `database/init.sql` |
| 1.7 | Build translation memory retriever (enrich sections with similar past translations) | `src/translation_memory.py` |
| 1.8 | Test: parse existing MDX files, verify hashing + embedding storage | manual test |

### Phase 2: Cloud GPU (RunPod worker)

| Step | Task | Files to Create/Modify |
|------|------|------------------------|
| 2.1 | Create RunPod account + API key | runpod.io dashboard |
| 2.2 | Create network volume (30GB) | runpod.io dashboard |
| 2.3 | Build worker Dockerfile + API | `runpod/Dockerfile`, `runpod/worker.py`, `runpod/entrypoint.sh` |
| 2.4 | Push worker image to Docker Hub | `docker build & push` |
| 2.5 | Create pod template on RunPod | runpod.io dashboard |
| 2.6 | Build RunPod manager (start/stop/translate) | `controller/runpod_manager.py` |
| 2.7 | Test: manually start pod, translate 1 paragraph, stop | manual test |

### Phase 3: Pipeline + Quality (controller)

| Step | Task | Files to Create/Modify |
|------|------|------------------------|
| 3.1 | Build quality scorer | `controller/quality_scorer.py` |
| 3.2 | Build full pipeline orchestrator | `controller/pipeline.py` |
| 3.3 | Build FastAPI webhook server | `controller/main.py` |
| 3.4 | Build controller Dockerfile | `controller/Dockerfile` |
| 3.5 | Update docker-compose.yml | `docker-compose.yml` |
| 3.6 | Update .env with RunPod + GitHub vars | `.env` |
| 3.7 | Test: `curl -X POST localhost:8000/trigger` | manual test |

### Phase 4: Grafana + Webhook

| Step | Task | Files to Create/Modify |
|------|------|------------------------|
| 4.1 | Set up Grafana PostgreSQL data source | Grafana UI |
| 4.2 | Create dashboard panels (queries above) | Grafana UI |
| 4.3 | Expose controller via Cloudflare Tunnel | `cloudflared tunnel` |
| 4.4 | Configure GitHub webhook on blog repo | GitHub UI |
| 4.5 | End-to-end test: push a KO post, verify full pipeline | manual test |

### Phase 5: Refinement

| Step | Task |
|------|------|
| 5.1 | Tune quality threshold (0.6 might be too strict/lenient) |
| 5.2 | Calibrate length ratio bounds with real data |
| 5.3 | Add Slack/Discord notification on blocked translations |
| 5.4 | Backfill cache with existing translations (so edits to old posts are efficient) |

---

## Time Estimate (4 hours/day)

### Per-Phase Breakdown

| Phase | Task | Estimated Days | Rationale |
|-------|------|:--------------:|-----------|
| **Phase 1** | Foundation (cache + parser + pgvector) | **4 days** | 1.1 DB schema (~1hr), 1.2 MDX parser (~3hrs — tricky edge cases: code blocks, frontmatter, nested markdown), 1.3 Cache manager (~2hrs), 1.4 DBManager methods (~1hr), 1.5-1.6 pgvector setup (~2hrs — Docker image swap + extension + index), 1.7 Translation memory retriever (~3hrs — embedding queries, prompt builder), 1.8 Manual testing + debugging (~3hrs) |
| **Phase 2** | Cloud GPU (RunPod worker) | **3 days** | 2.1-2.2 Account + volume (~1hr), 2.3 Dockerfile + worker API (~4hrs — Ollama setup, FastAPI endpoints, model pull script), 2.4 Docker Hub push (~1hr), 2.5 Pod template (~30min), 2.6 RunPod manager in Python (~3hrs — start/stop/health check/translate API calls), 2.7 Testing + debugging (~2hrs — network issues, model loading delays) |
| **Phase 3** | Pipeline + Quality (controller) | **4 days** | 3.1 Quality scorer (~4hrs — 4 scoring methods, composite weights, threshold logic), 3.2 Pipeline orchestrator (~4hrs — diff detection → RunPod call → quality gate → cache update → git commit/push, error handling), 3.3 FastAPI server (~2hrs — webhook endpoint, status API), 3.4-3.5 Dockerfile + compose (~1hr), 3.6 Env vars (~30min), 3.7 Integration testing (~3hrs — this is where most bugs surface) |
| **Phase 4** | Grafana + Webhook | **2 days** | 4.1-4.2 Grafana dashboard (~3hrs — 7 panels, SQL queries, layout), 4.3 Cloudflare Tunnel (~1hr), 4.4 GitHub webhook (~30min), 4.5 End-to-end test (~3hrs — full cycle from git push to Vercel deploy) |
| **Phase 5** | Refinement | **2 days** | 5.1-5.2 Quality tuning (~3hrs — translate 5-10 posts, analyze scores, adjust thresholds), 5.3 Slack notification (~2hrs), 5.4 Backfill cache with existing translations (~3hrs — parse all existing posts, embed, store) |
| | **Total** | **15 days** | |

### Calendar View (4 hrs/day, weekdays only)

```
Week 1  [Mon-Thu]    Phase 1: Foundation (cache + parser + pgvector)
Week 2  [Mon-Wed]    Phase 2: Cloud GPU (RunPod worker)
Week 2  [Thu]        Phase 3: Pipeline + Quality (start)
Week 3  [Mon-Wed]    Phase 3: Pipeline + Quality (finish)
Week 3  [Thu]        Phase 4: Grafana + Webhook (start)
Week 4  [Mon]        Phase 4: Grafana + Webhook (finish)
Week 4  [Tue-Wed]    Phase 5: Refinement
```

**~3.5 weeks** at 4 hours/day (weekdays).
**~15 working days** = **60 hours** total.

### Risk Buffer

| Risk | Impact | Likelihood | Buffer |
|------|--------|:----------:|:------:|
| RunPod networking issues (pod won't start, port blocked) | +1 day | Medium | Phase 2 |
| MDX edge cases (nested code blocks, JSX components, unusual frontmatter) | +1 day | High | Phase 1 |
| Quality scoring calibration takes longer than expected | +1 day | Medium | Phase 5 |
| pgvector index tuning (recall vs speed for similarity search) | +0.5 day | Low | Phase 1 |

**With buffer: ~4 weeks** (realistic estimate).

### Fastest Path (MVP first)

If you want a working system ASAP and refine later:

| Priority | What | Days | You Get |
|----------|------|:----:|---------|
| **MVP** | Phase 1 (cache) + Phase 2 (RunPod) + Phase 3 (pipeline, skip quality scorer) | **8 days** | Auto-translation with caching, MacBook free. No quality scoring yet. |
| **+Quality** | Add quality scorer from Phase 3.1 | **+1 day** | Real quality scores logged to DB. |
| **+Dashboard** | Phase 4 | **+2 days** | Grafana monitoring + GitHub webhook trigger. |
| **+Polish** | Phase 5 | **+2 days** | Tuned thresholds, notifications, backfilled cache. |

**MVP in ~2 weeks**, full system in ~4 weeks.

---

## Cost Estimate

| Scenario | Paragraphs to GPU | GPU Time | Cost |
|----------|-------------------|----------|------|
| New post (20 paragraphs, 2 langs) | 40 | ~5 min | ~$0.03 |
| Edit post (2 paragraphs changed) | 4 | ~30 sec | ~$0.003 |
| 10 posts/month (mix of new + edits) | ~100 | ~15 min | ~$0.10 |
| Pod startup overhead | — | ~2 min | ~$0.01 |
| **Monthly estimate** | | | **~$0.10-0.50** |

PostgreSQL + Grafana + Controller on Mac: $0 (Docker Compose, negligible RAM).
RunPod network volume (30GB): $1.50/month (stores models persistently).

**Total: ~$2/month** for fully automated, MacBook-free translation.
