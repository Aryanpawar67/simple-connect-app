"""
Taxonomy merger — compares DB skills against the taxonomy and produces
an updated xlsx file with the approved new skills appended to Sheet 1.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import openpyxl

from taxonomy.reader import TaxonomyData, _normalize
from taxonomy.domain_mapping import (
    CATEGORY_TO_DOMAIN,
    SUBCATEGORY_TO_SUBDOMAIN,
    SKILLTYPE_TO_CLASSIFICATION,
    DEFAULT_DOMAIN,
    DEFAULT_SUBDOMAIN,
    DEFAULT_CLASSIFICATION,
    DEFAULT_CRITICALITY,
)


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def compare_skills(taxonomy: TaxonomyData, db_skills: list[dict]) -> dict:
    """
    Compare DB skills against the taxonomy.

    Returns:
        {
            "total_db_skills": int,
            "matched": int,
            "new_skills": [...],       # in DB but not in taxonomy
            "unmappable": [...],       # new skills with empty category (needs manual domain)
        }
    """
    new_skills = []
    unmappable = []
    matched = 0

    for skill in db_skills:
        name = skill.get("skill_name") or ""
        norm = _normalize(name)
        if not norm:
            continue

        if norm in taxonomy.normalized_names:
            matched += 1
            continue

        # Not in taxonomy — prepare a proposed row
        category = skill.get("category") or ""
        subcategory = skill.get("subcategory") or ""
        skill_type = skill.get("skill_type") or ""

        proposed_domain = CATEGORY_TO_DOMAIN.get(category, DEFAULT_DOMAIN if category else "")
        proposed_subdomain = SUBCATEGORY_TO_SUBDOMAIN.get(subcategory, DEFAULT_SUBDOMAIN if subcategory else "")
        proposed_classification = SKILLTYPE_TO_CLASSIFICATION.get(skill_type, DEFAULT_CLASSIFICATION)

        entry = {
            "db_id":                  skill.get("id"),
            "skill_name":             name,
            "proposed_domain":        proposed_domain,
            "proposed_subdomain":     proposed_subdomain,
            "proposed_cluster":       proposed_subdomain,   # default cluster = subdomain
            "proposed_classification": proposed_classification,
            "proposed_criticality":   DEFAULT_CRITICALITY,
            "source":                 skill.get("source") or "",
            "confidence_score":       skill.get("confidence_score") or 0.0,
            "category":               category,
            "subcategory":            subcategory,
            "skill_type":             skill_type,
        }

        if not category:
            unmappable.append(entry)
        else:
            new_skills.append(entry)

    return {
        "total_db_skills": len(db_skills),
        "matched": matched,
        "new_skills": new_skills,
        "unmappable": unmappable,
    }


# ---------------------------------------------------------------------------
# Merge (write approved skills into a new xlsx file)
# ---------------------------------------------------------------------------

def apply_merge(
    taxonomy_path: Path,
    approved_skills: list[dict],
    output_dir: Path,
) -> tuple[Path, int]:
    """
    Append approved_skills to Sheet 1 of the taxonomy xlsx.
    Saves a new timestamped file in output_dir.  Never overwrites the original.

    Returns (output_path, added_count).

    Each item in approved_skills should have:
        skill_name, proposed_domain, proposed_subdomain, proposed_cluster,
        proposed_classification, proposed_criticality
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Use openpyxl in write-mode — we must load normally (not read_only) to append
    wb = openpyxl.load_workbook(taxonomy_path)
    ws = wb["Final 16 domains"]

    added = 0
    for skill in approved_skills:
        name = (skill.get("skill_name") or "").strip()
        if not name:
            continue
        ws.append([
            skill.get("proposed_domain") or DEFAULT_DOMAIN,
            skill.get("proposed_subdomain") or DEFAULT_SUBDOMAIN,
            skill.get("proposed_cluster") or skill.get("proposed_subdomain") or DEFAULT_SUBDOMAIN,
            name,
            skill.get("proposed_classification") or DEFAULT_CLASSIFICATION,
            skill.get("proposed_criticality") or DEFAULT_CRITICALITY,
        ])
        added += 1

    timestamp = datetime.date.today().isoformat()
    stem = Path(taxonomy_path).stem
    out_path = output_dir / f"{stem}_merged_{timestamp}.xlsx"

    wb.save(out_path)
    wb.close()

    return out_path, added
