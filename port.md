# Local LLM Observability — Architecture Portfolio

## 1. Why This System Exists

### The Starting Point: A Korean Developer Writing for the World

I write a Korean tech blog about algorithm study automation — a series called "Algorithm Bot" that documents building a Slack-based review system using Ebbinghaus forgetting curves, RAG-based similar problem recommendation, and embedding model benchmarks. The blog is built with MDX on Docusaurus/Astro and deployed via Vercel. It's written in Korean because that's how I think and explain best, but the content is relevant to developers worldwide.

### The Language Barrier Problem

Korean tech blog content is almost invisible to the global developer community. Japanese engineers on Zenn/Qiita and English-speaking developers on dev.to/Medium will never discover my posts because they simply can't read them. Manual translation is possible but unsustainable — each post takes 2-3 hours to translate properly into even one language, and I need both English and Japanese. After 5 posts, I've spent more time translating than writing.

### Why Not Google Translate or DeepL?

Machine translation services produce output that a developer would immediately recognize as machine-translated. They fail on three critical fronts: technical terminology (translating `commit & push` into the target language instead of keeping it in English), markdown structure (breaking code blocks, tables, and image links), and tone (producing stiff, formal output instead of the casual-professional developer blog voice). A tech blog that reads like a machine translation loses credibility with its audience.

### Why Not Commercial LLM APIs?

OpenAI, Anthropic, and Google offer excellent translation through their APIs. However, I want complete control over my translation pipeline. I need a custom glossary of 1,738 Korean technical terms mapped to English and Japanese equivalents, custom system prompts tuned for my specific writing style, and the ability to iterate on model selection without being locked into a single provider's pricing or availability. More importantly, building this system is itself a portfolio piece — it demonstrates MLOps, observability, and NLP pipeline design.

### The Vision: Write Once in Korean, Publish in Three Languages

The goal is a one-command translation pipeline: I finish writing a Korean `.mdx` post, run `python translate.py <file>`, review the output, apply corrections, and push. Vercel auto-deploys the Korean, English, and Japanese versions. The system remembers my corrections and uses them to improve future translations. Cost: under $2/month.

---

## 2. Architecture Decisions — Why Each Technology Was Chosen

### Why Pre-commit CLI Instead of Webhook Automation

The original design used GitHub Webhooks + Cloudflare Tunnel + FastAPI controller to trigger translations automatically on `git push`. I abandoned this in favor of a simple CLI script (`translate.py`) for four reasons. First, I want to review translations before they go live — automated publishing of unchecked translations risks publishing broken Japanese or hallucinated content. Second, the webhook approach requires a FastAPI controller, Cloudflare Tunnel, and webhook configuration — three additional infrastructure components that add complexity without adding value when I translate a few posts per month. Third, a pre-commit workflow lets me catch and correct errors before they reach the public blog, and those corrections feed back into the translation memory for continuous improvement. Fourth, network failures during webhook delivery would create silent translation gaps, while a CLI script fails loudly and can be retried immediately.

### Why RunPod Over Modal, Vast.ai, and Local Inference

I evaluated five GPU compute options for running Ollama with my translation models (~17GB total VRAM needed). RunPod won for this specific workload. Local inference on my MacBook (M-series, 16-24GB unified memory) works but blocks the machine for 5-15 minutes per post — I can't code, browse, or even switch apps smoothly while both models are loaded. Modal offers $30/month free credits and excellent developer experience, but its A10G (24GB) is tight for simultaneous model loading, and its custom image system adds friction when I want a standard Docker + Ollama setup. Vast.ai has the lowest prices ($0.32/hr for an A40) but unreliable hosts — community GPUs can be pulled without notice, which is unacceptable for an automated pipeline that needs to complete reliably. Lambda Labs only offers A100 80GB at $1.79/hr, massive overkill for a 17GB workload. RunPod's A40 (48GB) at $0.35/hr with per-second billing, full Docker support, and Network Volumes ($0.07/GB/month) for persistent model storage hits the sweet spot: models persist across restarts (no 14GB re-download), the pod starts in 60-90 seconds, and my Mac stays completely free during translation. Monthly cost: ~$3.26 (8 runs × $0.06 + $1.40 storage).

### Why TranslateGemma 12B for English and Qwen3 14B for Japanese

Model selection prioritized translation quality above all else. For Korean→English, TranslateGemma 12B (released January 2026 by Google) is purpose-built for translation, fine-tuned with reinforcement learning from professional translator evaluations. On the WMT24++ benchmark, it scores MetricX 3.60 — outperforming the 27B base Gemma 3 (MetricX 4.04) despite being less than half the size. It runs on ~8GB VRAM and is natively available in Ollama (`translategemma:12b`). For Korean→Japanese, Qwen3 14B (released April 2025 by Alibaba) is the strongest open-source model for CJK language pairs. Korean and Japanese share SOV grammar, honorific systems, and heavy technical loanword usage — Qwen3's training data emphasizes these exact patterns across 100+ languages with Korean and Japanese as first-class citizens. It handles complex system prompts (ASCII tree protection, LaTeX preservation, です・ます tone control) better than any translation-specialized model. Both models are Apache 2.0 licensed and run sequentially on the same A40 GPU using Ollama's `keep_alive=0` to free VRAM between languages. I considered using Qwen3 14B for both languages (simpler, one model), but TranslateGemma's RL-tuned translation quality gives a measurable edge for English output that justifies the two-model approach. I also evaluated EXAONE 3.5 7.8B (LG AI Research) — it's the best Korean-English specialist per parameter, but its non-commercial license and zero Japanese capability make it unsuitable.

### Why PostgreSQL + pgvector Instead of a Dedicated Vector Database

The translation cache stores ~1,000 paragraphs with 768-dimensional embeddings for RAG-based translation memory. Pinecone, Weaviate, and Qdrant are designed for millions of vectors in multi-tenant SaaS deployments — massive overkill for 1,000 paragraphs. ChromaDB adds another service to manage. FAISS works (I used it in Algorithm Bot 04 before ditching it in Bot 05 for numpy). pgvector adds vector similarity search to the PostgreSQL instance I'm already running for glossary and pipeline data — zero new infrastructure, one image swap in docker-compose (`postgres:15-alpine` → `pgvector/pgvector:pg15`). At 1,000 vectors, IVFFlat index search takes <1ms. The storage overhead is ~3MB. When I hit 100,000 paragraphs (which means I've translated 5,000 blog posts), I'll reconsider — but that's not happening.

### Why Paragraph-Level Caching Instead of File-Level Translation

My current translation agents translate entire files or large chunks in a single LLM call. This approach has three critical failures I discovered in production. The LLM adds hallucinated commentary — Algorithm_Bot_03_jp.mdx line 69 contains `この翻訳では、「データ前処理」から「モデル評価」までのプロセスと...` which doesn't exist in the Korean source. Code blocks get structurally broken — the ASCII tree in a ` ```text ``` ` block was exposed as raw text because the code fence was lost during translation. When I edit two paragraphs in a published post, the entire file gets re-translated, changing the phrasing of 18 paragraphs that were already correct. Paragraph-level caching solves all three: smaller input to the LLM means fewer structural errors, unchanged paragraphs are served from cache (SHA-256 hash comparison), and code blocks are never sent to the LLM at all — they pass through untouched. The diff-aware approach also cuts GPU cost dramatically: editing 2 paragraphs in a 20-paragraph post costs ~$0.003 instead of ~$0.05.

### Why a Human Review Loop Is the Core Quality Feature

No LLM produces 100% correct translations consistently. The question is how to handle the inevitable errors. My approach: translate, review, correct, and feed corrections back into the system. When I fix a bad translation in the output file and run `feedback.py`, the corrected text overwrites the cached version. In Phase 2, these human-corrected paragraphs become RAG examples — when translating a new paragraph, the system retrieves the 3 most semantically similar past translations (via pgvector) and includes them as few-shot examples in the prompt. After 50 corrected paragraphs, the LLM sees real examples of how I translate Korean tech content, not generic translation patterns. This is Translation Memory — a concept borrowed from professional translation tools like SDL Trados, implemented with a vector database and LLM prompting instead of exact-match segment lookup.

---

## 3. Problems, Solutions, and Results

### Problem: LLM Hallucination in Translation Output

When translating long documents, LLMs sometimes add explanatory text that doesn't exist in the source. In Algorithm_Bot_03_jp.mdx, the model appended a meta-commentary paragraph: "In this translation, I translated from 'Data Preprocessing' to 'Model Evaluation'..." This kind of hallucination is invisible to automated checks unless you specifically look for it, and it destroys reader trust when a Japanese engineer reads a sentence that clearly wasn't written by the author.

**Solution:** A multi-layered anti-hallucination system. First, translate at the paragraph level instead of file level — smaller inputs produce fewer hallucinations. Second, an anti-hallucination quality check compares the number of paragraphs in source vs. output, detects meta-commentary patterns (sentences starting with "この翻訳では" / "In this translation"), and flags character ratio anomalies (a paragraph that's 3x longer in the translation than expected is likely hallucinated). Third, the quality gate blocks output that fails these checks — the paragraph is re-translated with a stricter prompt.

**Expected Result:** Hallucination rate drops from ~5-10% of long documents to <1% of paragraphs. The remaining errors are caught during human review and fed back into the translation memory to prevent recurrence.

### Problem: Structural Corruption of Markdown Elements

Korean tech blog posts contain code blocks, ASCII art trees, LaTeX formulas, Markdown tables, image links, and inline code. The current translation pipeline sends all content to the LLM, which frequently corrupts these elements. Code fences (` ``` `) get removed or misplaced. Table delimiters (`|`) get misaligned. URLs inside image links get modified. ASCII tree characters (`├─`, `└─`, `│`) get replaced with Japanese equivalents or removed entirely.

**Solution:** The MDX parser (`mdx_parser.py`) classifies each section as either `paragraph` (translatable) or `code` (pass-through). Code blocks are never sent to the LLM — they're preserved exactly as-is in the output. For paragraphs containing mixed content (inline code, URLs, image references), a structural integrity check after translation verifies: code block count matches, heading count matches, all URLs are preserved, all image paths are preserved, and ≥80% of inline code spans are unchanged. Paragraphs that fail structural checks are re-translated with reinforced structural preservation instructions.

**Expected Result:** Zero structural corruption in code blocks (they're never touched). Structural integrity score for prose paragraphs improves from ~70% (current, file-level translation) to >95% (paragraph-level with verification).

### Problem: Inconsistent Terminology Across Blog Series

The "Algorithm Bot" series spans 5 posts that reference the same concepts repeatedly: "에빙하우스 망각 곡선" (Ebbinghaus forgetting curve), "유사 문제 추천" (similar problem recommendation), "벡터 검색" (vector search). Without enforced consistency, the same Korean term gets translated differently across posts — sometimes even within the same post. This makes the series read as if it were written by different authors.

**Solution:** A 1,738-term glossary (93 EN + 951 JP + 694 JP refined terms) is loaded from PostgreSQL and injected into every translation prompt. After translation, a glossary enforcement check scans the output: if the source paragraph contains a Korean glossary term, the corresponding English/Japanese term must appear in the translation. Missing terms trigger a re-translation with the specific missing terms highlighted in the prompt. In Phase 2, Translation Memory (RAG) provides additional consistency — when translating a paragraph about "벡터 검색," the system retrieves how the same concept was translated in previous posts and includes those examples as context.

**Expected Result:** Glossary compliance rises from ~60% (current, based on `verify_translation()` checks in `translation_model_test.py`) to >90%. Series-wide consistency improves noticeably after 3-5 posts of corrections are accumulated in the translation memory.

### Problem: Personal Voice Lost in Translation

My Korean writing style is casual-professional — I use expressions like "AI가 이 말을 겁나게 좋아합니다" (literally: "AI freaking loves this term") which conveys personality. The current translation flattens this to "AIにとってこの説明が大好きです" (flat formal: "AI really likes this explanation"). The humor, sarcasm, and personal voice that make a blog post feel human are stripped away. This isn't a model quality issue — it's a context issue. The LLM has no examples of how I personally translate casual Korean into casual-but-professional Japanese.

**Solution:** The human correction feedback loop is specifically designed to solve this. When I review `_jp.mdx` and fix tone issues — replacing "AIにとってこの説明が大好きです" with "AIがこの言葉を超気に入ってるんですよね" (casual: "AI is super into this term, you know?") — that correction is stored in `translation_cache` with the embedding of the Korean source. In Phase 2, when the RAG system encounters a similar casual expression, it retrieves my corrected version as a few-shot example. The LLM literally sees: "Here's how the author translates casual Korean humor — match this tone." After 50+ corrections, the model has a statistical profile of my translation voice.

**Expected Result:** Tone accuracy improves gradually over the first 3-5 posts as corrections accumulate. By post 10, the first-pass translation should capture my voice without correction for ~80% of casual expressions.

### Problem: Wasted GPU Cost When Editing Published Posts

I frequently edit published posts — fixing typos, adding sections, updating results. With the current system, any edit triggers a full re-translation: all 20 paragraphs are sent to the GPU, consuming 5-10 minutes and ~$0.05 of RunPod time, even if only 2 paragraphs changed. Over a month of active editing, this adds up and the GPU time is 90% wasted on paragraphs that haven't changed.

**Solution:** SHA-256 content hashing at the paragraph level. When a post is translated, each paragraph's hash is stored alongside its Korean source and English/Japanese translations. On re-translation, the parser hashes each paragraph and compares against the cache. Only paragraphs whose hash has changed are sent to the GPU. Unchanged paragraphs are assembled from cache. The reassembled file is structurally identical to a fresh translation — the reader can't tell which paragraphs are cached vs. newly translated.

**Expected Result:** For a typical edit (2-3 paragraphs changed in a 20-paragraph post), GPU time drops from ~10 minutes to ~30 seconds. Cost drops from ~$0.05 to ~$0.003. Cache hit rate after the first full translation of a post: 85-95%.

### Problem: No Visibility Into Translation Pipeline Performance

The current system provides zero feedback after translation completes. I don't know which paragraphs were problematic, how consistent the glossary usage was, how long inference took, or how much it cost. When a translation is bad, I discover it only during manual review with no data to help me understand why it failed or whether quality is trending up or down across posts.

**Solution:** Full observability through PostgreSQL logging and Grafana visualization. Every pipeline run logs: total sections, cached sections, new sections, GPU time, estimated cost, and final status. Every translated paragraph gets a quality score (structural integrity, length ratio, semantic similarity, glossary compliance). Grafana dashboards display quality scores over time (EN vs JP), cache hit rate trends, monthly cost bar charts, recent pipeline runs with status/cost/cache stats, and low-quality alerts. An automated weekly report (cron job) aggregates the week's data — posts translated, average quality score, GPU cost, cache efficiency — and stores it in a `weekly_reports` table for historical tracking.

**Expected Result:** Complete visibility into every pipeline run. Quality regressions are caught within one weekly report cycle. Cost tracking validates the ~$2/month target. Cache hit rate trends confirm the system is getting more efficient over time.

---

## 4. System Functions — What Each Component Does

### translate.py — The Single Entry Point

The CLI entry point replaces the three separate translation scripts (`translation_agent.py`, `translate_heavy.py`, `translation_model_test.py`) with a unified pipeline. It accepts a single MDX filename, orchestrates the full pipeline (parse → cache check → start RunPod → translate → quality gate → write output → stop RunPod), and prints section-by-section progress with quality scores to the terminal. It handles errors gracefully — if the RunPod pod fails to start, it reports the error and exits without corrupting any cached data. It always stops the GPU pod in a `finally` block to prevent runaway costs.

### mdx_parser.py — Structural Decomposition of MDX Files

The parser converts a raw MDX file into a structured list of sections. It extracts frontmatter fields (title, description, pubDate, heroImage, tags, category, series, seriesOrder) via YAML parsing. It splits the body into paragraphs at double-newline boundaries while preserving code blocks as atomic units — a paragraph inside a ` ``` ` block is never split. Each section gets a type (`paragraph` or `code`), a sequential index, the raw text, and a SHA-256 hash of the text. This structured output is the foundation for both cache diffing and translation — code sections are passed through, paragraph sections are sent to the LLM.

### cache_manager.py — Diff-Aware Translation Cache

The cache manager compares parsed sections against the PostgreSQL `translation_cache` table. For each section, it checks: does a cache row exist with the same filename, section index, and content hash? If yes and both EN/JP translations exist, it's a cache hit — the cached translations are used directly. If the hash has changed or no cache entry exists, it's a cache miss — the section is queued for translation. After translation, the cache is updated with the new hash and translations. This enables incremental translation: only changed content goes to the GPU.

### quality_scorer.py — Multi-Dimensional Translation Quality

The quality scorer evaluates each translated paragraph on four dimensions. Structural integrity checks that code blocks, headings, URLs, and image paths survived translation intact. Anti-hallucination detection compares source and output paragraph counts, flags meta-commentary patterns, and catches abnormal length ratios. Glossary enforcement verifies that required terminology was used correctly and identifies specific missing terms. Semantic similarity computes cosine similarity between source and translation embeddings to detect meaning drift. Each dimension produces a score between 0 and 1, and a weighted composite score determines whether the paragraph passes the quality gate. Failed paragraphs are flagged for re-translation or manual review.

### feedback.py — Human Correction Ingestion

The feedback script is run after human review. It reads the corrected `_en.mdx` or `_jp.mdx` file, parses it back into sections using the same paragraph-splitting logic as `mdx_parser.py`, and diffs each section against the cached version. Sections where the human made corrections are updated in `translation_cache` with the corrected text. In Phase 2, these corrected paragraphs are embedded and stored with their vectors, making them available as RAG examples for future translations. The feedback loop is what transforms the system from a static translation tool into an adaptive one that learns from every correction.

### weekly_report.py — Automated Pipeline Analytics

A cron-scheduled script that runs every Monday and generates a weekly summary. It queries `pipeline_runs` for all runs in the past 7 days, aggregates quality scores from `translation_quality`, calculates cache hit rates, and sums GPU costs. The report is stored in a `weekly_reports` table and is available in Grafana as a historical trend. This provides a clear picture of how the system is performing over time — whether quality is improving, whether the cache is getting more efficient, and whether costs are staying within the ~$2/month target.

### Grafana Dashboard — Real-Time Observability

The Grafana instance (port 3000) connects to PostgreSQL and displays five main panels. The quality score time series shows EN and JP composite scores over time with a threshold line at the quality gate cutoff. The cache hit rate trend shows what percentage of paragraphs are served from cache vs. sent to GPU. The monthly cost bar chart tracks RunPod spending. The recent pipeline runs table shows each run's status, file count, cache stats, GPU time, and cost. The low quality alerts panel highlights any translations that failed the quality gate, linking directly to the problematic file and language.

---

## 5. Cost Analysis

### Monthly Budget Breakdown

| Component | Monthly Cost | Notes |
|-----------|-------------|-------|
| RunPod GPU (A40, on-demand) | ~$0.50 | 8 runs × $0.06/run (10 min each) |
| RunPod Network Volume (20GB) | $1.40 | Persistent model storage |
| PostgreSQL (Docker on Mac) | $0 | ~100MB RAM |
| Grafana (Docker on Mac) | $0 | ~100MB RAM |
| GitHub + Vercel | $0 | Free tier |
| **Total** | **~$1.90/month** | |

### Cost Per Blog Post

| Scenario | Paragraphs to GPU | GPU Time | Cost |
|----------|-------------------|----------|------|
| New post (20 paragraphs, 2 languages) | 40 | ~5-10 min | ~$0.03-0.06 |
| Edit post (2 paragraphs changed) | 4 | ~30 sec | ~$0.003 |
| Full re-translation (rare) | 40 | ~10 min | ~$0.06 |

---

## 6. Technology Summary

| Layer | Technology | Why This One |
|-------|-----------|-------------|
| CLI Entry Point | `translate.py` (Python) | Simple, no server infrastructure needed |
| MDX Parsing | `mdx_parser.py` (regex + YAML) | Handles frontmatter + code block preservation |
| Translation Cache | PostgreSQL `translation_cache` + SHA-256 | Paragraph-level diffing, zero re-translation of unchanged content |
| Translation Memory | pgvector (Phase 2) | RAG pattern using existing PostgreSQL — zero new infrastructure |
| GPU Compute | RunPod A40 (on-demand) | Best Docker/Ollama support, persistent volumes, $0 when idle |
| EN Translation | TranslateGemma 12B | RL-tuned for translation, beats 27B Gemma3 on benchmarks |
| JP Translation | Qwen3 14B | Best open-source CJK multilingual, Apache 2.0 |
| Embedding | nomic-embed-text | Lightweight, multilingual, for RAG + semantic scoring |
| Quality Scoring | Python (regex + numpy + string matching) | Four-dimensional quality gate, runs on Mac |
| Glossary | PostgreSQL (1,738 terms across 3 tables) | KO→EN and KO→JP term enforcement |
| Observability | Grafana + PostgreSQL | Quality trends, cost tracking, cache efficiency |
| Weekly Report | Cron + Python script | Automated pipeline analytics |
| Blog Hosting | Vercel | Auto-deploys on git push |
| Containerization | Docker Compose | PostgreSQL + Grafana on Mac |
