from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import requests


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.mdx_parser import FRONTMATTER_RE, parse_mdx  # noqa: E402


OLLAMA_URL = "http://localhost:11434"

SYSTEM_PROMPTS = {
"en": """
You are a skilled Tech Blog Translator.
Translate the Korean text into natural, professional English for a developer audience.

[Critical Rules]
1. Tone: Casual but professional (DevLog style). Use "I" for the first person.
2. Technical Terms: Keep terms like 'Local LLM', 'vscode', 'commit & push', 'terminal' in English.
3. Preserve Markdown formatting exactly.
4. Do not add commentary, explanations, or extra sections.
5. Output only the translated text.
""",

"jp": """あなたはプロの技術ブロガーです。韓国語の技術ブログを日本のエンジニア向けに自然な日本語へ翻訳してください。

[Critical Rules]
1. 文体: 「です・ます」調。
2. 技術用語: 標準的なカタカナ表記または英語をそのまま使用してください。
3. Markdownの形式を崩さないでください。
4. 注釈や説明を追加しないでください。
5. 翻訳結果のみを出力してください。""",
}

DEFAULT_MODELS = {
    "en": "gemma4:e4b",
    "jp": "qwen3:14b",
}


def section_suffix(section_type: str) -> str:
    if section_type == "frontmatter_tags":
        return (
            "\n\nIMPORTANT: The input is a frontmatter tags value. DO NOT change the frontmatter structure. "
            "Preserve the bracketed list format exactly. Translate only the tag text. Output only the value."
        )
    if section_type == "frontmatter_title":
        return (
            "\n\nIMPORTANT: This is a frontmatter title value. DO NOT change the frontmatter structure. "
            "Translate only the value, keep it concise, and output exactly one line."
        )
    if section_type == "frontmatter_description":
        return (
            "\n\nIMPORTANT: This is a frontmatter description value. DO NOT change the frontmatter structure. "
            "Translate only this single value. Do not expand, summarize, or add extra lines. Output exactly one line."
        )
    if section_type.startswith("frontmatter"):
        return (
            "\n\nIMPORTANT: This is frontmatter metadata. DO NOT change the frontmatter structure. "
            "Translate only the value."
        )
    if section_type == "code":
        return (
            "\n\nIMPORTANT: The input is a fenced code block. Preserve the code, indentation, fences, "
            "identifiers, URLs, and string syntax exactly. Translate only human-language comments and "
            "docstrings into the target language. Do not add explanations."
        )
    return ""


def call_ollama(model: str, lang: str, text: str, section_type: str) -> str:
    prompt = SYSTEM_PROMPTS[lang] + section_suffix(section_type)
    response = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": text},
            ],
            "stream": False,
        },
        timeout=300,
    )

    if response.status_code == 404:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "system": prompt,
                "prompt": text,
                "stream": False,
            },
            timeout=300,
        )
        response.raise_for_status()
        payload = response.json()
        translated = payload["response"].strip()
    else:
        response.raise_for_status()
        payload = response.json()
        translated = payload["message"]["content"].strip()

    try:
        requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model, "keep_alive": 0},
            timeout=10,
        )
    except requests.RequestException:
        pass

    return translated.replace("```json", "").replace("```", "").strip()


def translate_frontmatter(raw_fm: str, lang: str, model: str) -> str:
    lines = raw_fm.split("\n")
    result = []
    for line in lines:
        title_match = re.match(r"(title:\s*)['\"](.+?)['\"]", line)
        if title_match:
            translated = call_ollama(model, lang, title_match.group(2), "frontmatter_title").strip("'\"")
            result.append(f"{title_match.group(1)}'{translated}'")
            continue

        desc_match = re.match(r"(description:\s*)['\"](.+?)['\"]", line)
        if desc_match:
            translated = call_ollama(model, lang, desc_match.group(2), "frontmatter_description").strip("'\"")
            result.append(f"{desc_match.group(1)}'{translated}'")
            continue

        tags_match = re.match(r"(tags:\s*)(\[.*\])", line)
        if tags_match:
            translated = call_ollama(model, lang, tags_match.group(2), "frontmatter_tags")
            result.append(f"{tags_match.group(1)}{translated}")
            continue

        result.append(line)
    return "\n".join(result)


def build_output_path(source_path: Path, lang: str, output_suffix: str | None) -> Path:
    suffix = f"_{lang}"
    if output_suffix:
        suffix += f"_{output_suffix}"
    return source_path.with_name(f"{source_path.stem}{suffix}.mdx")


def main():
    parser = argparse.ArgumentParser(description="Standalone local MDX translation test runner")
    parser.add_argument("file", help="Path to Korean .mdx source file")
    parser.add_argument("--lang", choices=["en", "jp"], default="en")
    parser.add_argument("--model", help="Ollama model name to use")
    parser.add_argument("--output-suffix", help="Extra suffix for the output filename, e.g. gemma4")
    args = parser.parse_args()

    source_path = Path(args.file)
    if not source_path.exists():
        raise SystemExit(f"File not found: {source_path}")

    model = args.model or DEFAULT_MODELS[args.lang]
    parsed = parse_mdx(str(source_path))
    content = source_path.read_text(encoding="utf-8")
    fm_match = FRONTMATTER_RE.match(content)

    if fm_match:
        translated_fm = translate_frontmatter(fm_match.group(1), args.lang, model)
    else:
        translated_fm = ""

    translated_sections = []
    total = len(parsed["sections"])
    for idx, section in enumerate(parsed["sections"], start=1):
        print(f"[{idx}/{total}] Translating {section['type']} section...", flush=True)
        translated_sections.append(call_ollama(model, args.lang, section["text"], section["type"]))

    body = "\n\n".join(translated_sections)
    if translated_fm:
        output = f"---\n{translated_fm}\n---\n\n{body}\n"
    else:
        output = f"{body}\n"

    output_path = build_output_path(source_path, args.lang, args.output_suffix)
    output_path.write_text(output, encoding="utf-8")

    print(f"Model: {model}")
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
