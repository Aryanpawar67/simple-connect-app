"""
Taxonomy reader — loads iMocha Gold Taxonomy xlsx and provides stat queries.

Caches the parsed workbook in memory; reloads automatically when the file's
mtime changes so the running server always reflects the latest file.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openpyxl


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TaxonomyData:
    sheet1_rows: list[dict]          # "Final 16 domains"
    sheet2_rows: list[dict]          # "Domain Independent & Irrelevant"
    normalized_names: set[str]       # all skill names, normalized, for O(1) lookup
    domains: dict[str, set[str]]     # domain -> set of subdomains


# ---------------------------------------------------------------------------
# Normalisation (mirrors processor/deduplicator.normalize_name)
# ---------------------------------------------------------------------------

def _normalize(name: str) -> str:
    """Lowercase + strip for membership checks."""
    if not name:
        return ""
    try:
        from processor.deduplicator import normalize_name
        return normalize_name(name).lower().strip()
    except Exception:
        return name.lower().strip()


# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------

_cache: dict[str, Any] = {
    "data": None,
    "mtime": 0.0,
    "path": "",
}


def load_taxonomy(path: Path) -> TaxonomyData:
    """
    Load the taxonomy xlsx.  Returns cached data if the file hasn't changed.
    """
    path = Path(path)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0

    if _cache["data"] is not None and _cache["path"] == str(path) and _cache["mtime"] == mtime:
        return _cache["data"]

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)

    sheet1_rows = _read_sheet1(wb)
    sheet2_rows = _read_sheet2(wb)
    wb.close()

    normalized_names: set[str] = set()
    for r in sheet1_rows:
        n = _normalize(r.get("skill_name", "") or "")
        if n:
            normalized_names.add(n)
    for r in sheet2_rows:
        n = _normalize(r.get("skill_name", "") or "")
        if n:
            normalized_names.add(n)

    # Build domain -> subdomains index
    domains: dict[str, set[str]] = {}
    for r in sheet1_rows:
        d = r.get("domain") or ""
        s = r.get("subdomain") or ""
        if d:
            domains.setdefault(d, set())
            if s:
                domains[d].add(s)

    data = TaxonomyData(
        sheet1_rows=sheet1_rows,
        sheet2_rows=sheet2_rows,
        normalized_names=normalized_names,
        domains=domains,
    )

    _cache["data"] = data
    _cache["mtime"] = mtime
    _cache["path"] = str(path)

    return data


def _read_sheet1(wb) -> list[dict]:
    ws = wb["Final 16 domains"]
    rows_iter = ws.rows
    headers = [c.value for c in next(rows_iter)]

    results = []
    for row in rows_iter:
        vals = [c.value for c in row]
        if not any(vals):
            continue
        results.append({
            "domain":             vals[0] or "",
            "subdomain":          vals[1] or "",
            "skill_cluster":      vals[2] or "",
            "skill_name":         vals[3] or "",
            "skill_classification": vals[4] or "",
            "skill_criticality":  vals[5] or "",
        })
    return results


def _read_sheet2(wb) -> list[dict]:
    ws = wb["Domain Independent & Irrelevant"]
    rows_iter = ws.rows
    next(rows_iter)  # skip header

    results = []
    for row in rows_iter:
        vals = [c.value for c in row]
        if not any(vals):
            continue
        results.append({
            "domain":             vals[0] or "",
            "subdomain":          vals[1] or "",
            "skill_cluster":      vals[2] or "",
            "skill_name":         vals[3] or "",
            "skill_classification": vals[5] or "",
            "skill_criticality":  vals[6] or "",
        })
    return results


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def get_taxonomy_stats(data: TaxonomyData) -> dict:
    """Return aggregate statistics about the loaded taxonomy."""
    domain_counts: dict[str, int] = {}
    subdomain_set: set[str] = set()
    cluster_set: set[str] = set()
    classification_counts: dict[str, int] = {}

    for r in data.sheet1_rows:
        d = r["domain"]
        if d:
            domain_counts[d] = domain_counts.get(d, 0) + 1
        s = r["subdomain"]
        if s:
            subdomain_set.add(s)
        c = r["skill_cluster"]
        if c:
            cluster_set.add(c)
        cl = r["skill_classification"]
        if cl:
            classification_counts[cl] = classification_counts.get(cl, 0) + 1

    return {
        "total_skills": len(data.sheet1_rows) + len(data.sheet2_rows),
        "sheet1_count": len(data.sheet1_rows),
        "sheet2_count": len(data.sheet2_rows),
        "domain_count": len(domain_counts),
        "subdomain_count": len(subdomain_set),
        "skill_cluster_count": len(cluster_set),
        "domain_breakdown": dict(sorted(domain_counts.items(), key=lambda x: -x[1])),
        "classification_breakdown": dict(sorted(classification_counts.items(), key=lambda x: -x[1])),
    }


def get_domains_index(data: TaxonomyData) -> dict:
    """Return {domain: sorted list of subdomains} for UI dropdowns."""
    return {d: sorted(subs) for d, subs in sorted(data.domains.items())}
