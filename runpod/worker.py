"""RunPod translation worker.

This service runs inside the RunPod container next to Ollama and exposes:
- GET /health
- POST /translate
- POST /embed

The controller calls these endpoints to translate changed MDX sections and
fetch embeddings for quality scoring / translation memory.
"""

from __future__ import annotations

import os
import time
from typing import Any

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")

MODELS = {
    "en": "translategemma:12b",
    "jp": "qwen3:14b",
}

SYSTEM_PROMPTS = {
    "en": """You are a skilled Tech Blog Translator.
Translate the Korean text into natural, professional English for a developer audience.

[Critical Rules]
1. Tone: Casual but professional (DevLog style). Use "I" for the first person.
2. Technical Terms: Keep terms like 'Local LLM', 'vscode', 'commit & push', 'terminal' in English.
3. Formatting: Preserve all Markdown exactly. Do not break headings, lists, links, tables, or inline code.
4. Do not add commentary, translator notes, or explanations.
5. Output only the translated text.""",
    "jp": """あなたはプロの技術ブロガーです。韓国語の技術ブログを日本のエンジニア向けに自然な日本語へ翻訳してください。

[Critical Rules]
1. 文体: 「です・ます」調で丁寧に、しかし技術的に正確に。
2. 技術用語: 標準的なカタカナ表記または英語をそのまま使用してください。
3. Markdownの形式を絶対に崩さないでください。見出し、箇条書き、リンク、表、インラインコードを保持してください。
4. 翻訳に関する注釈やコメントを追加しないでください。
5. 翻訳結果のみを出力してください。""",
}

EMBED_MODEL = "nomic-embed-text"

app = FastAPI(title="RunPod Translation Worker", version="1.0.0")


class Section(BaseModel):
    ko_text: str = Field(..., min_length=1)
    section_type: str = "paragraph"
    index: int | None = None
    filename: str | None = None
    metadata: dict[str, Any] | None = None


class TranslateRequest(BaseModel):
    sections: list[Section]
    target_lang: str
    glossary_text: str = ""


class EmbedRequest(BaseModel):
    texts: list[str]


def _normalize_lang(lang: str) -> str:
    normalized = lang.strip().lower()
    if normalized not in MODELS:
        raise HTTPException(status_code=400, detail=f"Unsupported target language: {lang}")
    return normalized


def _section_suffix(section_type: str) -> str:
    if section_type == "frontmatter_tags":
        return (
            "\n\nIMPORTANT: The input is a frontmatter tags value. DO NOT change the frontmatter structure. "
            "Preserve the bracketed list format exactly, including commas, quotes, and spacing style where possible. "
            "Translate only the tag text. Output only the value."
        )
    if section_type == "frontmatter_title":
        return (
            "\n\nIMPORTANT: This is a frontmatter title value. DO NOT change the frontmatter structure. "
            "Translate only the value, keep it concise, and output exactly one line with no extra explanation."
        )
    if section_type == "frontmatter_description":
        return (
            "\n\nIMPORTANT: This is a frontmatter description value. DO NOT change the frontmatter structure. "
            "Translate only this single value. Do not expand, summarize, add headings, bullet points, extra lines, "
            "or surrounding keys. Output exactly one line."
        )
    if section_type.startswith("frontmatter"):
        return (
            "\n\nIMPORTANT: This is frontmatter metadata. DO NOT change the frontmatter structure. "
            "Translate only the value and output only the translated value."
        )
    if section_type == "code":
        return (
            "\n\nIMPORTANT: The input is a fenced code block. Preserve the code, indentation, fences, "
            "identifiers, URLs, and string syntax exactly. Translate only human-language comments and "
            "docstrings into the target language. Do not add explanations."
        )
    return ""


def _cleanup_translation(section_type: str, translated: str) -> str:
    cleaned = translated.strip()
    if section_type == "frontmatter_tags":
        cleaned = cleaned.replace("```json", "").replace("```", "").strip()
    return cleaned


def _post_ollama(path: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    try:
        response = requests.post(f"{OLLAMA_URL}{path}", json=payload, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Ollama request failed: {exc}") from exc


def _release_model(model: str) -> None:
    try:
        requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model, "keep_alive": 0},
            timeout=10,
        )
    except requests.RequestException:
        # Memory release is best-effort and should not fail the request.
        pass


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        response.raise_for_status()
        tags = response.json().get("models", [])
        return {
            "status": "ready",
            "ollama_url": OLLAMA_URL,
            "models": [tag.get("name") for tag in tags],
        }
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail=f"Ollama not ready: {exc}") from exc


@app.post("/translate")
def translate(payload: TranslateRequest) -> dict[str, Any]:
    target_lang = _normalize_lang(payload.target_lang)
    model = MODELS[target_lang]
    base_prompt = SYSTEM_PROMPTS[target_lang]

    if payload.glossary_text.strip():
        base_prompt += f"\n\n[Glossary Reference]\n{payload.glossary_text.strip()}"

    results: list[dict[str, Any]] = []

    for section in payload.sections:
        prompt = base_prompt + _section_suffix(section.section_type)
        started_at = time.perf_counter()
        response = _post_ollama(
            "/api/chat",
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": section.ko_text},
                ],
                "stream": False,
            },
            timeout=300,
        )
        latency_ms = round((time.perf_counter() - started_at) * 1000, 1)
        translated = _cleanup_translation(
            section.section_type,
            response.get("message", {}).get("content", ""),
        )

        results.append(
            {
                "index": section.index,
                "filename": section.filename,
                "section_type": section.section_type,
                "ko_text": section.ko_text,
                "translated": translated,
                "model": model,
                "input_tokens": response.get("prompt_eval_count", 0),
                "output_tokens": response.get("eval_count", 0),
                "latency_ms": latency_ms,
                "total_duration_ns": response.get("total_duration", 0),
                "prompt_eval_duration_ns": response.get("prompt_eval_duration", 0),
                "eval_duration_ns": response.get("eval_duration", 0),
                "metadata": section.metadata or {},
            }
        )

    _release_model(model)

    return {
        "target_lang": target_lang,
        "model": model,
        "count": len(results),
        "translations": results,
    }


@app.post("/embed")
def embed(payload: EmbedRequest) -> dict[str, Any]:
    embeddings: list[list[float]] = []
    for text in payload.texts:
        response = _post_ollama(
            "/api/embed",
            {"model": EMBED_MODEL, "input": text},
            timeout=120,
        )
        batch = response.get("embeddings", [])
        if not batch:
            raise HTTPException(status_code=502, detail="Ollama returned no embedding")
        embeddings.append(batch[0])

    return {
        "model": EMBED_MODEL,
        "count": len(embeddings),
        "embeddings": embeddings,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
