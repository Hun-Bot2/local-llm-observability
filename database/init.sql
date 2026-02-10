CREATE TABLE IF NOT EXISTS translation_logs (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    model_name VARCHAR(50),
    source_lang VARCHAR(10),
    target_lang VARCHAR(10),
    input_length INT,
    output_length INT,
    latency_ms FLOAT,
    tokens_per_sec FLOAT,
    similarity_score FLOAT,
    input_text TEXT,
    output_text TEXT
);

CREATE INDEX idx_model ON translation_logs(model_name);
CREATE INDEX idx_timestamp ON translation_logs(timestamp);

-- 영어 전용 단어장
CREATE TABLE IF NOT EXISTS glossary_en (
    id SERIAL PRIMARY KEY,
    ko_term VARCHAR(255) UNIQUE NOT NULL,
    en_term VARCHAR(255) NOT NULL,
    type VARCHAR(50) DEFAULT 'common',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 일본어 전용 단어장
CREATE TABLE IF NOT EXISTS glossary_jp (
    id SERIAL PRIMARY KEY,
    ko_term VARCHAR(255) UNIQUE NOT NULL,
    jp_term VARCHAR(255) NOT NULL,
    type VARCHAR(50) DEFAULT 'common',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 감사 로그 (어느 언어로 번역하다 생긴 로그인지 target_lang 추가)
CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    target_lang VARCHAR(10), -- 'en' or 'jp'
    filename VARCHAR(255),
    paragraph_index INT,
    original_text TEXT,
    llm_reasoning JSONB,
    final_translation TEXT,
    model_name VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);