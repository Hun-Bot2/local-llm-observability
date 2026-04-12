import hashlib
import re
import yaml
from pathlib import Path


FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_mdx(filepath: str) -> dict:
    """Parse an MDX file and return frontmatter + structured sections.

    Returns:
        {
            "filename": "Algorithm_Bot_01.mdx",
            "frontmatter": { title, description, pubDate, heroImage, tags, category, series, seriesOrder },
            "sections": [
                { "type": "paragraph"|"code", "index": 0, "text": "...", "hash": "sha256..." },
                ...
            ]
        }
    """
    path = Path(filepath)
    content = path.read_text(encoding="utf-8")

    # Extract frontmatter
    fm_match = FRONTMATTER_RE.match(content)
    if fm_match:
        frontmatter = yaml.safe_load(fm_match.group(1))
        body = content[fm_match.end():]
    else:
        frontmatter = {}
        body = content

    sections = _split_body(body)

    return {
        "filename": path.name,
        "frontmatter": frontmatter,
        "sections": sections,
    }


def _split_body(body: str) -> list[dict]:
    """Split body into sections at double-newline boundaries, preserving code blocks."""
    sections = []
    index = 0

    # Split while preserving code blocks as single units
    parts = re.split(r"(```[\s\S]*?```)", body)

    for part in parts:
        if part.startswith("```"):
            # Code block — keep as single section
            text = part.strip()
            if text:
                sections.append({
                    "type": "code",
                    "index": index,
                    "text": text,
                    "hash": _sha256(text),
                })
                index += 1
        else:
            # Split prose at double-newline boundaries
            paragraphs = re.split(r"\n\n+", part)
            for para in paragraphs:
                text = para.strip()
                if not text:
                    continue
                sections.append({
                    "type": "paragraph",
                    "index": index,
                    "text": text,
                    "hash": _sha256(text),
                })
                index += 1

    return sections


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_all_korean_mdx(directory: str = "samples/mdx") -> list[dict]:
    """Parse all Korean (non-translated) MDX files in the given directory."""
    src = Path(directory)
    results = []
    for mdx_file in sorted(src.glob("Algorithm_Bot_0[0-9].mdx")):
        results.append(parse_mdx(str(mdx_file)))
    return results


if __name__ == "__main__":
    parsed = parse_all_korean_mdx()
    for doc in parsed:
        print(f"\n{'='*60}")
        print(f"File: {doc['filename']}")
        print(f"Title: {doc['frontmatter'].get('title')}")
        print(f"Sections: {len(doc['sections'])}")
        for s in doc["sections"]:
            preview = s["text"][:60].replace("\n", " ")
            print(f"  [{s['index']}] {s['type']:10s} {s['hash'][:12]}... {preview}")
