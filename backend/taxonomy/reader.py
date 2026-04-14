"""DEPRECATED — taxonomy data now lives in Neon DB. Use db.taxonomy_db instead."""

def load_taxonomy(*a, **kw):
    raise RuntimeError("Deprecated. Use db.taxonomy_db.get_stats()")

def get_taxonomy_stats(*a, **kw):
    raise RuntimeError("Deprecated. Use db.taxonomy_db.get_stats()")

def get_domains_index(*a, **kw):
    raise RuntimeError("Deprecated. Use db.taxonomy_db.get_domains_index()")

def _normalize(name: str) -> str:
    try:
        from processor.deduplicator import normalize_name
        return normalize_name(name).lower().strip()
    except Exception:
        return name.lower().strip()

class TaxonomyData:
    pass
