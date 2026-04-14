"""
Taxonomy DB — all operations against the `taxonomy` table in Neon.
Replaces the on-disk Excel master file entirely.
"""
from __future__ import annotations

import io
import datetime
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
    conn.commit()
    conn.close()
    return inserted


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

        cur.execute(
            "SELECT COUNT(DISTINCT subdomain) AS c FROM taxonomy "
            "WHERE sheet='sheet1' AND subdomain != ''"
        )
        subdomain_count = cur.fetchone()["c"]

        cur.execute(
            "SELECT COUNT(DISTINCT skill_cluster) AS c FROM taxonomy "
            "WHERE sheet='sheet1' AND skill_cluster != ''"
        )
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
    """Return {domain: [subdomains]} for UI dropdowns."""
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
    Returns same shape as the old compare_skills() so callers need no changes.
    """
    from taxonomy.domain_mapping import (
        CATEGORY_TO_DOMAIN, SUBCATEGORY_TO_SUBDOMAIN, SKILLTYPE_TO_CLASSIFICATION,
        DEFAULT_DOMAIN, DEFAULT_SUBDOMAIN, DEFAULT_CLASSIFICATION, DEFAULT_CRITICALITY,
    )

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

        category    = skill.get("category") or ""
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
    """INSERT approved skills into taxonomy table. Returns count inserted."""
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
    import openpyxl

    conn = get_conn(dsn)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT domain, subdomain, skill_cluster, skill_name,
                   classification, criticality, sheet
            FROM taxonomy ORDER BY sheet, domain, subdomain, skill_name
        """)
        rows = cur.fetchall()
    conn.close()

    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Final 16 domains"
    ws1.append(["Domain", "Subdomain", "Skill Cluster", "Skill Name",
                "SkillClassification", "SkillCriticality"])
    ws2 = wb.create_sheet("Domain Independent & Irrelevant")
    ws2.append(["Domain", "SubDomain", "SkillCluster", "SkillName",
                "SkillClassification", "SkillCriticality"])

    for row in rows:
        r = [row["domain"], row["subdomain"], row["skill_cluster"],
             row["skill_name"], row["classification"], row["criticality"]]
        (ws1 if row["sheet"] == "sheet1" else ws2).append(r)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()
