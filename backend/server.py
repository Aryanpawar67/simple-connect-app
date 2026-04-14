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

import sys
import uuid
import json
import threading
import queue
import asyncio
import subprocess
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse

from lightcast_changelog_scraper import LightcastChangelogScraper

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = FastAPI(title="Lightcast Scraper API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

import datetime

OUTPUT_DIR = Path(__file__).parent / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CHANGELOG_URL = "https://docs.lightcast.dev/updates/skills-taxonomy-changelog"
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


def _append_changelog_history(entry: dict):
    history = _read_changelog_history()
    history.insert(0, entry)          # newest first
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

        # Append to persistent history
        file_size = Path(output_path).stat().st_size
        _append_changelog_history({
            "date": datetime.date.today().isoformat(),
            "filename": filename,
            "filter": _filter_label(date_filter),
            "totalRecords": total_records,
            "matchedRecords": matched_records,
            "fileSizeBytes": file_size,
        })

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
    output_path = str(OUTPUT_DIR / filename)
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
    """Return the list of past changelog exports, newest first."""
    history = _read_changelog_history()
    # Attach human-readable file size and confirm file still exists
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
    """Download a historical changelog export by filename."""
    path = OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        path=str(path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ---------------------------------------------------------------------------
# Skill Discovery — config
# ---------------------------------------------------------------------------

_BACKEND_DIR = Path(__file__).parent
SKILL_SCRAPER_BRIDGE = _BACKEND_DIR / "api_bridge.py"
SKILL_SCRAPER_SHEETS = _BACKEND_DIR / "sheets"

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
        cmd = [
            sys.executable,
            str(SKILL_SCRAPER_BRIDGE),
            "--threshold", str(threshold),
            "--formats", ",".join(formats),
        ]
        if sources:
            cmd += ["--sources", ",".join(sources)]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(_BACKEND_DIR),
        )

        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            event = msg.pop("event", None)
            if event is None:
                continue

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
                q.put(("complete", json.dumps(msg)))
            elif event == "error":
                q.put(("skill-error", json.dumps(msg)))
            else:
                q.put((event, json.dumps(msg)))

        proc.wait()

        if proc.returncode != 0 and job_id not in _skill_jobs:
            stderr = proc.stderr.read() if proc.stderr else ""
            q.put(("skill-error", json.dumps({"message": stderr or "Bridge process failed"})))

    except Exception as exc:
        q.put(("skill-error", json.dumps({"message": str(exc)})))


# ---------------------------------------------------------------------------
# Skill Discovery — routes
# ---------------------------------------------------------------------------

@app.get("/api/skills/stream")
async def skills_stream(
    sources: Optional[str] = Query(None, description="Comma-separated display names"),
    threshold: float = Query(0.25),
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
    """Return list of past scrape runs from the sheets directory."""
    if not SKILL_SCRAPER_SHEETS.exists():
        return []

    entries = []
    seen_dates: set = set()

    for csv_file in sorted(SKILL_SCRAPER_SHEETS.glob("*.csv"), reverse=True):
        stem = csv_file.stem  # e.g. "2026-04-09"
        if stem in seen_dates:
            continue
        seen_dates.add(stem)

        # Count rows (subtract header)
        try:
            with open(csv_file, "r", encoding="utf-8") as f:
                row_count = max(0, sum(1 for _ in f) - 1)
        except Exception:
            row_count = 0

        # Count new skills
        new_count = 0
        try:
            import csv as csv_mod
            with open(csv_file, "r", encoding="utf-8") as f:
                reader = csv_mod.DictReader(f)
                for row in reader:
                    if row.get("is_new", "").strip().lower() in ("true", "1", "yes"):
                        new_count += 1
        except Exception:
            pass

        file_size_kb = round(csv_file.stat().st_size / 1024, 1)
        xlsx_file = SKILL_SCRAPER_SHEETS / f"{stem}.xlsx"

        formats = ["CSV"]
        if xlsx_file.exists():
            formats.append("XLSX")

        entries.append({
            "date": stem,
            "rows": row_count,
            "newSkills": new_count,
            "fileSize": f"{file_size_kb} KB",
            "formats": formats,
        })

    return entries


@app.get("/api/skills/history/{run_date}/download")
async def skills_history_download(run_date: str, format: str = Query("csv")):
    """Download a historical sheet by date (e.g. 2026-04-09)."""
    fmt = format.lower()
    ext = "xlsx" if fmt == "xlsx" else "csv"
    file_path = SKILL_SCRAPER_SHEETS / f"{run_date}.{ext}"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"No {ext.upper()} sheet for {run_date}.")
    media = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if fmt == "xlsx"
        else "text/csv"
    )
    return FileResponse(path=str(file_path), filename=file_path.name, media_type=media)


# ---------------------------------------------------------------------------
# Taxonomy Manager — config & state
# ---------------------------------------------------------------------------

from pydantic import BaseModel
from taxonomy.reader import load_taxonomy, get_taxonomy_stats, get_domains_index
from taxonomy.merger import compare_skills, apply_merge
from db.client import open_db as _open_db

# Original source-of-truth — never overwritten
# Use TAXONOMY_PATH env var on Vercel; fall back to repo-relative path locally
import os as _os
_TAXONOMY_ORIGINAL = Path(
    _os.environ.get("TAXONOMY_PATH", str(_BACKEND_DIR.parent / "iMocha Gold Taxonomy_v1.xlsx"))
)

# State file: tracks which file is the current living master
_TAXONOMY_STATE_FILE = _BACKEND_DIR / "taxonomy_state.json"

# Merge history: one entry per merge run
_TAXONOMY_HISTORY_FILE = OUTPUT_DIR / "merge_history.json"

# In-memory job store for download links
_taxonomy_jobs: dict = {}

# Use DATABASE_URL env var on Vercel; fall back to local Docker DSN
_DB_DSN = _os.environ.get(
    "DATABASE_URL",
    "postgresql://skills:skills_pass@localhost:5434/skillsdb",
)
_DB_CONFIG = {
    "database": {
        "enabled": True,
        "dsn": _DB_DSN,
    }
}


def _get_master_path() -> Path:
    """Return the current living master path (falls back to original if no state exists)."""
    if _TAXONOMY_STATE_FILE.exists():
        try:
            state = json.loads(_TAXONOMY_STATE_FILE.read_text())
            p = Path(state.get("master_path", ""))
            if p.exists():
                return p
        except Exception:
            pass
    return _TAXONOMY_ORIGINAL


def _set_master_path(path: Path) -> None:
    """Persist the new master path to the state file."""
    _TAXONOMY_STATE_FILE.write_text(json.dumps({
        "master_path": str(path),
        "original_path": str(_TAXONOMY_ORIGINAL),
    }, indent=2))


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
# Taxonomy Manager — routes
# ---------------------------------------------------------------------------

@app.get("/api/taxonomy/stats")
async def taxonomy_stats():
    """Return statistics about the current living master taxonomy."""
    master = _get_master_path()
    if not master.exists():
        raise HTTPException(status_code=404, detail="Taxonomy file not found.")
    data = load_taxonomy(master)
    stats = get_taxonomy_stats(data)
    stats["master_filename"] = master.name
    stats["is_original"] = (master == _TAXONOMY_ORIGINAL)
    return stats


@app.get("/api/taxonomy/domains")
async def taxonomy_domains():
    """Return domain -> [subdomains] index for UI dropdowns."""
    master = _get_master_path()
    if not master.exists():
        raise HTTPException(status_code=404, detail="Taxonomy file not found.")
    data = load_taxonomy(master)
    return get_domains_index(data)


@app.get("/api/taxonomy/compare")
async def taxonomy_compare():
    """Compare all DB skills against the current living master taxonomy."""
    master = _get_master_path()
    if not master.exists():
        raise HTTPException(status_code=404, detail="Taxonomy file not found.")

    data = load_taxonomy(master)

    db = _open_db(_DB_CONFIG)
    if db is None:
        raise HTTPException(status_code=503, detail="Could not connect to skills database.")
    try:
        db_skills = db.all_skills()
    finally:
        db.close()

    result = compare_skills(data, db_skills)
    result["master_filename"] = master.name
    return result


@app.post("/api/taxonomy/merge")
async def taxonomy_merge(body: MergeRequest):
    """
    Append approved skills to the living master taxonomy.
    The merged file becomes the new master for future comparisons.
    Appends an entry to merge_history.json.
    """
    master = _get_master_path()
    if not master.exists():
        raise HTTPException(status_code=404, detail="Taxonomy file not found.")
    if not body.approved_skills:
        raise HTTPException(status_code=400, detail="No skills provided.")

    approved = [s.model_dump() for s in body.approved_skills]
    out_path, added = apply_merge(master, approved, OUTPUT_DIR)

    # Promote merged file to new living master
    _set_master_path(out_path)

    today = datetime.date.today()

    # Mark skills as merged in the DB (grouped by domain/subdomain)
    db = _open_db(_DB_CONFIG)
    if db:
        try:
            from collections import defaultdict
            groups: dict = defaultdict(list)
            for s in approved:
                key = (s.get("proposed_domain",""), s.get("proposed_subdomain",""))
                groups[key].append(s["skill_name"])
            for (domain, subdomain), names in groups.items():
                db.mark_taxonomy_merged(names, domain, subdomain, today)
        finally:
            db.close()

    # Record in history
    _append_merge_history({
        "date": today.isoformat(),
        "added_count": added,
        "filename": out_path.name,
        "previous_master": master.name,
        "skills": [s["skill_name"] for s in approved],
    })

    job_id = str(uuid.uuid4())
    _taxonomy_jobs[job_id] = {
        "path": str(out_path),
        "filename": out_path.name,
    }

    return {
        "job_id": job_id,
        "filename": out_path.name,
        "added_count": added,
        "new_master": out_path.name,
    }


@app.get("/api/taxonomy/merged-stats")
async def taxonomy_merged_stats():
    """Return DB-level stats on which scraped skills have been merged into the taxonomy."""
    db = _open_db(_DB_CONFIG)
    if db is None:
        raise HTTPException(status_code=503, detail="Could not connect to skills database.")
    try:
        return db.merged_skills_summary()
    finally:
        db.close()


@app.get("/api/taxonomy/history")
async def taxonomy_history():
    """Return the list of past merge runs, newest first."""
    history = _read_merge_history()
    enriched = []
    for entry in history:
        path = OUTPUT_DIR / entry["filename"]
        size_str = ""
        if path.exists():
            kb = path.stat().st_size / 1024
            size_str = f"{kb:.0f} KB" if kb < 1024 else f"{kb / 1024:.1f} MB"
        enriched.append({**entry, "file_exists": path.exists(), "file_size": size_str})
    return enriched


@app.get("/api/taxonomy/history/{filename}/download")
async def taxonomy_history_download(filename: str):
    """Download a historical merged taxonomy file by filename."""
    path = OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        path=str(path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/api/taxonomy/download/{job_id}")
async def taxonomy_download(job_id: str):
    """Download the merged taxonomy xlsx produced by a merge job."""
    if job_id not in _taxonomy_jobs:
        raise HTTPException(status_code=404, detail="Job not found or has expired.")
    job = _taxonomy_jobs[job_id]
    return FileResponse(
        path=job["path"],
        filename=job["filename"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
