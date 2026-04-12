from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from local_llm_observability.blog_scanner import DEFAULT_LANG_DIRS, DEFAULT_LAYOUT, DEFAULT_SOURCE_DIR, scan_blog_posts
from local_llm_observability.db.db_manager import DBManager
from local_llm_observability.mdx_parser import parse_mdx
from local_llm_observability.translator import OLLAMA_LOCAL_URL, Translator


app = FastAPI(title="Local LLM Translator Controller")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TranslateRequest(BaseModel):
    relative_path: str
    lang: Literal["en", "jp"]
    model: str = "gemma4:latest"
    backend: Literal["local", "runpod"] = "local"
    runpod_url: str | None = None


def _db() -> DBManager:
    return DBManager()


def _source_path(relative_path: str) -> Path:
    source_root = Path(DEFAULT_SOURCE_DIR).expanduser().resolve()
    path = (source_root / relative_path).resolve()
    if source_root not in path.parents and path != source_root:
        raise HTTPException(status_code=400, detail="Path escapes source directory")
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Source file not found: {relative_path}")
    return path


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "source_dir": DEFAULT_SOURCE_DIR}


@app.get("/api/posts")
def posts() -> dict:
    summary = scan_blog_posts(
        source_dir=DEFAULT_SOURCE_DIR,
        langs=["en", "jp"],
        layout=DEFAULT_LAYOUT,
        en_dir=DEFAULT_LANG_DIRS["en"],
        jp_dir=DEFAULT_LANG_DIRS["jp"],
    )
    return summary.to_dict()


@app.get("/api/file-detail")
def file_detail(path: str) -> dict:
    source_path = _source_path(path)
    content = source_path.read_text(encoding="utf-8")
    parsed = parse_mdx(str(source_path))
    lines = content.count("\n") + 1
    code_sections = [section for section in parsed["sections"] if section["type"] == "code"]
    paragraph_sections = [section for section in parsed["sections"] if section["type"] != "code"]

    return {
        "relative_path": path,
        "absolute_path": str(source_path),
        "filename": source_path.name,
        "characters": len(content),
        "bytes": source_path.stat().st_size,
        "lines": lines,
        "sections": len(parsed["sections"]),
        "paragraph_sections": len(paragraph_sections),
        "code_sections": len(code_sections),
        "frontmatter": parsed["frontmatter"],
    }


@app.get("/api/runs")
def runs(limit: int = 20) -> dict:
    db = _db()
    try:
        return {"runs": db.get_recent_pipeline_runs(limit=limit)}
    finally:
        db.close()


@app.get("/api/runs/{run_id}")
def run_detail(run_id: int) -> dict:
    db = _db()
    try:
        run = db.get_pipeline_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return {"run": run, "events": db.get_run_events(run_id)}
    finally:
        db.close()


@app.get("/api/quality/rubric/{lang}")
def quality_rubric(lang: Literal["en", "jp"]) -> dict:
    db = _db()
    try:
        rubric = db.get_active_translation_rubric(lang)
        if not rubric:
            raise HTTPException(status_code=404, detail="No active rubric found")
        return {"rubric": rubric}
    finally:
        db.close()


@app.get("/api/llm-calls")
def llm_calls(
    run_id: int | None = None,
    validation_passed: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    db = _db()
    try:
        return {
            "calls": db.get_recent_llm_calls(
                run_id=run_id,
                validation_passed=validation_passed,
                limit=limit,
            )
        }
    finally:
        db.close()


@app.get("/api/review-queue")
def review_queue(
    status: str = "open",
    target_lang: Literal["en", "jp"] | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    db = _db()
    try:
        return {
            "items": db.get_human_review_queue(
                status=status,
                target_lang=target_lang,
                limit=limit,
            )
        }
    finally:
        db.close()


@app.post("/api/translate")
def translate(request: TranslateRequest) -> dict:
    source_path = _source_path(request.relative_path)
    db = _db()
    try:
        run_id = db.insert_pipeline_run("dashboard")
        db.insert_run_event(
            run_id,
            "queued",
            f"Queued {request.lang.upper()} translation",
            {"file": request.relative_path, "model": request.model, "backend": request.backend},
        )
    finally:
        db.close()

    thread = threading.Thread(target=_run_translation, args=(run_id, source_path, request), daemon=True)
    thread.start()
    return {"run_id": run_id, "status": "queued", "file": request.relative_path}


@app.get("/api/runs/{run_id}/events")
def run_events(run_id: int) -> StreamingResponse:
    def stream():
        last_event_id = 0
        terminal = {"completed", "failed"}
        while True:
            db = _db()
            try:
                events = db.get_run_events(run_id, after_id=last_event_id)
            finally:
                db.close()

            for event in events:
                last_event_id = event["id"]
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event["event_type"] in terminal:
                    return

            time.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream")


def _run_translation(run_id: int, source_path: Path, request: TranslateRequest):
    output_dirs = {
        "en": DEFAULT_LANG_DIRS["en"],
        "jp": DEFAULT_LANG_DIRS["jp"],
    }
    model_overrides = {request.lang: request.model}
    service_url = request.runpod_url if request.backend == "runpod" and request.runpod_url else OLLAMA_LOCAL_URL
    use_worker = request.backend == "runpod"

    def emit(event_type: str, message: str, details: dict | None = None):
        db = _db()
        try:
            db.insert_run_event(run_id, event_type, message, details or {})
        finally:
            db.close()

    try:
        translator = Translator(
            service_url=service_url,
            use_worker=use_worker,
            output_dirs=output_dirs,
            source_root=DEFAULT_SOURCE_DIR,
            model_overrides=model_overrides,
            event_callback=emit,
        )
        translator.translate_file(str(source_path), [request.lang], run_id=run_id)
    except Exception as exc:
        db = _db()
        try:
            db.update_pipeline_run(run_id=run_id, status="failed")
        finally:
            db.close()
        emit("failed", str(exc), {"error": exc.__class__.__name__})
