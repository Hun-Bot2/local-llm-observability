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

    def log_audit(self, target_lang, filename, p_idx, original, reasoning, final, model):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO audit_logs (target_lang, filename, paragraph_index, original_text, llm_reasoning, final_translation, model_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (target_lang, filename, p_idx, original, Json(reasoning), final, model))

    def close(self):
        self.conn.close()