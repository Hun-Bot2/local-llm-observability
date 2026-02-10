import os
import re
import glob
import json
import frontmatter
import ollama
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from src.db.db_manager import DBManager

BLOG_PATH = os.path.expanduser("~/hun-bot-blog/src/content/blog/ko/**/*.mdx")
MODEL_EN = "gemma2:9b"
MODEL_JP = "qwen2.5:14b"

console = Console()

def extract_en(text):
    """한국어 -> 영어 (프롬프트 유지 + 정규식 파싱 적용)"""

    prompt = f"""
    You are a Technical Editor for an English Tech Blog.
    Analyze the provided Korean text and extract key technical terms, translating them into English based on the following Strict Rules:

    [Rules]
    1. **Official Casing**: Respect the official capitalization of libraries/frameworks (e.g., 'Next.js', 'React', 'PostgreSQL', 'iOS'). Do NOT lowercase them.
    2. **Developer Slang**: Translate Korean developer slang into natural English idioms.
       - Example: '삽질' -> 'trial and error' OR 'digging into'
       - Example: '가성비' -> 'cost-effectiveness'
    3. **Compound Nouns**: Translate technical compound words naturally.
       - Example: '로그인 로직' -> 'login logic'
       - Example: '동적 라우팅' -> 'dynamic routing'
    4. **Exclusion**: Do NOT extract too common words like '데이터(data)', '함수(function)', '변수(variable)' unless they are part of a specific concept.

    [Negative Constraints]
    - NEVER translate URLs, file paths, variable names, or function names.
    - Keep source code and strict commands verbatim.
    
    Output JSON list ONLY:
    [
      {{ "ko": "삽질", "en": "trial and error", "type": "slang" }},
      {{ "ko": "Next.js", "en": "Next.js", "type": "tech" }},
      {{ "ko": "동적 라우팅", "en": "dynamic routing", "type": "concept" }}
    ]

    --- TEXT ---
    {text}
    """
    
    try:
        res = ollama.chat(model=MODEL_EN, messages=[{'role': 'user', 'content': prompt}])
        content = res['message']['content']
        
        # 🛠️ [수정된 부분] 단순 replace 대신 강력한 정규식(Regex) 사용
        # Gemma가 앞뒤로 무슨 말을 붙이든, 대괄호 [...] 로 감싸진 리스트만 찾아냅니다.
        match = re.search(r"\[.*\]", content, re.DOTALL)
        
        if match:
            json_str = match.group(0) # 찾은 JSON 문자열
            return json.loads(json_str)
        else:
            # JSON 리스트 형태를 아예 못 찾은 경우
            # console.print(f"[red] [EN] JSON 패턴 발견 실패: {content[:50]}...[/red]") 
            return []

    except Exception as e:
        # JSON 문법이 깨졌거나 기타 에러
        # console.print(f"[red] [EN] 파싱 에러: {e}[/red]")
        return []
    
def extract_jp(text):
    """한국어 -> 일본어 (기술 용어 영어 유지)"""
    prompt = f"""
    Analyze the Korean technical text.
    Extract key technical terms and translate them to Japanese following these strict rules:

    [Translation Rules]
    1. **Tech Stacks & Proper Nouns**: KEEP strictly in English (e.g., 'Golang', 'LLM API', 'Python', 'AWS', 'JSON'). **Do NOT** convert these to Katakana.
    2. **General Loanwords**: Use Katakana for general English concepts (e.g., '로직' -> 'ロジック', '서버' -> 'サーバー').
    3. **Korean Concepts**: Translate to natural Japanese.
    [Negative Constraints]
    - NEVER translate URLs, file paths, variable names, or function names.
    - Keep source code and strict commands verbatim.

    Output JSON list ONLY: 
    [ 
      {{ "ko": "Golang", "jp": "Golang", "type": "tech" }},
      {{ "ko": "삽질", "jp": "試行錯誤", "type": "idiom" }}
    ]

    --- TEXT ---
    {text}
    """
    try:
        res = ollama.chat(model=MODEL_JP, messages=[{'role': 'user', 'content': prompt}])
        return json.loads(res['message']['content'].replace("```json", "").replace("```", "").strip())
    except: return []

def main():
    console.print("[bold green] Separated Language Pipeline Started[/bold green]")
    db = DBManager()
    files = glob.glob(BLOG_PATH, recursive=True)
    console.print(f"[cyan] 검색된 파일 개수: {len(files)}개[/cyan]")
    
    # 테이블 2개 생성 (영어용, 일본어용)
    table_en = Table(title="English Glossary Updates")
    table_en.add_column("File", style="dim")
    table_en.add_column("Korean", style="magenta")
    table_en.add_column("English", style="green")

    table_jp = Table(title="Japanese Glossary Updates")
    table_jp.add_column("File", style="dim")
    table_jp.add_column("Korean", style="magenta")
    table_jp.add_column("Japanese", style="cyan")

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
        task = progress.add_task("Processing...", total=len(files))

        for file_path in files:
            filename = os.path.basename(file_path)
            with open(file_path, "r", encoding="utf-8") as f:
                content = frontmatter.load(f).content

            # 1. 영어 처리
            progress.update(task, description=f"Analyzing {filename} (Gemma)...")
            items_en = extract_en(content)
            for item in items_en:
                db.upsert_en(item['ko'], item['en'], item.get('type', 'common'))
                table_en.add_row(filename, item['ko'], item['en'])

            # 2. 일본어 처리
            progress.update(task, description=f"Analyzing {filename} (Qwen)...")
            items_jp = extract_jp(content)
            for item in items_jp:
                db.upsert_jp(item['ko'], item['jp'], item.get('type', 'common'))
                table_jp.add_row(filename, item['ko'], item['jp'])
            
            progress.advance(task)

    # 결과 따로 출력
    console.print("\n")
    console.print(table_en)
    console.print("\n")
    console.print(table_jp)
    
    db.close()

if __name__ == "__main__":
    main()