import psycopg2
from psycopg2.extras import Json
import os
from dotenv import load_dotenv
from local_llm_observability.quality_policy import default_rubric_for

load_dotenv()

class DBManager:
    def __init__(self):
        self.conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            dbname=os.getenv("DB_NAME", "mlops"),
            user=os.getenv("DB_USER", "user"),
            password=os.getenv("DB_PASS", "password")
        )
        self.conn.autocommit = True
        self._ensure_runtime_tables()

    def _ensure_runtime_tables(self):
        with self.conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS translation_sections (
                    id SERIAL PRIMARY KEY,
                    run_id INT,
                    filename VARCHAR(255) NOT NULL,
                    section_index INT,
                    section_type VARCHAR(50) NOT NULL DEFAULT 'paragraph',
                    target_lang VARCHAR(10) NOT NULL,
                    model_name VARCHAR(100),
                    source_text TEXT NOT NULL,
                    translated_text TEXT NOT NULL,
                    input_tokens INT DEFAULT 0,
                    output_tokens INT DEFAULT 0,
                    latency_ms FLOAT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_translation_sections_run
                ON translation_sections(run_id);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_translation_sections_file
                ON translation_sections(filename);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_translation_sections_lang
                ON translation_sections(target_lang);
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS llm_calls (
                    id SERIAL PRIMARY KEY,
                    run_id INT,
                    filename TEXT,
                    section_index INT,
                    section_type TEXT,
                    target_lang VARCHAR(10),
                    backend TEXT,
                    endpoint TEXT,
                    model_name TEXT,
                    system_prompt TEXT,
                    user_prompt TEXT,
                    glossary_text TEXT,
                    raw_response JSONB,
                    raw_output TEXT,
                    normalized_output TEXT,
                    validation_passed BOOLEAN DEFAULT FALSE,
                    validation_errors JSONB DEFAULT '[]',
                    input_tokens INT DEFAULT 0,
                    output_tokens INT DEFAULT 0,
                    latency_ms FLOAT DEFAULT 0,
                    total_duration_ns BIGINT,
                    prompt_eval_duration_ns BIGINT,
                    eval_duration_ns BIGINT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_llm_calls_run
                ON llm_calls(run_id, created_at);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_llm_calls_validation
                ON llm_calls(validation_passed, target_lang);
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS run_events (
                    id SERIAL PRIMARY KEY,
                    run_id INT NOT NULL,
                    event_type VARCHAR(50) NOT NULL,
                    message TEXT NOT NULL,
                    details JSONB DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_run_events_run
                ON run_events(run_id, created_at);
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS translation_rubrics (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    target_lang VARCHAR(10) NOT NULL,
                    version TEXT NOT NULL,
                    rules JSONB NOT NULL,
                    weights JSONB DEFAULT '{}',
                    thresholds JSONB DEFAULT '{}',
                    active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(name, target_lang, version)
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_translation_rubrics_active
                ON translation_rubrics(target_lang, active);
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS translation_corrections (
                    id SERIAL PRIMARY KEY,
                    run_id INT,
                    llm_call_id INT,
                    filename TEXT NOT NULL,
                    section_index INT,
                    section_type TEXT,
                    target_lang VARCHAR(10) NOT NULL,
                    source_text TEXT NOT NULL,
                    model_output TEXT,
                    corrected_output TEXT NOT NULL,
                    error_types JSONB DEFAULT '[]',
                    human_scores JSONB DEFAULT '{}',
                    reviewer TEXT,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_translation_corrections_file
                ON translation_corrections(filename, target_lang);
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS human_review_queue (
                    id SERIAL PRIMARY KEY,
                    run_id INT,
                    llm_call_id INT,
                    filename TEXT NOT NULL,
                    section_index INT,
                    section_type TEXT,
                    target_lang VARCHAR(10) NOT NULL,
                    source_text TEXT NOT NULL,
                    model_output TEXT,
                    reason TEXT NOT NULL,
                    details JSONB DEFAULT '{}',
                    status VARCHAR(20) DEFAULT 'open',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_human_review_queue_status
                ON human_review_queue(status, target_lang, created_at);
            """)
            for lang in ("en", "jp"):
                self.upsert_translation_rubric(**default_rubric_for(lang))

    # 영어 단어장 저장
    def upsert_en(self, ko, en, type="common"):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO glossary_en (ko_term, en_term, type) 
                VALUES (%s, %s, %s)
                ON CONFLICT (ko_term) 
                DO UPDATE SET en_term = EXCLUDED.en_term, updated_at = CURRENT_TIMESTAMP;
            """, (ko, en, type))

    # 일본어 단어장 저장
    def upsert_jp(self, ko, jp, type="common"):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO glossary_jp (ko_term, jp_term, type) 
                VALUES (%s, %s, %s)
                ON CONFLICT (ko_term) 
                DO UPDATE SET jp_term = EXCLUDED.jp_term, updated_at = CURRENT_TIMESTAMP;
            """, (ko, jp, type))

    # 단어장 조회 (언어별로 따로 가져오기)
    def get_glossary(self, lang):
        table = "glossary_en" if lang == "en" else "glossary_jp"
        col = "en_term" if lang == "en" else "jp_term"
        
        with self.conn.cursor() as cur:
            # SQL Injection 방지를 위해 테이블명은 포맷팅하지 않고 로직으로 분기
            query = f"SELECT ko_term, {col} FROM {table}"
            cur.execute(query)
            return {row[0]: row[1] for row in cur.fetchall()}

    # ── Blog Posts ──

    def upsert_blog_post(self, filename, frontmatter):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO blog_posts (filename, title, description, pub_date, hero_image, tags, category, series, series_order)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (filename)
                DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    pub_date = EXCLUDED.pub_date,
                    hero_image = EXCLUDED.hero_image,
                    tags = EXCLUDED.tags,
                    category = EXCLUDED.category,
                    series = EXCLUDED.series,
                    series_order = EXCLUDED.series_order,
                    updated_at = CURRENT_TIMESTAMP;
            """, (
                filename,
                frontmatter.get("title"),
                frontmatter.get("description"),
                frontmatter.get("pubDate"),
                frontmatter.get("heroImage"),
                Json(frontmatter.get("tags", [])),
                frontmatter.get("category"),
                frontmatter.get("series"),
                frontmatter.get("seriesOrder"),
            ))

    # ── Translation Cache ──

    def upsert_cache(self, filename, section_type, section_index, content_hash, ko_text,
                     en_text=None, jp_text=None, model_name=None, embedding=None):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO translation_cache
                    (filename, section_type, section_index, content_hash, ko_text, en_text, jp_text, model_name, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (filename, section_index)
                DO UPDATE SET
                    section_type = EXCLUDED.section_type,
                    content_hash = EXCLUDED.content_hash,
                    ko_text = EXCLUDED.ko_text,
                    en_text = COALESCE(EXCLUDED.en_text, translation_cache.en_text),
                    jp_text = COALESCE(EXCLUDED.jp_text, translation_cache.jp_text),
                    model_name = COALESCE(EXCLUDED.model_name, translation_cache.model_name),
                    embedding = COALESCE(EXCLUDED.embedding, translation_cache.embedding),
                    updated_at = CURRENT_TIMESTAMP;
            """, (filename, section_type, section_index, content_hash, ko_text,
                  en_text, jp_text, model_name, embedding))

    def get_cached_sections(self, filename):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT section_index, section_type, content_hash, ko_text, en_text, jp_text
                FROM translation_cache
                WHERE filename = %s
                ORDER BY section_index;
            """, (filename,))
            columns = ["section_index", "section_type", "content_hash", "ko_text", "en_text", "jp_text"]
            return [dict(zip(columns, row)) for row in cur.fetchall()]

    def search_similar(self, embedding, exclude_filename=None, limit=3):
        with self.conn.cursor() as cur:
            if exclude_filename:
                cur.execute("""
                    SELECT filename, section_index, ko_text, en_text, jp_text,
                           1 - (embedding <=> %s::vector) AS similarity
                    FROM translation_cache
                    WHERE embedding IS NOT NULL AND filename != %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s;
                """, (embedding, exclude_filename, embedding, limit))
            else:
                cur.execute("""
                    SELECT filename, section_index, ko_text, en_text, jp_text,
                           1 - (embedding <=> %s::vector) AS similarity
                    FROM translation_cache
                    WHERE embedding IS NOT NULL
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s;
                """, (embedding, embedding, limit))
            columns = ["filename", "section_index", "ko_text", "en_text", "jp_text", "similarity"]
            return [dict(zip(columns, row)) for row in cur.fetchall()]

    # ── Pipeline Runs ──

    def insert_pipeline_run(self, trigger_type="manual"):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO pipeline_runs (trigger_type)
                VALUES (%s)
                RETURNING id;
            """, (trigger_type,))
            return cur.fetchone()[0]

    def update_pipeline_run(self, run_id, status, total_files=0, cached_sections=0,
                            new_sections=0, gpu_time_sec=0, estimated_cost=0):
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE pipeline_runs
                SET status = %s, total_files = %s, cached_sections = %s,
                    new_sections = %s, gpu_time_sec = %s, estimated_cost = %s,
                    finished_at = CURRENT_TIMESTAMP
                WHERE id = %s;
            """, (status, total_files, cached_sections, new_sections,
                  gpu_time_sec, estimated_cost, run_id))

    def insert_run_event(self, run_id, event_type, message, details=None):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO run_events (run_id, event_type, message, details)
                VALUES (%s, %s, %s, %s)
                RETURNING id, created_at;
            """, (run_id, event_type, message, Json(details or {})))
            event_id, created_at = cur.fetchone()
            return {
                "id": event_id,
                "run_id": run_id,
                "event_type": event_type,
                "message": message,
                "details": details or {},
                "created_at": created_at.isoformat(),
            }

    def get_run_events(self, run_id, after_id=0):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT id, run_id, event_type, message, details, created_at
                FROM run_events
                WHERE run_id = %s AND id > %s
                ORDER BY id;
            """, (run_id, after_id))
            columns = ["id", "run_id", "event_type", "message", "details", "created_at"]
            events = []
            for row in cur.fetchall():
                event = dict(zip(columns, row))
                event["created_at"] = event["created_at"].isoformat()
                events.append(event)
            return events

    def get_pipeline_run(self, run_id):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT id, trigger_type, status, total_files, cached_sections, new_sections,
                       gpu_time_sec, estimated_cost, started_at, finished_at
                FROM pipeline_runs
                WHERE id = %s;
            """, (run_id,))
            row = cur.fetchone()
            if not row:
                return None
            columns = [
                "id", "trigger_type", "status", "total_files", "cached_sections",
                "new_sections", "gpu_time_sec", "estimated_cost", "started_at", "finished_at",
            ]
            run = dict(zip(columns, row))
            run["started_at"] = run["started_at"].isoformat() if run["started_at"] else None
            run["finished_at"] = run["finished_at"].isoformat() if run["finished_at"] else None
            return run

    def get_recent_pipeline_runs(self, limit=20):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT id, trigger_type, status, total_files, cached_sections, new_sections,
                       gpu_time_sec, estimated_cost, started_at, finished_at
                FROM pipeline_runs
                ORDER BY started_at DESC
                LIMIT %s;
            """, (limit,))
            columns = [
                "id", "trigger_type", "status", "total_files", "cached_sections",
                "new_sections", "gpu_time_sec", "estimated_cost", "started_at", "finished_at",
            ]
            runs = []
            for row in cur.fetchall():
                run = dict(zip(columns, row))
                run["started_at"] = run["started_at"].isoformat() if run["started_at"] else None
                run["finished_at"] = run["finished_at"].isoformat() if run["finished_at"] else None
                runs.append(run)
            return runs

    # ── Human-Owned Quality Policy ──

    def upsert_translation_rubric(self, name, target_lang, version, rules,
                                  weights=None, thresholds=None, active=True):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO translation_rubrics
                    (name, target_lang, version, rules, weights, thresholds, active)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (name, target_lang, version)
                DO UPDATE SET
                    rules = EXCLUDED.rules,
                    weights = EXCLUDED.weights,
                    thresholds = EXCLUDED.thresholds,
                    active = EXCLUDED.active,
                    updated_at = CURRENT_TIMESTAMP;
            """, (
                name, target_lang, version, Json(rules), Json(weights or {}),
                Json(thresholds or {}), active,
            ))

    def get_active_translation_rubric(self, target_lang):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, target_lang, version, rules, weights, thresholds, active, created_at, updated_at
                FROM translation_rubrics
                WHERE target_lang = %s AND active = TRUE
                ORDER BY updated_at DESC
                LIMIT 1;
            """, (target_lang,))
            row = cur.fetchone()
            if not row:
                return None
            columns = [
                "id", "name", "target_lang", "version", "rules", "weights",
                "thresholds", "active", "created_at", "updated_at",
            ]
            rubric = dict(zip(columns, row))
            rubric["created_at"] = rubric["created_at"].isoformat() if rubric["created_at"] else None
            rubric["updated_at"] = rubric["updated_at"].isoformat() if rubric["updated_at"] else None
            return rubric

    def insert_human_review_item(self, run_id, filename, section_index, section_type,
                                 target_lang, source_text, model_output, reason,
                                 details=None, llm_call_id=None):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO human_review_queue
                    (run_id, llm_call_id, filename, section_index, section_type,
                     target_lang, source_text, model_output, reason, details)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (
                run_id, llm_call_id, filename, section_index, section_type,
                target_lang, source_text, model_output, reason, Json(details or {}),
            ))
            return cur.fetchone()[0]

    def get_human_review_queue(self, status="open", target_lang=None, limit=50):
        with self.conn.cursor() as cur:
            if target_lang:
                cur.execute("""
                    SELECT id, run_id, llm_call_id, filename, section_index, section_type,
                           target_lang, source_text, model_output, reason, details, status, created_at
                    FROM human_review_queue
                    WHERE status = %s AND target_lang = %s
                    ORDER BY created_at DESC
                    LIMIT %s;
                """, (status, target_lang, limit))
            else:
                cur.execute("""
                    SELECT id, run_id, llm_call_id, filename, section_index, section_type,
                           target_lang, source_text, model_output, reason, details, status, created_at
                    FROM human_review_queue
                    WHERE status = %s
                    ORDER BY created_at DESC
                    LIMIT %s;
                """, (status, limit))
            columns = [
                "id", "run_id", "llm_call_id", "filename", "section_index",
                "section_type", "target_lang", "source_text", "model_output",
                "reason", "details", "status", "created_at",
            ]
            rows = []
            for row in cur.fetchall():
                item = dict(zip(columns, row))
                item["created_at"] = item["created_at"].isoformat() if item["created_at"] else None
                rows.append(item)
            return rows

    def insert_translation_correction(self, filename, section_index, section_type,
                                      target_lang, source_text, corrected_output,
                                      model_output=None, error_types=None,
                                      human_scores=None, reviewer=None, notes=None,
                                      run_id=None, llm_call_id=None):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO translation_corrections
                    (run_id, llm_call_id, filename, section_index, section_type,
                     target_lang, source_text, model_output, corrected_output,
                     error_types, human_scores, reviewer, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (
                run_id, llm_call_id, filename, section_index, section_type,
                target_lang, source_text, model_output, corrected_output,
                Json(error_types or []), Json(human_scores or {}), reviewer, notes,
            ))
            return cur.fetchone()[0]

    def get_recent_llm_calls(self, run_id=None, validation_passed=None, limit=50):
        with self.conn.cursor() as cur:
            filters = []
            params = []
            if run_id is not None:
                filters.append("run_id = %s")
                params.append(run_id)
            if validation_passed is not None:
                filters.append("validation_passed = %s")
                params.append(validation_passed)
            where = f"WHERE {' AND '.join(filters)}" if filters else ""
            params.append(limit)
            cur.execute(f"""
                SELECT id, run_id, filename, section_index, section_type, target_lang,
                       backend, endpoint, model_name, validation_passed,
                       validation_errors, input_tokens, output_tokens, latency_ms, created_at
                FROM llm_calls
                {where}
                ORDER BY created_at DESC
                LIMIT %s;
            """, params)
            columns = [
                "id", "run_id", "filename", "section_index", "section_type",
                "target_lang", "backend", "endpoint", "model_name",
                "validation_passed", "validation_errors", "input_tokens",
                "output_tokens", "latency_ms", "created_at",
            ]
            rows = []
            for row in cur.fetchall():
                item = dict(zip(columns, row))
                item["created_at"] = item["created_at"].isoformat() if item["created_at"] else None
                rows.append(item)
            return rows

    # ── Translation Quality ──

    def insert_quality_score(self, filename, target_lang, structural_score, length_score,
                             semantic_score, glossary_score, composite_score, passed, run_id=None):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO translation_quality
                    (filename, target_lang, run_id, structural_score, length_score,
                     semantic_score, glossary_score, composite_score, passed)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
            """, (filename, target_lang, run_id, structural_score, length_score,
                  semantic_score, glossary_score, composite_score, passed))

    def insert_translation_section(self, run_id, filename, section_index, section_type, target_lang,
                                   model_name, source_text, translated_text,
                                   input_tokens=0, output_tokens=0, latency_ms=0):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO translation_sections
                    (run_id, filename, section_index, section_type, target_lang, model_name,
                     source_text, translated_text, input_tokens, output_tokens, latency_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """, (
                run_id, filename, section_index, section_type, target_lang, model_name,
                source_text, translated_text, input_tokens, output_tokens, latency_ms,
            ))

    def insert_llm_call(self, run_id, filename, section_index, section_type, target_lang,
                        backend, endpoint, model_name, system_prompt, user_prompt,
                        glossary_text, raw_response, raw_output, normalized_output,
                        validation_passed, validation_errors=None, input_tokens=0,
                        output_tokens=0, latency_ms=0, total_duration_ns=None,
                        prompt_eval_duration_ns=None, eval_duration_ns=None):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO llm_calls
                    (run_id, filename, section_index, section_type, target_lang,
                     backend, endpoint, model_name, system_prompt, user_prompt,
                     glossary_text, raw_response, raw_output, normalized_output,
                     validation_passed, validation_errors, input_tokens, output_tokens,
                     latency_ms, total_duration_ns, prompt_eval_duration_ns, eval_duration_ns)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                     %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (
                run_id, filename, section_index, section_type, target_lang,
                backend, endpoint, model_name, system_prompt, user_prompt,
                glossary_text, Json(raw_response or {}), raw_output, normalized_output,
                validation_passed, Json(validation_errors or []), input_tokens,
                output_tokens, latency_ms, total_duration_ns,
                prompt_eval_duration_ns, eval_duration_ns,
            ))
            return cur.fetchone()[0]

    # ── Weekly Reports ──

    def insert_weekly_report(self, week_start, week_end, posts_translated, total_sections,
                             cached_sections, new_sections, avg_quality_en, avg_quality_jp,
                             total_gpu_time_sec, total_cost, pipeline_runs, cache_hit_rate):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO weekly_reports
                    (week_start, week_end, posts_translated, total_sections, cached_sections,
                     new_sections, avg_quality_en, avg_quality_jp, total_gpu_time_sec,
                     total_cost, pipeline_runs, cache_hit_rate)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (week_start)
                DO UPDATE SET
                    posts_translated = EXCLUDED.posts_translated,
                    total_sections = EXCLUDED.total_sections,
                    cached_sections = EXCLUDED.cached_sections,
                    new_sections = EXCLUDED.new_sections,
                    avg_quality_en = EXCLUDED.avg_quality_en,
                    avg_quality_jp = EXCLUDED.avg_quality_jp,
                    total_gpu_time_sec = EXCLUDED.total_gpu_time_sec,
                    total_cost = EXCLUDED.total_cost,
                    pipeline_runs = EXCLUDED.pipeline_runs,
                    cache_hit_rate = EXCLUDED.cache_hit_rate;
            """, (week_start, week_end, posts_translated, total_sections,
                  cached_sections, new_sections, avg_quality_en, avg_quality_jp,
                  total_gpu_time_sec, total_cost, pipeline_runs, cache_hit_rate))

    def get_pipeline_runs_between(self, start_date, end_date):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT id, status, total_files, cached_sections, new_sections,
                       gpu_time_sec, estimated_cost, started_at
                FROM pipeline_runs
                WHERE started_at >= %s AND started_at < %s;
            """, (start_date, end_date))
            columns = ["id", "status", "total_files", "cached_sections", "new_sections",
                        "gpu_time_sec", "estimated_cost", "started_at"]
            return [dict(zip(columns, row)) for row in cur.fetchall()]

    def get_quality_scores_between(self, start_date, end_date):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT filename, target_lang, composite_score, passed, created_at
                FROM translation_quality
                WHERE created_at >= %s AND created_at < %s;
            """, (start_date, end_date))
            columns = ["filename", "target_lang", "composite_score", "passed", "created_at"]
            return [dict(zip(columns, row)) for row in cur.fetchall()]

    def close(self):
        self.conn.close()
