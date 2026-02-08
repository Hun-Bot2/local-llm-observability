import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

class MLOpsMonitor:
    def __init__(self):
        self.db_config = {
            "dbname": os.getenv("DB_NAME"),
            "user": os.getenv("DB_USER"),
            "password": os.getenv("DB_PASS"),
            "host": os.getenv("DB_HOST"),
            "port": "5432"
        }
        self.conn = None
        self._connect()

    def _connect(self):
        try:
            self.conn = psycopg2.connect(**self.db_config)
        except Exception as e:
            print(f"[Monitor Error] DB Connection failed: {e}")

    def log_inference(self, model, src_lang, tgt_lang, input_text, output_text, latency, tps, score=0.0):
        if not self.conn:
            self._connect()
            if not self.conn:
                return

        query = """
            INSERT INTO translation_logs 
            (model_name, source_lang, target_lang, input_length, output_length, latency_ms, tokens_per_sec, similarity_score, input_text, output_text)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (
                    model, src_lang, tgt_lang, 
                    len(input_text), len(output_text), 
                    latency, tps, score, 
                    input_text, output_text
                ))
                self.conn.commit()
            print(f"   [DB Log] Saved: {model} | {latency:.2f}ms | {tps:.2f} TPS")
        except Exception as e:
            print(f"[Monitor Error] Failed to insert log: {e}")
            self.conn.rollback()

    def close(self):
        if self.conn:
            self.conn.close()