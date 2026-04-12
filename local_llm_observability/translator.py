"""Unified translation CLI.

Usage:
    python translate.py samples/mdx/Algorithm_Bot_01.mdx
    python translate.py samples/mdx/Algorithm_Bot_01.mdx --lang en
    python translate.py samples/mdx/Algorithm_Bot_01.mdx --lang jp
    python translate.py samples/mdx/Algorithm_Bot_01.mdx --runpod-url https://xxx-8000.proxy.runpod.net
"""

from __future__ import annotations

import argparse
import re
import time
from pathlib import Path
from typing import Any, Callable

import requests

from local_llm_observability.blog_scanner import SOURCE_LANG_DIR
from local_llm_observability.cache_manager import CacheManager
from local_llm_observability.db.db_manager import DBManager
from local_llm_observability.mdx_parser import FRONTMATTER_RE, parse_mdx
from local_llm_observability.quality_scorer import QualityScorer
from local_llm_observability.translation_validator import validate_translation


OLLAMA_LOCAL_URL = "http://localhost:11434"
RUNPOD_HOURLY_RATE = 0.39

MODELS = {
    "en": "gemma4:latest",
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
    def __init__(
        self,
        service_url: str = OLLAMA_LOCAL_URL,
        use_worker: bool = False,
        output_dirs: dict[str, str] | None = None,
        source_root: str | None = None,
        model_overrides: dict[str, str] | None = None,
        event_callback: Callable[[str, str, dict[str, Any] | None], None] | None = None,
    ):
        self.service_url = service_url.rstrip("/")
        self.use_worker = use_worker
        self.output_dirs = {lang: Path(path).expanduser().resolve() for lang, path in (output_dirs or {}).items()}
        self.source_root = Path(source_root).expanduser().resolve() if source_root else None
        self.models = {**MODELS, **(model_overrides or {})}
        self.event_callback = event_callback
        self.db = DBManager()
        self.cache = CacheManager(self.db)
        self.scorer = QualityScorer(self.db)

    def translate_file(self, filepath: str, langs: list[str] | None = None, run_id: int | None = None):
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

        self._emit("started", f"Started translation for {path.name}", {"file": str(path), "langs": langs})
        self.cache.sync_blog_post(filepath)
        run_id = run_id or self.db.insert_pipeline_run("manual")
        start_time = time.time()

        try:
            self._emit("parsing", "Parsing MDX and checking cache", {"file": str(path)})
            diff = self.cache.diff(filepath)
            diff["source_path"] = str(path)
            print(f"\nSections: {diff['total']} total, {diff['cached']} cached, {diff['new']} to translate")
            self._emit(
                "cache_checked",
                f"Cache checked: {diff['cached']} cached, {diff['new']} new",
                {"total": diff["total"], "cached": diff["cached"], "new": diff["new"]},
            )

            for lang in langs:
                print(f"\n--- {lang.upper()} Translation ---")
                self._emit("language_started", f"Starting {lang.upper()} translation", {"lang": lang})
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
            self._emit(
                "completed",
                f"Completed in {gpu_time:.1f}s",
                {"gpu_time_sec": round(gpu_time, 2), "estimated_cost": round(cost, 6)},
            )
        except Exception as exc:
            self.db.update_pipeline_run(run_id=run_id, status="failed")
            print(f"\nPipeline failed: {exc}")
            self._emit("failed", str(exc), {"error": exc.__class__.__name__})
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
                model_name=translated_map.get(section["index"], {}).get("model", self.models.get(lang)),
                **{lang_key: translated},
            )

        all_sections.sort(key=lambda section: section["index"])

        source_parsed = parse_mdx(str(source_path))
        ko_sections = source_parsed["sections"]
        tr_sections = [{"type": section["type"], "text": section["text"]} for section in all_sections]
        scores = self.scorer.score_file(ko_sections, tr_sections, lang, filename, run_id)
        self._emit("quality_scored", f"Quality scored for {lang.upper()}", {"lang": lang, "sections": len(scores)})

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
            f"  [{self.models[lang]}] Translating {len(sections_to_translate)} section(s) "
            f"({char_count} chars total)...",
            end=" ",
            flush=True,
        )
        self._emit(
            "model_started",
            f"Sending {len(sections_to_translate)} section(s) to {self.models[lang]}",
            {
                "lang": lang,
                "model": self.models[lang],
                "sections": len(sections_to_translate),
                "characters": char_count,
            },
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
        self._emit(
            "model_completed",
            f"Model returned {len(translated)} section(s)",
            {"lang": lang, "elapsed_sec": round(elapsed, 2), "sections": len(translated)},
        )

        for payload in translated:
            validation_errors = validate_translation(
                payload["ko_text"],
                payload["translated"],
                lang,
                payload.get("section_type", "paragraph"),
            )
            llm_call_id = self._record_llm_call(run_id, payload, lang, validation_errors)
            if validation_errors:
                section_index = payload.get("index")
                self._queue_human_review(run_id, payload, lang, validation_errors, llm_call_id)
                raise RuntimeError(
                    f"Rejected invalid {lang.upper()} translation for "
                    f"{filename} section {section_index}: {'; '.join(validation_errors)}"
                )

            self.db.insert_translation_section(
                run_id=run_id,
                filename=payload.get("filename") or filename,
                section_index=payload.get("index"),
                section_type=payload.get("section_type", "paragraph"),
                target_lang=lang,
                model_name=payload.get("model", self.models[lang]),
                source_text=payload["ko_text"],
                translated_text=payload["translated"],
                input_tokens=payload.get("input_tokens", 0),
                output_tokens=payload.get("output_tokens", 0),
                latency_ms=payload.get("latency_ms", 0),
            )

        input_tokens = sum(payload.get("input_tokens", 0) or 0 for payload in translated)
        output_tokens = sum(payload.get("output_tokens", 0) or 0 for payload in translated)
        self._emit(
            "tokens_recorded",
            f"Recorded {input_tokens + output_tokens} token(s)",
            {
                "lang": lang,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
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

        payload = response.json()
        translations = payload["translations"]
        for translation in translations:
            translation.setdefault("backend", "runpod_worker")
            translation.setdefault("endpoint", "/translate")
            translation.setdefault("raw_response", translation.copy())
            translation.setdefault("raw_output", translation.get("translated", ""))
            translation.setdefault("normalized_output", translation.get("translated", ""))
            translation.setdefault("system_prompt", None)
            translation.setdefault("user_prompt", translation.get("ko_text", ""))
            translation.setdefault("glossary_text", glossary_text)
        return translations

    def _translate_direct(self, text: str, lang: str, section_type: str, index: int | None,
                          filename: str | None, glossary_text: str = "") -> dict[str, Any]:
        model = self.models[lang]
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
        elif section_type == "frontmatter_series":
            system_prompt += (
                "\n\nIMPORTANT: This is a frontmatter series value. DO NOT change the frontmatter structure. "
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
                "\n\nIMPORTANT: The input is a fenced code block. You MUST preserve the opening and closing "
                "triple-backtick fences exactly. Keep the language marker after the opening fence exactly, "
                "for example ```yaml or ```python. Preserve indentation, identifiers, URLs, commands, and string "
                "syntax exactly. Translate only human-language comments and docstrings into the target language. "
                "Do not add explanations before or after the fenced code block."
            )

        started_at = time.perf_counter()
        endpoint = "/api/chat"
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
            if response.status_code == 404 or response.status_code >= 500:
                endpoint = "/api/generate"
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

        translated = self._normalize_translated_section(text, translated_text, section_type)
        return {
            "index": index,
            "filename": filename,
            "section_type": section_type,
            "ko_text": text,
            "translated": translated,
            "model": model,
            "backend": "local_ollama",
            "endpoint": endpoint,
            "system_prompt": system_prompt,
            "user_prompt": text,
            "glossary_text": glossary_text,
            "raw_response": payload,
            "raw_output": translated_text,
            "normalized_output": translated,
            "input_tokens": payload.get("prompt_eval_count", 0),
            "output_tokens": payload.get("eval_count", 0),
            "latency_ms": round((time.perf_counter() - started_at) * 1000, 1),
            "total_duration_ns": payload.get("total_duration"),
            "prompt_eval_duration_ns": payload.get("prompt_eval_duration"),
            "eval_duration_ns": payload.get("eval_duration"),
        }

    def _record_llm_call(self, run_id: int, payload: dict[str, Any], lang: str,
                         validation_errors: list[str]):
        return self.db.insert_llm_call(
            run_id=run_id,
            filename=payload.get("filename"),
            section_index=payload.get("index"),
            section_type=payload.get("section_type", "paragraph"),
            target_lang=lang,
            backend=payload.get("backend", "unknown"),
            endpoint=payload.get("endpoint"),
            model_name=payload.get("model", self.models.get(lang)),
            system_prompt=payload.get("system_prompt"),
            user_prompt=payload.get("user_prompt") or payload.get("ko_text"),
            glossary_text=payload.get("glossary_text", ""),
            raw_response=payload.get("raw_response", {}),
            raw_output=payload.get("raw_output", ""),
            normalized_output=payload.get("normalized_output") or payload.get("translated"),
            validation_passed=not validation_errors,
            validation_errors=validation_errors,
            input_tokens=payload.get("input_tokens", 0),
            output_tokens=payload.get("output_tokens", 0),
            latency_ms=payload.get("latency_ms", 0),
            total_duration_ns=payload.get("total_duration_ns"),
            prompt_eval_duration_ns=payload.get("prompt_eval_duration_ns"),
            eval_duration_ns=payload.get("eval_duration_ns"),
        )

    def _queue_human_review(self, run_id: int, payload: dict[str, Any], lang: str,
                            validation_errors: list[str], llm_call_id: int | None):
        review_id = self.db.insert_human_review_item(
            run_id=run_id,
            llm_call_id=llm_call_id,
            filename=payload.get("filename") or "<unknown>",
            section_index=payload.get("index"),
            section_type=payload.get("section_type", "paragraph"),
            target_lang=lang,
            source_text=payload.get("ko_text") or payload.get("user_prompt") or "",
            model_output=payload.get("translated") or payload.get("normalized_output") or "",
            reason="hard_validator_failed",
            details={"validation_errors": validation_errors},
        )
        self._emit(
            "human_review_queued",
            f"Queued section {payload.get('index')} for human review",
            {"lang": lang, "review_id": review_id, "validation_errors": validation_errors},
        )

    def _release_local_model(self, model: str):
        try:
            requests.post(
                f"{self.service_url}/api/generate",
                json={"model": model, "keep_alive": 0},
                timeout=10,
            )
        except requests.RequestException:
            pass

    def _normalize_translated_section(self, source_text: str, translated_text: str, section_type: str) -> str:
        translated = self._strip_outer_json_fence(translated_text.strip())
        if section_type == "code":
            return self._restore_code_fence(source_text, translated)
        return translated

    def _strip_outer_json_fence(self, text: str) -> str:
        match = re.fullmatch(r"```(?:json)?\s*\n([\s\S]*?)\n```", text.strip(), re.IGNORECASE)
        if match:
            inner = match.group(1).strip()
            if not inner.startswith("{") and not inner.startswith("["):
                return text.strip()
            return inner
        return text.strip()

    def _restore_code_fence(self, source_text: str, translated_text: str) -> str:
        source_match = re.match(r"^(```[^\n]*)(?:\n([\s\S]*?)\n)?```$", source_text.strip())
        if not source_match:
            return translated_text.strip()

        opening_fence = source_match.group(1)
        translated = translated_text.strip()
        if translated.startswith("```") and translated.endswith("```"):
            lines = translated.splitlines()
            if lines:
                lines[0] = opening_fence
            return "\n".join(lines).strip()

        lines = translated.splitlines()
        if lines and lines[0].strip().lower() == opening_fence[3:].strip().lower():
            translated = "\n".join(lines[1:]).strip()

        return f"{opening_fence}\n{translated}\n```"

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

        validation_errors = validate_translation(
            text,
            translated["translated"],
            lang,
            section_type,
        )
        llm_call_id = self._record_llm_call(run_id, translated, lang, validation_errors)
        if validation_errors:
            self._queue_human_review(run_id, translated, lang, validation_errors, llm_call_id)
            raise RuntimeError(
                f"Rejected invalid {lang.upper()} frontmatter translation for "
                f"{filename} {field_name}: {'; '.join(validation_errors)}"
            )

        self.db.insert_translation_section(
            run_id=run_id,
            filename=filename,
            section_index=None,
            section_type=section_type,
            target_lang=lang,
            model_name=translated.get("model", self.models[lang]),
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

        output_path = self._output_path(source_path, lang)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
        print(f"  Saved: {output_path}")
        self._emit("saved", f"Saved {lang.upper()} output", {"lang": lang, "path": str(output_path)})

    def _output_path(self, source_path: Path, lang: str) -> Path:
        output_dir = self.output_dirs.get(lang)
        if not output_dir:
            return source_path.with_name(source_path.stem + f"_{lang}.mdx")

        if not self.source_root:
            return output_dir / source_path.name

        relative_path = source_path.resolve().relative_to(self.source_root.resolve())
        if len(relative_path.parts) > 1 and relative_path.parts[0] == SOURCE_LANG_DIR:
            relative_path = Path(*relative_path.parts[1:])
        return output_dir / relative_path

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

    def _emit(self, event_type: str, message: str, details: dict[str, Any] | None = None):
        if self.event_callback:
            self.event_callback(event_type, message, details or {})


def main():
    parser = argparse.ArgumentParser(description="Translate Korean MDX blog posts to EN/JP")
    parser.add_argument("file", help="Path to Korean .mdx file (e.g., samples/mdx/Algorithm_Bot_01.mdx)")
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
