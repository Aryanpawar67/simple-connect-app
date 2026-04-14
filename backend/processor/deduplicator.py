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
