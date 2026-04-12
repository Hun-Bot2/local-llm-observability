"""Automated weekly pipeline analytics.

Aggregates pipeline_runs, translation_quality, and cache stats
into the weekly_reports table. Designed to run via cron every Monday.

Usage:
    python -m local_llm_observability.weekly_report           # generate report for last week
    python -m local_llm_observability.weekly_report --dry-run # preview without writing to DB

Cron setup (every Monday at 9:00 AM):
    0 9 * * 1 cd /path/to/local-llm-observability && venv/bin/python -m local_llm_observability.weekly_report
"""

import argparse
from datetime import date, timedelta

from local_llm_observability.db.db_manager import DBManager


def generate_report(db: DBManager, week_start: date = None, dry_run: bool = False):
    """Generate a weekly report for the given week."""
    if week_start is None:
        # Default: last Monday to last Sunday
        today = date.today()
        last_monday = today - timedelta(days=today.weekday() + 7)
        week_start = last_monday

    week_end = week_start + timedelta(days=7)

    print(f"Weekly Report: {week_start} to {week_end}")
    print("=" * 50)

    # Aggregate pipeline runs
    runs = db.get_pipeline_runs_between(str(week_start), str(week_end))
    completed_runs = [r for r in runs if r["status"] == "completed"]

    total_runs = len(runs)
    total_files = sum(r["total_files"] for r in completed_runs)
    total_cached = sum(r["cached_sections"] for r in completed_runs)
    total_new = sum(r["new_sections"] for r in completed_runs)
    total_gpu_time = sum(r["gpu_time_sec"] for r in completed_runs)
    total_cost = sum(r["estimated_cost"] for r in completed_runs)
    total_sections = total_cached + total_new
    cache_hit_rate = total_cached / total_sections if total_sections > 0 else 0.0

    # Aggregate quality scores
    quality = db.get_quality_scores_between(str(week_start), str(week_end))
    en_scores = [q["composite_score"] for q in quality if q["target_lang"] == "en" and q["composite_score"]]
    jp_scores = [q["composite_score"] for q in quality if q["target_lang"] == "jp" and q["composite_score"]]
    avg_en = sum(en_scores) / len(en_scores) if en_scores else None
    avg_jp = sum(jp_scores) / len(jp_scores) if jp_scores else None

    # Print summary
    print(f"  Pipeline runs:    {total_runs} ({len(completed_runs)} completed)")
    print(f"  Posts translated: {total_files}")
    print(f"  Sections:         {total_sections} total ({total_cached} cached, {total_new} new)")
    print(f"  Cache hit rate:   {cache_hit_rate:.1%}")
    print(f"  GPU time:         {total_gpu_time:.1f}s")
    print(f"  Cost:             ${total_cost:.4f}")
    print(f"  Avg quality (EN): {f'{avg_en:.3f}' if avg_en else 'N/A'}")
    print(f"  Avg quality (JP): {f'{avg_jp:.3f}' if avg_jp else 'N/A'}")

    if dry_run:
        print("\n[Dry run — not saved to DB]")
        return

    # Store in weekly_reports table
    db.insert_weekly_report(
        week_start=str(week_start),
        week_end=str(week_end),
        posts_translated=total_files,
        total_sections=total_sections,
        cached_sections=total_cached,
        new_sections=total_new,
        avg_quality_en=avg_en,
        avg_quality_jp=avg_jp,
        total_gpu_time_sec=total_gpu_time,
        total_cost=total_cost,
        pipeline_runs=total_runs,
        cache_hit_rate=cache_hit_rate,
    )
    print("\nReport saved to weekly_reports table.")


def main():
    parser = argparse.ArgumentParser(description="Generate weekly translation pipeline report")
    parser.add_argument("--dry-run", action="store_true", help="Preview report without saving")
    parser.add_argument("--week-start", help="Week start date (YYYY-MM-DD), defaults to last Monday")
    args = parser.parse_args()

    week_start = date.fromisoformat(args.week_start) if args.week_start else None

    db = DBManager()
    try:
        generate_report(db, week_start=week_start, dry_run=args.dry_run)
    finally:
        db.close()


if __name__ == "__main__":
    main()
