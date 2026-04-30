"""
PostgreSQL client for skill persistence.

Responsibilities:
- Initialize schema on first run (idempotent DDL)
- mark_is_new(): compare incoming records against DB, set is_new + restore first_seen
- upsert_skills(): persist the run — insert new, update existing
"""
import logging
from datetime import date
from typing import Optional

import psycopg2
import psycopg2.extras

log = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS skills (
    id                  SERIAL PRIMARY KEY,
    skill_name          TEXT    NOT NULL,
    normalized_name     TEXT    NOT NULL UNIQUE,
    category            TEXT    NOT NULL DEFAULT '',
    subcategory         TEXT    NOT NULL DEFAULT '',
    skill_type          TEXT    NOT NULL DEFAULT '',
    source              TEXT    NOT NULL DEFAULT '',
    confidence_score    REAL    NOT NULL DEFAULT 0.0,
    popularity          INTEGER NOT NULL DEFAULT 0,
    language            TEXT    NOT NULL DEFAULT '',
    tags                TEXT    NOT NULL DEFAULT '',
    first_seen          DATE    NOT NULL,
    last_seen           DATE    NOT NULL,
    run_count           INTEGER NOT NULL DEFAULT 1,
    taxonomy_merged_at  DATE             DEFAULT NULL,
    taxonomy_domain     TEXT    NOT NULL DEFAULT '',
    taxonomy_subdomain  TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_skills_normalized    ON skills (normalized_name);
CREATE INDEX IF NOT EXISTS idx_skills_first_seen    ON skills (first_seen);
CREATE INDEX IF NOT EXISTS idx_skills_category      ON skills (category);
CREATE INDEX IF NOT EXISTS idx_skills_confidence    ON skills (confidence_score);
CREATE INDEX IF NOT EXISTS idx_skills_merged        ON skills (taxonomy_merged_at);
"""

_ALTER_DDL = """
ALTER TABLE skills ADD COLUMN IF NOT EXISTS taxonomy_merged_at DATE DEFAULT NULL;
ALTER TABLE skills ADD COLUMN IF NOT EXISTS taxonomy_domain    TEXT NOT NULL DEFAULT '';
ALTER TABLE skills ADD COLUMN IF NOT EXISTS taxonomy_subdomain TEXT NOT NULL DEFAULT '';
ALTER TABLE skills ADD COLUMN IF NOT EXISTS reclaim_dismissed_at DATE DEFAULT NULL;
"""

_REJECTED_DDL = """
CREATE TABLE IF NOT EXISTS rejected_skills (
    id               SERIAL PRIMARY KEY,
    skill_name       TEXT    NOT NULL,
    normalized_name  TEXT    NOT NULL,
    category         TEXT    NOT NULL DEFAULT '',
    subcategory      TEXT    NOT NULL DEFAULT '',
    source           TEXT    NOT NULL DEFAULT '',
    confidence_score REAL    NOT NULL DEFAULT 0.0,
    popularity       INTEGER NOT NULL DEFAULT 0,
    rejection_reason TEXT    NOT NULL DEFAULT 'below_threshold',
    first_rejected_at DATE   NOT NULL,
    last_rejected_at  DATE   NOT NULL,
    times_rejected   INTEGER NOT NULL DEFAULT 1,
    dismissed        BOOLEAN NOT NULL DEFAULT FALSE,
    dismissed_at     TIMESTAMPTZ      DEFAULT NULL,
    CONSTRAINT uq_rejected_normalized UNIQUE (normalized_name)
);
CREATE INDEX IF NOT EXISTS idx_rejected_confidence ON rejected_skills (confidence_score DESC);
CREATE INDEX IF NOT EXISTS idx_rejected_date ON rejected_skills (last_rejected_at DESC);
CREATE INDEX IF NOT EXISTS idx_rejected_dismissed ON rejected_skills (dismissed);
"""

_SCRAPE_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS scrape_runs (
    id              SERIAL PRIMARY KEY,
    job_id          TEXT NOT NULL UNIQUE,
    run_date        DATE NOT NULL,
    raw_count       INT NOT NULL DEFAULT 0,
    dedup_count     INT NOT NULL DEFAULT 0,
    final_count     INT NOT NULL DEFAULT 0,
    new_count       INT NOT NULL DEFAULT 0,
    returning_count INT NOT NULL DEFAULT 0,
    sources         TEXT NOT NULL DEFAULT '',
    completed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_scrape_runs_date ON scrape_runs(run_date DESC);
"""

_CHANGELOG_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS changelog_runs (
    id              SERIAL PRIMARY KEY,
    run_date        DATE NOT NULL,
    filter_desc     TEXT NOT NULL DEFAULT '',
    filename        TEXT NOT NULL DEFAULT '',
    total_records   INT  NOT NULL DEFAULT 0,
    matched_records INT  NOT NULL DEFAULT 0,
    raw_records     JSONB NOT NULL DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_changelog_runs_date ON changelog_runs(run_date DESC);
"""

_TAXONOMY_MERGES_DDL = """
CREATE TABLE IF NOT EXISTS taxonomy_merges (
    id           SERIAL PRIMARY KEY,
    batch        TEXT NOT NULL,
    merge_date   DATE NOT NULL,
    added_count  INT  NOT NULL DEFAULT 0,
    skills       JSONB NOT NULL DEFAULT '[]',
    job_id       TEXT,
    run_date     DATE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_taxonomy_merges_date ON taxonomy_merges(merge_date DESC);
ALTER TABLE taxonomy_merges ADD COLUMN IF NOT EXISTS job_id   TEXT;
ALTER TABLE taxonomy_merges ADD COLUMN IF NOT EXISTS run_date DATE;
CREATE INDEX IF NOT EXISTS idx_taxonomy_merges_job ON taxonomy_merges(job_id);
"""


def _normalize(name: str) -> str:
    """
    Mirror the deduplicator's normalize_name but return a stable lowercase key
    suitable for DB storage.  Import lazily to avoid circular deps at module load.
    """
    from processor.deduplicator import normalize_name
    return normalize_name(name).lower().strip()


class SkillsDB:
    """Thin wrapper around a psycopg2 connection."""

    def __init__(self, dsn: str):
        self._dsn = dsn
        self._conn: Optional[psycopg2.extensions.connection] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        self._conn = psycopg2.connect(self._dsn)
        self._conn.autocommit = False

    def init_schema(self) -> None:
        """Create tables / indexes if they don't exist yet (idempotent).
        Also runs ALTER TABLE to add new columns to existing tables."""
        with self._conn.cursor() as cur:
            cur.execute(_DDL)
            cur.execute(_ALTER_DDL)
            cur.execute(_SCRAPE_RUNS_DDL)
            cur.execute(_REJECTED_DDL)
            cur.execute(_CHANGELOG_RUNS_DDL)
            cur.execute(_TAXONOMY_MERGES_DDL)
        self._conn.commit()
        log.debug("DB schema ready.")

    def close(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def mark_is_new(self, records: list) -> list:
        """
        Set is_new on every record:
          - False  → normalized name already in DB  (restore first_seen from DB)
          - True   → genuinely new skill

        Name changes (e.g. "GPT-3" → "GPT-4", "React 18" → "React 19") produce
        different normalized keys and are therefore treated as new — no special
        handling needed.

        Returns the same list (mutated in place).
        """
        if not records:
            return records

        # Build a {normalized_key: record} map.
        # If two records in the same batch normalize identically, the deduplicator
        # already merged them, so this is a 1:1 mapping in practice.
        norm_map: dict[str, object] = {}
        for r in records:
            key = _normalize(r.skill_name)
            if key:
                norm_map[key] = r

        if not norm_map:
            return records

        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT normalized_name, first_seen "
                "FROM skills WHERE normalized_name = ANY(%s)",
                (list(norm_map.keys()),),
            )
            existing: dict[str, date] = {
                row["normalized_name"]: row["first_seen"]
                for row in cur.fetchall()
            }

        for key, record in norm_map.items():
            if key in existing:
                record.is_new = False
                # Preserve the original discovery date so the sheet always
                # shows when a skill was *first* seen, not when it resurfaced.
                record.first_seen = existing[key]
            else:
                record.is_new = True

        return records

    def upsert_skills(self, records: list, run_date: date) -> None:
        """
        Persist the current run:
          - New skills   → INSERT
          - Seen before  → UPDATE last_seen, popularity (keep max), confidence
                           (keep max), source list, run_count++

        Popularity and confidence are only updated upward so a noisy run can't
        degrade a well-established skill's scores.
        """
        if not records:
            return

        rows = []
        for r in records:
            key = _normalize(r.skill_name)
            if not key:
                continue
            rows.append((
                r.skill_name,
                key,
                r.category or "",
                r.subcategory or "",
                r.skill_type or "",
                r.source or "",
                r.confidence_score,
                r.popularity,
                r.language or "",
                ", ".join(r.tags) if r.tags else "",
                run_date,   # first_seen (ignored on conflict)
                run_date,   # last_seen
            ))

        if not rows:
            return

        with self._conn.cursor() as cur:
            psycopg2.extras.execute_batch(
                cur,
                """
                INSERT INTO skills
                    (skill_name, normalized_name, category, subcategory, skill_type,
                     source, confidence_score, popularity, language, tags,
                     first_seen, last_seen, run_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                ON CONFLICT (normalized_name) DO UPDATE SET
                    last_seen        = EXCLUDED.last_seen,
                    popularity       = GREATEST(skills.popularity,       EXCLUDED.popularity),
                    confidence_score = GREATEST(skills.confidence_score, EXCLUDED.confidence_score),
                    source           = EXCLUDED.source,
                    category         = CASE WHEN EXCLUDED.category  <> '' THEN EXCLUDED.category
                                            ELSE skills.category END,
                    subcategory      = CASE WHEN EXCLUDED.subcategory <> '' THEN EXCLUDED.subcategory
                                            ELSE skills.subcategory END,
                    run_count        = skills.run_count + 1
                """,
                rows,
                page_size=200,
            )
        self._conn.commit()
        log.debug("Upserted %d skills into DB.", len(rows))

    # ------------------------------------------------------------------
    # Convenience queries (for future UI/stats use)
    # ------------------------------------------------------------------

    def total_skills(self) -> int:
        with self._conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM skills")
            return cur.fetchone()[0]

    def new_since(self, since_date: date) -> int:
        with self._conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM skills WHERE first_seen >= %s", (since_date,))
            return cur.fetchone()[0]

    def all_skills(self) -> list[dict]:
        """Return all skills as plain dicts for taxonomy comparison."""
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, skill_name, normalized_name, category, subcategory, "
                "skill_type, source, confidence_score, popularity, "
                "taxonomy_merged_at, taxonomy_domain, taxonomy_subdomain "
                "FROM skills ORDER BY skill_name"
            )
            return [dict(r) for r in cur.fetchall()]

    def latest_run_skills(self) -> list[dict]:
        """Return skills seen in the most recent scrape run only."""
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, skill_name, normalized_name, category, subcategory, "
                "skill_type, source, confidence_score, popularity, "
                "taxonomy_merged_at, taxonomy_domain, taxonomy_subdomain "
                "FROM skills "
                "WHERE last_seen = (SELECT MAX(last_seen) FROM skills) "
                "ORDER BY skill_name"
            )
            return [dict(r) for r in cur.fetchall()]

    def mark_taxonomy_merged(self, skill_names: list[str], domain: str, subdomain: str, merged_date) -> int:
        """
        Mark skills as merged into the taxonomy.
        Sets taxonomy_merged_at, taxonomy_domain, taxonomy_subdomain for each skill_name.
        Returns the count of rows updated.
        """
        if not skill_names:
            return 0
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE skills
                SET taxonomy_merged_at = %s,
                    taxonomy_domain    = CASE WHEN %s <> '' THEN %s ELSE taxonomy_domain END,
                    taxonomy_subdomain = CASE WHEN %s <> '' THEN %s ELSE taxonomy_subdomain END
                WHERE skill_name = ANY(%s)
                  AND taxonomy_merged_at IS NULL
                """,
                (merged_date, domain, domain, subdomain, subdomain, skill_names),
            )
            updated = cur.rowcount
        self._conn.commit()
        return updated

    def save_run(
        self,
        job_id: str,
        run_date,
        raw_count: int,
        dedup_count: int,
        final_count: int,
        new_count: int,
        returning_count: int,
        sources_list: list,
    ) -> None:
        """Insert (or update on conflict) a scrape run record."""
        sources_str = ", ".join(sources_list) if sources_list else ""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO scrape_runs
                    (job_id, run_date, raw_count, dedup_count, final_count,
                     new_count, returning_count, sources, completed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (job_id) DO UPDATE SET
                    run_date        = EXCLUDED.run_date,
                    raw_count       = EXCLUDED.raw_count,
                    dedup_count     = EXCLUDED.dedup_count,
                    final_count     = EXCLUDED.final_count,
                    new_count       = EXCLUDED.new_count,
                    returning_count = EXCLUDED.returning_count,
                    sources         = EXCLUDED.sources,
                    completed_at    = EXCLUDED.completed_at
                """,
                (job_id, run_date, raw_count, dedup_count, final_count,
                 new_count, returning_count, sources_str),
            )
        self._conn.commit()
        log.debug("Saved scrape run %s to DB.", job_id)

    def list_runs(self, limit: int = 50) -> list:
        """Return scrape runs ordered by completed_at DESC."""
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT job_id, run_date, raw_count, dedup_count, final_count,
                       new_count, returning_count, sources, completed_at
                FROM scrape_runs
                ORDER BY completed_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]

    def skills_by_date(self, run_date: str) -> list:
        """Return skills whose first_seen equals run_date (YYYY-MM-DD string)."""
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT skill_name, category, subcategory, skill_type,
                       confidence_score, source,
                       (first_seen = last_seen) AS is_new
                FROM skills
                WHERE first_seen = %s::date
                ORDER BY skill_name
                """,
                (run_date,),
            )
            return [dict(r) for r in cur.fetchall()]

    def skills_by_run_date(self, run_date: str) -> list:
        """Return skills whose last_seen equals run_date — i.e. all skills present
        in the scrape run on that date. Mirrors the shape of all_skills() so it
        can be passed straight into compare_with_skills()."""
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, skill_name, normalized_name, category, subcategory, "
                "skill_type, source, confidence_score, popularity, "
                "taxonomy_merged_at, taxonomy_domain, taxonomy_subdomain "
                "FROM skills "
                "WHERE last_seen = %s::date "
                "ORDER BY skill_name",
                (run_date,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_run_by_job_id(self, job_id: str) -> dict | None:
        """Look up a single scrape run by job_id."""
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT job_id, run_date, final_count, new_count, sources, completed_at "
                "FROM scrape_runs WHERE job_id = %s",
                (job_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def delete_run(self, job_id: str) -> dict:
        """Delete a scrape run and its footprint:
          - skills rows whose first_seen = last_seen = run_date (only-in-this-run)
          - rejected_skills rows whose first_rejected_at = last_rejected_at = run_date
          - taxonomy_merges rows tagged with this job_id
          - the scrape_runs row itself

        Skills that were also seen in earlier runs (first_seen < run_date) are kept;
        gold taxonomy entries that were merged from this run are NOT touched
        (they're committed master data). Returns deleted counts.
        """
        with self._conn.cursor() as cur:
            cur.execute("SELECT run_date FROM scrape_runs WHERE job_id = %s", (job_id,))
            row = cur.fetchone()
            if not row:
                return {"found": False}
            run_date = row[0]

            cur.execute(
                "DELETE FROM skills WHERE first_seen = %s AND last_seen = %s",
                (run_date, run_date),
            )
            skills_deleted = cur.rowcount

            try:
                cur.execute(
                    "DELETE FROM rejected_skills "
                    "WHERE first_rejected_at = %s AND last_rejected_at = %s",
                    (run_date, run_date),
                )
                rejected_deleted = cur.rowcount
            except psycopg2.errors.UndefinedColumn:
                rejected_deleted = 0

            cur.execute("DELETE FROM taxonomy_merges WHERE job_id = %s", (job_id,))
            merges_deleted = cur.rowcount

            cur.execute("DELETE FROM scrape_runs WHERE job_id = %s", (job_id,))
            run_deleted = cur.rowcount
        self._conn.commit()
        return {
            "found": True,
            "run_date": run_date.isoformat() if hasattr(run_date, "isoformat") else str(run_date),
            "skills_deleted": skills_deleted,
            "rejected_deleted": rejected_deleted,
            "merges_deleted": merges_deleted,
            "run_deleted": run_deleted,
        }

    def upsert_rejected_skills(self, records: list, run_date, reason: str = "below_threshold") -> None:
        """Save below-threshold skills for later reclamation review."""
        if not records:
            return
        rows = []
        for r in records:
            key = _normalize(r.skill_name)
            if not key:
                continue
            rows.append((
                r.skill_name, key,
                r.category or "", r.subcategory or "",
                r.source or "", r.confidence_score, r.popularity,
                reason, run_date, run_date,
            ))
        if not rows:
            return
        with self._conn.cursor() as cur:
            psycopg2.extras.execute_batch(
                cur,
                """
                INSERT INTO rejected_skills
                    (skill_name, normalized_name, category, subcategory, source,
                     confidence_score, popularity, rejection_reason,
                     first_rejected_at, last_rejected_at, times_rejected)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                ON CONFLICT (normalized_name) DO UPDATE SET
                    last_rejected_at  = EXCLUDED.last_rejected_at,
                    times_rejected    = rejected_skills.times_rejected + 1,
                    confidence_score  = GREATEST(rejected_skills.confidence_score, EXCLUDED.confidence_score),
                    popularity        = GREATEST(rejected_skills.popularity, EXCLUDED.popularity),
                    dismissed         = FALSE
                """,
                rows,
                page_size=200,
            )
        self._conn.commit()

    def get_reclaim_pool(self, pool: str = "all", limit: int = 500) -> dict:
        """Return rejected + unmerged skills for monthly review."""
        result = {"rejected": [], "unmerged": []}
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if pool in ("all", "rejected"):
                cur.execute("""
                    SELECT id, skill_name, category, subcategory, source,
                           confidence_score, popularity, rejection_reason,
                           first_rejected_at::text, last_rejected_at::text, times_rejected
                    FROM rejected_skills
                    WHERE dismissed = FALSE
                    ORDER BY times_rejected DESC, confidence_score DESC
                    LIMIT %s
                """, (limit,))
                result["rejected"] = [dict(r) for r in cur.fetchall()]
            if pool in ("all", "unmerged"):
                cur.execute("""
                    SELECT id, skill_name, category, subcategory, source,
                           confidence_score, popularity,
                           first_seen::text, last_seen::text, run_count
                    FROM skills
                    WHERE taxonomy_merged_at IS NULL
                      AND (reclaim_dismissed_at IS NULL)
                      AND first_seen <= CURRENT_DATE - INTERVAL '7 days'
                      AND confidence_score < 0.6
                    ORDER BY run_count DESC, confidence_score DESC
                    LIMIT %s
                """, (limit,))
                result["unmerged"] = [dict(r) for r in cur.fetchall()]
        return result

    def dismiss_rejected(self, ids: list) -> int:
        if not ids:
            return 0
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE rejected_skills SET dismissed = TRUE, dismissed_at = NOW() WHERE id = ANY(%s)",
                (ids,)
            )
            count = cur.rowcount
        self._conn.commit()
        return count

    def dismiss_unmerged(self, ids: list) -> int:
        if not ids:
            return 0
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE skills SET reclaim_dismissed_at = CURRENT_DATE WHERE id = ANY(%s)",
                (ids,)
            )
            count = cur.rowcount
        self._conn.commit()
        return count

    def promote_rejected(self, ids: list, run_date) -> int:
        """Move rejected skills into the main skills table and mark as dismissed in rejected pool."""
        if not ids:
            return 0
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT skill_name, normalized_name, category, subcategory,
                       source, confidence_score, popularity
                FROM rejected_skills
                WHERE id = ANY(%s) AND dismissed = FALSE
            """, (ids,))
            to_promote = cur.fetchall()
            if not to_promote:
                return 0
            psycopg2.extras.execute_batch(
                cur,
                """
                INSERT INTO skills
                    (skill_name, normalized_name, category, subcategory, skill_type,
                     source, confidence_score, popularity, language, tags,
                     first_seen, last_seen, run_count)
                VALUES (%s, %s, %s, %s, '', %s, %s, %s, '', '', %s, %s, 1)
                ON CONFLICT (normalized_name) DO UPDATE SET
                    confidence_score = GREATEST(skills.confidence_score, EXCLUDED.confidence_score),
                    last_seen = EXCLUDED.last_seen,
                    run_count = skills.run_count + 1
                """,
                [(r['skill_name'], r['normalized_name'], r['category'], r['subcategory'],
                  r['source'], r['confidence_score'], r['popularity'],
                  run_date, run_date) for r in to_promote],
            )
            cur.execute(
                "UPDATE rejected_skills SET dismissed = TRUE, dismissed_at = NOW() WHERE id = ANY(%s)",
                (ids,)
            )
            count = len(to_promote)
        self._conn.commit()
        return count

    # ------------------------------------------------------------------
    # Changelog runs
    # ------------------------------------------------------------------

    def save_changelog_run(
        self,
        run_date,
        filter_desc: str,
        filename: str,
        total_records: int,
        matched_records: int,
        raw_records: list,
    ) -> int:
        """Insert a changelog scrape run and return its id."""
        import json as _json
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO changelog_runs
                    (run_date, filter_desc, filename, total_records, matched_records, raw_records)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                RETURNING id
                """,
                (run_date, filter_desc, filename, total_records, matched_records,
                 _json.dumps(raw_records)),
            )
            row_id = cur.fetchone()[0]
        self._conn.commit()
        return row_id

    def list_changelog_runs(self, limit: int = 50) -> list:
        """Return changelog runs newest first."""
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, run_date, filter_desc, filename,
                       total_records, matched_records,
                       jsonb_array_length(raw_records) AS stored_records,
                       created_at
                FROM changelog_runs
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_changelog_records(self, run_id: int) -> list:
        """Return raw records stored for a given changelog run."""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT raw_records FROM changelog_runs WHERE id = %s",
                (run_id,),
            )
            row = cur.fetchone()
        return row[0] if row else []

    def save_taxonomy_merge(
        self,
        batch: str,
        merge_date,
        added_count: int,
        skills: list,
        job_id: str | None = None,
        run_date=None,
    ) -> None:
        """Persist a taxonomy merge run for the History tab."""
        import json
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO taxonomy_merges (batch, merge_date, added_count, skills, job_id, run_date) "
                "VALUES (%s, %s, %s, %s::jsonb, %s, %s)",
                (batch, merge_date, added_count, json.dumps(skills), job_id, run_date),
            )
        self._conn.commit()

    def list_taxonomy_merges(self, limit: int = 50) -> list:
        """Return recent taxonomy merges for the UI History tab."""
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT batch, merge_date, added_count, skills, job_id, run_date, created_at "
                "FROM taxonomy_merges ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]

    def merged_run_skills(self, run_date: str) -> list:
        """Skills already merged into gold whose last_seen = run_date.
        Used to regenerate the per-run merged xlsx after a merge has happened."""
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT skill_name, taxonomy_domain, taxonomy_subdomain, "
                "category, subcategory, skill_type, source, confidence_score "
                "FROM skills "
                "WHERE last_seen = %s::date AND taxonomy_merged_at IS NOT NULL "
                "ORDER BY skill_name",
                (run_date,),
            )
            return [dict(r) for r in cur.fetchall()]

    def merged_skills_summary(self) -> dict:
        """Return count of merged vs unmerged skills and per-date breakdown."""
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE taxonomy_merged_at IS NOT NULL) AS merged,
                    COUNT(*) FILTER (WHERE taxonomy_merged_at IS NULL)     AS not_merged,
                    COUNT(*)                                                AS total
                FROM skills
            """)
            totals = dict(cur.fetchone())
            cur.execute("""
                SELECT taxonomy_merged_at::text AS date, COUNT(*) AS count
                FROM skills
                WHERE taxonomy_merged_at IS NOT NULL
                GROUP BY taxonomy_merged_at
                ORDER BY taxonomy_merged_at DESC
            """)
            totals["by_date"] = [dict(r) for r in cur.fetchall()]
        return totals


# ------------------------------------------------------------------
# Module-level helper: build a DB instance from config, return None on failure
# ------------------------------------------------------------------

def open_db(config: dict) -> Optional[SkillsDB]:
    """
    Construct and connect a SkillsDB from config.  Returns None (with a
    warning) if the database section is missing, disabled, or unreachable —
    callers fall back to the CSV-based is_new detection automatically.
    """
    db_cfg = config.get("database", {})
    if not db_cfg.get("enabled", False):
        return None

    dsn = db_cfg.get("dsn", "")
    if not dsn:
        log.warning("DB enabled but no DSN configured — skipping DB.")
        return None

    db = SkillsDB(dsn)
    try:
        db.connect()
        db.init_schema()
        return db
    except Exception as exc:
        log.warning("Could not connect to DB (%s) — falling back to CSV comparison.", exc)
        return None
