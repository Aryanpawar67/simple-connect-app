"""
Semantic deduplication using Claude.
Called after rapidfuzz to resolve borderline fuzzy-match candidates
(score between 75 and 91 inclusive).
"""
from __future__ import annotations
import json
from ai.client import get_client, chat, HAIKU, batch_chunks


_PROMPT_TEMPLATE = """\
You are an expert in tech skill taxonomy deduplication.
For each pair of skill names below, decide if they represent the SAME underlying skill.
Be strict: only mark as duplicate if a recruiter or engineer would consider them interchangeable.

Pairs (JSON array of {{a, b}}):
{pairs_json}

Return ONLY a JSON array of objects with keys: a, b, is_duplicate (boolean).
No explanation, no markdown, just the JSON array.
"""


def ai_find_duplicates(candidate_pairs: list[tuple[str, str]], client=None) -> set[tuple[str, str]]:
    """
    Given a list of (name_a, name_b) pairs that fuzzy-matched in the grey zone,
    return the set of pairs Claude confirms as true duplicates.

    Falls back to empty set (keep all as-is) if client is None or API fails.
    """
    if client is None:
        client = get_client()
    if client is None or not candidate_pairs:
        return set()

    confirmed: set[tuple[str, str]] = set()

    for chunk in batch_chunks(candidate_pairs, 30):
        pairs_input = [{"a": a, "b": b} for a, b in chunk]
        prompt = _PROMPT_TEMPLATE.format(pairs_json=json.dumps(pairs_input, indent=2))
        try:
            reply = chat(client, HAIKU, prompt, max_tokens=2048)
            reply = reply.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            results = json.loads(reply)
            for r in results:
                if r.get("is_duplicate"):
                    confirmed.add((r["a"], r["b"]))
                    confirmed.add((r["b"], r["a"]))  # symmetrical
        except Exception:
            pass

    return confirmed
