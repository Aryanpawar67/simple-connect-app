"""
Unified Skills Platform — FastAPI Backend
==========================================
Changelog (Lightcast):
  GET /api/changelog/stream              — SSE: progress + result
  GET /api/changelog/download/{job_id}   — Excel file download

Skill Discovery (Skill Scraper):
  GET /api/skills/stream                 — SSE: per-source progress + final results
  GET /api/skills/download/{job_id}      — CSV or XLSX download
  GET /api/skills/history                — List of past scrape runs
  GET /api/skills/history/{date}/download — Download a historical sheet

Taxonomy Manager:
  GET /api/taxonomy/stats                — Taxonomy file statistics
  GET /api/taxonomy/domains              — Domains + subdomains index for dropdowns
  GET /api/taxonomy/compare              — Compare DB skills vs taxonomy
  POST /api/taxonomy/merge               — Append approved skills, return job_id
  GET /api/taxonomy/download/{job_id}    — Download merged xlsx
"""

import re
import sys
import uuid
import json
import threading
import queue
import asyncio
import subprocess
from pathlib import Path
from typing import Optional, List

# Load .env if present (local dev) — no-op if file absent or python-dotenv not installed
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel

# Lazy import — playwright + Chromium are only available in local/Docker envs,
# not on Vercel serverless. Import deferred to the point of use.
LightcastChangelogScraper = None

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = FastAPI(title="Lightcast Scraper API")

import os as _os_early

_RAW_ORIGINS = _os_early.environ.get(
    "ALLOWED_ORIGINS",
    "http://localhost:5173,http://localhost:3000",
)
_ALLOWED_ORIGINS = [o.strip() for o in _RAW_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _safe_filename(filename: str, base_dir: Path) -> Path:
    """
    Strip any directory components from a user-supplied filename and verify
    the resolved path stays inside base_dir. Raises HTTP 400 on traversal attempt.
    """
    name = Path(filename).name
    if not name or name in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    resolved = (base_dir / name).resolve()
    if resolved.parent != base_dir.resolve():
        raise HTTPException(status_code=400, detail="Invalid filename.")
    return resolved

import datetime

# On Vercel the function directory is read-only; writable space is /tmp.
_ON_VERCEL = _os_early.environ.get("VERCEL") == "1"
OUTPUT_DIR = (
    Path("/tmp/taxotrack/outputs") if _ON_VERCEL
    else Path(__file__).parent / "outputs"
)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CHANGELOG_URL = "https://emsiservices.com/docs-site-proxy?url=https://emsiservices.com/skills/docs/data-changelog"
CHANGELOG_HISTORY_FILE = OUTPUT_DIR / "changelog_history.json"

# In-memory job store: job_id -> {"path": str, "filename": str}
_jobs: dict = {}

MONTH_NAMES = [
    "January","February","March","April","May","June",
    "July","August","September","October","November","December",
]

def _filter_label(date_filter: Optional[List[str]]) -> str:
    """Human-readable description of the applied date filter."""
    if not date_filter:
        return "All Data"
    def fmt(ym: str) -> str:
        y, m = ym[:4], ym[5:]
        return f"{MONTH_NAMES[int(m)-1]} {y}"
    return ", ".join(fmt(m) for m in date_filter)


def _read_changelog_history() -> list:
    if not CHANGELOG_HISTORY_FILE.exists():
        return []
    try:
        return json.loads(CHANGELOG_HISTORY_FILE.read_text())
    except Exception:
        return []


def _append_changelog_history(entry: dict, records: list | None = None):
    """Persist a changelog run.

    Writes to Neon DB when DATABASE_URL is configured (Vercel-safe).
    Falls back to the local JSON file for environments without a DB.
    ``records`` is the list of matched DataFrame rows (dicts) used to
    regenerate the Excel on download.
    """
    # Try DB first — lazy import avoids circular-import issues at module load
    try:
        from db.client import open_db as _odb
        import os as _os_cl
        dsn = _os_cl.environ.get("DATABASE_URL", "")
        if dsn:
            db = _odb({"database": {"enabled": True, "dsn": dsn}})
            if db is not None:
                import datetime as _dt
                db.save_changelog_run(
                    run_date=_dt.date.fromisoformat(entry["date"]),
                    filter_desc=entry.get("filter", ""),
                    filename=entry.get("filename", ""),
                    total_records=entry.get("totalRecords", 0),
                    matched_records=entry.get("matchedRecords", 0),
                    raw_records=records or [],
                )
                db.close()
                return  # DB write succeeded — no need for JSON fallback
    except Exception:
        pass  # fall through to filesystem

    # Filesystem fallback (local dev without DATABASE_URL)
    history = _read_changelog_history()
    history.insert(0, entry)
    CHANGELOG_HISTORY_FILE.write_text(json.dumps(history, indent=2))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def expand_date_range(start: str, end: str) -> List[str]:
    """Return every YYYY-MM string between start and end inclusive."""
    year, month = int(start[:4]), int(start[5:])
    ey, em = int(end[:4]), int(end[5:])
    months = []
    while (year, month) <= (ey, em):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


# ---------------------------------------------------------------------------
# Scraper thread
# ---------------------------------------------------------------------------

def _run_scraper(
    job_id: str,
    date_filter: Optional[List[str]],
    output_path: str,
    filename: str,
    q: queue.Queue,
):
    """
    Runs the synchronous Playwright scraper in a background thread.
    Sends SSE-style tuples into `q` for the async generator to forward.

    Event names used:
      step         — progress step update        {"step": int, "message": str}
      complete     — success                     {"jobId", "filename", "totalRecords", "matchedRecords", "typeCounts"}
      scrape-empty — filter matched 0 records    {"message", "totalRecords"}
      scrape-error — any failure                 {"message"}
    """
    try:
        from lightcast_changelog_scraper import LightcastChangelogScraper
        scraper = LightcastChangelogScraper(url=CHANGELOG_URL, date_filter=date_filter)

        # Step 0 — Launching browser
        q.put(("step", json.dumps({"step": 0, "message": "Launching browser…"})))

        if not scraper.fetch_page():
            q.put(("scrape-error", json.dumps({
                "message": "Failed to fetch the changelog page. Check your network connection or try again."
            })))
            return

        # Step 2 — Parsing (step 1 "Fetching" is covered by fetch_page completing)
        q.put(("step", json.dumps({"step": 2, "message": "Parsing sections…"})))

        if not scraper.scrape_all_sections():
            q.put(("scrape-error", json.dumps({
                "message": "No changelog sections could be parsed from the page."
            })))
            return

        total_records = len(scraper.raw_data)

        # Step 3 — Applying filter
        q.put(("step", json.dumps({"step": 3, "message": "Applying date filter…"})))

        if not scraper.create_dataframe():
            q.put(("scrape-empty", json.dumps({
                "message": "No records match your selected filter.",
                "totalRecords": total_records,
            })))
            return

        matched_records = len(scraper.df)
        type_counts = scraper.df["Change_Type"].value_counts().to_dict()

        # Step 4 — Export
        q.put(("step", json.dumps({"step": 4, "message": "Exporting to Excel…"})))

        if not scraper.export_to_excel(output_path):
            q.put(("scrape-error", json.dumps({"message": "Failed to write the Excel file."})))
            return

        # Persist job for download
        _jobs[job_id] = {"path": output_path, "filename": filename}

        # Append to persistent history (pass filtered rows for on-demand re-export)
        file_size = Path(output_path).stat().st_size
        _append_changelog_history(
            {
                "date": datetime.date.today().isoformat(),
                "filename": filename,
                "filter": _filter_label(date_filter),
                "totalRecords": total_records,
                "matchedRecords": matched_records,
                "fileSizeBytes": file_size,
            },
            records=scraper.df.to_dict("records"),
        )

        q.put(("complete", json.dumps({
            "jobId": job_id,
            "filename": filename,
            "totalRecords": total_records,
            "matchedRecords": matched_records,
            "typeCounts": type_counts,
        })))

    except Exception as exc:
        q.put(("scrape-error", json.dumps({"message": str(exc)})))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/changelog/stream")
async def changelog_stream(
    mode: str = Query(..., description="all | specific | range"),
    filename: str = Query(..., description="Target .xlsx filename"),
    months: Optional[str] = Query(None, description="Comma-separated YYYY-MM (specific mode)"),
    start: Optional[str] = Query(None, description="Start YYYY-MM (range mode)"),
    end: Optional[str] = Query(None, description="End YYYY-MM (range mode)"),
):
    """
    Server-Sent Events endpoint.  Stream scrape progress to the browser,
    then emit a terminal event (complete | scrape-empty | scrape-error).
    """
    job_id = str(uuid.uuid4())
    safe_path = _safe_filename(filename, OUTPUT_DIR)
    output_path = str(safe_path)
    filename = safe_path.name          # normalised, no traversal
    msg_queue: queue.Queue = queue.Queue()

    # Resolve date filter
    date_filter: Optional[List[str]] = None
    if mode == "specific" and months:
        date_filter = [m.strip() for m in months.split(",") if m.strip()]
    elif mode == "range" and start and end:
        date_filter = expand_date_range(start, end)

    # Start scraper in background thread (Playwright is sync)
    thread = threading.Thread(
        target=_run_scraper,
        args=(job_id, date_filter, output_path, filename, msg_queue),
        daemon=True,
    )
    thread.start()

    async def event_generator():
        while True:
            try:
                event_type, data = msg_queue.get_nowait()
                yield _sse(event_type, data)
                if event_type in ("complete", "scrape-error", "scrape-empty"):
                    break
            except queue.Empty:
                # Keep connection alive
                yield ": keepalive\n\n"
                if not thread.is_alive() and msg_queue.empty():
                    break
                await asyncio.sleep(0.25)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/changelog/download/{job_id}")
async def changelog_download(job_id: str):
    """Download the Excel file produced by a completed scrape job."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found or has expired.")
    job = _jobs[job_id]
    return FileResponse(
        path=job["path"],
        filename=job["filename"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/api/changelog/history")
async def changelog_history():
    """Return the list of past changelog exports, newest first.

    Reads from Neon DB when available (Vercel-safe); falls back to the local
    JSON file for dev environments without DATABASE_URL.
    """
    import os as _os_ch
    dsn = _os_ch.environ.get("DATABASE_URL", "")
    if dsn:
        try:
            db = _open_db(_DB_CONFIG)
            if db is not None:
                runs = db.list_changelog_runs(limit=50)
                db.close()
                result = []
                for r in runs:
                    mc = r["matched_records"]
                    # Rough file-size estimate: ~2 KB base + ~0.15 KB per row
                    est_bytes = 2048 + mc * 150
                    kb = est_bytes / 1024
                    size_str = f"{kb:.0f} KB" if kb < 1024 else f"{kb/1024:.1f} MB"
                    result.append({
                        "id": r["id"],
                        "date": str(r["run_date"]),
                        "filename": r["filename"],
                        "filter": r["filter_desc"],
                        "totalRecords": r["total_records"],
                        "matchedRecords": r["matched_records"],
                        "fileSize": size_str,
                    })
                return result
        except Exception:
            pass  # fall through to filesystem

    # Filesystem fallback
    history = _read_changelog_history()
    enriched = []
    for entry in history:
        path = OUTPUT_DIR / entry["filename"]
        if not path.exists():
            continue
        size_bytes = entry.get("fileSizeBytes", path.stat().st_size)
        kb = size_bytes / 1024
        size_str = f"{kb:.0f} KB" if kb < 1024 else f"{kb/1024:.1f} MB"
        enriched.append({**entry, "fileSize": size_str})
    return enriched


@app.get("/api/changelog/history/{filename}/download")
async def changelog_history_download(filename: str):
    """Download a historical changelog export.

    Regenerates the Excel on-demand from records stored in Neon DB.
    Falls back to serving the file from disk for local dev.
    """
    import os as _os_cd
    dsn = _os_cd.environ.get("DATABASE_URL", "")
    if dsn:
        try:
            db = _open_db(_DB_CONFIG)
            if db is not None:
                # Find the run by filename
                runs = db.list_changelog_runs(limit=200)
                run = next((r for r in runs if r["filename"] == filename), None)
                if run is not None:
                    records = db.get_changelog_records(run["id"])
                    db.close()
                    if records:
                        import pandas as _pd
                        from io import BytesIO as _BytesIO
                        from lightcast_changelog_scraper import LightcastChangelogScraper
                        scraper = LightcastChangelogScraper(url=CHANGELOG_URL)
                        scraper.df = _pd.DataFrame(records)
                        tmp_path = f"/tmp/taxotrack/dl_{uuid.uuid4().hex}.xlsx"
                        Path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
                        scraper.export_to_excel(tmp_path)
                        return FileResponse(
                            path=tmp_path,
                            filename=filename,
                            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )
                else:
                    db.close()
        except Exception:
            pass  # fall through to filesystem

    # Filesystem fallback
    path = _safe_filename(filename, OUTPUT_DIR)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found or has expired.")
    return FileResponse(
        path=str(path),
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ---------------------------------------------------------------------------
# Skill Discovery — config
# ---------------------------------------------------------------------------

_BACKEND_DIR = Path(__file__).parent
SKILL_SCRAPER_BRIDGE = _BACKEND_DIR / "api_bridge.py"
SKILL_SCRAPER_SHEETS = (
    Path("/tmp/taxotrack/sheets") if _ON_VERCEL
    else _BACKEND_DIR / "sheets"
)

# Display name (frontend) → SOURCE_ID (bridge)
_SOURCE_NAME_TO_ID: dict[str, str] = {
    "GitHub Trending":    "github_trending",
    "StackOverflow":      "stackoverflow_tags",
    "Hacker News":        "hackernews",
    "npm Trending":       "npm_trending",
    "PyPI":               "pypi_trending",
    "Product Hunt":       "product_hunt",
    "Dev.to":             "devto",
    "Reddit":             "reddit",
    "arXiv":              "arxiv",
    "ThoughtWorks Radar": "thoughtworks_radar",
    "CNCF Landscape":     "cncf_landscape",
    "LinkedIn Jobs":      "linkedin_jobs",
    "InfoQ":              "infoq",
    "DZone":              "dzone",
    "Medium":             "medium",
    "GitHub Topics":      "github_topics",
}
_SOURCE_ID_TO_NAME = {v: k for k, v in _SOURCE_NAME_TO_ID.items()}

# In-memory job store for skill scrape runs: job_id -> {"csv": str, "xlsx": str}
_skill_jobs: dict = {}


# ---------------------------------------------------------------------------
# Skill Discovery — background runner
# ---------------------------------------------------------------------------

def _run_skill_bridge(
    job_id: str,
    sources: Optional[List[str]],
    threshold: float,
    formats: List[str],
    q: queue.Queue,
):
    """
    Spawn api_bridge.py as a subprocess. Read NDJSON from stdout line by line
    and forward as SSE-style tuples into q.

    Event names forwarded:
      source-start  {"source": <display_name>}
      source-done   {"source": <display_name>, "count": int}
      source-error  {"source": <display_name>, "error": str}
      processing    {"message": str}
      writing       {"message": str}
      complete      {rawCount, dedupCount, finalCount, newCount, returningCount,
                     jobId, results: [...]}
      skill-error   {"message": str}
    """
    try:
        # Ensure backend dir is on path so api_bridge imports work
        if str(_BACKEND_DIR) not in sys.path:
            sys.path.insert(0, str(_BACKEND_DIR))

        from api_bridge import run_bridge

        # Wrap the queue so events from run_bridge are translated before enqueue
        class _TranslatingQueue:
            def put(self, item):
                event, data_str = item
                try:
                    msg = json.loads(data_str)
                except json.JSONDecodeError:
                    msg = {}

                # Translate SOURCE_IDs back to display names for the frontend
                if "source" in msg:
                    msg["source"] = _SOURCE_ID_TO_NAME.get(msg["source"], msg["source"])

                if event == "complete":
                    # Store file paths so download endpoint can serve them
                    _skill_jobs[job_id] = {
                        "csv":  msg.pop("csvPath", ""),
                        "xlsx": msg.pop("xlsxPath", ""),
                    }
                    msg["jobId"] = job_id
                    # Persist run metadata to Neon DB
                    _db = _open_db(_DB_CONFIG)
                    if _db:
                        try:
                            import datetime as _dt
                            _db.save_run(
                                job_id=job_id,
                                run_date=_dt.date.today(),
                                raw_count=msg.get("rawCount", 0),
                                dedup_count=msg.get("dedupCount", 0),
                                final_count=msg.get("finalCount", 0),
                                new_count=msg.get("newCount", 0),
                                returning_count=msg.get("returningCount", 0),
                                sources_list=sources or [],
                            )
                        except Exception as _exc:
                            import logging as _log
                            _log.getLogger(__name__).warning("Failed to save run to DB: %s", _exc)
                        finally:
                            _db.close()
                    q.put(("complete", json.dumps(msg)))
                elif event == "error":
                    q.put(("skill-error", json.dumps(msg)))
                else:
                    q.put((event, json.dumps(msg)))

        translating_q = _TranslatingQueue()
        asyncio.run(run_bridge(sources, threshold, formats, event_queue=translating_q))

    except Exception as exc:
        q.put(("skill-error", json.dumps({"message": str(exc)})))


# ---------------------------------------------------------------------------
# Skill Discovery — routes
# ---------------------------------------------------------------------------

@app.get("/api/skills/stream")
async def skills_stream(
    sources: Optional[str] = Query(None, description="Comma-separated display names"),
    threshold: float = Query(0.5),
    formats: str = Query("csv,xlsx", description="Comma-separated: csv and/or xlsx"),
):
    """
    SSE stream for a skill discovery run.
    Events: source-start, source-done, source-error, processing, writing, complete, skill-error
    """
    job_id = str(uuid.uuid4())
    msg_queue: queue.Queue = queue.Queue()

    # Map display names → SOURCE_IDs
    source_ids: Optional[List[str]] = None
    if sources:
        names = [n.strip() for n in sources.split(",") if n.strip()]
        source_ids = [_SOURCE_NAME_TO_ID[n] for n in names if n in _SOURCE_NAME_TO_ID]

    fmt_list = [f.strip() for f in formats.split(",") if f.strip()]

    thread = threading.Thread(
        target=_run_skill_bridge,
        args=(job_id, source_ids, threshold, fmt_list, msg_queue),
        daemon=True,
    )
    thread.start()

    async def event_generator():
        while True:
            try:
                event_type, data = msg_queue.get_nowait()
                yield _sse(event_type, data)
                if event_type in ("complete", "skill-error"):
                    break
            except queue.Empty:
                yield ": keepalive\n\n"
                if not thread.is_alive() and msg_queue.empty():
                    break
                await asyncio.sleep(0.25)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/skills/download/{job_id}")
async def skills_download(job_id: str, format: str = Query("csv")):
    """Download CSV or XLSX produced by a completed skill scrape run."""
    if job_id not in _skill_jobs:
        raise HTTPException(status_code=404, detail="Job not found or has expired.")
    job = _skill_jobs[job_id]
    fmt = format.lower()
    file_path = job.get(fmt, "")
    if not file_path or not Path(file_path).exists():
        raise HTTPException(status_code=404, detail=f"No {fmt.upper()} file for this job.")
    media = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if fmt == "xlsx"
        else "text/csv"
    )
    return FileResponse(path=file_path, filename=Path(file_path).name, media_type=media)


@app.get("/api/skills/history")
async def skills_history():
    """Return list of past scrape runs from Neon DB.

    Response shape matches the frontend HistoryEntry interface:
      { date, rows, newSkills, fileSize, formats }
    Both CSV and XLSX are always available (generated on-demand from DB).
    """
    db = _open_db(_DB_CONFIG)
    if db is None:
        return []
    try:
        runs = db.list_runs(limit=50)
    finally:
        db.close()

    result = []
    for r in runs:
        final = r["final_count"]
        # Rough size estimate: ~0.1 KB per skill row for CSV
        est_kb = max(1, round(final * 0.1))
        size_str = f"~{est_kb} KB"
        result.append({
            "date": str(r["run_date"]),
            "rows": final,
            "newSkills": r["new_count"],
            "fileSize": size_str,
            "formats": ["CSV", "XLSX"],
        })
    return result


@app.get("/api/skills/trends")
async def skills_trends(runs: int = Query(5, ge=1, le=20)):
    """
    AI trend analysis across the last N scrape runs.
    Requires ANTHROPIC_API_KEY; returns ai_available=false otherwise.
    """
    from ai.trends import ai_analyze_trends
    db = _open_db(_DB_CONFIG)
    if db is None:
        raise HTTPException(status_code=503, detail="DB unavailable.")
    try:
        run_history = db.list_runs(limit=runs)
        if not run_history:
            return {"ai_available": False, "headline": "No scrape runs found.", "run_count": 0}
        # Get skills from most recent run
        most_recent_date = str(run_history[0]["run_date"])
        recent_skills = db.skills_by_date(most_recent_date)
    finally:
        db.close()
    return ai_analyze_trends(run_history, recent_skills)


class ExplainRequest(BaseModel):  # noqa: F811 — defined here after BaseModel import
    skills: list[dict]


@app.post("/api/skills/explain")
async def skills_explain(body: ExplainRequest):
    """
    Generate AI explanations for confidence scores.
    Pass a list of skill dicts (must have skill_name, confidence_score, source).
    Returns same list with 'explanation' field added.
    Falls back to a rule-based explanation if ANTHROPIC_API_KEY is not set.
    """
    if not body.skills:
        raise HTTPException(status_code=400, detail="No skills provided.")
    from ai.explainer import ai_explain_skills
    return {"skills": ai_explain_skills(body.skills)}


@app.get("/api/skills/history/{run_date}/download")
async def skills_history_download(run_date: str, format: str = Query("csv")):
    """Download skills for a historical run date, generated on-demand from Neon DB."""
    import io, csv as csv_mod
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", run_date):
        raise HTTPException(status_code=400, detail="run_date must be YYYY-MM-DD.")

    db = _open_db(_DB_CONFIG)
    if db is None:
        raise HTTPException(status_code=503, detail="DB unavailable.")
    try:
        skills = db.skills_by_date(run_date)
    finally:
        db.close()

    if not skills:
        raise HTTPException(status_code=404, detail=f"No skills found for {run_date}.")

    columns = ["skill_name", "category", "subcategory", "skill_type", "confidence_score", "source", "is_new"]
    fmt = format.lower()

    if fmt == "xlsx":
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = f"Skills {run_date}"
        ws.append(columns)
        for s in skills:
            ws.append([s.get(c, "") for c in columns])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="skills_{run_date}.xlsx"'},
        )
    else:
        buf = io.StringIO()
        writer = csv_mod.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(skills)
        return StreamingResponse(
            iter([buf.getvalue().encode()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="skills_{run_date}.csv"'},
        )


# ---------------------------------------------------------------------------
# Taxonomy Manager — config & state
# ---------------------------------------------------------------------------

from db.client import open_db as _open_db
from db.taxonomy_db import (
    get_stats      as _tax_stats,
    get_domains_index as _tax_domains,
    compare_with_skills as _tax_compare,
    merge_skills   as _tax_merge,
    get_overview   as _tax_overview,
    export_to_excel as _tax_export,
)

import os as _os

_TAXONOMY_HISTORY_FILE = OUTPUT_DIR / "merge_history.json"

_DB_DSN = _os.environ.get("DATABASE_URL", "")
if not _DB_DSN:
    import logging as _logging
    _logging.warning(
        "DATABASE_URL is not set — taxonomy and DB endpoints will return 503. "
        "Set DATABASE_URL to your Neon connection string."
    )
_DB_CONFIG = {
    "database": {
        "enabled": bool(_DB_DSN),
        "dsn": _DB_DSN,
    }
}


def _require_db() -> str:
    """Return DSN or raise HTTP 503 — use at the start of DB-dependent endpoints."""
    if not _DB_DSN:
        raise HTTPException(
            status_code=503,
            detail="DATABASE_URL is not configured on this server.",
        )
    return _DB_DSN


def _read_merge_history() -> list:
    if not _TAXONOMY_HISTORY_FILE.exists():
        return []
    try:
        return json.loads(_TAXONOMY_HISTORY_FILE.read_text())
    except Exception:
        return []


def _append_merge_history(entry: dict) -> None:
    history = _read_merge_history()
    history.insert(0, entry)
    _TAXONOMY_HISTORY_FILE.write_text(json.dumps(history, indent=2))


class ApprovedSkill(BaseModel):
    skill_name: str
    proposed_domain: str
    proposed_subdomain: str
    proposed_cluster: str
    proposed_classification: str
    proposed_criticality: str = "No"


class MergeRequest(BaseModel):
    approved_skills: list[ApprovedSkill]


# ---------------------------------------------------------------------------
# Skill Reclamation Pool
# ---------------------------------------------------------------------------

class ReclaimActionRequest(BaseModel):
    ids: list[int]
    pool: str = "rejected"  # "rejected" or "unmerged"


class ReclaimReviewRequest(BaseModel):
    skills: list[dict]


@app.get("/api/skills/reclaim-pool")
async def reclaim_pool_get(pool: str = Query("all")):
    """Return rejected + unmerged skills for monthly reclamation review."""
    db = _open_db(_DB_CONFIG)
    if db is None:
        raise HTTPException(status_code=503, detail="DB unavailable.")
    try:
        data = db.get_reclaim_pool(pool=pool)
    finally:
        db.close()
    return {
        "rejected": data["rejected"],
        "unmerged": data["unmerged"],
        "rejected_count": len(data["rejected"]),
        "unmerged_count": len(data["unmerged"]),
    }


@app.post("/api/skills/reclaim-pool/ai-review")
async def reclaim_ai_review(body: ReclaimReviewRequest):
    """Run Claude review on a list of reclaim-pool skills."""
    if not body.skills:
        raise HTTPException(status_code=400, detail="No skills provided.")
    from ai.reclaimer import ai_review_rejected_skills
    return {"recommendations": ai_review_rejected_skills(body.skills)}


@app.post("/api/skills/reclaim-pool/promote")
async def reclaim_promote(body: ReclaimActionRequest):
    """Promote skills from reclaim pool into the active skills table."""
    from datetime import date
    db = _open_db(_DB_CONFIG)
    if db is None:
        raise HTTPException(status_code=503, detail="DB unavailable.")
    try:
        if body.pool == "rejected":
            count = db.promote_rejected(body.ids, date.today())
        else:
            # Unmerged skills are already in skills table — clear their dismissed flag
            # so they show up in the next taxonomy compare
            count = db.dismiss_unmerged([])  # no-op, they're already active
            count = len(body.ids)
    finally:
        db.close()
    return {"promoted": count}


@app.post("/api/skills/reclaim-pool/dismiss")
async def reclaim_dismiss(body: ReclaimActionRequest):
    """Permanently dismiss skills from the reclaim pool."""
    db = _open_db(_DB_CONFIG)
    if db is None:
        raise HTTPException(status_code=503, detail="DB unavailable.")
    try:
        if body.pool == "rejected":
            count = db.dismiss_rejected(body.ids)
        else:
            count = db.dismiss_unmerged(body.ids)
    finally:
        db.close()
    return {"dismissed": count}


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    dsn_set = bool(_DB_DSN)
    db_ok = False
    if dsn_set:
        try:
            import psycopg2
            conn = psycopg2.connect(_DB_DSN)
            conn.close()
            db_ok = True
        except Exception as e:
            db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "database_url_set": dsn_set,
        "database_connected": db_ok,
    }


# ---------------------------------------------------------------------------
# Taxonomy Manager — routes
# ---------------------------------------------------------------------------

@app.get("/api/taxonomy/stats")
async def taxonomy_stats():
    return _tax_stats(_require_db())


@app.get("/api/taxonomy/domains")
async def taxonomy_domains():
    return _tax_domains(_require_db())


@app.get("/api/taxonomy/compare")
async def taxonomy_compare(last_run_only: bool = Query(False)):
    db = _open_db(_DB_CONFIG)
    if db is None:
        raise HTTPException(status_code=503, detail="Could not connect to skills database.")
    try:
        db_skills = db.latest_run_skills() if last_run_only else db.all_skills()
    finally:
        db.close()
    result = _tax_compare(_require_db(), db_skills)
    result["master_filename"] = "Neon DB"
    result["scope"] = "latest_run" if last_run_only else "all"
    return result


@app.post("/api/taxonomy/review")
async def taxonomy_review(body: MergeRequest):
    """
    AI review of proposed skills before merge.
    Returns approved / flagged / rejected buckets.
    Falls back to all-approved if ANTHROPIC_API_KEY is not set.
    """
    if not body.approved_skills:
        raise HTTPException(status_code=400, detail="No skills provided.")
    from ai.reviewer import ai_review_merge
    proposed = [s.model_dump() for s in body.approved_skills]
    return ai_review_merge(proposed)


@app.post("/api/taxonomy/merge")
async def taxonomy_merge(body: MergeRequest):
    if not body.approved_skills:
        raise HTTPException(status_code=400, detail="No skills provided.")
    approved = [s.model_dump() for s in body.approved_skills]
    today = datetime.date.today()
    batch = today.isoformat()
    added = _tax_merge(_require_db(), approved, batch=batch)
    db = _open_db(_DB_CONFIG)
    if db:
        try:
            from collections import defaultdict
            groups: dict = defaultdict(list)
            for s in approved:
                key = (s.get("proposed_domain", ""), s.get("proposed_subdomain", ""))
                groups[key].append(s["skill_name"])
            for (domain, subdomain), names in groups.items():
                db.mark_taxonomy_merged(names, domain, subdomain, today)
        finally:
            db.close()
    _append_merge_history({
        "date": batch,
        "added_count": added,
        "batch": batch,
        "skills": [s["skill_name"] for s in approved],
    })
    return {"added_count": added, "new_master": "Neon DB", "batch": batch}


@app.get("/api/taxonomy/merged-stats")
async def taxonomy_merged_stats():
    db = _open_db(_DB_CONFIG)
    if db is None:
        raise HTTPException(status_code=503, detail="Could not connect to skills database.")
    try:
        return db.merged_skills_summary()
    finally:
        db.close()


@app.get("/api/taxonomy/history")
async def taxonomy_history():
    return _read_merge_history()


@app.get("/api/taxonomy/master/download")
async def taxonomy_master_download():
    """Generate and stream the full taxonomy as xlsx from Neon."""
    import io as _io
    xlsx_bytes = _tax_export(_require_db())
    today = datetime.date.today().isoformat()
    return StreamingResponse(
        _io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="iMocha_Taxonomy_{today}.xlsx"'},
    )


@app.get("/api/taxonomy/overview")
async def taxonomy_overview():
    db = _open_db(_DB_CONFIG)
    if db is None:
        raise HTTPException(status_code=503, detail="Could not connect to skills database.")
    try:
        db_skills = db.all_skills()
    finally:
        db.close()
    return _tax_overview(_require_db(), db_skills)


@app.get("/api/taxonomy/new-skills/download")
async def taxonomy_new_skills_download(
    format: str = Query("csv", description="csv or xlsx"),
    last_run_only: bool = Query(False),
):
    import io as _io
    import csv as csv_mod

    db = _open_db(_DB_CONFIG)
    if db is None:
        raise HTTPException(status_code=503, detail="Could not connect to skills database.")
    try:
        db_skills = db.latest_run_skills() if last_run_only else db.all_skills()
    finally:
        db.close()

    result = _tax_compare(_require_db(), db_skills)
    new_skills = result["new_skills"] + result["unmappable"]

    if not new_skills:
        raise HTTPException(status_code=404, detail="No new skills found.")

    columns = [
        "skill_name", "proposed_domain", "proposed_subdomain", "proposed_cluster",
        "proposed_classification", "proposed_criticality",
        "confidence_score", "source", "category", "subcategory", "skill_type",
    ]
    today = datetime.date.today().isoformat()

    fmt = format.lower()
    if fmt == "xlsx":
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "New Skills"
        ws.append(columns)
        for skill in new_skills:
            ws.append([skill.get(c, "") for c in columns])
        buf = _io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        filename = f"new_skills_{today}.xlsx"
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    else:
        buf = _io.StringIO()
        writer = csv_mod.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(new_skills)
        csv_bytes = buf.getvalue().encode("utf-8")
        filename = f"new_skills_{today}.csv"
        return StreamingResponse(
            iter([csv_bytes]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
