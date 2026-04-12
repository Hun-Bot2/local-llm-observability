"""V2 incremental translation runner.

This script scans for missing/stale translations first, then runs the existing
translator only for files that need work. It defaults to dry-run for safety.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from local_llm_observability.blog_scanner import DEFAULT_LANG_DIRS, DEFAULT_LANGS, DEFAULT_LAYOUT, DEFAULT_SOURCE_DIR, posts_needing_translation, scan_blog_posts
from local_llm_observability.translator import OLLAMA_LOCAL_URL, Translator


def main() -> None:
    parser = argparse.ArgumentParser(description="Translate only missing/stale Korean MDX posts")
    parser.add_argument(
        "--source-dir",
        default=DEFAULT_SOURCE_DIR,
        help=f"Directory containing Korean source .mdx files (default: {DEFAULT_SOURCE_DIR})",
    )
    parser.add_argument("--langs", nargs="+", default=list(DEFAULT_LANGS), choices=list(DEFAULT_LANGS))
    parser.add_argument("--layout", choices=["suffix", "mirror"], default=DEFAULT_LAYOUT)
    parser.add_argument("--en-dir", default=DEFAULT_LANG_DIRS["en"], help="English output root")
    parser.add_argument("--jp-dir", default=DEFAULT_LANG_DIRS["jp"], help="Japanese output root")
    parser.add_argument("--en-model", default="gemma4:latest", help="Local/worker model name for English")
    parser.add_argument("--jp-model", default="qwen3:14b", help="Local/worker model name for Japanese")
    parser.add_argument("--limit", type=int, help="Translate only the first N pending posts")
    parser.add_argument("--only", help="Translate only posts whose relative path or filename contains this text")
    parser.add_argument("--changed-only", action="store_true", help="Only translate source files changed since --since-ref")
    parser.add_argument("--since-ref", help="Git ref for changed detection, e.g. HEAD~1 or origin/main")
    parser.add_argument("--runpod-url", help="RunPod worker URL")
    parser.add_argument("--local", action="store_true", help="Force local Ollama")
    parser.add_argument("--execute", action="store_true", help="Actually run translation. Without this, dry-run only.")
    args = parser.parse_args()

    summary = scan_blog_posts(
        source_dir=args.source_dir,
        langs=args.langs,
        layout=args.layout,
        en_dir=args.en_dir,
        jp_dir=args.jp_dir,
        changed_only=args.changed_only,
        since_ref=args.since_ref,
    )
    pending = posts_needing_translation(summary)
    if args.only:
        pending = [
            post for post in pending
            if args.only in post.relative_path or args.only in post.source_path
        ]
    if args.limit is not None:
        pending = pending[:args.limit]

    print(f"Scanned {summary.total_sources} source post(s).")
    print(f"Pending translation: {len(pending)} post(s).")
    for post in pending:
        needed_langs = [target.lang for target in post.targets if target.status != "ok"]
        print(f"- {post.relative_path}: {', '.join(needed_langs)}")

    if not pending:
        return

    if not args.execute:
        print("\nDry-run only. Add --execute to run translation.")
        return

    use_worker = bool(args.runpod_url) and not args.local
    service_url = args.runpod_url or OLLAMA_LOCAL_URL
    output_dirs = {
        "en": args.en_dir,
        "jp": args.jp_dir,
    }
    model_overrides = {
        "en": args.en_model,
        "jp": args.jp_model,
    }
    for post in pending:
        needed_langs = [target.lang for target in post.targets if target.status != "ok"]
        translator = Translator(
            service_url=service_url,
            use_worker=use_worker,
            output_dirs=output_dirs,
            source_root=args.source_dir,
            model_overrides=model_overrides,
        )
        translator.translate_file(post.source_path, needed_langs)


if __name__ == "__main__":
    main()
