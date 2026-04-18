from collections import defaultdict
from rapidfuzz import fuzz, process
from slugify import slugify
from scraper.base import SkillRecord

# Alias -> canonical name normalisations
NORMALIZATIONS = {
    "k8s": "Kubernetes",
    "kube": "Kubernetes",
    "kubectl": "Kubernetes",
    "tf": "Terraform",
    "py": "Python",
    "js": "JavaScript",
    "ts": "TypeScript",
    "golang": "Go",
    "node": "Node.js",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "vue.js": "Vue",
    "vuejs": "Vue",
    "reactjs": "React",
    "react.js": "React",
    "nextjs": "Next.js",
    "next.js": "Next.js",
    "pg": "PostgreSQL",
    "postgres": "PostgreSQL",
    "mongo": "MongoDB",
    "gh-actions": "GitHub Actions",
    "github-actions": "GitHub Actions",
    "gha": "GitHub Actions",
    "ml": "Machine Learning",
    "ai": "Artificial Intelligence",
    "llms": "LLMs",
    "rag": "RAG",
    "vdb": "Vector Database",
    "genai": "Generative AI",
    "devops": "DevOps",
    "mlops": "MLOps",
    "llmops": "LLMOps",
    "devsecops": "DevSecOps",
}


def normalize_name(name: str) -> str:
    """Lowercase, strip punctuation, apply alias table."""
    cleaned = name.lower().strip().strip("-_.@/")
    return NORMALIZATIONS.get(cleaned, name.strip())


def deduplicate(records: list, fuzzy_threshold: int = 92) -> list:
    """
    Deduplicate and merge SkillRecords. Returns a new sorted list.

    Pass 1: normalize names via alias table
    Pass 2: group by slug (exact case-insensitive match)
    Pass 3: fuzzy merge within remaining records at fuzzy_threshold
    """
    if not records:
        return []

    # Pass 1 — normalize
    for r in records:
        r.skill_name = normalize_name(r.skill_name)

    # Pass 2 — group by slug
    slug_groups: dict = defaultdict(list)
    for r in records:
        slug = slugify(r.skill_name)
        if not slug or len(slug) < 2:
            continue
        slug_groups[slug].append(r)

    merged = [_merge_group(g) for g in slug_groups.values()]

    # Pass 3 — fuzzy dedup
    final = []
    used: set = set()
    names = [r.skill_name for r in merged]

    for i, record in enumerate(merged):
        if i in used:
            continue
        group = [record]
        results = process.extract(
            record.skill_name,
            names,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=fuzzy_threshold,
            limit=None,
        )
        for _, score, j in results:
            if j != i and j not in used:
                group.append(merged[j])
                used.add(j)
        used.add(i)
        final.append(_merge_group(group))

    return sorted(final, key=lambda r: r.popularity, reverse=True)


def _merge_group(group: list) -> SkillRecord:
    """Merge duplicates — keep highest popularity, union sources/tags."""
    if len(group) == 1:
        return group[0]
    primary = max(group, key=lambda r: r.popularity)
    primary.source = ", ".join(sorted({r.source for r in group}))
    primary.tags = list({tag for r in group for tag in r.tags})
    primary.description = max((r.description for r in group), key=len)
    return primary


# ---------------------------------------------------------------------------
# AI enhancement (optional)
# ---------------------------------------------------------------------------

def ai_enhance_dedup(records: list, fuzzy_low: int = 75, fuzzy_high: int = 91) -> list:
    """
    Find borderline fuzzy candidates (score in [fuzzy_low, fuzzy_high]) and ask
    Claude to confirm which are true duplicates. Merges confirmed pairs.
    No-op if ANTHROPIC_API_KEY is not set.
    """
    try:
        from ai.deduplicator import ai_find_duplicates
    except Exception:
        return records

    names = [r.skill_name for r in records]
    candidate_pairs: list[tuple[str, str]] = []

    used_indices: set[int] = set()
    for i, record in enumerate(records):
        if i in used_indices:
            continue
        results = process.extract(
            record.skill_name,
            names,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=fuzzy_low,
            limit=None,
        )
        for _, score_val, j in results:
            if j != i and j not in used_indices and score_val <= fuzzy_high:
                candidate_pairs.append((record.skill_name, records[j].skill_name))

    if not candidate_pairs:
        return records

    confirmed = ai_find_duplicates(candidate_pairs)

    # Merge confirmed duplicate pairs
    name_to_idx = {r.skill_name: i for i, r in enumerate(records)}
    merged_indices: set[int] = set()
    final = []

    for i, record in enumerate(records):
        if i in merged_indices:
            continue
        group = [record]
        for a, b in confirmed:
            if a == record.skill_name and b in name_to_idx:
                j = name_to_idx[b]
                if j not in merged_indices and j != i:
                    group.append(records[j])
                    merged_indices.add(j)
        merged_indices.add(i)
        final.append(_merge_group(group))

    return final
