import math
import re
from scraper.base import SkillRecord

HIGH_SIGNAL_SOURCES = {
    "thoughtworks_radar",
    "cncf_landscape",
    "stackoverflow_tags",
    "github_topics",
}
MEDIUM_SIGNAL_SOURCES = {
    "github_trending",
    "npm_trending",
    "pypi_trending",
    "devto",
    "infoq",
}
LOW_SIGNAL_SOURCES = {
    "hackernews", "reddit", "arxiv", "medium",
    "dzone", "product_hunt", "linkedin_jobs",
}

MULTI_SOURCE_BONUS = 0.15

NOISE_PATTERNS = [
    re.compile(r'^@[a-zA-Z0-9_-]+/'),             # any scoped npm package (@scope/...)
    re.compile(r'^v\d+\.\d+'),                    # version strings
    re.compile(r'^\d+'),                          # starts with digit
    re.compile(r'.{60,}'),                        # too long
    re.compile(r'^(the|a|an|is|it|in|on|at|to|of|and|or|but|for|not|with)\b', re.I),
]


def score(record: SkillRecord) -> SkillRecord:
    """Compute confidence_score (0.0–1.0) and attach to record in-place."""
    base = 0.0
    sources = [s.strip() for s in record.source.split(",")]

    # Source quality
    if any(s in HIGH_SIGNAL_SOURCES for s in sources):
        base += 0.50
    elif any(s in MEDIUM_SIGNAL_SOURCES for s in sources):
        base += 0.35
    else:
        base += 0.20

    # Multi-source bonus (up to +0.15 for 3+ sources)
    if len(sources) > 1:
        base += MULTI_SOURCE_BONUS * min(len(sources) - 1, 3) / 3

    # Popularity (log-scaled, max ~0.15)
    if record.popularity > 0:
        base += min(0.15, math.log10(record.popularity + 1) / 10)

    # Category quality
    if record.category and record.category != "Developer Tools":
        base += 0.05
    if record.subcategory:
        base += 0.03

    # Noise penalties
    for pattern in NOISE_PATTERNS:
        if pattern.search(record.skill_name):
            base -= 0.30
            break

    # Name length
    name_len = len(record.skill_name)
    if name_len < 2 or name_len > 60:
        base -= 0.40
    elif 2 <= name_len <= 30:
        base += 0.05

    record.confidence_score = round(max(0.0, min(1.0, base)), 3)
    return record
