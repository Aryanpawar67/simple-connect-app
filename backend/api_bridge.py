#!/usr/bin/env python3
"""
api_bridge.py — subprocess bridge between the FastAPI server and Skill Scraper.

Outputs one JSON line per event to stdout (NDJSON). Called by server.py.
Lives in simple-connect-app/backend/ alongside all scraper modules.

Usage:
  python api_bridge.py \
    --sources github_trending,stackoverflow_tags \
    --threshold 0.25 \
    --formats csv,xlsx
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import date

# Load .env if present (local dev)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# Ensure backend/ root is on the path (scraper/, processor/, output/, db/ live here)
_BACKEND_DIR = Path(__file__).parent
sys.path.insert(0, str(_BACKEND_DIR))


def emit(event: str, **kwargs):
    """Write a JSON line to stdout and flush immediately."""
    print(json.dumps({"event": event, **kwargs}), flush=True)


async def run_bridge(sources: list, threshold: float, formats: list, event_queue=None):
    import yaml
    from scraper.github_trending import GitHubTrendingScraper
    from scraper.stackoverflow_tags import StackOverflowTagsScraper
    from scraper.hackernews import HackerNewsScraper
    from scraper.npm_trending import NpmTrendingScraper
    from scraper.pypi_trending import PypiTrendingScraper
    from scraper.product_hunt import ProductHuntScraper
    from scraper.devto import DevtoScraper
    from scraper.reddit import RedditScraper
    from scraper.arxiv import ArxivScraper
    from scraper.thoughtworks_radar import ThoughtworksRadarScraper
    from scraper.cncf_landscape import CncfLandscapeScraper
    from scraper.linkedin_jobs import LinkedInJobsScraper
    from scraper.infoq import InfoqScraper
    from scraper.dzone import DzoneScraper
    from scraper.medium import MediumScraper
    from scraper.github_topics import GitHubTopicsScraper
    from processor.classifier import classify
    from processor.deduplicator import deduplicate
    from processor.confidence import score
    from output.writer import write_output
    from db.client import open_db

    # Local emit: route to queue when provided, otherwise print to stdout
    def _emit(event: str, **kwargs):
        if event_queue is not None:
            event_queue.put((event, json.dumps(kwargs)))
        else:
            emit(event, **kwargs)

    config_path = _BACKEND_DIR / "config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Resolve sheets dir — try backend/sheets first, fall back to /tmp (Vercel, read-only fs)
    _preferred = _BACKEND_DIR / "sheets"
    try:
        _preferred.mkdir(parents=True, exist_ok=True)
        _sheets_dir = _preferred
    except OSError:
        _sheets_dir = Path("/tmp/taxotrack/sheets")
        _sheets_dir.mkdir(parents=True, exist_ok=True)
    config["output"]["sheets_dir"] = str(_sheets_dir)
    # Override output formats from caller
    config["output"]["formats"] = formats
    # Inject DATABASE_URL from env — overrides the (now empty) dsn in config.yaml
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url:
        config["database"]["dsn"] = db_url
    elif not config["database"].get("dsn"):
        _emit("error", message="DATABASE_URL is not set — DB unavailable, falling back to CSV.")
        config["database"]["enabled"] = False

    ALL_SCRAPER_CLASSES = [
        GitHubTrendingScraper, StackOverflowTagsScraper, HackerNewsScraper,
        NpmTrendingScraper, PypiTrendingScraper, ProductHuntScraper,
        DevtoScraper, RedditScraper, ArxivScraper, ThoughtworksRadarScraper,
        CncfLandscapeScraper, LinkedInJobsScraper, InfoqScraper,
        DzoneScraper, MediumScraper, GitHubTopicsScraper,
    ]

    # Select active scrapers — sources list overrides config enabled flags
    active = [
        S(config) for S in ALL_SCRAPER_CLASSES
        if sources is None or S.SOURCE_ID in sources
    ]

    # ── Scraping phase ────────────────────────────────────────────────────────
    all_records = []
    for scraper in active:
        _emit("source-start", source=scraper.SOURCE_ID)
        try:
            records = await scraper.scrape()
            all_records.extend(records)
            _emit("source-done", source=scraper.SOURCE_ID, count=len(records))
        except Exception as exc:
            _emit("source-error", source=scraper.SOURCE_ID, error=str(exc))

    raw_count = len(all_records)

    # ── Pre-filter: skip skills already in DB ─────────────────────────────────
    # Load all normalized names already stored so we only process genuine new candidates.
    # Falls back gracefully if DB is unavailable.
    try:
        from db.client import open_db
        from processor.deduplicator import normalize_name
        _pre_db = open_db(config)
        if _pre_db:
            known_norms: set = {normalize_name(s["skill_name"]) for s in _pre_db.all_skills()}
            _pre_db.close()
            before = len(all_records)
            all_records = [r for r in all_records if normalize_name(r.skill_name) not in known_norms]
            _emit("processing", message=f"Pre-filter: {before - len(all_records)} already known, {len(all_records)} new candidates to process.")
    except Exception:
        pass  # If pre-filter fails, process everything as before

    # ── Processing phase ──────────────────────────────────────────────────────
    _emit("processing", message="Classifying skills…")
    records = [classify(r) for r in all_records]

    _emit("processing", message="AI-enhancing unclassified skills…")
    from processor.classifier import ai_enhance_classification
    records = ai_enhance_classification(records)

    _emit("processing", message="Deduplicating…")
    records = deduplicate(records)

    _emit("processing", message="AI semantic dedup check…")
    from processor.deduplicator import ai_enhance_dedup
    records = ai_enhance_dedup(records)
    dedup_count = len(records)

    _emit("processing", message="Scoring confidence…")
    records = [score(r) for r in records]
    records = [r for r in records if r.confidence_score >= threshold]
    final_count = len(records)

    # ── Writing phase ─────────────────────────────────────────────────────────
    _emit("writing", message="Saving files…")
    db = open_db(config)
    run_date = date.today()
    paths = write_output(records, config, run_date=run_date, db=db)
    if db is not None:
        db.close()

    new_count = sum(1 for r in records if r.is_new)
    returning_count = final_count - new_count

    # Top 30 for inline preview
    top30 = [
        {
            "skill_name": r.skill_name,
            "category": r.category,
            "confidence_score": round(r.confidence_score, 4),
            "popularity": r.popularity,
            "is_new": r.is_new,
            "source": r.source,
        }
        for r in records[:30]
    ]

    _emit(
        "complete",
        rawCount=raw_count,
        dedupCount=dedup_count,
        finalCount=final_count,
        newCount=new_count,
        returningCount=returning_count,
        csvPath=str(paths.get("csv", "")),
        xlsxPath=str(paths.get("xlsx", "")),
        results=top30,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Skill Scraper API bridge")
    parser.add_argument(
        "--sources", default="",
        help="Comma-separated SOURCE_IDs to run. Empty = all enabled in config.",
    )
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--formats", default="csv,xlsx")
    args = parser.parse_args()

    sources = [s.strip() for s in args.sources.split(",") if s.strip()] or None
    formats = [f.strip() for f in args.formats.split(",") if f.strip()] or ["csv", "xlsx"]

    try:
        asyncio.run(run_bridge(sources, args.threshold, formats))
    except Exception as exc:
        emit("error", message=str(exc))
        sys.exit(1)
