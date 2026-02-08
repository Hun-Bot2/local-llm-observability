import argparse
import sys
import os
from pathlib import Path
from tqdm import tqdm
from monitor_agent import MLOpsMonitor
from translation_agent import TranslationAgent

# 블로그 원본 경로
DEFAULT_BLOG_PATH = os.path.expanduser("~/hun-bot-blog/src/content/blog/ko")

def get_latest_file(source_dir):
    """
    지정된 폴더에서 '가장 최근에 수정된' MDX 파일 하나를 찾아 반환
    """
    source_path = Path(source_dir).resolve()
    # 모든 MDX 파일 검색
    all_files = list(source_path.rglob("*.mdx"))
    
    if not all_files:
        return None

    # 수정 시간(getmtime) 기준으로 정렬하여 가장 마지막 파일 선택
    latest_file = max(all_files, key=os.path.getmtime)
    return latest_file

def get_files_to_process(target_path_str, force_mode, is_last_mode):
    """
    target이 파일인지, 폴더인지, 아니면 '--last' 모드인지 판단
    """
    files = []

    # 1. [--last] 모드: 가장 최근 파일 1개 자동 선택
    if is_last_mode:
        print(f"[INFO] Looking for the most recently modified file in {DEFAULT_BLOG_PATH}...")
        latest_file = get_latest_file(DEFAULT_BLOG_PATH)
        if latest_file:
            print(f"[INFO] Found latest file: {latest_file.name}")
            files.append(latest_file)
        else:
            print(f"[ERROR] No MDX files found in {DEFAULT_BLOG_PATH}")
        return files

    # 2. 경로 처리 (파일 or 폴더)
    if target_path_str:
        # 입력이 있으면 그 경로를 사용
        if target_path_str.startswith("~"):
            target_path = Path(os.path.expanduser(target_path_str)).resolve()
        else:
            target_path = Path(target_path_str).resolve()
    else:
        # 입력이 없으면 기본 블로그 폴더 사용
        target_path = Path(DEFAULT_BLOG_PATH).resolve()
    
    if target_path.is_file():
        print(f"[INFO] Target is a single file: {target_path.name}")
        files.append(target_path)
        
    elif target_path.is_dir():
        print(f"[INFO] Target is a directory. Scanning: {target_path}")
        all_files = list(target_path.rglob("*.mdx"))
        
        if force_mode:
            files = all_files
            print(f"[INFO] Force Mode: Included all {len(files)} files.")
        else:
            # 번역 안 된 것만 필터링
            for file in all_files:
                en_path = Path(str(file).replace("/ko/", "/en/"))
                jp_path = Path(str(file).replace("/ko/", "/jp/"))
                if not en_path.exists() or not jp_path.exists():
                    files.append(file)
            print(f"[INFO] Found {len(files)} files to translate.")
            
    else:
        print(f"[ERROR] Path does not exist: {target_path}")

    return files

def main():
    parser = argparse.ArgumentParser(description="Hybrid Translation Orchestrator")
    
    # target을 Optional(선택)로 변경
    parser.add_argument("target", nargs="?", help="Specific file path OR Directory path")
    
    parser.add_argument("--force", action="store_true", help="Translate even if files exist")
    parser.add_argument("--last", action="store_true", help="Automatically process ONLY the most recently modified file")
    
    args = parser.parse_args()

    # 1. Init Agents
    monitor = MLOpsMonitor()
    translator = TranslationAgent(monitor)

    try:
        # 2. 작업할 파일 리스트 확보
        files_to_process = get_files_to_process(args.target, args.force, args.last)

        if not files_to_process:
            print("[INFO] No files to process.")
            return

        # 3. Execution
        print(f"\n[INFO] Starting Processing for {len(files_to_process)} file(s)...")
        
        pbar = tqdm(files_to_process, unit="file")
        
        for file_path in pbar:
            pbar.set_description(f"Processing {file_path.name}")
            
            try:
                translator.process_file(str(file_path))
            except Exception as e:
                print(f"\n[ERROR] processing {file_path.name}: {e}")
                continue

    except KeyboardInterrupt:
        print("\n[INFO] Stopped by user.")
    finally:
        monitor.close()
        print("\n[INFO] Done.")

if __name__ == "__main__":
    main()