"""Detect Korean MDX posts that need translation.

This module is intentionally deterministic. It does not call an LLM; it only
answers which source files are missing or stale for each target language.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_LANGS = ("en", "jp")
DEFAULT_SOURCE_DIR = "/Users/jeonghun/hun-bot-blog/src/content/blog"
SOURCE_LANG_DIR = "ko"
DEFAULT_LAYOUT = "mirror"
DEFAULT_LANG_DIRS = {
    "en": "/Users/jeonghun/hun-bot-blog/src/content/blog/en",
    "jp": "/Users/jeonghun/hun-bot-blog/src/content/blog/jp",
}
TRANSLATED_SUFFIXES = ("_en", "_jp")
TRANSLATED_NAME_RE = re.compile(r"(^|_)(en|jp)(?:_[A-Za-z0-9][A-Za-z0-9.-]*)*$", re.IGNORECASE)


@dataclass(frozen=True)
class TranslationTargetStatus:
    lang: str
    path: str
    status: str
    reason: str


@dataclass(frozen=True)
class BlogPostStatus:
    source_path: str
    relative_path: str
    slug: str
    source_hash: str
    source_mtime: float
    changed_by_git: bool
    targets: list[TranslationTargetStatus]

    @property
    def needs_translation(self) -> bool:
        return any(target.status != "ok" for target in self.targets)


@dataclass(frozen=True)
class ScanSummary:
    source_dir: str
    layout: str
    langs: list[str]
    total_sources: int
    needs_translation: int
    ok: int
    git_ref: str | None
    changed_only: bool
    posts: list[BlogPostStatus]

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def scan_blog_posts(
    source_dir: str | Path,
    langs: Iterable[str] = DEFAULT_LANGS,
    layout: str = DEFAULT_LAYOUT,
    en_dir: str | Path | None = DEFAULT_LANG_DIRS["en"],
    jp_dir: str | Path | None = DEFAULT_LANG_DIRS["jp"],
    changed_only: bool = False,
    since_ref: str | None = None,
) -> ScanSummary:
    """Scan source posts and translation outputs.

    Args:
        source_dir: Directory containing Korean source `.mdx` files.
        langs: Target languages to check.
        layout: `suffix` uses `post_en.mdx`; `mirror` uses the same relative
            filename under each language output directory.
        en_dir: Optional English output root.
        jp_dir: Optional Japanese output root.
        changed_only: If true, only include files changed since `since_ref`.
        since_ref: Git ref used for changed-file detection, for example
            `HEAD~1`, `origin/main`, or a commit SHA.
    """
    source_root = Path(source_dir).expanduser().resolve()
    if not source_root.exists():
        raise FileNotFoundError(f"Source directory does not exist: {source_root}")
    if not source_root.is_dir():
        raise NotADirectoryError(f"Source path is not a directory: {source_root}")
    if layout not in {"suffix", "mirror"}:
        raise ValueError("layout must be either 'suffix' or 'mirror'")

    lang_roots = {
        "en": Path(en_dir).expanduser().resolve() if en_dir else None,
        "jp": Path(jp_dir).expanduser().resolve() if jp_dir else None,
    }
    target_langs = list(langs)

    changed_paths = _changed_mdx_paths(source_root, since_ref) if changed_only else None
    posts: list[BlogPostStatus] = []

    for source_path in _iter_source_mdx(source_root):
        if changed_paths is not None and source_path not in changed_paths:
            continue

        relative_path = source_path.relative_to(source_root)
        source_hash = _sha256_file(source_path)
        targets = [
            _target_status(source_path, source_root, relative_path, lang, layout, lang_roots.get(lang))
            for lang in target_langs
        ]
        posts.append(
            BlogPostStatus(
                source_path=str(source_path),
                relative_path=str(relative_path),
                slug=source_path.stem,
                source_hash=source_hash,
                source_mtime=source_path.stat().st_mtime,
                changed_by_git=changed_paths is not None and source_path in changed_paths,
                targets=targets,
            )
        )

    needs = sum(1 for post in posts if post.needs_translation)
    return ScanSummary(
        source_dir=str(source_root),
        layout=layout,
        langs=target_langs,
        total_sources=len(posts),
        needs_translation=needs,
        ok=len(posts) - needs,
        git_ref=since_ref,
        changed_only=changed_only,
        posts=posts,
    )


def posts_needing_translation(summary: ScanSummary) -> list[BlogPostStatus]:
    return [post for post in summary.posts if post.needs_translation]


def _iter_source_mdx(source_root: Path) -> list[Path]:
    candidates = sorted(source_root.rglob("*.mdx"))
    return [
        path
        for path in candidates
        if path.is_file()
        and not path.name.startswith(".")
        and _is_source_language_path(path, source_root)
        and not _looks_translated(path)
    ]


def _target_status(
    source_path: Path,
    source_root: Path,
    relative_path: Path,
    lang: str,
    layout: str,
    lang_root: Path | None,
) -> TranslationTargetStatus:
    target_path = _target_path(source_path, source_root, relative_path, lang, layout, lang_root)
    if not target_path.exists():
        return TranslationTargetStatus(
            lang=lang,
            path=str(target_path),
            status="missing",
            reason="translated file does not exist",
        )

    source_mtime = source_path.stat().st_mtime
    target_mtime = target_path.stat().st_mtime
    if target_mtime < source_mtime:
        return TranslationTargetStatus(
            lang=lang,
            path=str(target_path),
            status="stale",
            reason="source file is newer than translated file",
        )

    if target_path.stat().st_size == 0:
        return TranslationTargetStatus(
            lang=lang,
            path=str(target_path),
            status="stale",
            reason="translated file is empty",
        )

    return TranslationTargetStatus(
        lang=lang,
        path=str(target_path),
        status="ok",
        reason="translated file exists and is newer than source",
    )


def _target_path(
    source_path: Path,
    source_root: Path,
    relative_path: Path,
    lang: str,
    layout: str,
    lang_root: Path | None,
) -> Path:
    output_root = lang_root or source_root
    if layout == "mirror":
        output_relative = _strip_source_lang_dir(relative_path)
        return output_root / output_relative
    output_relative = relative_path.with_name(f"{relative_path.stem}_{lang}{relative_path.suffix}")
    if lang_root:
        return output_root / output_relative
    return source_path.with_name(f"{source_path.stem}_{lang}{source_path.suffix}")


def _changed_mdx_paths(source_root: Path, since_ref: str | None) -> set[Path]:
    if not since_ref:
        raise ValueError("--changed-only requires --since-ref, for example HEAD~1")

    repo_root = _git_repo_root(source_root)
    rel_source = source_root.relative_to(repo_root)
    command = [
        "git",
        "-C",
        str(repo_root),
        "diff",
        "--name-only",
        "--diff-filter=AM",
        f"{since_ref}..HEAD",
        "--",
        str(rel_source),
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    paths = set()
    for line in completed.stdout.splitlines():
        if not line.endswith(".mdx"):
            continue
        candidate = (repo_root / line).resolve()
        if candidate.exists() and not _looks_translated(candidate):
            paths.add(candidate)
    return paths


def _looks_translated(path: Path) -> bool:
    stem = path.stem.lower()
    return stem.endswith(TRANSLATED_SUFFIXES) or bool(TRANSLATED_NAME_RE.search(stem))


def _is_source_language_path(path: Path, source_root: Path) -> bool:
    relative = path.relative_to(source_root)
    if len(relative.parts) == 1:
        return True
    return relative.parts[0] == SOURCE_LANG_DIR


def _strip_source_lang_dir(relative_path: Path) -> Path:
    if len(relative_path.parts) > 1 and relative_path.parts[0] == SOURCE_LANG_DIR:
        return Path(*relative_path.parts[1:])
    return relative_path


def _git_repo_root(path: Path) -> Path:
    completed = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(completed.stdout.strip()).resolve()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
