# New Architecture: High-Precision Local Translation Service

Last updated: 2026-04-13

## Principle

The goal is not to make one open model magically perfect. The goal is to build a service where bad translations do not ship.

The system follows the research direction from `Raising Korean-Japanese Translation to >=99% Service Accuracy with Local Models.pdf`:

1. Human-defined quality rubric and numeric pass criteria.
2. Full LLM call tracing.
3. Hard structural validators.
4. Human review and correction capture.
5. Reference-free QE gating.
6. Retrieval, glossary constraints, and fallback models.
7. Fine-tuning only after enough clean correction data exists.

## Target Definition

The project should use "service accuracy", not a vague model accuracy number.

- `SPR@MQM`: at least 99% of reviewed segments have no Major or Critical errors.
- `SVPR`: at least 99.9% of segments pass hard structural validators.
- Critical errors allowed: 0.
- Major errors allowed per accepted segment: 0.
- Hard validator failure action: reject and queue for human review.
- Future QE action: accept, retry, fallback, or human review based on calibrated thresholds.

## Human-Owned Quality Rubric

The first job belongs to the human reviewer: define what "good translation" means with rules, numbers, and examples.

Initial rubric dimensions:

- `adequacy`: source meaning is preserved; no omission, contradiction, or invented content.
- `structure`: MDX, Markdown, frontmatter, links, tables, code fences, placeholders, and inline code are preserved.
- `terminology`: glossary terms, product names, libraries, models, and algorithm terms are consistent.
- `fluency`: Japanese/English reads naturally for a technical blog audience.
- `register`: author voice is preserved; no promotional rewrite or translator commentary.

Initial weights:

| Dimension | Weight |
| --- | ---: |
| adequacy | 0.35 |
| structure | 0.25 |
| terminology | 0.20 |
| fluency | 0.10 |
| register | 0.10 |

Initial hard reject examples:

- Adds a heading that does not exist in the source.
- Adds a URL that does not exist in the source.
- Adds translator commentary.
- Leaves too much Korean in Japanese output.
- Expands a section far beyond the source.
- Breaks code fences, frontmatter, links, or MDX structure.

## Current Foundation Implemented

The system now has these foundation pieces:

- `llm_calls`: forensic trace of every model attempt.
- `translation_rubrics`: active human-owned quality rubric per target language.
- `human_review_queue`: rejected or low-confidence segments waiting for human review.
- `translation_corrections`: human-corrected outputs for cache updates and future fine-tuning.
- Hard validator in `local_llm_observability/translation_validator.py`.
- Rejected model outputs are recorded before failure.
- Rejected sections are queued for human review.
- Feedback ingestion stores corrections instead of only updating cache.

## Repository Layout

```text
local-llm-observability/
├── local_llm_observability/     # Python application package
│   ├── api/                     # FastAPI controller
│   ├── db/                      # PostgreSQL access layer
│   ├── translator.py            # Main translation pipeline
│   ├── translation_validator.py # Hard validators
│   └── quality_policy.py        # Human-owned rubric defaults
├── scripts/                     # Scanner and incremental runner CLIs
├── tests/                       # Deterministic tests and local model tester
├── samples/mdx/                 # Local MDX fixtures and generated samples
├── runpod/                      # GPU worker image and worker API
├── database/                    # SQL schema
├── frontend/                    # SvelteKit dashboard
├── docs/                        # Architecture diagrams
├── translate.py                 # Compatibility wrapper
├── scan_posts.py                # Compatibility wrapper
└── translate_changed.py         # Compatibility wrapper
```

## Runtime Pipeline

```text
Korean MDX section
  -> parse and protect structure
  -> cache lookup
  -> retrieve glossary and future translation-memory examples
  -> model translation
  -> normalize output
  -> record llm_calls
  -> hard validator
      -> fail: queue human review, stop/fallback
      -> pass: continue
  -> future QE scoring with COMETKiwi/xCOMET
      -> high confidence: accept
      -> medium confidence: retry/fallback
      -> low confidence: human review
  -> write accepted translation_sections
  -> update translation_cache
  -> write MDX output
```

## Development Order

### 1. Human Quality Contract

Owner: human.

Deliverables:

- Finalize the active rubric in `translation_rubrics`.
- Create 30-50 positive examples of good Ko-Ja and Ko-En translations.
- Create 30-50 negative examples with labels: hallucination, structure break, wrong term, wrong tone, leftover source language.
- Define Major/Critical error examples for this blog.
- Decide first publish gate:
  - hard validators pass
  - no Critical errors
  - no Major errors in sampled review

Exit criteria:

- A reviewer can label a section consistently using the rubric.
- The same rubric can be used for dashboard, tests, and training data.

### 2. Trace Everything

Owner: system.

Deliverables:

- Store raw model response, raw output, normalized output, prompt, model, backend, tokens, latency, validation status.
- Expose traces through `/api/llm-calls`.
- Add dashboard view for failed calls and validation errors.

Exit criteria:

- Every accepted and rejected model attempt is inspectable.
- A bad generated section can be traced back to prompt, model, backend, and validator errors.

### 3. Human Review Loop

Owner: human + system.

Deliverables:

- Use `human_review_queue` for rejected sections.
- Add dashboard UI to compare source, model output, and corrected output.
- Store corrections in `translation_corrections`.
- Update cache only after correction is saved.

Exit criteria:

- Human corrections become structured data.
- Corrections can be exported as SFT/DPO training examples.

### 4. Strong Hard Validators

Owner: system.

Deliverables:

- Expand validators for numbers, dates, inline code, links, image links, tables, MDX components, frontmatter keys, code fences.
- Add language-specific script checks.
- Add glossary-required-term checks.
- Add tests using real bad outputs.

Exit criteria:

- Structural Validity Pass Rate can be measured.
- Known catastrophic failures are blocked before output files are written.

### 5. Quality Estimation Gate

Owner: system.

Deliverables:

- Add local QE scorer interface.
- Start with optional stub/offline mode.
- Integrate COMETKiwi or xCOMET when model/dependencies are selected.
- Store QE scores and issue spans.
- Define thresholds:
  - high: accept
  - middle: retry/fallback
  - low: human review

Exit criteria:

- Good-looking but semantically risky outputs no longer pass only because structure is valid.

### 6. Retry And Fallback Policy

Owner: system.

Deliverables:

- Retry failed sections with stricter prompt.
- Try alternate local model.
- Try lower temperature or deterministic decoding if backend supports it.
- Queue for human review after retry budget is exhausted.

Exit criteria:

- A single bad generation does not fail the whole run when a safe fallback exists.

### 7. Retrieval And Glossary Constraints

Owner: system.

Deliverables:

- Retrieve similar approved sections from translation cache/corrections.
- Build prompt context from translation memory.
- Enforce glossary terms with validator checks first.
- Later evaluate constrained decoding or placeholder protection.

Exit criteria:

- Repeated terms and repeated phrasing become consistent across posts.

### 8. Evaluation Set

Owner: human + system.

Deliverables:

- Freeze a held-out test set of blog sections.
- Add human references for key sections.
- Track validator pass rate, correction rate, MQM labels, and future COMET scores.
- Keep test data out of training data.

Exit criteria:

- Model or prompt changes can be compared without guessing.

### 9. Data Pipeline For Fine-Tuning

Owner: system.

Deliverables:

- Export accepted corrections as SFT JSONL.
- Export rejected-vs-corrected pairs as preference JSONL.
- Add deduplication and quality filters.
- Keep provenance: source file, section index, model, prompt version, reviewer, error labels.

Exit criteria:

- Training data is clean enough for LoRA/QLoRA experiments.

### 10. Model Adaptation

Owner: system.

Order:

1. Evaluate stronger base translation models.
2. Fine-tune with clean parallel/correction data using LoRA/QLoRA.
3. Add back-translation/self-training only with QE filtering.
4. Add DPO only after enough preference pairs exist.

Exit criteria:

- Fine-tuned model improves the frozen evaluation set without lowering validator pass rate.

## Near-Term Tasks

1. Add dashboard panels for active rubric, failed `llm_calls`, and open review queue.
2. Add correction editor API and UI.
3. Expand hard validators for numbers, dates, inline code, tables, and MDX components.
4. Add QE scorer abstraction with a disabled default implementation.
5. Export `translation_corrections` to SFT JSONL.
6. Build the first 100-section human evaluation set.

## Do Not Do Yet

- Do not start DPO before collecting preference pairs.
- Do not fine-tune on noisy generated translations.
- Do not optimize for BLEU alone.
- Do not treat validator pass as semantic correctness.
- Do not publish sections that fail hard validators.
