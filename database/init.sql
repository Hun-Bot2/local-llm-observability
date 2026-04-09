-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- =============================================
-- Glossary Tables (existing, unchanged)
-- =============================================

CREATE TABLE IF NOT EXISTS glossary_en (
    id SERIAL PRIMARY KEY,
    ko_term VARCHAR(255) UNIQUE NOT NULL,
    en_term VARCHAR(255) NOT NULL,
    type VARCHAR(50) DEFAULT 'common',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS glossary_jp (
    id SERIAL PRIMARY KEY,
    ko_term VARCHAR(255) UNIQUE NOT NULL,
    jp_term VARCHAR(255) NOT NULL,
    type VARCHAR(50) DEFAULT 'common',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS glossary_jp_refined (
    id SERIAL PRIMARY KEY,
    ko_term VARCHAR(255) UNIQUE NOT NULL,
    jp_term VARCHAR(255) NOT NULL,
    type VARCHAR(50),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- Blog Posts — MDX frontmatter registry
-- =============================================

CREATE TABLE IF NOT EXISTS blog_posts (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(255) UNIQUE NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    pub_date DATE,
    hero_image TEXT,
    tags JSONB DEFAULT '[]',
    category VARCHAR(100),
    series VARCHAR(255),
    series_order INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_blog_posts_category ON blog_posts(category);
CREATE INDEX idx_blog_posts_series ON blog_posts(series);

-- =============================================
-- Translation Cache — paragraph-level with embeddings
-- =============================================

CREATE TABLE IF NOT EXISTS translation_cache (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    section_type VARCHAR(50) NOT NULL DEFAULT 'paragraph',
    section_index INT NOT NULL,
    content_hash CHAR(64) NOT NULL,
    ko_text TEXT NOT NULL,
    en_text TEXT,
    jp_text TEXT,
    model_name VARCHAR(100),
    embedding vector(768),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(filename, section_index)
);

CREATE INDEX idx_cache_filename ON translation_cache(filename);
CREATE INDEX idx_cache_hash ON translation_cache(content_hash);
CREATE INDEX idx_cache_embedding ON translation_cache USING ivfflat (embedding vector_cosine_ops);

-- =============================================
-- Translation Quality — per-file scoring
-- =============================================

CREATE TABLE IF NOT EXISTS translation_quality (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    target_lang VARCHAR(10) NOT NULL,
    run_id INT,
    structural_score FLOAT,
    length_score FLOAT,
    semantic_score FLOAT,
    glossary_score FLOAT,
    composite_score FLOAT,
    passed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_quality_filename ON translation_quality(filename);
CREATE INDEX idx_quality_run ON translation_quality(run_id);

-- =============================================
-- Translation Sections — per-section inference metrics
-- =============================================

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

CREATE INDEX idx_translation_sections_run ON translation_sections(run_id);
CREATE INDEX idx_translation_sections_file ON translation_sections(filename);
CREATE INDEX idx_translation_sections_lang ON translation_sections(target_lang);

-- =============================================
-- Pipeline Runs — execution tracking
-- =============================================

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id SERIAL PRIMARY KEY,
    trigger_type VARCHAR(50) NOT NULL DEFAULT 'manual',
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    total_files INT DEFAULT 0,
    cached_sections INT DEFAULT 0,
    new_sections INT DEFAULT 0,
    gpu_time_sec FLOAT DEFAULT 0,
    estimated_cost FLOAT DEFAULT 0,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP
);

CREATE INDEX idx_pipeline_status ON pipeline_runs(status);

-- =============================================
-- Weekly Reports — automated analytics
-- =============================================

CREATE TABLE IF NOT EXISTS weekly_reports (
    id SERIAL PRIMARY KEY,
    week_start DATE NOT NULL,
    week_end DATE NOT NULL,
    posts_translated INT DEFAULT 0,
    total_sections INT DEFAULT 0,
    cached_sections INT DEFAULT 0,
    new_sections INT DEFAULT 0,
    avg_quality_en FLOAT,
    avg_quality_jp FLOAT,
    total_gpu_time_sec FLOAT DEFAULT 0,
    total_cost FLOAT DEFAULT 0,
    pipeline_runs INT DEFAULT 0,
    cache_hit_rate FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(week_start)
);

CREATE INDEX idx_weekly_reports_week ON weekly_reports(week_start);
