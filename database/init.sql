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