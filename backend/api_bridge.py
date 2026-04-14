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
import sys
from pathlib import Path
from datetime import date

# Ensure backend/ root is on the path (scraper/, processor/, output/, db/ live here)
_BACKEND_DIR = Path(__file__).parent
sys.path.insert(0, str(_BACKEND_DIR))


def emit(event: str, **kwargs):
    """Write a JSON line to stdout and flush immediately."""
    print(json.dumps({"event": event, **kwargs}), flush=True)


async def run_bridge(sources: list, threshold: float, formats: list):
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

    config_path = _BACKEND_DIR / "config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Always resolve sheets dir relative to this file — makes the project portable
    config["output"]["sheets_dir"] = str(_BACKEND_DIR / "sheets")
    # Override output formats from caller
    config["output"]["formats"] = formats

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
        emit("source-start", source=scraper.SOURCE_ID)
        try:
            records = await scraper.scrape()
            all_records.extend(records)
            emit("source-done", source=scraper.SOURCE_ID, count=len(records))
        except Exception as exc:
            emit("source-error", source=scraper.SOURCE_ID, error=str(exc))

    raw_count = len(all_records)

    # ── Processing phase ──────────────────────────────────────────────────────
    emit("processing", message="Classifying skills…")
    records = [classify(r) for r in all_records]

    emit("processing", message="Deduplicating…")
    records = deduplicate(records)
    dedup_count = len(records)

    emit("processing", message="Scoring confidence…")
    records = [score(r) for r in records]
    records = [r for r in records if r.confidence_score >= threshold]
    final_count = len(records)

    # ── Writing phase ─────────────────────────────────────────────────────────
    emit("writing", message="Saving files…")
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

    emit(
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
    parser.add_argument("--threshold", type=float, default=0.25)
    parser.add_argument("--formats", default="csv,xlsx")
    args = parser.parse_args()

    sources = [s.strip() for s in args.sources.split(",") if s.strip()] or None
    formats = [f.strip() for f in args.formats.split(",") if f.strip()] or ["csv", "xlsx"]

    try:
        asyncio.run(run_bridge(sources, args.threshold, formats))
    except Exception as exc:
        emit("error", message=str(exc))
        sys.exit(1)
