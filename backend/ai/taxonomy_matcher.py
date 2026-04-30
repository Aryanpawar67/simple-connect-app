"""
Claude-assisted matching of borderline scraped skills against the taxonomy.
Called after rapidfuzz fails to auto-accept (score < 92), but the scraped
name has at least one taxonomy candidate in the 78-91 grey zone.
"""
from __future__ import annotations
import json
from ai.client import get_client, chat, HAIKU, batch_chunks


_PROMPT_TEMPLATE = """\
You are matching scraped tech skill names against an existing skill taxonomy.

For each item below, decide whether the scraped name is just a variant (alias,
version, abbreviation, casing or punctuation difference, common typo) of one of
the listed candidates — or whether it is a GENUINELY different skill that
should be treated as new.

Be strict. Only confirm a match if a recruiter or engineer would consider the
two interchangeable. Different versions of the same product are matches
("Java 17" matches "Java"). Related but distinct skills are NOT matches
("PySpark" is not "Python", "Next.js" is not "React"). When in doubt, return null.

Items (JSON):
{items_json}

Return ONLY a JSON array of objects with these exact keys:
  - "scraped": echo the scraped name
  - "match":   the chosen candidate string verbatim, or null if none fit
No markdown fences, no commentary.
"""


def ai_resolve_taxonomy_matches(
    items: list[tuple[str, list[str]]],
    client=None,
) -> dict[str, str]:
    """
    items: list of (scraped_name, [top_candidate_taxonomy_names])
    Returns: {scraped_name: matched_taxonomy_name} for items Claude confirmed.
             Rejected items are absent from the result.

    Graceful no-op (returns {}) if ANTHROPIC_API_KEY is unset or the API fails.
    """
    if client is None:
        client = get_client()
    if client is None or not items:
        return {}

    confirmed: dict[str, str] = {}

    for chunk in batch_chunks(items, 20):
        valid_pairs = {scraped: set(cands) for scraped, cands in chunk}
        items_payload = [{"scraped": s, "candidates": c} for s, c in chunk]
        prompt = _PROMPT_TEMPLATE.format(items_json=json.dumps(items_payload, indent=2))
        try:
            reply = chat(client, HAIKU, prompt, max_tokens=2048)
            reply = reply.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            results = json.loads(reply)
            for r in results:
                scraped = r.get("scraped")
                match = r.get("match")
                if scraped and match and match in valid_pairs.get(scraped, ()):
                    confirmed[scraped] = match
        except Exception:
            continue

    return confirmed
