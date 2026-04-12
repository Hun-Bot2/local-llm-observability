"""Human correction ingestion.

After reviewing a translated file (_en.mdx or _jp.mdx), run this script
to diff the corrected output against the cached version and update the cache.

Usage:
    python -m local_llm_observability.feedback samples/mdx/Algorithm_Bot_01_jp.mdx
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from local_llm_observability.db.db_manager import DBManager
from local_llm_observability.mdx_parser import _split_body, FRONTMATTER_RE
from local_llm_observability.translation_validator import validate_translation


def ingest_corrections(translated_path: str, db: DBManager = None,
                       reviewer: str | None = None, notes: str | None = None):
    """Read a corrected translated file and update the cache with corrections."""
    path = Path(translated_path)
    if not path.exists():
        print(f"File not found: {translated_path}")
        return

    # Determine source filename and target language
    name = path.name
    path_parts = set(path.parts)
    if name.endswith("_en.mdx"):
        target_lang = "en"
        source_filename = name.replace("_en.mdx", ".mdx")
    elif name.endswith("_jp.mdx"):
        target_lang = "jp"
        source_filename = name.replace("_jp.mdx", ".mdx")
    elif "en" in path_parts:
        target_lang = "en"
        source_filename = name
    elif "jp" in path_parts:
        target_lang = "jp"
        source_filename = name
    else:
        print(f"Cannot determine language from filename: {name}")
        print("Expected pattern: *_en.mdx, *_jp.mdx, or a path under /en/ or /jp/")
        return

    own_db = db is None
    if own_db:
        db = DBManager()

    try:
        # Parse the corrected file into sections
        content = path.read_text(encoding="utf-8")
        fm_match = FRONTMATTER_RE.match(content)
        body = content[fm_match.end():] if fm_match else content
        corrected_sections = _split_body(body)

        # Get cached sections for the source file
        cached = db.get_cached_sections(source_filename)
        cache_map = {row["section_index"]: row for row in cached}

        updated = 0
        for section in corrected_sections:
            idx = section["index"]
            cached_row = cache_map.get(idx)

            if not cached_row:
                continue

            if section["type"] == "code":
                continue

            # Compare corrected text vs cached translation
            lang_key = f"{target_lang}_text"
            cached_translation = cached_row.get(lang_key, "")
            corrected_text = section["text"]

            if corrected_text != cached_translation:
                validation_errors = validate_translation(
                    cached_row["ko_text"],
                    cached_translation,
                    target_lang,
                    cached_row["section_type"],
                )
                error_types = validation_errors or ["human_corrected"]
                db.insert_translation_correction(
                    filename=source_filename,
                    section_index=idx,
                    section_type=cached_row["section_type"],
                    target_lang=target_lang,
                    source_text=cached_row["ko_text"],
                    model_output=cached_translation,
                    corrected_output=corrected_text,
                    error_types=error_types,
                    reviewer=reviewer,
                    notes=notes,
                )
                # Human made a correction — update cache
                kwargs = {
                    "filename": source_filename,
                    "section_type": cached_row["section_type"],
                    "section_index": idx,
                    "content_hash": cached_row["content_hash"],
                    "ko_text": cached_row["ko_text"],
                }
                kwargs[f"{target_lang}_text"] = corrected_text
                # Use the underlying upsert which preserves other lang via COALESCE
                db.upsert_cache(**kwargs)
                updated += 1
                print(f"  Updated section [{idx}]: {corrected_text[:50]}...")

        print(f"\nFeedback applied: {updated} section(s) corrected for {source_filename} ({target_lang})")

    finally:
        if own_db:
            db.close()


def main():
    parser = argparse.ArgumentParser(description="Ingest human corrections into translation cache")
    parser.add_argument("file", help="Path to corrected translated file (*_en.mdx or *_jp.mdx)")
    parser.add_argument("--reviewer", help="Reviewer name or handle")
    parser.add_argument("--notes", help="Optional correction batch notes")
    args = parser.parse_args()
    ingest_corrections(args.file, reviewer=args.reviewer, notes=args.notes)


if __name__ == "__main__":
    main()
