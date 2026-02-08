import time
import re
from pathlib import Path
import ollama
from monitor_agent import MLOpsMonitor

# --- Configuration: System Prompts ---
SYSTEM_PROMPTS = {
    "EN": """
    You are a skilled Tech Blog Translator. 
    Translate the Korean text into natural, professional English for a developer audience.

    [Critical Rules]
    1. **Tone**: Casual but professional (DevLog style). Use "I" for the first person.
    2. **Technical Terms**: Keep terms like 'Local LLM', 'vscode', 'commit & push', 'terminal' in English.
    3. **Tags Handling**: If the input is a list of tags (e.g., ['A', 'B']), translate the words inside but KEEP the ['...'] format strictly.
    4. **Formatting**: Preserve all Markdown formatting.
    """,
    "JP": """
    あなたはプロの技術ブロガーです。韓国語の技術ブログを日本のエンジニア向けに自然な日本語へ翻訳してください。

    [Critical Rules]
    1. **Tone**: Polite but technical (「です・ます」調).
    2. **Technical Terms**: Use standard Katakana or English (e.g., Local LLM, vscode).
    3. **Tags Handling**: If the input is a list of tags (e.g., ['A', 'B']), translate the words inside but KEEP the ['...'] format strictly.
    4. **Formatting**: Markdownの形式を崩さないでください。
    """
}

# 성능 최적화: 일본어 모델을 14B -> 7B로 변경 (렉 방지)
MODELS = {
    "EN": "gemma2:9b",
    "JP": "qwen2.5:7b" 
}

class TranslationAgent:
    def __init__(self, monitor: MLOpsMonitor):
        self.monitor = monitor

    def _call_llm(self, text, target_lang, is_metadata=False, is_tags=False):
        """
        LLM 호출 및 모니터링 로그 적재
        is_tags: True일 경우 태그 리스트 포맷 유지를 위한 특별 지시 추가
        """
        model_name = MODELS.get(target_lang, "gemma2:9b")
        system_prompt = SYSTEM_PROMPTS.get(target_lang, "")
        
        # 프롬프트 동적 조정
        if is_tags:
            system_prompt += "\nIMPORTANT: The input is a list of tags. Translate the terms but output ONLY the Python-style list format: ['Tag1', 'Tag2']. Do not explain."
        elif is_metadata:
            system_prompt += "\nTranslate this short metadata text accurately. Keep it concise."

        print(f"   [Inference] {model_name} -> {target_lang} ({'Tags' if is_tags else ('Metadata' if is_metadata else 'Body')})...")
        start_time = time.time()
        
        response = ollama.chat(model=model_name, messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': text},
        ])
        
        end_time = time.time()
        result_text = response['message']['content'].strip()
        
        # 태그 번역 시 불필요한 마크다운 제거 (가끔 ```json ... ``` 이렇게 줄 때가 있음)
        if is_tags:
            result_text = result_text.replace("```json", "").replace("```", "").strip()

        # Metrics Calculation
        latency_ms = (end_time - start_time) * 1000
        eval_duration = response.get('eval_duration', 0)
        eval_count = response.get('eval_count', 0)
        tps = eval_count / (eval_duration / 1e9) if eval_duration > 0 else 0
        
        # DB Logging
        self.monitor.log_inference(
            model=model_name,
            src_lang="KO",
            tgt_lang=target_lang,
            input_text=text,
            output_text=result_text,
            latency=latency_ms,
            tps=tps,
            score=0.95
        )

        # 메모리 즉시 해제 (렉 방지 핵심)
        ollama.generate(model=model_name, keep_alive=0)
        
        return result_text

    def _translate_frontmatter(self, raw_frontmatter, target_lang):
        new_frontmatter = raw_frontmatter
        
        # 1. Title 번역
        title_match = re.search(r"title:\s*['\"](.*?)['\"]", raw_frontmatter)
        if title_match:
            original_title = title_match.group(1)
            translated_title = self._call_llm(original_title, target_lang, is_metadata=True)
            # 단순 replace는 본문에 같은 단어가 있을 때 위험하므로, 앞부분(Frontmatter) 내에서만 교체한다고 가정
            new_frontmatter = new_frontmatter.replace(f"'{original_title}'", f"'{translated_title}'")

        # 2. Description 번역
        desc_match = re.search(r"description:\s*['\"](.*?)['\"]", raw_frontmatter)
        if desc_match:
            original_desc = desc_match.group(1)
            translated_desc = self._call_llm(original_desc, target_lang, is_metadata=True)
            new_frontmatter = new_frontmatter.replace(f"'{original_desc}'", f"'{translated_desc}'")

        # 3. Tags 번역
        # tags: ['A', 'B', 'C'] 패턴을 찾습니다.
        tags_match = re.search(r"tags:\s*(\[.*?\])", raw_frontmatter)
        if tags_match:
            original_tags_str = tags_match.group(1) # ['Local LLM', '자동 번역', '블로그']
            translated_tags_str = self._call_llm(original_tags_str, target_lang, is_tags=True)
            
            # 번역 결과가 리스트 형식이 깨졌을 경우를 대비해 원본 유지 (안전장치)
            if "[" in translated_tags_str and "]" in translated_tags_str:
                new_frontmatter = new_frontmatter.replace(original_tags_str, translated_tags_str)
            else:
                print(f"   [Warning] Tags translation format error. Keeping original tags.")

        return new_frontmatter

    def process_file(self, file_path_str):
        path = Path(file_path_str)
        if not path.exists():
            print(f"[Error] File not found: {path}")
            return

        print(f"Processing Post: {path.name}")
        
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        parts = content.split('---', 2)
        
        if len(parts) < 3:
            print("[Warning] No Frontmatter detected. Translating entire content.")
            frontmatter = ""
            body = content
        else:
            frontmatter = parts[1]
            body = parts[2]

        for lang in ["EN", "JP"]:
            print(f"\n--- Starting {lang} Translation ---")
            
            translated_frontmatter = self._translate_frontmatter(frontmatter, lang) if frontmatter else ""
            translated_body = self._call_llm(body.strip(), lang)
            
            final_content = f"---{translated_frontmatter}---\n\n{translated_body}\n"
            
            if "/ko/" in str(path):
                target_path_str = str(path).replace("/ko/", f"/{lang.lower()}/")
            else:
                target_path_str = str(path.parent / lang.lower() / path.name)

            target_path = Path(target_path_str)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(final_content)
            
            print(f"[Saved] {target_path}")