import json
import ollama
import re
from local_llm_observability.db.db_manager import DBManager

class GlossaryMigrator:
    def __init__(self):
        # DBManager 내부의 .env 설정이 mlops_logs를 가리키고 있어야 합니다.
        self.db = DBManager()
        self.model = "qwen2.5:14b"

    def fetch_raw_data(self):
        with self.db.conn.cursor() as cur:
            # 951개의 원본 데이터를 가져옵니다.
            cur.execute("SELECT ko_term, jp_term FROM glossary_jp")
            return cur.fetchall()

    def refine_batch(self, batch):
        """LLM을 필터로 사용하여 노이즈를 제거합니다."""
        items_text = "\n".join([f"- {item[0]} : {item[1]}" for item in batch])
        
        prompt = f"""
        Extract only technical terms, frameworks, or key concepts. 
        Exclude full sentences, long descriptions, or conversational noise.
        Example of BAD: '결과로 포트폴리오 완성', '오지에서 적용해보기'
        Example of GOOD: 'Golang', 'P2P Network', '에지 추론'

        Return ONLY a JSON list: [{{ "ko": "...", "jp": "...", "type": "tech" }}]

        --- LIST ---
        {items_text}
        """
        
        try:
            res = ollama.chat(model=self.model, messages=[{'role': 'user', 'content': prompt}])
            content = res['message']['content']
            match = re.search(r"\[.*\]", content, re.DOTALL)
            return json.loads(match.group(0)) if match else []
        except:
            return []

    def run(self):
        raw_data = self.fetch_raw_data()
        total = len(raw_data)
        batch_size = 25
        
        print(f"Starting migration: {total} items found in glossary_jp.")

        for i in range(0, total, batch_size):
            batch = raw_data[i : i + batch_size]
            refined_items = self.refine_batch(batch)
            
            for item in refined_items:
                with self.db.conn.cursor() as cur:
                    # 정제된 테이블에 삽입 (중복 시 업데이트)
                    cur.execute("""
                        INSERT INTO glossary_jp_refined (ko_term, jp_term, type)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (ko_term) DO UPDATE SET jp_term = EXCLUDED.jp_term;
                    """, (item['ko'], item['jp'], item.get('type', 'tech')))
            
            print(f"Progress: {min(i + batch_size, total)} / {total}")

        self.db.close()
        print("Migration and Refining completed successfully.")

if __name__ == "__main__":
    migrator = GlossaryMigrator()
    migrator.run()