# Taxonomy → Neon DB Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the iMocha Gold Taxonomy from an on-disk Excel file into a Neon PostgreSQL table so that compares, merges, stats, and history all survive Vercel deploys and work via fast SQL queries.

**Architecture:** Create a `taxonomy` table in Neon, import all 26,120 rows once, then replace every Excel file operation (load, compare, merge, stats) with SQL queries. Keep Excel export as on-demand generation only. Drop `taxonomy_state.json` and file-based master tracking entirely.

**Tech Stack:** Python, psycopg2, openpyxl (import only), FastAPI, Neon PostgreSQL

---

## File Map

| File | Action | Purpose |
|------|---------|---------|
| `backend/db/taxonomy_db.py` | **Create** | All taxonomy DB operations: import, compare, merge, stats, domains index, export |
| `backend/taxonomy/reader.py` | **Modify** | Remove Excel load/cache; add thin shim that delegates to taxonomy_db |
| `backend/taxonomy/merger.py` | **Modify** | Replace xlsx append with taxonomy_db.merge_skills() |
| `backend/server.py` | **Modify** | Remove file-path tracking; wire endpoints to taxonomy_db; add `/api/taxonomy/export` |
| `backend/migrate_taxonomy.py` | **Create** | One-time CLI script: reads Excel, INSERTs 26,120 rows, prints summary |

---

## Task 1: Create `taxonomy` table in Neon

**Files:**
- Create: `backend/db/taxonomy_db.py`

- [ ] **Write the DDL and `create_table()` function**

```python
# backend/db/taxonomy_db.py
"""
Taxonomy DB — all operations against the `taxonomy` table in Neon.
Replaces the on-disk Excel master file entirely.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import psycopg2
import psycopg2.extras

_DDL = """
CREATE TABLE IF NOT EXISTS taxonomy (
    id                  SERIAL PRIMARY KEY,
    skill_name          TEXT    NOT NULL,
    normalized_name     TEXT    NOT NULL UNIQUE,
    domain              TEXT    NOT NULL DEFAULT '',
    subdomain           TEXT    NOT NULL DEFAULT '',
    skill_cluster       TEXT    NOT NULL DEFAULT '',
    classification      TEXT    NOT NULL DEFAULT '',
    criticality         TEXT    NOT NULL DEFAULT '',
    sheet               TEXT    NOT NULL DEFAULT 'sheet1',
    added_at            DATE    NOT NULL DEFAULT CURRENT_DATE,
    merge_batch         TEXT    NOT NULL DEFAULT 'initial'
);

CREATE INDEX IF NOT EXISTS idx_taxonomy_normalized ON taxonomy (normalized_name);
CREATE INDEX IF NOT EXISTS idx_taxonomy_domain     ON taxonomy (domain);
CREATE INDEX IF NOT EXISTS idx_taxonomy_sheet      ON taxonomy (sheet);
"""


def _normalize(name: str) -> str:
    try:
        from processor.deduplicator import normalize_name
        return normalize_name(name).lower().strip()
    except Exception:
        return name.lower().strip()


def get_conn(dsn: str):
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    return conn


def create_table(dsn: str) -> None:
    """Create taxonomy table and indexes if not present (idempotent)."""
    conn = get_conn(dsn)
    with conn.cursor() as cur:
        cur.execute(_DDL)
    conn.commit()
    conn.close()
```

- [ ] **Run it against Neon to create the table**

```bash
cd /Users/aryan/Desktop/simple-connect-app/backend
python3 -c "
from dotenv import load_dotenv; load_dotenv('.env')
import os
from db.taxonomy_db import create_table
create_table(os.environ['DATABASE_URL'])
print('Table created.')
"
```

Expected output: `Table created.`

- [ ] **Verify table exists in Neon**

```bash
python3 -c "
from dotenv import load_dotenv; load_dotenv('.env')
import os, psycopg2
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute(\"SELECT COUNT(*) FROM taxonomy\")
print('Row count:', cur.fetchone()[0])
conn.close()
"
```

Expected output: `Row count: 0`

- [ ] **Commit**

```bash
git add backend/db/taxonomy_db.py
git commit -m "feat: add taxonomy table DDL in Neon"
```

---

## Task 2: One-time import of 26,120 rows from Excel

**Files:**
- Create: `backend/migrate_taxonomy.py`
- Modify: `backend/db/taxonomy_db.py` (add `bulk_insert()`)

- [ ] **Add `bulk_insert()` to taxonomy_db.py**

```python
# Add to backend/db/taxonomy_db.py

def bulk_insert(dsn: str, rows: list[dict], batch: str = "initial") -> int:
    """
    Insert rows into taxonomy table. Skips duplicates by normalized_name.
    Each row must have: skill_name, domain, subdomain, skill_cluster,
                        classification, criticality, sheet
    Returns count of inserted rows.
    """
    if not rows:
        return 0

    conn = get_conn(dsn)
    inserted = 0
    with conn.cursor() as cur:
        for row in rows:
            norm = _normalize(row["skill_name"])
            if not norm:
                continue
            try:
                cur.execute(
                    """
                    INSERT INTO taxonomy
                        (skill_name, normalized_name, domain, subdomain,
                         skill_cluster, classification, criticality, sheet, merge_batch)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (normalized_name) DO NOTHING
                    """,
                    (
                        row["skill_name"],
                        norm,
                        row.get("domain", ""),
                        row.get("subdomain", ""),
                        row.get("skill_cluster", ""),
                        row.get("classification", ""),
                        row.get("criticality", ""),
                        row.get("sheet", "sheet1"),
                        batch,
                    ),
                )
                if cur.rowcount:
                    inserted += 1
            except Exception as e:
                conn.rollback()
                raise e
    conn.commit()
    conn.close()
    return inserted
```

- [ ] **Create the migration script**

```python
# backend/migrate_taxonomy.py
"""
One-time migration: load iMocha Gold Taxonomy xlsx → Neon taxonomy table.

Usage:
    cd backend && python migrate_taxonomy.py
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import openpyxl
from db.taxonomy_db import create_table, bulk_insert

XLSX_PATH = Path(__file__).parent.parent / "iMocha Gold Taxonomy_v1.xlsx"
DSN = os.environ["DATABASE_URL"]


def read_sheet1(wb) -> list[dict]:
    ws = wb["Final 16 domains"]
    rows = list(ws.rows)
    result = []
    for row in rows[1:]:
        vals = [c.value for c in row]
        if not any(vals):
            continue
        result.append({
            "domain":         vals[0] or "",
            "subdomain":      vals[1] or "",
            "skill_cluster":  vals[2] or "",
            "skill_name":     vals[3] or "",
            "classification": vals[4] or "",
            "criticality":    vals[5] or "",
            "sheet":          "sheet1",
        })
    return result


def read_sheet2(wb) -> list[dict]:
    ws = wb["Domain Independent & Irrelevant"]
    rows = list(ws.rows)
    result = []
    for row in rows[1:]:
        vals = [c.value for c in row]
        if not any(vals):
            continue
        result.append({
            "domain":         vals[0] or "",
            "subdomain":      vals[1] or "",
            "skill_cluster":  vals[2] or "",
            "skill_name":     vals[3] or "",
            "classification": vals[5] or "",
            "criticality":    vals[6] or "",
            "sheet":          "sheet2",
        })
    return result


if __name__ == "__main__":
    print(f"Loading {XLSX_PATH}...")
    wb = openpyxl.load_workbook(XLSX_PATH, read_only=True, data_only=True)
    sheet1 = read_sheet1(wb)
    sheet2 = read_sheet2(wb)
    wb.close()
    print(f"  Sheet1 rows: {len(sheet1)}")
    print(f"  Sheet2 rows: {len(sheet2)}")

    print("Ensuring taxonomy table exists...")
    create_table(DSN)

    print("Inserting sheet1...")
    n1 = bulk_insert(DSN, sheet1, batch="initial")
    print(f"  Inserted: {n1}")

    print("Inserting sheet2...")
    n2 = bulk_insert(DSN, sheet2, batch="initial")
    print(f"  Inserted: {n2}")

    print(f"\nDone. Total inserted: {n1 + n2}")
```

- [ ] **Run the migration**

```bash
cd /Users/aryan/Desktop/simple-connect-app/backend
python3 migrate_taxonomy.py
```

Expected output:
```
Loading .../iMocha Gold Taxonomy_v1.xlsx...
  Sheet1 rows: 24706
  Sheet2 rows: 1415
Ensuring taxonomy table exists...
Inserting sheet1...
  Inserted: ~24XXX
Inserting sheet2...
  Inserted: ~1XXX
Done. Total inserted: ~26120
```

- [ ] **Verify count in Neon**

```bash
python3 -c "
from dotenv import load_dotenv; load_dotenv('.env')
import os, psycopg2
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute(\"SELECT sheet, COUNT(*) FROM taxonomy GROUP BY sheet\")
for row in cur.fetchall(): print(row)
conn.close()
"
```

Expected: `('sheet1', ~24706)` and `('sheet2', ~1415)`

- [ ] **Commit**

```bash
git add backend/db/taxonomy_db.py backend/migrate_taxonomy.py
git commit -m "feat: migrate iMocha taxonomy Excel into Neon taxonomy table"
```

---

## Task 3: DB-backed stats, domains index, and compare

**Files:**
- Modify: `backend/db/taxonomy_db.py` (add `get_stats()`, `get_domains_index()`, `compare_with_skills()`)

- [ ] **Add the three query functions to taxonomy_db.py**

```python
# Add to backend/db/taxonomy_db.py

def get_stats(dsn: str) -> dict:
    """Return aggregate statistics — replaces get_taxonomy_stats()."""
    conn = get_conn(dsn)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT COUNT(*) AS total FROM taxonomy")
        total = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS c FROM taxonomy WHERE sheet='sheet1'")
        sheet1 = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) AS c FROM taxonomy WHERE sheet='sheet2'")
        sheet2 = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(DISTINCT domain) AS c FROM taxonomy WHERE sheet='sheet1'")
        domain_count = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(DISTINCT subdomain) AS c FROM taxonomy WHERE sheet='sheet1' AND subdomain != ''")
        subdomain_count = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(DISTINCT skill_cluster) AS c FROM taxonomy WHERE sheet='sheet1' AND skill_cluster != ''")
        cluster_count = cur.fetchone()["c"]

        cur.execute("""
            SELECT domain, COUNT(*) AS cnt
            FROM taxonomy WHERE sheet='sheet1' AND domain != ''
            GROUP BY domain ORDER BY cnt DESC
        """)
        domain_breakdown = {r["domain"]: r["cnt"] for r in cur.fetchall()}

        cur.execute("""
            SELECT classification, COUNT(*) AS cnt
            FROM taxonomy WHERE classification != ''
            GROUP BY classification ORDER BY cnt DESC
        """)
        classification_breakdown = {r["classification"]: r["cnt"] for r in cur.fetchall()}

    conn.close()
    return {
        "total_skills": total,
        "sheet1_count": sheet1,
        "sheet2_count": sheet2,
        "domain_count": domain_count,
        "subdomain_count": subdomain_count,
        "skill_cluster_count": cluster_count,
        "domain_breakdown": domain_breakdown,
        "classification_breakdown": classification_breakdown,
        "master_filename": "Neon DB",
        "is_original": False,
    }


def get_domains_index(dsn: str) -> dict:
    """Return {domain: [subdomains]} for UI dropdowns — replaces get_domains_index()."""
    conn = get_conn(dsn)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT domain, subdomain FROM taxonomy
            WHERE sheet='sheet1' AND domain != '' AND subdomain != ''
            ORDER BY domain, subdomain
        """)
        index: dict[str, list[str]] = {}
        for row in cur.fetchall():
            index.setdefault(row["domain"], [])
            if row["subdomain"] not in index[row["domain"]]:
                index[row["domain"]].append(row["subdomain"])
    conn.close()
    return index


def compare_with_skills(dsn: str, db_skills: list[dict]) -> dict:
    """
    Compare scraped skills against taxonomy using normalized_name lookup.
    Returns same shape as the old compare_skills() so server.py needs no changes.
    """
    from taxonomy.domain_mapping import (
        CATEGORY_TO_DOMAIN, SUBCATEGORY_TO_SUBDOMAIN, SKILLTYPE_TO_CLASSIFICATION,
        DEFAULT_DOMAIN, DEFAULT_SUBDOMAIN, DEFAULT_CLASSIFICATION, DEFAULT_CRITICALITY,
    )

    # Fetch all normalized names from taxonomy in one query
    conn = get_conn(dsn)
    with conn.cursor() as cur:
        cur.execute("SELECT normalized_name FROM taxonomy")
        taxonomy_norms: set[str] = {r[0] for r in cur.fetchall()}
    conn.close()

    new_skills, unmappable = [], []
    matched = 0

    for skill in db_skills:
        name = skill.get("skill_name") or ""
        norm = _normalize(name)
        if not norm:
            continue

        if norm in taxonomy_norms:
            matched += 1
            continue

        category   = skill.get("category") or ""
        subcategory = skill.get("subcategory") or ""
        skill_type  = skill.get("skill_type") or ""

        entry = {
            "db_id":                   skill.get("id"),
            "skill_name":              name,
            "proposed_domain":         CATEGORY_TO_DOMAIN.get(category, DEFAULT_DOMAIN if category else ""),
            "proposed_subdomain":      SUBCATEGORY_TO_SUBDOMAIN.get(subcategory, DEFAULT_SUBDOMAIN if subcategory else ""),
            "proposed_cluster":        SUBCATEGORY_TO_SUBDOMAIN.get(subcategory, DEFAULT_SUBDOMAIN if subcategory else ""),
            "proposed_classification": SKILLTYPE_TO_CLASSIFICATION.get(skill_type, DEFAULT_CLASSIFICATION),
            "proposed_criticality":    DEFAULT_CRITICALITY,
            "source":                  skill.get("source") or "",
            "confidence_score":        skill.get("confidence_score") or 0.0,
            "category":                category,
            "subcategory":             subcategory,
            "skill_type":              skill_type,
        }
        (unmappable if not category else new_skills).append(entry)

    return {
        "total_db_skills": len(db_skills),
        "matched": matched,
        "new_skills": new_skills,
        "unmappable": unmappable,
    }


def merge_skills(dsn: str, approved_skills: list[dict], batch: str) -> int:
    """
    INSERT approved skills into taxonomy table.
    Returns count of rows actually inserted (skips duplicates).
    """
    rows = [
        {
            "skill_name":     s.get("skill_name", ""),
            "domain":         s.get("proposed_domain", ""),
            "subdomain":      s.get("proposed_subdomain", ""),
            "skill_cluster":  s.get("proposed_cluster", ""),
            "classification": s.get("proposed_classification", ""),
            "criticality":    s.get("proposed_criticality", "No"),
            "sheet":          "sheet1",
        }
        for s in approved_skills
    ]
    return bulk_insert(dsn, rows, batch=batch)


def get_overview(dsn: str, scraped_skills: list[dict]) -> dict:
    """Return all 4 pipeline numbers in one call."""
    conn = get_conn(dsn)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM taxonomy")
        taxonomy_size = cur.fetchone()[0]
        cur.execute("SELECT normalized_name FROM taxonomy")
        taxonomy_norms: set[str] = {r[0] for r in cur.fetchall()}
    conn.close()

    new_count = sum(
        1 for s in scraped_skills
        if _normalize(s.get("skill_name", "")) not in taxonomy_norms
    )

    return {
        "taxonomy_size": taxonomy_size,
        "scraped_count": len(scraped_skills),
        "new_skills_count": new_count,
        "master_filename": "Neon DB",
        "is_original": False,
    }


def export_to_excel(dsn: str) -> bytes:
    """Generate an in-memory xlsx from the taxonomy table and return raw bytes."""
    import io
    import openpyxl

    conn = get_conn(dsn)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT domain, subdomain, skill_cluster, skill_name, classification, criticality, sheet
            FROM taxonomy ORDER BY sheet, domain, subdomain, skill_name
        """)
        rows = cur.fetchall()
    conn.close()

    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Final 16 domains"
    ws1.append(["Domain", "Subdomain", "Skill Cluster", "Skill Name", "SkillClassification", "SkillCriticality"])
    ws2 = wb.create_sheet("Domain Independent & Irrelevant")
    ws2.append(["Domain", "SubDomain", "SkillCluster", "SkillName", "SkillClassification", "SkillCriticality"])

    for row in rows:
        r = [row["domain"], row["subdomain"], row["skill_cluster"],
             row["skill_name"], row["classification"], row["criticality"]]
        if row["sheet"] == "sheet1":
            ws1.append(r)
        else:
            ws2.append(r)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()
```

- [ ] **Smoke-test stats against known count**

```bash
cd /Users/aryan/Desktop/simple-connect-app/backend
python3 -c "
from dotenv import load_dotenv; load_dotenv('.env')
import os
from db.taxonomy_db import get_stats
s = get_stats(os.environ['DATABASE_URL'])
print('total_skills:  ', s['total_skills'])
print('domain_count:  ', s['domain_count'])
print('sheet1_count:  ', s['sheet1_count'])
print('sheet2_count:  ', s['sheet2_count'])
"
```

Expected: `total_skills` matches the migrate output (~26120), `domain_count` > 0.

- [ ] **Commit**

```bash
git add backend/db/taxonomy_db.py
git commit -m "feat: add DB-backed stats, domains, compare, merge, and export to taxonomy_db"
```

---

## Task 4: Wire server.py to taxonomy_db (drop all file-path tracking)

**Files:**
- Modify: `backend/server.py`

- [ ] **Replace taxonomy imports and remove file-path state**

Find and replace this block in `server.py`:

```python
# REMOVE these imports/variables entirely:
from taxonomy.reader import load_taxonomy, get_taxonomy_stats, get_domains_index
from taxonomy.merger import compare_skills, apply_merge

_TAXONOMY_ORIGINAL = Path(...)
_TAXONOMY_STATE_FILE = ...
_TAXONOMY_HISTORY_FILE = ...
_taxonomy_jobs: dict = {}

def _get_master_path() -> Path: ...
def _set_master_path(path: Path) -> None: ...
def _read_merge_history() -> list: ...
def _append_merge_history(entry: dict) -> None: ...
```

Replace with:

```python
from db.taxonomy_db import (
    get_stats as _tax_stats,
    get_domains_index as _tax_domains,
    compare_with_skills as _tax_compare,
    merge_skills as _tax_merge,
    get_overview as _tax_overview,
    export_to_excel as _tax_export,
)

# Merge history still tracked in JSON (lightweight, not taxonomy data)
_TAXONOMY_HISTORY_FILE = OUTPUT_DIR / "merge_history.json"
```

- [ ] **Replace `GET /api/taxonomy/stats`**

```python
@app.get("/api/taxonomy/stats")
async def taxonomy_stats():
    """Return statistics about the taxonomy table in Neon."""
    return _tax_stats(_DB_DSN)
```

- [ ] **Replace `GET /api/taxonomy/domains`**

```python
@app.get("/api/taxonomy/domains")
async def taxonomy_domains():
    """Return domain -> [subdomains] index for UI dropdowns."""
    return _tax_domains(_DB_DSN)
```

- [ ] **Replace `GET /api/taxonomy/compare`**

```python
@app.get("/api/taxonomy/compare")
async def taxonomy_compare():
    """Compare all DB skills against the taxonomy table."""
    db = _open_db(_DB_CONFIG)
    if db is None:
        raise HTTPException(status_code=503, detail="Could not connect to skills database.")
    try:
        db_skills = db.all_skills()
    finally:
        db.close()
    result = _tax_compare(_DB_DSN, db_skills)
    result["master_filename"] = "Neon DB"
    return result
```

- [ ] **Replace `POST /api/taxonomy/merge`**

```python
@app.post("/api/taxonomy/merge")
async def taxonomy_merge(body: MergeRequest):
    """Append approved skills directly into the Neon taxonomy table."""
    if not body.approved_skills:
        raise HTTPException(status_code=400, detail="No skills provided.")

    approved = [s.model_dump() for s in body.approved_skills]
    today = datetime.date.today()
    batch = today.isoformat()

    added = _tax_merge(_DB_DSN, approved, batch=batch)

    # Mark skills as merged in the skills table
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

    # Record in history
    _append_merge_history({
        "date": batch,
        "added_count": added,
        "batch": batch,
        "skills": [s["skill_name"] for s in approved],
    })

    return {
        "added_count": added,
        "new_master": "Neon DB",
        "batch": batch,
    }
```

- [ ] **Replace `GET /api/taxonomy/overview`**

```python
@app.get("/api/taxonomy/overview")
async def taxonomy_overview():
    """All 4 pipeline numbers from Neon in one call."""
    db = _open_db(_DB_CONFIG)
    if db is None:
        raise HTTPException(status_code=503, detail="Could not connect to skills database.")
    try:
        db_skills = db.all_skills()
    finally:
        db.close()
    return _tax_overview(_DB_DSN, db_skills)
```

- [ ] **Replace `GET /api/taxonomy/master/download` with on-demand export**

```python
@app.get("/api/taxonomy/master/download")
async def taxonomy_master_download():
    """Generate and download the full taxonomy as xlsx from Neon."""
    import io
    xlsx_bytes = _tax_export(_DB_DSN)
    today = datetime.date.today().isoformat()
    filename = f"iMocha_Taxonomy_{today}.xlsx"
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

- [ ] **Replace `GET /api/taxonomy/new-skills/download`**

```python
@app.get("/api/taxonomy/new-skills/download")
async def taxonomy_new_skills_download(format: str = Query("csv", description="csv or xlsx")):
    """Run compare and return only new skills as CSV or XLSX."""
    import io, csv as csv_mod

    db = _open_db(_DB_CONFIG)
    if db is None:
        raise HTTPException(status_code=503, detail="Could not connect to skills database.")
    try:
        db_skills = db.all_skills()
    finally:
        db.close()

    result = _tax_compare(_DB_DSN, db_skills)
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
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="new_skills_{today}.xlsx"'},
        )
    else:
        buf = io.StringIO()
        writer = csv_mod.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(new_skills)
        return StreamingResponse(
            iter([buf.getvalue().encode("utf-8")]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="new_skills_{today}.csv"'},
        )
```

- [ ] **Remove `GET /api/taxonomy/download/{job_id}` and `GET /api/taxonomy/history/{filename}/download`**

These endpoints served per-merge Excel files on disk. They no longer apply — history downloads should use `/api/taxonomy/master/download` (full export) or be removed. Remove both from server.py.

- [ ] **Commit**

```bash
git add backend/server.py
git commit -m "feat: wire all taxonomy endpoints to Neon DB — drop file-based master tracking"
```

---

## Task 5: Update taxonomy/reader.py and taxonomy/merger.py (make them no-ops / removed)

**Files:**
- Modify: `backend/taxonomy/reader.py`
- Modify: `backend/taxonomy/merger.py`

These files are no longer called by server.py after Task 4, but other scripts may import them. Keep them as thin stubs that raise a clear error if called, to catch any missed callers.

- [ ] **Replace reader.py with a deprecation stub**

```python
# backend/taxonomy/reader.py
"""
DEPRECATED — taxonomy data now lives in Neon DB.
Use db.taxonomy_db functions instead.
This stub exists so any missed import produces a clear error rather than silently doing nothing.
"""

def load_taxonomy(*args, **kwargs):
    raise RuntimeError("load_taxonomy() is deprecated. Use db.taxonomy_db.get_stats() instead.")

def get_taxonomy_stats(*args, **kwargs):
    raise RuntimeError("get_taxonomy_stats() is deprecated. Use db.taxonomy_db.get_stats() instead.")

def get_domains_index(*args, **kwargs):
    raise RuntimeError("get_domains_index() is deprecated. Use db.taxonomy_db.get_domains_index() instead.")
```

- [ ] **Replace merger.py with a deprecation stub**

```python
# backend/taxonomy/merger.py
"""
DEPRECATED — taxonomy merges now go directly to Neon DB.
Use db.taxonomy_db.merge_skills() instead.
"""

def compare_skills(*args, **kwargs):
    raise RuntimeError("compare_skills() is deprecated. Use db.taxonomy_db.compare_with_skills() instead.")

def apply_merge(*args, **kwargs):
    raise RuntimeError("apply_merge() is deprecated. Use db.taxonomy_db.merge_skills() instead.")
```

- [ ] **Commit**

```bash
git add backend/taxonomy/reader.py backend/taxonomy/merger.py
git commit -m "refactor: deprecate file-based taxonomy reader and merger — Neon is now source of truth"
```

---

## Task 6: Test everything end-to-end

- [ ] **Restart the server**

```bash
kill $(lsof -ti:8002) 2>/dev/null
cd /Users/aryan/Desktop/simple-connect-app/backend
uvicorn server:app --host 0.0.0.0 --port 8002 &
sleep 4
```

- [ ] **Test /api/taxonomy/stats**

```bash
curl -s http://localhost:8002/api/taxonomy/stats | python3 -m json.tool
```

Expected: `total_skills` ~26120, `domain_count` > 0, `master_filename` = `"Neon DB"`.

- [ ] **Test /api/taxonomy/overview**

```bash
curl -s http://localhost:8002/api/taxonomy/overview | python3 -m json.tool
```

Expected:
```json
{
  "taxonomy_size": 26120,
  "scraped_count": 5242,
  "new_skills_count": 4856,
  "master_filename": "Neon DB",
  "is_original": false
}
```

- [ ] **Test /api/taxonomy/compare**

```bash
curl -s http://localhost:8002/api/taxonomy/compare | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('total_db_skills:', d['total_db_skills'])
print('matched:        ', d['matched'])
print('new_skills:     ', len(d['new_skills']))
print('unmappable:     ', len(d['unmappable']))
"
```

Expected: `total_db_skills: 5242`, `matched: 386`, `new_skills + unmappable: 4856`.

- [ ] **Test /api/taxonomy/domains**

```bash
curl -s http://localhost:8002/api/taxonomy/domains | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('Domain count:', len(d))
print('First domain:', list(d.keys())[0])
"
```

Expected: 16 domains, each with a list of subdomains.

- [ ] **Test master download (Excel generation from DB)**

```bash
curl -s http://localhost:8002/api/taxonomy/master/download -o /tmp/taxonomy_test.xlsx
python3 -c "
import openpyxl
wb = openpyxl.load_workbook('/tmp/taxonomy_test.xlsx', read_only=True)
for sheet in wb.sheetnames:
    ws = wb[sheet]
    print(sheet, ':', ws.max_row, 'rows')
wb.close()
"
```

Expected: `Final 16 domains : ~24707 rows`, `Domain Independent & Irrelevant : ~1416 rows`.

- [ ] **Test new-skills CSV download**

```bash
curl -s "http://localhost:8002/api/taxonomy/new-skills/download?format=csv" -o /tmp/new_skills_v2.csv
wc -l /tmp/new_skills_v2.csv
head -2 /tmp/new_skills_v2.csv
```

Expected: ~4857 lines (4856 + header), columns match `skill_name,proposed_domain,...`

- [ ] **Final commit**

```bash
git add -A
git commit -m "feat: taxonomy fully migrated to Neon DB — Excel is now generated on-demand"
```
