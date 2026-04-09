import psycopg2
from psycopg2.extras import Json
import os
from dotenv import load_dotenv

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
