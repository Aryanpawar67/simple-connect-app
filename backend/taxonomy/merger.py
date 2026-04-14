"""DEPRECATED — taxonomy merges now go directly to Neon DB. Use db.taxonomy_db instead."""

def compare_skills(*a, **kw):
    raise RuntimeError("Deprecated. Use db.taxonomy_db.compare_with_skills()")

def apply_merge(*a, **kw):
    raise RuntimeError("Deprecated. Use db.taxonomy_db.merge_skills()")
