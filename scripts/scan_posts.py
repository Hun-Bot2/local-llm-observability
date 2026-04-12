"""V2 scanner CLI.

Examples:
    python scripts/scan_posts.py --source-dir samples/mdx
    python scripts/scan_posts.py --source-dir /path/to/blog/posts --changed-only --since-ref HEAD~1
    python scripts/scan_posts.py --source-dir /path/to/ko --en-dir /path/to/en --jp-dir /path/to/jp --layout mirror
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from local_llm_observability.blog_scanner import (
    DEFAULT_LANG_DIRS,
    DEFAULT_LANGS,
    DEFAULT_LAYOUT,
    DEFAULT_SOURCE_DIR,
    posts_needing_translation,
    scan_blog_posts,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan Korean MDX posts for missing/stale translations")
    parser.add_argument(
        "--source-dir",
        default=DEFAULT_SOURCE_DIR,
        help=f"Directory containing Korean source .mdx files (default: {DEFAULT_SOURCE_DIR})",
    )
    parser.add_argument("--langs", nargs="+", default=list(DEFAULT_LANGS), choices=list(DEFAULT_LANGS))
    parser.add_argument("--layout", choices=["suffix", "mirror"], default=DEFAULT_LAYOUT)
    parser.add_argument("--en-dir", default=DEFAULT_LANG_DIRS["en"], help="English output root")
    parser.add_argument("--jp-dir", default=DEFAULT_LANG_DIRS["jp"], help="Japanese output root")
    parser.add_argument("--changed-only", action="store_true", help="Only scan source files changed since --since-ref")
    parser.add_argument("--since-ref", help="Git ref for changed detection, e.g. HEAD~1 or origin/main")
    parser.add_argument("--json-out", help="Optional path to write full JSON report")
    parser.add_argument("--json", action="store_true", help="Print full JSON report instead of readable summary")
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

    if args.json_out:
        Path(args.json_out).write_text(summary.to_json() + "\n", encoding="utf-8")

    if args.json:
        print(summary.to_json())
        return

    print(f"Source dir: {summary.source_dir}")
    print(f"Layout: {summary.layout}")
    print(f"Languages: {', '.join(summary.langs)}")
    print(f"Total source posts: {summary.total_sources}")
    print(f"Needs translation: {summary.needs_translation}")
    print(f"OK: {summary.ok}")

    pending = posts_needing_translation(summary)
    if not pending:
        print("\nNo missing or stale translations found.")
        return

    print("\nPosts needing work:")
    for post in pending:
        problems = [f"{target.lang}:{target.status}" for target in post.targets if target.status != "ok"]
        print(f"- {post.relative_path} ({', '.join(problems)})")


if __name__ == "__main__":
    main()
