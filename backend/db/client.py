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
    id               SERIAL PRIMARY KEY,
    skill_name       TEXT    NOT NULL,
    normalized_name  TEXT    NOT NULL UNIQUE,
    category         TEXT    NOT NULL DEFAULT '',
    subcategory      TEXT    NOT NULL DEFAULT '',
    skill_type       TEXT    NOT NULL DEFAULT '',
    source           TEXT    NOT NULL DEFAULT '',
    confidence_score REAL    NOT NULL DEFAULT 0.0,
    popularity       INTEGER NOT NULL DEFAULT 0,
    language         TEXT    NOT NULL DEFAULT '',
    tags             TEXT    NOT NULL DEFAULT '',
    first_seen       DATE    NOT NULL,
    last_seen        DATE    NOT NULL,
    run_count        INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_skills_normalized  ON skills (normalized_name);
CREATE INDEX IF NOT EXISTS idx_skills_first_seen  ON skills (first_seen);
CREATE INDEX IF NOT EXISTS idx_skills_category    ON skills (category);
CREATE INDEX IF NOT EXISTS idx_skills_confidence  ON skills (confidence_score);
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
        """Create tables / indexes if they don't exist yet (idempotent)."""
        with self._conn.cursor() as cur:
            cur.execute(_DDL)
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
                "skill_type, source, confidence_score, popularity "
                "FROM skills ORDER BY skill_name"
            )
            return [dict(r) for r in cur.fetchall()]


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
