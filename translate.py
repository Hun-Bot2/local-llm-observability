"""Unified translation CLI.

Usage:
    python translate.py src/Algorithm_Bot_01.mdx
    python translate.py src/Algorithm_Bot_01.mdx --lang en
    python translate.py src/Algorithm_Bot_01.mdx --lang jp
    python translate.py src/Algorithm_Bot_01.mdx --runpod-url https://xxx-8000.proxy.runpod.net
"""

from __future__ import annotations

import argparse
import re
import time
from pathlib import Path
from typing import Any

import requests

from src.cache_manager import CacheManager
from src.db.db_manager import DBManager
from src.mdx_parser import FRONTMATTER_RE, parse_mdx
from src.quality_scorer import QualityScorer


OLLAMA_LOCAL_URL = "http://localhost:11434"
RUNPOD_HOURLY_RATE = 0.39

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
3. Formatting: Preserve ALL Markdown formatting exactly — headings, bold, italic, links, lists.
4. Do NOT add any commentary, notes, or explanations about your translation.
5. Output ONLY the translated text, nothing else.""",
    "jp": """あなたはプロの技術ブロガーです。韓国語の技術ブログを日本のエンジニア向けに自然な日本語へ翻訳してください。

[Critical Rules]
1. 文体: 「です・ます」調で丁寧に、しかし技術的に正確に。
2. 技術用語: 標準的なカタカナ表記または英語をそのまま使用してください。
3. フォーマット: Markdownの形式を一切崩さないでください — 見出し、太字、斜体、リンク、リスト。
4. 翻訳に関するコメントや注釈を絶対に追加しないでください。
5. 翻訳されたテキストのみを出力してください。""",
}


class Translator:
    def __init__(self, service_url: str = OLLAMA_LOCAL_URL, use_worker: bool = False):
        self.service_url = service_url.rstrip("/")
        self.use_worker = use_worker
        self.db = DBManager()
        self.cache = CacheManager(self.db)
        self.scorer = QualityScorer(self.db)

    def translate_file(self, filepath: str, langs: list[str] | None = None):
        """Full translation pipeline for a single MDX file."""
        langs = langs or ["en", "jp"]
        path = Path(filepath)
        if not path.exists():
            print(f"Error: {filepath} not found")
            return

        mode = "RunPod worker" if self.use_worker else "local Ollama"
        print(f"\n{'=' * 60}")
        print(f"Translating: {path.name}")
        print(f"Languages: {', '.join(langs)}")
        print(f"Backend: {mode} ({self.service_url})")
        print(f"{'=' * 60}")

        self.cache.sync_blog_post(filepath)
        run_id = self.db.insert_pipeline_run("manual")
        start_time = time.time()

        try:
            diff = self.cache.diff(filepath)
            diff["source_path"] = str(path)
            print(f"\nSections: {diff['total']} total, {diff['cached']} cached, {diff['new']} to translate")

            for lang in langs:
                print(f"\n--- {lang.upper()} Translation ---")
                self._translate_lang(diff, lang, run_id)

            gpu_time = time.time() - start_time
            cost = self._estimate_cost(gpu_time)
            self.db.update_pipeline_run(
                run_id=run_id,
                status="completed",
                total_files=1,
                cached_sections=diff["cached"],
                new_sections=diff["new"],
                gpu_time_sec=gpu_time,
                estimated_cost=cost,
            )

            print(f"\n{'=' * 60}")
            print(f"Done in {gpu_time:.1f}s | Cache hits: {diff['cached']}/{diff['total']} | Cost: ${cost:.4f}")
            print(f"{'=' * 60}")
        except Exception as exc:
            self.db.update_pipeline_run(run_id=run_id, status="failed")
            print(f"\nPipeline failed: {exc}")
            raise
        finally:
            self.db.close()

    def _translate_lang(self, diff: dict[str, Any], lang: str, run_id: int):
        filename = diff["filename"]
        source_path = Path(diff["source_path"])
        lang_key = f"{lang}_text"
        all_sections: list[dict[str, Any]] = []

        translated_payloads = self._translate_missing_sections(diff["misses"], filename, lang, run_id)
        translated_map = {payload["index"]: payload for payload in translated_payloads}

        for section in diff["hits"]:
            all_sections.append(
                {
                    "index": section["index"],
                    "type": section["type"],
                    "text": section.get(lang_key, section["text"]),
                    "source": "cache",
                }
            )

        for section in diff["misses"]:
            if section.get(lang_key):
                translated = section[lang_key]
            else:
                translated = translated_map[section["index"]]["translated"]

            all_sections.append(
                {
                    "index": section["index"],
                    "type": section["type"],
                    "text": translated,
                    "source": "new",
                }
            )

            self.cache.update_cache(
                filename=filename,
                section={
                    "type": section["type"],
                    "index": section["index"],
                    "hash": section["hash"],
                    "text": section["text"],
                },
                model_name=translated_map.get(section["index"], {}).get("model", MODELS.get(lang)),
                **{lang_key: translated},
            )

        all_sections.sort(key=lambda section: section["index"])

        source_parsed = parse_mdx(str(source_path))
        ko_sections = source_parsed["sections"]
        tr_sections = [{"type": section["type"], "text": section["text"]} for section in all_sections]
        scores = self.scorer.score_file(ko_sections, tr_sections, lang, filename, run_id)

        failed = [section for section, score in zip(all_sections, scores) if not score.passed]
        if failed:
            print(f"  Warning: {len(failed)} section(s) below quality threshold")

        self._write_output(source_path, filename, all_sections, lang, run_id)

    def _translate_missing_sections(self, sections: list[dict[str, Any]], filename: str, lang: str, run_id: int):
        sections_to_translate = []
        for section in sections:
            if section.get(f"{lang}_text"):
                continue
            sections_to_translate.append(
                {
                    "ko_text": section["text"],
                    "section_type": section["type"],
                    "index": section["index"],
                    "filename": filename,
                }
            )

        if not sections_to_translate:
            return []

        char_count = sum(len(section["ko_text"]) for section in sections_to_translate)
        print(
            f"  [{MODELS[lang]}] Translating {len(sections_to_translate)} section(s) "
            f"({char_count} chars total)...",
            end=" ",
            flush=True,
        )
        started_at = time.time()
        glossary_text = self._glossary_text_for(
            lang,
            "\n".join(section["ko_text"] for section in sections_to_translate),
        )

        if self.use_worker:
            translated = self._translate_via_worker(sections_to_translate, lang, glossary_text)
        else:
            translated = [
                self._translate_direct(
                    section["ko_text"],
                    lang,
                    section_type=section["section_type"],
                    index=section["index"],
                    filename=filename,
                    glossary_text=glossary_text,
                )
                for section in sections_to_translate
            ]

        elapsed = time.time() - started_at
        print(f"done ({elapsed:.1f}s)")

        for payload in translated:
            self.db.insert_translation_section(
                run_id=run_id,
                filename=payload.get("filename") or filename,
                section_index=payload.get("index"),
                section_type=payload.get("section_type", "paragraph"),
                target_lang=lang,
                model_name=payload.get("model", MODELS[lang]),
                source_text=payload["ko_text"],
                translated_text=payload["translated"],
                input_tokens=payload.get("input_tokens", 0),
                output_tokens=payload.get("output_tokens", 0),
                latency_ms=payload.get("latency_ms", 0),
            )

        return translated

    def _translate_via_worker(self, sections: list[dict[str, Any]], lang: str, glossary_text: str):
        try:
            response = requests.post(
                f"{self.service_url}/translate",
                json={
                    "target_lang": lang,
                    "sections": sections,
                    "glossary_text": glossary_text,
                },
                timeout=600,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"RunPod worker request failed: {exc}") from exc

        return response.json()["translations"]

    def _translate_direct(self, text: str, lang: str, section_type: str, index: int | None,
                          filename: str | None, glossary_text: str = "") -> dict[str, Any]:
        model = MODELS[lang]
        system_prompt = SYSTEM_PROMPTS[lang]
        if glossary_text:
            system_prompt += f"\n\n[Glossary — use these exact translations]\n{glossary_text}"

        if section_type == "frontmatter_tags":
            system_prompt += (
                "\n\nIMPORTANT: The input is a frontmatter tags value. DO NOT change the frontmatter structure. "
                "Preserve the bracketed list format exactly, including commas, quotes, and spacing style where possible. "
                "Translate only the tag text. Output only the value."
            )
        elif section_type == "frontmatter_title":
            system_prompt += (
                "\n\nIMPORTANT: This is a frontmatter title value. DO NOT change the frontmatter structure. "
                "Translate only the value, keep it concise, and output exactly one line with no extra explanation."
            )
        elif section_type == "frontmatter_description":
            system_prompt += (
                "\n\nIMPORTANT: This is a frontmatter description value. DO NOT change the frontmatter structure. "
                "Translate only this single value. Do not expand, summarize, add headings, bullet points, extra lines, "
                "or surrounding keys. Output exactly one line."
            )
        elif section_type.startswith("frontmatter"):
            system_prompt += (
                "\n\nIMPORTANT: This is frontmatter metadata. DO NOT change the frontmatter structure. "
                "Translate only the value and output only the translated value."
            )
        elif section_type == "code":
            system_prompt += (
                "\n\nIMPORTANT: The input is a fenced code block. Preserve the code, indentation, fences, "
                "identifiers, URLs, and string syntax exactly. Translate only human-language comments and "
                "docstrings into the target language. Do not add explanations."
            )

        started_at = time.perf_counter()
        try:
            response = requests.post(
                f"{self.service_url}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text},
                    ],
                    "stream": False,
                },
                timeout=300,
            )
            if response.status_code == 404:
                response = requests.post(
                    f"{self.service_url}/api/generate",
                    json={
                        "model": model,
                        "system": system_prompt,
                        "prompt": text,
                        "stream": False,
                    },
                    timeout=300,
                )
                response.raise_for_status()
                payload = response.json()
                translated_text = payload["response"].strip()
            else:
                response.raise_for_status()
                payload = response.json()
                translated_text = payload["message"]["content"].strip()
        except requests.RequestException as exc:
            raise RuntimeError(f"Local Ollama request failed: {exc}") from exc
        finally:
            self._release_local_model(model)

        translated = translated_text.replace("```json", "").replace("```", "").strip()
        return {
            "index": index,
            "filename": filename,
            "section_type": section_type,
            "ko_text": text,
            "translated": translated,
            "model": model,
            "input_tokens": payload.get("prompt_eval_count", 0),
            "output_tokens": payload.get("eval_count", 0),
            "latency_ms": round((time.perf_counter() - started_at) * 1000, 1),
        }

    def _release_local_model(self, model: str):
        try:
            requests.post(
                f"{self.service_url}/api/generate",
                json={"model": model, "keep_alive": 0},
                timeout=10,
            )
        except requests.RequestException:
            pass

    def _glossary_text_for(self, lang: str, text: str) -> str:
        glossary = self.db.get_glossary(lang)
        relevant_terms = {source: target for source, target in glossary.items() if source in text}
        return "\n".join(f"- {source}: {target}" for source, target in relevant_terms.items())

    def _translate_frontmatter_field(self, text: str, lang: str, filename: str,
                                     field_name: str, run_id: int) -> str:
        section_type = f"frontmatter_{field_name}"
        glossary_text = self._glossary_text_for(lang, text)
        if self.use_worker:
            translated = self._translate_via_worker(
                [
                    {
                        "ko_text": text,
                        "section_type": section_type,
                        "index": None,
                        "filename": filename,
                    }
                ],
                lang,
                glossary_text,
            )[0]
        else:
            translated = self._translate_direct(
                text,
                lang,
                section_type=section_type,
                index=None,
                filename=filename,
                glossary_text=glossary_text,
            )

        self.db.insert_translation_section(
            run_id=run_id,
            filename=filename,
            section_index=None,
            section_type=section_type,
            target_lang=lang,
            model_name=translated.get("model", MODELS[lang]),
            source_text=text,
            translated_text=translated["translated"],
            input_tokens=translated.get("input_tokens", 0),
            output_tokens=translated.get("output_tokens", 0),
            latency_ms=translated.get("latency_ms", 0),
        )
        return translated["translated"].strip("'\"")

    def _write_output(self, source_path: Path, filename: str, sections: list[dict[str, Any]], lang: str, run_id: int):
        content = source_path.read_text(encoding="utf-8")
        fm_match = FRONTMATTER_RE.match(content)
        if fm_match:
            raw_fm = fm_match.group(1)
            translated_fm = self._translate_frontmatter(raw_fm, lang, filename, run_id)
        else:
            translated_fm = ""

        body = "\n\n".join(section["text"] for section in sections)
        if translated_fm:
            output = f"---\n{translated_fm}\n---\n\n{body}\n"
        else:
            output = f"{body}\n"

        output_path = source_path.with_name(source_path.stem + f"_{lang}.mdx")
        output_path.write_text(output, encoding="utf-8")
        print(f"  Saved: {output_path}")

    def _translate_frontmatter(self, raw_fm: str, lang: str, filename: str, run_id: int) -> str:
        lines = raw_fm.split("\n")
        result = []
        for line in lines:
            title_match = re.match(r"(title:\s*)['\"](.+?)['\"]", line)
            if title_match:
                translated = self._translate_frontmatter_field(
                    title_match.group(2),
                    lang,
                    filename,
                    "title",
                    run_id,
                )
                result.append(f"{title_match.group(1)}'{translated}'")
                continue

            desc_match = re.match(r"(description:\s*)['\"](.+?)['\"]", line)
            if desc_match:
                translated = self._translate_frontmatter_field(
                    desc_match.group(2),
                    lang,
                    filename,
                    "description",
                    run_id,
                )
                result.append(f"{desc_match.group(1)}'{translated}'")
                continue

            result.append(line)

        return "\n".join(result)

    def _estimate_cost(self, gpu_time_sec: float) -> float:
        return (gpu_time_sec / 3600) * RUNPOD_HOURLY_RATE


def main():
    parser = argparse.ArgumentParser(description="Translate Korean MDX blog posts to EN/JP")
    parser.add_argument("file", help="Path to Korean .mdx file (e.g., src/Algorithm_Bot_01.mdx)")
    parser.add_argument("--lang", choices=["en", "jp"], help="Translate to specific language only")
    parser.add_argument("--local", action="store_true", help="Force local Ollama instead of the RunPod worker")
    parser.add_argument("--runpod-url", help="RunPod worker URL (e.g., https://xxx-8000.proxy.runpod.net)")
    args = parser.parse_args()

    langs = [args.lang] if args.lang else ["en", "jp"]
    use_worker = bool(args.runpod_url) and not args.local
    service_url = args.runpod_url or OLLAMA_LOCAL_URL

    translator = Translator(service_url=service_url, use_worker=use_worker)
    translator.translate_file(args.file, langs)


if __name__ == "__main__":
    main()
