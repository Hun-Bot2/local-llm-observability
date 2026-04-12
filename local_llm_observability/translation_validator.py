from __future__ import annotations

import re


KOREAN_RE = re.compile(r"[\uac00-\ud7a3]")
HEADING_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)
URL_RE = re.compile(r"https?://[^\s)>\"]+")

META_PATTERNS = [
    r"この翻訳では",
    r"翻訳にあたり",
    r"以上の翻訳",
    r"翻訳について",
    r"翻訳ルール",
    r"(?i)translator'?s?\s+note",
    r"(?i)in this translation",
    r"(?i)note:?\s*(?:the|this) translation",
]


class TranslationValidationError(ValueError):
    pass


def validate_translation(source_text: str, translated_text: str | None,
                         target_lang: str | None, section_type: str) -> list[str]:
    """Return hard validation failures for a translated MDX section."""
    failures: list[str] = []
    translated = (translated_text or "").strip()
    source = source_text.strip()

    if not translated:
        return ["translation is empty"]

    if section_type == "code":
        failures.extend(_validate_code_block(source, translated))
        return failures

    if section_type.startswith("frontmatter") and "\n" in translated:
        failures.append("frontmatter translation must be one line")

    failures.extend(_validate_markdown_structure(source, translated))
    failures.extend(_validate_hallucination_markers(source, translated))

    if target_lang:
        failures.extend(_validate_target_language(source, translated, target_lang))
        failures.extend(_validate_length(source, translated, target_lang, section_type))

    return failures


def assert_valid_translation(source_text: str, translated_text: str | None,
                             target_lang: str | None, section_type: str) -> None:
    failures = validate_translation(source_text, translated_text, target_lang, section_type)
    if failures:
        joined = "; ".join(failures)
        raise TranslationValidationError(joined)


def _validate_code_block(source: str, translated: str) -> list[str]:
    failures = []
    if source.startswith("```") and not translated.startswith("```"):
        failures.append("missing opening code fence")
    if source.endswith("```") and not translated.endswith("```"):
        failures.append("missing closing code fence")
    source_opening = source.splitlines()[0].strip() if source.startswith("```") else ""
    translated_opening = translated.splitlines()[0].strip() if translated.startswith("```") else ""
    if source_opening and translated_opening and source_opening != translated_opening:
        failures.append("code fence language marker changed")
    return failures


def _validate_markdown_structure(source: str, translated: str) -> list[str]:
    failures = []

    source_headings = len(HEADING_RE.findall(source))
    translated_headings = len(HEADING_RE.findall(translated))
    if translated_headings != source_headings:
        failures.append(
            f"heading count changed from {source_headings} to {translated_headings}"
        )

    source_urls = set(URL_RE.findall(source))
    translated_urls = set(URL_RE.findall(translated))
    extra_urls = translated_urls - source_urls
    if extra_urls:
        failures.append(f"added URL(s): {', '.join(sorted(extra_urls))}")

    return failures


def _validate_hallucination_markers(source: str, translated: str) -> list[str]:
    failures = []
    for pattern in META_PATTERNS:
        if re.search(pattern, translated):
            failures.append("contains translator/meta commentary")
            break

    if "example.com" in translated and "example.com" not in source:
        failures.append("added placeholder example.com link")

    return failures


def _validate_target_language(source: str, translated: str, target_lang: str) -> list[str]:
    if target_lang != "jp":
        return []

    source_korean = len(KOREAN_RE.findall(source))
    translated_korean = len(KOREAN_RE.findall(translated))
    if source_korean >= 10 and translated_korean > max(4, int(source_korean * 0.12)):
        return [f"too much Korean remains in Japanese output ({translated_korean} chars)"]
    return []


def _validate_length(source: str, translated: str, target_lang: str, section_type: str) -> list[str]:
    source_len = len(source)
    if source_len == 0:
        return []

    ratio = len(translated) / source_len
    if section_type.startswith("frontmatter"):
        max_ratio = 2.2 if target_lang == "en" else 1.8
    elif target_lang == "en":
        max_ratio = 3.5
    else:
        max_ratio = 2.4

    if ratio > max_ratio:
        return [f"translation expanded too much ({ratio:.2f}x > {max_ratio:.2f}x)"]
    return []
