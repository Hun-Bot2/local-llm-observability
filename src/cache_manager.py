from src.db.db_manager import DBManager
from src.mdx_parser import parse_mdx


class CacheManager:
    def __init__(self, db: DBManager):
        self.db = db

    def diff(self, filepath: str) -> dict:
        """Compare parsed MDX sections against the DB cache.

        Returns:
            {
                "filename": str,
                "hits": [section_dict with cached en/jp],
                "misses": [section_dict needing translation],
                "total": int,
                "cached": int,
                "new": int,
            }
        """
        parsed = parse_mdx(filepath)
        filename = parsed["filename"]
        sections = parsed["sections"]

        cached_rows = self.db.get_cached_sections(filename)
        cache_map = {row["section_index"]: row for row in cached_rows}

        hits = []
        misses = []

        for section in sections:
            idx = section["index"]
            cached = cache_map.get(idx)

            if cached and cached["content_hash"] == section["hash"]:
                # Hash matches — check if translations exist
                if cached.get("en_text") and cached.get("jp_text"):
                    hits.append({**section, "en_text": cached["en_text"], "jp_text": cached["jp_text"]})
                else:
                    # Hash matches but missing translation(s)
                    misses.append({
                        **section,
                        "en_text": cached.get("en_text"),
                        "jp_text": cached.get("jp_text"),
                    })
            else:
                # Hash changed or no cache entry — needs translation
                misses.append(section)

        return {
            "filename": filename,
            "frontmatter": parsed["frontmatter"],
            "hits": hits,
            "misses": misses,
            "total": len(sections),
            "cached": len(hits),
            "new": len(misses),
        }

    def update_cache(self, filename: str, section: dict, en_text: str = None,
                     jp_text: str = None, model_name: str = None):
        """Write a translated section back to the cache."""
        self.db.upsert_cache(
            filename=filename,
            section_type=section["type"],
            section_index=section["index"],
            content_hash=section["hash"],
            ko_text=section["text"],
            en_text=en_text,
            jp_text=jp_text,
            model_name=model_name,
        )

    def sync_blog_post(self, filepath: str):
        """Parse an MDX file and upsert its frontmatter into blog_posts."""
        parsed = parse_mdx(filepath)
        self.db.upsert_blog_post(parsed["filename"], parsed["frontmatter"])
        return parsed["filename"]
